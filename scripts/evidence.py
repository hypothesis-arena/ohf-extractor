#!/usr/bin/env python3
"""A session transcript of this extractor, turned into `call@1` records through the accepted scrubber.

What this is for: `callstore.py` can write a `call@1` record, but a **real** record needs a receipt that
names a scrubbed evidence file, because a session transcript carries machine paths, session ids, host
names and whatever a tool printed. Until now the kit could therefore write only
`record_kind: synthetic_fixture`. This module is the missing adapter: it reads a transcript, builds the
record from what the transcript actually holds, and hands it to the **accepted** scrubber.

What it deliberately does not do:

- **It does not carry a copy of the scrubber and does not patch it.** The scrubber is someone else's
  accepted artefact; a fork of it would be a second policy with the same name. It is imported from
  wherever the operator says it lives (`OHF_SCRUBBER`, or the `where` argument), and it is imported
  only after its bytes hash to the accepted digests below. A path is not an identifier, so the pin is
  the digest and the path is an input.
- **It does not invent what the transcript does not say.** No model, no timing, no token count and no
  licence is guessed. Where the transcript is silent the record carries one of the schema's ten
  availability codes and nothing else; where the schema has no member for something, that something
  stays out of the record (and, for which call a record is, in a private mapping beside the records).
- **It does not decide what the call was about.** Which card, which role, which instruction files,
  which materials and under which licence are operator-supplied pins, as they are for the other
  exporter of these records. A transcript cannot say under what licence a passage was readable, and a
  record that guessed would be a false statement about a right.
- **It writes nothing itself.** Callers write the public record where public records go and the audit
  where private things go. The audit is private: it carries the digest of the raw transcript bytes and
  the inventory digest, and publishing it would undo the scrubbing.

Usage, from a private directory:
  evidence.py calls TRANSCRIPT.jsonl              list the calls a transcript holds, with no content
  evidence.py scrubber-pins                       the digests this kit accepts
"""
import hashlib
import importlib.util
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import callstore  # noqa: E402

# The accepted scrubber, pinned by the bytes the lead accepted (F1/F2) and the contract it validates
# through. Both are pinned: a changed contract changes what scrubbing accepts, which is as much a
# policy change as a changed pattern list.
SCRUBBER_PINS = {
    # The accepted bytes as of 2026-10-23, after the owners fixed the email pattern this kit reported:
    # an address at the end of a sentence used to survive, because the pattern required that no `.`
    # follow it. Implementation 74539185..., policy 3fb6dc0d... . The previous bytes (7a3598d7...) are
    # not accepted for a new record: a record names the policy it was scrubbed by, and that policy let
    # an address through.
    'scrubber.py': '745391858dbfb3fe9d24b1f27711395aba5dd4ca3ed94ad724f1f2dff41d18b0',
    'build_contract.py': 'ab67c0cd6641938864f0ed152c8f48355fd9abb3ac9bd9502d347858b429e277',
}
ENV_SCRUBBER = 'OHF_SCRUBBER'

# What a transcript event is called, and which events belong to a call made by an agent of this kit.
# A step 5, 6 or 7 agent runs as its own session branch, which the transcript marks `isSidechain`.
PROMPT_TYPES = ('user',)
ANSWER_TYPES = ('assistant',)
# The event types a record's `session_events` carries: what was asked, what came back, what the
# harness reported, and what was queued. Everything else a transcript holds is left out **by name**,
# because a record should say what it holds:
#   api-request, api-request-blob, api-request-shape - the request itself, with the whole context the
#     model was sent. That is not an event of the call, and a record is not the place to republish a
#     conversation; the prompt of this call is in `input.prompt`, where it belongs.
#   mode, permission-mode, atis-latch, last-prompt, ai-title - the harness's own bookkeeping, which
#     says nothing about what was asked or answered.
#   file-history-snapshot, file-history-delta - the editor's undo history of files on this machine.
#   attachment - context the harness injects into the conversation, which is where it puts the
#     operator's own details (their email address among them). It is not an event of the call and
#     nothing in a record needs it. Measured before deciding: with these events kept, five real
#     records carried the operator's email address, because the policy's email pattern does not match
#     an address that ends a sentence. The pattern is the policy's to fix - reported - and keeping a
#     context injection out of a record is this kit's to fix, which is this line.
KEPT_TYPES = ('user', 'assistant', 'system', 'queue-operation')

# The adapter's own last look before it hands a record back. It is **not** a second redaction policy:
# it rewrites nothing and decides nothing about what should be removed. It refuses, with the shape
# named, when something unmistakable is still there - an address, a machine path, a session uuid, an
# inventoried secret, a private host. A refusal costs a record; publishing one of these costs more,
# and the policy itself says a residual means the source needs review rather than another pass.
RESIDUAL = (
    ('an address', re.compile(r'[\w.+-]+@[A-Za-z0-9-]+\.[A-Za-z]{2,}')),
    ('a machine path', re.compile(r'/home/[A-Za-z0-9._-]+|/Users/[A-Za-z0-9._-]+')),
    ('a session uuid', re.compile(r'\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b', re.I)),
)

# The second class, which no redaction policy should be asked to catch, because it is not about
# secrets: the working language of the people and the processes around the work. A record of a call is
# published for transparency about a card, and the names of the roles that coordinate the work, the
# identifiers of their messages and the quoted text of their rules have no place in it.
#
# These are refusals, never rewrites. A record carrying them is not a record with a few words too
# many: it is evidence of the wrong call - a session doing coordination rather than an extraction whose
# whole input is a skill, a card and its sources. The remedy is a clean run, not a cleaner record.
FORBIDDEN = (
    ('a role name', re.compile(r'\barena-\w+')),
    ('a job identifier', re.compile(r'THJOB-')),
    ('the messaging helper', re.compile(r'tmux-helper')),
    ('the owner\'s role name', re.compile(r'\bmaster\b', re.I)),
)
# An operator-supplied file of further strings that may not be published, one per line, `#` for a
# comment. Supplied the way the secret inventory is: this kit does not decide the list.
ENV_FORBIDDEN = 'ARENA_FORBIDDEN_FILE'


def forbidden_strings(path=None):
    """The operator's forbidden-public strings, or [] when no file is named."""
    path = path or os.environ.get(ENV_FORBIDDEN)
    if not path:
        return []
    return [line.strip() for line in Path(path).read_text(encoding='utf-8').splitlines()
            if line.strip() and not line.strip().startswith('#')]


class EvidenceError(ValueError):
    """The transcript cannot be turned into a record as it stands."""


def _digest(raw):
    return hashlib.sha256(raw).hexdigest()


_IMPORTED = {}


def scrubber(where=None):
    """The accepted scrubber module, built from the bytes this kit accepts and from nothing else.

    `where` is the directory it lives in (or `OHF_SCRUBBER`). **Every** pinned file is verified, every
    time: there is no way to ask for a subset. A second review showed why - asking for the scrubber
    alone left the contract unverified, so an ambient `build_contract` was used even when the accepted
    file was not there at all, and the module built that way was then cached and handed to every later
    caller. A partial verification is not a verification.

    The three ways an independent review got other code to run here, and what stops each:

    - **A stale or planted `.pyc`.** `exec_module` happily runs a cached bytecode file whose timestamp
      and size match the source, so a verified `.py` was no guarantee of what executed. The verified
      **source text** is now compiled in memory and executed; no bytecode cache is read or written.
    - **An ambient `build_contract`.** The scrubber does `import build_contract`, which is resolved
      through `sys.modules` and `sys.path`: a module already sitting under that name was used, with the
      accepted bytes never consulted. The accepted contract is now compiled here, installed under that
      name for the duration of the import only, and whatever was there before is put back.
    - **A second read.** The bytes that were hashed are the bytes that are compiled - one read, held in
      memory - so nothing can change between the check and the execution.

    The verified module is cached by directory, because the alternative - letting a caller pass a
    module in - is the fourth way, and it is now closed too.
    """
    where = Path(where or os.environ.get(ENV_SCRUBBER) or '')
    if not where.name:
        raise EvidenceError(f'set {ENV_SCRUBBER} to the directory of the accepted scrubber: this kit '
                            f'carries no copy of it, on purpose')
    where = where.resolve()
    key = str(where)
    wanted = sorted(SCRUBBER_PINS)
    if key in _IMPORTED:
        return _IMPORTED[key]
    source = {}
    for name in wanted:
        path = where / name
        if not path.exists():
            raise EvidenceError(f'{path} is missing: the accepted scrubber is '
                                f'{", ".join(sorted(SCRUBBER_PINS))}')
        raw = path.read_bytes()          # read once: these are the bytes that are hashed and compiled
        got = _digest(raw)
        if got != SCRUBBER_PINS[name]:
            raise EvidenceError(f'{name} in {where} hashes to {got}, not the accepted '
                                f'{SCRUBBER_PINS[name]}: this kit will not scrub through bytes it has '
                                f'not been told to accept, and will not patch or copy them either')
        source[name] = raw

    def built(name, module_name):
        """A module from verified bytes, compiled in memory, with no bytecode cache involved."""
        module = importlib.util.module_from_spec(
            importlib.util.spec_from_loader(module_name, loader=None, origin=str(where / name)))
        module.__file__ = str(where / name)
        exec(compile(source[name].decode('utf-8'), str(where / name), 'exec'), module.__dict__)
        return module

    # The contract first, installed under the name the scrubber imports, for that import only.
    previous, had = sys.modules.get('build_contract'), 'build_contract' in sys.modules
    bytecode = sys.dont_write_bytecode
    try:
        sys.dont_write_bytecode = True
        sys.modules['build_contract'] = built('build_contract.py', 'build_contract')
        module = built('scrubber.py', 'ohf_accepted_scrubber')
    finally:
        sys.dont_write_bytecode = bytecode
        if had:
            sys.modules['build_contract'] = previous
        else:
            sys.modules.pop('build_contract', None)
    _IMPORTED[key] = module
    return module


def snapshot(transcript):
    """(digest, text) from **one** read of a transcript.

    One read, because two reads are a race: the digest was taken from the first and the event lines
    from the second, so a file replaced in between passed the check and then supplied other lines. A
    second review demonstrated it. Everything downstream works from the text this returns.
    """
    raw = Path(transcript).read_bytes()
    return _digest(raw), raw.decode('utf-8', errors='strict')


def transcript_digest(transcript):
    """The sha256 of a transcript's bytes."""
    return snapshot(transcript)[0]


def events(transcript, text=None):
    """Every line of a transcript as (line_number, text, parsed), refusing a line that is not JSON.

    The raw text is kept beside the parsed event because the record carries the **lines**: the scrubber
    reads `session_events` as JSONL and insists every non-empty line parse strictly, so a line this kit
    rewrote before scrubbing would be a line the scrubber never saw.
    """
    out = []
    for n, line in enumerate((text if text is not None else snapshot(transcript)[1]).splitlines(), 1):
        if not line.strip():
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError as exc:
            raise EvidenceError(f'{transcript}:{n} is not JSON ({exc.msg}): a transcript line this kit '
                                f'cannot read is not a line it may hand on as evidence') from exc
        if not isinstance(parsed, dict) or not isinstance(parsed.get('type'), str):
            raise EvidenceError(f'{transcript}:{n} has no event type: the scrubber refuses an event '
                                f'envelope it cannot recognise, and so does this')
        out.append((n, line, parsed))
    return out


def _text_of(message):
    """The text of one message, as the transcript holds it: the text blocks, in order, joined.

    Thinking blocks are not text of the call's answer and tool blocks are not either; both are in the
    session events, where they belong, and neither is silently folded into the answer.
    """
    content = (message or {}).get('content')
    if isinstance(content, str):
        return content
    parts = []
    for block in content or []:
        if isinstance(block, dict) and block.get('type') == 'text' and isinstance(block.get('text'), str):
            parts.append(block['text'])
    return '\n'.join(parts)


def calls(transcript, branch='agent'):
    """The calls a transcript holds, newest last, as dicts with no content of their own.

    Two shapes, because a transcript holds two kinds of call and they are not interchangeable:

    - `branch='agent'`: one agent of steps 5-7, which the transcript marks `isSidechain`. A branch
      runs from its prompt to its last answer, it was given its own instructions, and it wrote a
      response file. This is the shape the store exists for, because it is where a second reader or a
      checker is independent of the converter.
    - `branch='session'`: one turn of the session itself - the converter at work, prompted and
      answering, with no separate instruction set and no response file. These are real model calls
      about a card and they are logged as such, but a record of one claims no independence: the same
      session holds the whole conversion, and `role` is `extractor` for all of them.

    A transcript of this harness need not hold any agent branch at all; where it holds none, `agent`
    returns nothing rather than falling back to the session's turns, because a session turn is not an
    independent reader and a record that implied otherwise would be the one thing this store is for.

    **One call is one request to the model**, not one turn of the conversation. A turn can be dozens
    of calls: the model answers, a tool runs, and the model is asked again with the result. The
    transcript says which is which - every answer carries the `requestId` of the request that produced
    it - and that is the unit, because it is the unit the model was actually asked anything in. Group
    by turn instead and a record's `timing`, `usage` and `effort` would be sums over several calls
    that nothing in the record distinguishes.

    What each call carries is what the transcript says and no more: the model as requested and as
    reported, the effort as the harness reported it, the first and last timestamps, the token counts
    where they are there, and the line numbers of its events. The prompt is the text of the events
    between the previous call and this one - what this call was asked, as the transcript holds it,
    which is not the whole context the model was sent.
    """
    if branch not in ('agent', 'session'):
        raise EvidenceError("branch is 'agent' (an agent of steps 5-7) or 'session' (a turn of the "
                            "conversion itself); there is no third kind in a transcript")
    found, call, asked, asked_lines = [], None, [], []
    digest, text = snapshot(transcript)
    for n, line, ev in events(transcript, text):
        if bool(ev.get('isSidechain')) != (branch == 'agent'):
            continue
        kind = ev.get('type')
        if kind not in KEPT_TYPES:
            continue
        if kind not in ANSWER_TYPES:
            # A new prompt closes the call before it: what follows was asked after that call answered.
            if kind in PROMPT_TYPES and call is not None:
                found.append(call)
                call = None
            if kind in PROMPT_TYPES:
                text = _text_of(ev.get('message'))
                if text:
                    asked.append(text)
            if call is None:
                asked_lines.append(n)
            else:
                call['lines'].append(n)
            continue
        message = ev.get('message') or {}
        request = ev.get('requestId') or ev.get('requestRef') or f'line-{n}'
        if call is not None and call['request'] != request:
            found.append(call)
            call = None
        if call is None:
            call = {'request': request, 'branch': branch, 'prompt': '\n'.join(asked),
                    'transcript_sha256': digest, 'answered': {},
                    'started_at': ev.get('timestamp'), 'finished_at': ev.get('timestamp'),
                    'lines': asked_lines + [n], 'answers': 0,
                    'model_requested': None, 'model_reported': None, 'effort': None,
                    'usage': {'input_tokens': None, 'output_tokens': None, 'reasoning_tokens': None},
                    'final_message': None, 'status': 'interrupted'}
            asked, asked_lines = [], []
        else:
            call['lines'].append(n)
        call['finished_at'] = ev.get('timestamp') or call['finished_at']
        seen = message.get('id') or f'line-{n}'
        # One answer is written several times as it streams: the harness emits a line per content block
        # under the same message id, with `stop_reason` null until the last. Measured on a real agent
        # transcript, where one id appeared three times - text, tool_use, then tool_use with the stop
        # reason and the full token count (1, 1, then 212 output tokens). So an unfinished occurrence
        # adds no usage and is not an answer; the finished one is the answer.
        #
        # What stays refused is what a review demonstrated: **two finished answers under one id**, which
        # would let the later one set the final message and the status while the tokens stayed with the
        # first, and the record would mix two answers without saying so.
        finished = message.get('stop_reason') is not None
        fingerprint = _digest(json.dumps(message, sort_keys=True, ensure_ascii=False).encode())
        if finished and seen in call['answered'] and call['answered'][seen] != fingerprint:
            raise EvidenceError(
                f'two finished answers in this transcript carry the message id {seen!r}: a record built '
                f'from them would take its tokens from one and its final message and status from the '
                f'other. Refused - read the transcript again, or ask the harness which answer is the '
                f'answer')
        repeat = seen in call['answered']
        if finished:
            call['answered'][seen] = fingerprint
        if finished and not repeat:
            call['answers'] += 1
        call['model_requested'] = ev.get('requestedModel') or call['model_requested']
        call['model_reported'] = message.get('model') or call['model_reported']
        call['effort'] = ev.get('effort') or ev.get('perTurnEffort') or call['effort']
        # the finished occurrence carries the call's totals; the partial ones carry a running count
        usage = (message.get('usage') or {}) if finished and not repeat else {}
        for member in ('input_tokens', 'output_tokens'):
            if isinstance(usage.get(member), int):
                call['usage'][member] = (call['usage'][member] or 0) + usage[member]
        thinking = (usage.get('output_tokens_details') or {}).get('reasoning_tokens')
        if isinstance(thinking, int):
            call['usage']['reasoning_tokens'] = (call['usage']['reasoning_tokens'] or 0) + thinking
        text = _text_of(message)
        if text:
            call['final_message'] = text
        # A call that ended by asking for a tool ended normally: the answer it gave was a tool use.
        # Only a call the transcript shows no ending for stays `interrupted`.
        stop = message.get('stop_reason')
        if stop in ('end_turn', 'stop_sequence', 'tool_use', 'max_tokens'):
            call['status'] = 'completed'
        elif stop == 'refusal':
            call['status'] = 'refusal'
        elif stop in ('error', 'invalid'):
            call['status'] = 'error'
    if call is not None:
        found.append(call)
    return found


def record(call, transcript, *, role, card_id, version, receipt_id, instructions, materials=(),
           projections=(), response_file=None, first_write_proven=False, availability_notes=()):
    """A `call@1` record for one call of a transcript, ready for the scrubber.

    The operator supplies what a transcript cannot say: `role` (an extractor's call or a critic's),
    the card, the receipt's id, the instruction files with their bytes, and each material with the
    licence **and the locator the licence was read from**. `response_file` is the file the agent was
    told to write, as (text, first_write_proven); where the harness did not show that it was written
    once and not rewritten, `first_write_proven` stays false and the record says
    `first_response_unproven`.

    The record's `receipt.sha256` is left as zeros here and is filled by the scrubber from the
    snapshot it builds, which is the only hash that covers what is actually published.
    """
    # The call was read from a transcript; the events are read from it again here. If the file has
    # changed in between, the two halves of the record are about different files: the prompt and the
    # answer of one, the event lines of another. Refused rather than stitched together.
    now, text = snapshot(transcript)
    if call.get('transcript_sha256') and call['transcript_sha256'] != now:
        raise EvidenceError(f'this call was read from a transcript hashing to {call["transcript_sha256"]}, '
                            f'and the file now hashes to {now}: the record would mix one transcript\'s '
                            f'prompt with another\'s events. Read the calls again')
    notes = list(availability_notes)
    if not call.get('model_reported'):
        notes.append('reported_model_unavailable')
    if not any(isinstance(v, int) for v in call['usage'].values()):
        notes.append('usage_unavailable')
    if response_file is None:
        notes.append('response_file_unavailable')
    elif not first_write_proven:
        notes.append('first_response_unproven')
    if call.get('final_message') is None:
        notes.append('final_message_unavailable')
    if call['status'] == 'interrupted':
        notes.append('interrupted_before_response')
    if not call.get('started_at') or not call.get('finished_at'):
        raise EvidenceError('the transcript gives this call no times, and a record whose timing is '
                            'invented is not evidence of when anything ran')

    lines = {n for n in call['lines']}
    # the lines come from the same read whose digest was just checked, not from a third read
    session_events = '\n'.join(raw for n, raw, _ in events(transcript, text) if n in lines)
    usage = call['usage'] if any(isinstance(v, int) for v in call['usage'].values()) else None
    return callstore.record(
        role=role, card_id=card_id, version=version, stage=callstore.STAGE_OF_ROLE[role],
        receipt={'id': receipt_id, 'sha256': '0' * 64, 'kind': 'scrubbed-agent-evidence@1'},
        model_requested=call.get('model_requested') or call.get('model_reported') or 'unrecorded',
        model_reported=call.get('model_reported'), effort=call.get('effort'),
        started_at=call['started_at'], finished_at=call['finished_at'],
        prompt=call['prompt'], instructions=list(instructions), projections=list(projections),
        materials=list(materials),
        response_file=(None if response_file is None else
                       callstore.response(response_file, first_write_proven)),
        final_message=call.get('final_message'), status=call['status'], usage=usage,
        session_events=[session_events] if session_events else [],
        availability_notes=sorted(set(notes)), record_kind='model_call',
        redaction={'state': 'scrubbed', 'policy_sha256': '0' * 64})


def export(rec, *, secret_inventory, private_hosts, where=None, forbidden_file=None):
    """(public record, published snapshot, PRIVATE audit) from the accepted scrubber, unmodified.

    The inventories are the operator's: the scrubber refuses to run without them, and this adapter
    does not read an environment, a credential store or a home directory to fill them in. A record
    that comes back `model_call` has been scrubbed by the accepted policy and carries that policy's
    digest; nothing here rewrites the result, and a refusal is passed on as it is, with its code.

    After the policy has run, two further checks of this adapter's own, both refusals and never
    rewrites: RESIDUAL, for a leak the policy left, and FORBIDDEN plus the operator's
    forbidden-public file, for the working language of the process - role names, message identifiers,
    the messaging helper, quoted rules. The second is not a redaction question. A record of a call is
    published to show how a card was made; a call whose input was a charter and a stream of messages is
    not such a call, and the answer is a clean run rather than a tidier record.
    """
    module = scrubber(where)
    try:
        public, snapshot, audit = module.scrub(rec, secret_inventory=list(secret_inventory),
                                               private_hosts=list(private_hosts))
    except module.Refused as exc:
        raise EvidenceError(f'the accepted scrubber refused this record: {exc}. The record is not '
                            f'written, and the refusal is not worked around here') from exc
    if public.get('redaction', {}).get('state') != 'scrubbed':
        raise EvidenceError('the scrubber returned a record that does not say it was scrubbed')
    published = json.dumps([public, snapshot], ensure_ascii=False)
    for name, pattern in RESIDUAL:
        found = pattern.search(published)
        if found:
            raise EvidenceError(
                f'the scrubbed record still holds {name} ({found.group(0)[:12]}...): this adapter will '
                f'not hand it on. Nothing is rewritten here - the policy decides what is removed - and '
                f'the record is refused so that the source can be looked at. A leak this check names is '
                f'a case for the policy\'s owners, not for a second policy in this kit')
    for name, pattern in FORBIDDEN:
        found = pattern.search(published)
        if found:
            raise EvidenceError(
                f'the record holds {name} ({found.group(0)[:24]!r}), which is the working language of '
                f'the process and not of the card. A record for publication comes from a run whose whole '
                f'input is a skill, a card and its sources - no charter, no messages - so this is a '
                f'refusal and not something to edit out: the call itself was the wrong call to record')
    for string in forbidden_strings(forbidden_file):
        if string in published:
            raise EvidenceError(f'the record holds a string the operator forbids publishing '
                                f'({string[:24]!r}): refused, not edited')
    for secret in secret_inventory:
        if secret and secret in published:
            raise EvidenceError('the scrubbed record still holds an inventoried secret: refused')
    for host in private_hosts:
        if host and re.search(r'(?<![\w.-])' + re.escape(host) + r'(?![\w.-])', published, re.I):
            raise EvidenceError(f'the scrubbed record still holds the private host {host!r}: refused')
    return public, snapshot, audit


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    if sys.argv[1] == 'scrubber-pins':
        for name, want in sorted(SCRUBBER_PINS.items()):
            print(f'{want}  {name}')
        return
    if sys.argv[1] == 'calls' and len(sys.argv) in (3, 4):
        for i, call in enumerate(calls(sys.argv[2], sys.argv[3] if len(sys.argv) == 4 else 'agent'), 1):
            print(f'{i}\t{call["started_at"]}\t{call["finished_at"]}\t'
                  f'{call.get("model_reported") or "model unrecorded"}\t'
                  f'effort {call.get("effort") or "unrecorded"}\t{call["answers"]} answers\t'
                  f'{len(call["lines"])} events\t{call["status"]}')
        return
    sys.exit(__doc__)


if __name__ == '__main__':
    main()
