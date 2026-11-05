#!/usr/bin/env python3
"""The adapter from a session transcript to a scrubbed `call@1` record.

Two things are tested here and they are different: that the adapter reads a transcript honestly, and
that nothing a transcript carries reaches a public record. The second is tested through the **accepted**
scrubber, not through a copy of it: if the accepted bytes are not available, those tests skip rather
than pretend, because a test that scrubbed with this kit's own imitation would prove nothing about what
is published.
"""
import hashlib
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import callstore  # noqa: E402
import evidence  # noqa: E402

SCRUBBER_DIR = os.environ.get(evidence.ENV_SCRUBBER)
needs_scrubber = pytest.mark.skipif(
    not (SCRUBBER_DIR and (Path(SCRUBBER_DIR) / 'scrubber.py').exists()),
    reason='evidence-export: SKIPPED (scrubber not supplied)')

# Every shape this kit's own transcripts carry that must not be published. The value is what a reader
# of the public record must not find; `want` is what the accepted policy does with it.
LEAKS = {
    'home path': '/ho' + 'me/' + 'som' + 'eon' + 'e/s' + 'tre' + 'ams' + '/ar' + 'ena' + '-oh' + 'f/o' + 'ut/' + 'car' + 'd.j' + 'son',
    'tilde path': '~/w' + 'ork' + '/no' + 'tes' + '/pr' + 'iva' + 'te.' + 'md',
    'session id': '3f2' + '504' + 'e0-' + '4f8' + '9-1' + '1d3' + '-9a' + '0c-' + '030' + '5e8' + '2c3' + '301',
    'private host': 'bui' + 'lde' + 'r.i' + 'nte' + 'rna' + 'l',
    'localhost': 'loc' + 'alh' + 'ost',
    'ip address': '10.' + '11.' + '12.' + '13',
    'api token': 'sk-' + 'ant' + '-ap' + 'i03' + '-ZZ' + 'ZZZ' + 'ZZZ' + 'ZZZ' + 'ZZZ' + 'ZZZ' + 'ZZZ',
    'github token': 'ghp' + '_ZZ' + 'ZZZ' + 'ZZZ' + 'ZZZ' + 'ZZZ' + 'ZZZ' + 'ZZZ' + 'ZZZ' + 'ZZZ' + 'ZZZ' + 'Z',
    'bearer': 'Aut' + 'hor' + 'iza' + 'tio' + 'n: ' + 'Bea' + 'rer' + ' ZZ' + 'ZZZ' + 'ZZZ' + 'ZZZ' + 'ZZZ' + 'ZZZ' + 'ZZZ',
    'jwt': 'eyJ' + 'hbG' + 'ciO' + 'iJI' + 'UzI' + '1Ni' + 'J9.' + 'eyJ' + 'zdW' + 'IiO' + 'iIx' + 'In0' + '.ZZ' + 'ZZZ' + 'ZZZ' + 'ZZZ' + 'ZZZ' + 'ZZZ' + 'ZZZ',
    'assignment': 'API' + '_KE' + 'Y=Z' + 'ZZZ' + 'ZZZ' + 'ZZZ' + 'ZZZ' + 'ZZZ' + 'ZZZ' + 'Z',
    'cookie header': '\nCo' + 'oki' + 'e: ' + 'ses' + 'sio' + 'n=Z' + 'ZZZ' + 'ZZZ' + 'ZZZ' + 'ZZZ' + 'ZZZ' + 'ZZZ' + 'Z\n',
    'email': 'som' + 'eon' + 'e@e' + 'xam' + 'ple' + '.or' + 'g',
}
INVENTORY = ['ZZZZ-explicit-secret-from-the-operator']
HOSTS = ['builder', 'builder.internal']


def event(**fields):
    base = {'type': 'assistant', 'isSidechain': False, 'timestamp': '2026-10-23T12:00:00.000Z'}
    return json.dumps({**base, **fields}, ensure_ascii=False)


def answer(request, text, stop='end_turn', model='claude-opus-5', **fields):
    return event(requestId=request, requestedModel=model, effort='high',
                 message={'model': model, 'role': 'assistant', 'stop_reason': stop,
                          'content': [{'type': 'text', 'text': text}],
                          'usage': {'input_tokens': 10, 'output_tokens': 3,
                                    'output_tokens_details': {'reasoning_tokens': 7}}}, **fields)


def prompt(text, **fields):
    return event(type='user', message={'role': 'user', 'content': text}, **fields)


def transcript(tmp_path, lines, name='t.jsonl'):
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / name
    path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return path


def test_a_call_is_one_request_to_the_model_and_not_one_turn(tmp_path):
    """One turn can be many calls: the model answers, a tool runs, and it is asked again. Grouping by
    turn would sum the timing, the tokens and the effort of several calls into one record with nothing
    in it to say so."""
    path = transcript(tmp_path, [
        prompt('convert this card'),
        answer('req-1', 'reading the article', stop='tool_use'),
        prompt('<tool result>'),
        answer('req-2', 'writing the atoms', stop='tool_use', timestamp='2026-10-23T12:00:05.000Z'),
        prompt('<tool result>'),
        answer('req-3', 'done', timestamp='2026-10-23T12:00:09.000Z'),
    ])
    calls = evidence.calls(path, 'session')
    assert [c['request'] for c in calls] == ['req-1', 'req-2', 'req-3']
    assert [c['status'] for c in calls] == ['completed'] * 3, 'a call that asked for a tool completed'
    assert calls[0]['prompt'] == 'convert this card' and calls[1]['prompt'] == '<tool result>'
    assert calls[0]['usage'] == {'input_tokens': 10, 'output_tokens': 3, 'reasoning_tokens': 7}
    assert calls[2]['finished_at'] == '2026-10-23T12:00:09.000Z'
    # an agent of steps 5-7 is a different branch, and a transcript with none has none: the session's
    # own calls are never offered in its place
    assert evidence.calls(path, 'agent') == []


def test_an_agent_branch_is_read_as_its_own_call(tmp_path):
    path = transcript(tmp_path, [
        prompt('converter at work'), answer('req-1', 'spawning the second reader', stop='tool_use'),
        prompt('read this article and list its claims', isSidechain=True),
        answer('req-2', 'twelve claims, written to the file', isSidechain=True),
    ])
    agent = evidence.calls(path, 'agent')
    assert len(agent) == 1 and agent[0]['prompt'] == 'read this article and list its claims'
    assert agent[0]['model_reported'] == 'claude-opus-5' and agent[0]['effort'] == 'high'


@pytest.mark.parametrize('line, why', [
    ('not json at all', 'is not JSON'),
    ('{"no":"type"}', 'has no event type'),
])
def test_a_transcript_line_the_kit_cannot_read_is_not_handed_on(tmp_path, line, why):
    path = transcript(tmp_path, [prompt('x'), answer('req-1', 'y'), line])
    with pytest.raises(evidence.EvidenceError, match=why):
        evidence.calls(path, 'session')


def test_the_scrubber_is_not_carried_here_and_is_refused_if_its_bytes_differ(tmp_path, monkeypatch):
    """The scrubber is someone else's accepted artefact. This kit holds its digest, not its code: a
    copy would be a second policy under the same name, and bytes that are not the accepted bytes are
    exactly that."""
    monkeypatch.delenv(evidence.ENV_SCRUBBER, raising=False)
    with pytest.raises(evidence.EvidenceError, match=f'set {evidence.ENV_SCRUBBER}'):
        evidence.scrubber()
    (tmp_path / 'scrubber.py').write_text('def scrub(*a, **k):\n    return {}, {}, {}\n')
    (tmp_path / 'build_contract.py').write_text('')
    with pytest.raises(evidence.EvidenceError, match='hashes to'):
        evidence.scrubber(tmp_path)
    (tmp_path / 'build_contract.py').unlink()
    with pytest.raises(evidence.EvidenceError, match='is missing'):
        evidence.scrubber(tmp_path / 'elsewhere')
    assert len(evidence.SCRUBBER_PINS) == 2, 'the contract is pinned too: it decides what scrubbing accepts'


def leaky_record(tmp_path, extra_event=None, prompt_text=None):
    """A record of one real-shaped call whose every field carries something that must not be published."""
    leaks = ' '.join(LEAKS.values())
    lines = [prompt(prompt_text or f'convert the card at {LEAKS["home path"]} {LEAKS["api token"]}')]
    if extra_event:
        lines.append(extra_event)
    lines.append(answer('req-1', f'written to {LEAKS["tilde path"]}, session {LEAKS["session id"]}'))
    path = transcript(tmp_path, lines)
    call = evidence.calls(path, 'session')[0]
    instruction_text = f'read only what is shown. {leaks}'
    material_text = f'The article, as fetched from {LEAKS["private host"]}.'
    return evidence.record(
        call, path, role='extractor', card_id='h_demo', version=1, receipt_id='receipt-demo-1',
        instructions=[callstore.instruction('SKILL.md', instruction_text)],
        materials=[callstore.material('https://www.ebi.ac.uk/europepmc/webservices/rest/PMC1/fullTextXML',
                                      material_text.encode(), 'CC-BY-4.0',
                                      f'the licence block of the XML, read on {LEAKS["localhost"]}',
                                      text=material_text)],
        response_file=f'the answer, written beside {LEAKS["home path"]}', first_write_proven=True)


@needs_scrubber
def test_nothing_a_transcript_carries_reaches_the_public_record(tmp_path):
    """The whole point of the adapter: the record goes through the accepted scrubber, and what comes
    back carries none of the shapes a transcript of this kit is full of - machine paths, session ids,
    hosts, tokens, cookies, an email."""
    rec = leaky_record(tmp_path)
    raw = json.dumps(rec, ensure_ascii=False)
    assert LEAKS['home path'] in raw and LEAKS['api token'] in raw, \
        'the record before scrubbing holds them: it is the scrubber that removes them, not this kit'
    assert rec['redaction']['state'] == 'scrubbed' and rec['record_kind'] == 'model_call'
    public, snapshot, audit = evidence.export(rec, secret_inventory=INVENTORY, private_hosts=HOSTS,
                                              where=SCRUBBER_DIR)
    out = json.dumps([public, snapshot], ensure_ascii=False)
    for name, value in LEAKS.items():
        assert value not in out, f'{name} survived into the public record'
    # not even a prefix of a secret, and not the digest of the raw bytes
    assert LEAKS['api token'][:12] not in out and audit['source_sha256'] not in out
    # a secret the operator inventoried is replaced, not refused: a refusal is for what is left after
    # scrubbing, and an inventoried string can be scrubbed
    inventoried = leaky_record(tmp_path / 'inventoried',
                               prompt_text=f'the operator inventoried {INVENTORY[0]}')
    public2, snapshot2, audit2 = evidence.export(inventoried, secret_inventory=INVENTORY,
                                                 private_hosts=HOSTS, where=SCRUBBER_DIR)
    out2 = json.dumps([public2, snapshot2], ensure_ascii=False)
    assert INVENTORY[0] not in out2 and INVENTORY[0][:8] not in out2
    assert audit2['counts'].get('explicit-secret-inventory'), 'the audit counts what it replaced'
    assert public['redaction']['policy_sha256'] == audit['policy_sha256'] != '0' * 64
    assert public['context']['receipt']['sha256'] != '0' * 64, 'the receipt names what is published'
    assert audit['PRIVATE_DO_NOT_PUBLISH'] is True and snapshot['schema'] == 'scrubbed-agent-evidence@1'


@needs_scrubber
@pytest.mark.parametrize('shape, text', [
    ('percent-encoded path', 'see %2Fhome%2Fsomeone%2Fstreams for the file'),
    ('escaped slashes', 'see \\/home\\/someone\\/streams for the file'),
    ('base64 blob', 'payload base64: ZZZZZZZZZZZZZZZZZZZZ=='),
])
def test_an_encoded_or_inventoried_leak_is_refused_and_not_written(tmp_path, shape, text):
    """A leak the policy cannot rewrite safely stops the record. The refusal is passed on with its
    code; nothing here works around it, and no partially scrubbed record is returned."""
    rec = leaky_record(tmp_path / shape.replace(' ', '-'), prompt_text=text)
    with pytest.raises(evidence.EvidenceError, match='the accepted scrubber refused'):
        evidence.export(rec, secret_inventory=INVENTORY, private_hosts=HOSTS, where=SCRUBBER_DIR)


@needs_scrubber
def test_a_malformed_session_event_stops_the_record(tmp_path):
    """A duplicate JSON key in a session event is refused by the policy, not silently resolved: two
    values under one key mean the event cannot be read the way its writer meant it."""
    duplicate = '{"type": "system", "a": 1, "a": 2, "isSidechain": false}'
    rec = leaky_record(tmp_path, extra_event=duplicate)
    with pytest.raises(evidence.EvidenceError, match='the accepted scrubber refused'):
        evidence.export(rec, secret_inventory=INVENTORY, private_hosts=HOSTS, where=SCRUBBER_DIR)


@needs_scrubber
def test_the_inventories_are_the_operators_and_are_not_guessed(tmp_path):
    """The scrubber refuses to run without them, and this adapter does not read an environment, a
    credential store or a home directory to fill them in."""
    rec = leaky_record(tmp_path)
    for secrets, hosts in (('not a list', HOSTS), (INVENTORY, 'not a list'), (['ab'], HOSTS)):
        with pytest.raises(evidence.EvidenceError, match='the accepted scrubber refused'):
            evidence.export(rec, secret_inventory=secrets, private_hosts=hosts, where=SCRUBBER_DIR)


def test_a_record_says_what_the_transcript_did_not_show(tmp_path):
    """Where the transcript is silent the record carries one of the schema's ten availability codes and
    nothing else: no model is guessed, no token count is invented, and a response nobody saw written is
    not claimed as written once."""
    path = transcript(tmp_path, [
        prompt('convert'),
        event(requestId='req-1', message={'role': 'assistant', 'content': [], 'stop_reason': None}),
    ])
    call = evidence.calls(path, 'session')[0]
    rec = evidence.record(call, path, role='extractor', card_id='h_demo', version=1,
                          receipt_id='r1', instructions=[callstore.instruction('SKILL.md', 'read')])
    assert rec['model']['reported'] is None and rec['usage'] is None
    assert set(rec['availability_notes']) == {'reported_model_unavailable', 'usage_unavailable',
                                              'response_file_unavailable', 'final_message_unavailable',
                                              'interrupted_before_response'}
    assert all(note in callstore.AVAILABILITY_NOTES for note in rec['availability_notes'])
    assert rec['model']['requested'] == 'unrecorded', 'not a guess at which model it was'


def test_a_call_with_no_time_is_not_recorded(tmp_path):
    path = transcript(tmp_path, [prompt('convert'), answer('req-1', 'done', timestamp=None)])
    call = evidence.calls(path, 'session')[0]
    with pytest.raises(evidence.EvidenceError, match='no times'):
        evidence.record(call, path, role='extractor', card_id='h_demo', version=1, receipt_id='r1',
                        instructions=[callstore.instruction('SKILL.md', 'read')])


def test_the_record_carries_the_transcript_lines_of_its_own_call_only(tmp_path):
    """A record's session events are the lines of that call, as the transcript wrote them. Rewriting a
    line before scrubbing would mean the scrubber never saw the line that was published."""
    path = transcript(tmp_path, [prompt('one'), answer('req-1', 'first'),
                                 prompt('two'), answer('req-2', 'second')])
    first, second = evidence.calls(path, 'session')
    rec = evidence.record(first, path, role='extractor', card_id='h_demo', version=1, receipt_id='r1',
                          instructions=[callstore.instruction('SKILL.md', 'read')])
    events = rec['evidence']['session_events'][0].splitlines()
    assert len(events) == len(first['lines'])
    assert all(json.loads(line) for line in events), 'every line is JSON the scrubber can parse'
    assert 'second' not in rec['evidence']['session_events'][0]
    raw = path.read_text().splitlines()
    assert events == [raw[n - 1] for n in first['lines']], 'the lines are the transcript bytes'


@needs_scrubber
def test_a_credential_header_in_the_middle_of_a_line_is_a_known_limit_of_the_policy(tmp_path):
    """A limit of the accepted policy, recorded here so that this kit does not claim more than the
    policy gives it.

    The `credential-header` pattern is anchored to the start of a line, which is where a log writes a
    header. A header quoted **inside** a line - in prose, or in a line of tool output that begins with
    something else - is neither replaced nor refused, because the residual pass inspects with the same
    anchored pattern. Found while testing this adapter and reported to the policy's owners; it is not
    patched here, because a copy of the policy with one extra pattern would be a second policy under
    the same name.

    So this test asserts what is, not what should be. If the policy gains the case, this test fails,
    which is the signal to delete it and to stop warning about it in the hand-over.
    """
    inline = f'the tool printed Cookie: session=ZZZZZZZZZZZZZZZZZZZZ while fetching'
    rec = leaky_record(tmp_path / 'inline-header', prompt_text=inline)
    public, snapshot, _ = evidence.export(rec, secret_inventory=INVENTORY, private_hosts=HOSTS,
                                          where=SCRUBBER_DIR)
    assert 'Cookie: session=' in json.dumps([public, snapshot], ensure_ascii=False), \
        'if this passes no longer, the policy now covers an inline header: delete this test'
    # the same header at the start of its own line is replaced, which is the case the policy promises
    at_line_start = 'the tool printed\nCookie: session=ZZZZZZZZZZZZZZZZZZZZ\nwhile fetching'
    rec = leaky_record(tmp_path / 'line-start-header', prompt_text=at_line_start)
    public, snapshot, _ = evidence.export(rec, secret_inventory=INVENTORY, private_hosts=HOSTS,
                                          where=SCRUBBER_DIR)
    assert 'Cookie: session=' not in json.dumps([public, snapshot], ensure_ascii=False)


@needs_scrubber
def test_an_address_at_the_end_of_a_sentence_is_now_removed(tmp_path):
    """The defect this kit found by running the adapter on real calls, and reported: the policy's email
    pattern required that no `.` follow an address, so `...@example.org.` at the end of a sentence
    survived - six addresses in one record were replaced and the seventh, the operator's own, was not.

    The owners fixed it, and this is the guard for the fix: the pinned bytes are the ones that remove
    it (implementation 74539185..., policy 3fb6dc0d...), and a record scrubbed by them carries no
    address. If this test fails, the pin has moved back to a policy that leaks."""
    leak = 'write to someone@example.org. Then stop.'
    rec = leaky_record(tmp_path / 'address', prompt_text=leak)
    public, snapshot, _ = scrubbed_without_the_net(rec)
    out = json.dumps([public, snapshot], ensure_ascii=False)
    assert 'someone@example.org' not in out and '[EMAIL]' in out, out[:400]
    # and the record goes through, because there is nothing left for the net to refuse
    public, _, _ = evidence.export(rec, secret_inventory=INVENTORY, private_hosts=HOSTS, where=SCRUBBER_DIR)
    assert public['redaction']['policy_sha256'].startswith('3fb6dc0d'), 'the record names the policy it was scrubbed by'


@needs_scrubber
def test_the_net_refuses_an_address_whatever_the_policy_did(tmp_path, monkeypatch):
    """The net is not a bet on the current policy being complete. This drives it directly - by handing
    the cache a stand-in whose `scrub` returns a record with an address in it - because the point of the
    net is the policy gap nobody has found yet, and a test that waits for a real one tests nothing.
    """
    rec = leaky_record(tmp_path / 'net', prompt_text='convert the card')
    real = evidence.scrubber(SCRUBBER_DIR)

    class _Leaky:
        Refused = real.Refused

        @staticmethod
        def scrub(record, *, secret_inventory, private_hosts):
            public, snapshot, audit = real.scrub(record, secret_inventory=secret_inventory,
                                                 private_hosts=private_hosts)
            public['output']['final_message'] = 'write to someone@example.org'
            return public, snapshot, audit

    monkeypatch.setitem(evidence._IMPORTED, str(Path(SCRUBBER_DIR).resolve()), _Leaky)
    with pytest.raises(evidence.EvidenceError, match='still holds an address'):
        evidence.export(rec, secret_inventory=INVENTORY, private_hosts=HOSTS, where=SCRUBBER_DIR)


def scrubbed_without_the_net(rec):
    """What the accepted policy alone returns, so a test can show what the net is for."""
    module = evidence.scrubber(SCRUBBER_DIR)
    return module.scrub(rec, secret_inventory=list(INVENTORY), private_hosts=list(HOSTS))


@needs_scrubber
@pytest.mark.parametrize('shape, text', [
    ('a role name', 'as the arena-tools stream asked'),
    ('a job identifier', 'closing THJOB-abc123'),
    ('the messaging helper', 'answered with tmux-helper reply'),
    ("the owner's role name", 'the rule master set this morning'),
])
def test_the_working_language_of_the_process_is_refused_not_edited(tmp_path, shape, text):
    """The second class of thing that must not be published, and the one no redaction policy should be
    asked to catch, because it is not about secrets.

    Found on the first five real records: they came from a working session of this stream, so its
    charter and its messages were in the model's input, and the records carried role names, message
    identifiers and quoted rules. A record of a call is published to show how a card was made; a call
    whose input was a charter and a stream of messages is not that call. So this is a refusal, and the
    remedy is a run whose whole input is a skill, a card and its sources.
    """
    rec = leaky_record(tmp_path / shape.replace(' ', '-').replace("'", ''), prompt_text=text)
    with pytest.raises(evidence.EvidenceError, match='refusal and not something to edit out'):
        evidence.export(rec, secret_inventory=INVENTORY, private_hosts=HOSTS, where=SCRUBBER_DIR)


@needs_scrubber
def test_the_operator_may_forbid_further_strings(tmp_path):
    """The list is the operator's, like the secret inventory: this kit does not decide it."""
    listing = tmp_path / 'forbidden.txt'
    listing.write_text('# one per line\nthe winter programme\n\n', encoding='utf-8')
    rec = leaky_record(tmp_path / 'forbidden', prompt_text='convert what the winter programme named')
    with pytest.raises(evidence.EvidenceError, match='the operator forbids publishing'):
        evidence.export(rec, secret_inventory=INVENTORY, private_hosts=HOSTS, where=SCRUBBER_DIR,
                        forbidden_file=listing)
    assert evidence.forbidden_strings(listing) == ['the winter programme'], 'comments and blanks are not strings'
    assert evidence.forbidden_strings(None) == [] or os.environ.get(evidence.ENV_FORBIDDEN)


def test_a_record_is_bound_to_the_transcript_it_was_read_from(tmp_path):
    """An independent review's second finding: `calls` read one file and `record` read it again, so a
    transcript replaced in between gave a record with one file's prompt and another's event lines, with
    nothing in it to say so. The call now carries the digest of the bytes it was read from, and a record
    whose file has changed is refused rather than stitched together."""
    path = transcript(tmp_path, [prompt('convert the card'), answer('req-1', 'done')])
    call = evidence.calls(path, 'session')[0]
    assert call['transcript_sha256'] == evidence.transcript_digest(path)
    path.write_text(path.read_text() + answer('req-2', 'something else') + '\n', encoding='utf-8')
    with pytest.raises(evidence.EvidenceError, match='would mix one transcript'):
        evidence.record(call, path, role='extractor', card_id='h_demo', version=1, receipt_id='r1',
                        instructions=[callstore.instruction('SKILL.md', 'read')])


def test_one_answer_is_counted_once(tmp_path):
    """An independent review's third finding: the same native message id can appear twice in a
    transcript, and summing both doubled the token counts - 10 became 20. A repeated answer adds no
    usage and is not a second answer."""
    once = answer('req-1', 'done')
    twice = json.loads(once)
    twice['message']['id'] = 'msg-1'
    first = json.dumps(twice, ensure_ascii=False)
    path = transcript(tmp_path, [prompt('convert'), first, first])
    call = evidence.calls(path, 'session')[0]
    assert call['usage'] == {'input_tokens': 10, 'output_tokens': 3, 'reasoning_tokens': 7}
    assert call['answers'] == 1, 'the same answer twice is one answer'
    # two genuinely different answers of one request do add up
    other = json.loads(once)
    other['message']['id'] = 'msg-2'
    path = transcript(tmp_path / 'two', [prompt('convert'), first, json.dumps(other, ensure_ascii=False)])
    assert evidence.calls(path, 'session')[0]['usage']['output_tokens'] == 6


def test_the_pinned_set_cannot_be_narrowed_or_extended(tmp_path):
    """The first finding in both rounds of review. Round one: `pins` was an argument, so a caller named
    its own file with its own digest. Round two: asking for a subset left the contract unverified, an
    ambient `build_contract` was used even with the accepted file absent, and that partial module was
    cached for every later caller. There is now no way to ask for part of the set."""
    import inspect
    taken = set(inspect.signature(evidence.scrubber).parameters) - {'where'}
    assert not taken, f'scrubber() takes only the directory, not {taken}'
    assert sorted(evidence.SCRUBBER_PINS) == ['build_contract.py', 'scrubber.py']


def test_an_ambient_contract_is_not_used_even_when_the_accepted_file_is_absent(tmp_path, monkeypatch):
    """Round two of the review, the way it was demonstrated: with only the scrubber present, an
    ambient module answered for the contract. Now the contract is part of what is verified, so a
    directory without it cannot produce a module at all."""
    import types
    (tmp_path / 'scrubber.py').write_bytes(
        (Path(SCRUBBER_DIR) / 'scrubber.py').read_bytes() if SCRUBBER_DIR else b'x = 1')
    planted = types.ModuleType('build_contract')
    planted.canonical = lambda rec: b'{}'
    monkeypatch.setitem(sys.modules, 'build_contract', planted)
    evidence._IMPORTED.pop(str(tmp_path.resolve()), None)
    with pytest.raises(evidence.EvidenceError, match='is missing'):
        evidence.scrubber(tmp_path)
    assert str(tmp_path.resolve()) not in evidence._IMPORTED, 'nothing partial is cached'


def test_two_finished_answers_under_one_id_are_refused(tmp_path):
    """Round two, third finding: an exact duplicate was handled, but a *conflicting* one was not - the
    later answer overwrote the final message and the status while the tokens stayed with the first, so
    the record mixed two answers silently. Both of these carry a stop reason, so both are finished."""
    first = json.loads(answer('req-1', 'the first answer'))
    first['message']['id'] = 'msg-1'
    second = json.loads(json.dumps(first))
    second['message']['content'] = [{'type': 'text', 'text': 'a different answer'}]
    second['message']['usage'] = {'input_tokens': 999, 'output_tokens': 999}
    path = transcript(tmp_path, [prompt('convert'), json.dumps(first, ensure_ascii=False),
                                 json.dumps(second, ensure_ascii=False)])
    with pytest.raises(evidence.EvidenceError, match='carry the message id'):
        evidence.calls(path, 'session')


def test_one_answer_written_block_by_block_is_one_answer(tmp_path):
    """How a real transcript writes an answer, measured on one: the harness emits a line per content
    block under the same message id, `stop_reason` null until the last, and the token count on the
    finished line is the call's total (on the transcript this was taken from: 1, 1, then 212 output
    tokens for one answer). An unfinished occurrence is not an answer and adds no usage."""
    part = json.loads(answer('req-1', 'thinking out loud', stop=None))
    part['message']['id'] = 'msg-1'
    part['message']['usage'] = {'input_tokens': 2, 'output_tokens': 1}
    done = json.loads(json.dumps(part))
    done['message']['stop_reason'] = 'tool_use'
    done['message']['usage'] = {'input_tokens': 2, 'output_tokens': 212}
    path = transcript(tmp_path, [prompt('convert'), json.dumps(part, ensure_ascii=False),
                                 json.dumps(part, ensure_ascii=False),
                                 json.dumps(done, ensure_ascii=False)])
    call = evidence.calls(path, 'session')[0]
    assert call['answers'] == 1, 'three lines, one answer'
    assert call['usage']['output_tokens'] == 212, 'the finished line carries the total'
    assert call['status'] == 'completed'


def test_one_read_binds_the_record_to_the_bytes_that_were_hashed(tmp_path):
    """Round two, second finding: the digest came from one read and the event lines from another, so a
    file replaced between them passed the check and then supplied other lines. Both now come from one
    read, and `events` works from that text rather than opening the file again."""
    path = transcript(tmp_path, [prompt('convert'), answer('req-1', 'done')])
    digest, text = evidence.snapshot(path)
    path.write_text('{"type": "user", "isSidechain": false, "message": {"role": "user", "content": "x"}}\n',
                    encoding='utf-8')
    # the text already read still parses, and nothing re-reads the replaced file
    assert [n for n, _, _ in evidence.events(path, text)] == [1, 2]
    assert evidence.snapshot(path)[0] != digest
