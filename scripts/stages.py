"""Fix the search step and the first draft without changing how an article is extracted.

  search.py close-step --workdir DIR
  stages.py build BUILDER.py --from-log --workdir DIR

The builder defines build(calls, workdir) and returns its card. It receives the written search
records, not a search client. Search calls and in-process urllib requests raise during the build,
even if a caller tries to catch that error. This is a workflow guard for kit builders, not a sandbox
for hostile Python or child processes. Source documents must already be in the work directory.
"""
import argparse
import copy
from contextlib import ExitStack
import http.client
import json
import os
from pathlib import Path
import sys
import socket
import tempfile
import urllib.request
from unittest.mock import patch

import ohfkit
import search

STEP = search.STEP_ONE
DRAFT = 'first-draft'
DECISION_KEYS = {'verdict', 'verdicts', 'direction'}
DECISION_TOOLS = {'not_cited', 'relevance', 'known_result'}


class StageError(RuntimeError):
    pass


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode()


def has_decision(value):
    if isinstance(value, dict):
        return bool(DECISION_KEYS & value.keys()) or any(has_decision(v) for v in value.values())
    return isinstance(value, list) and any(has_decision(v) for v in value)


def log_snapshot(workdir):
    """Parse the actual log, but project only call/work metadata into the stop record."""
    path = Path(workdir) / search.LOG
    if not path.is_file():
        raise StageError('search-log.jsonl is missing; run the search before closing its step')
    raw = path.read_bytes()
    try:
        calls = [json.loads(line) for line in raw.decode().splitlines() if line.strip()]
    except (ValueError, UnicodeError) as error:
        raise StageError('the search log is not complete JSON lines') from error
    if not calls or any(not isinstance(r, dict) or not r.get('call_id') or not r.get('tool') for r in calls):
        raise StageError('the search log needs at least one complete call with call_id and tool')
    if len({r['call_id'] for r in calls}) != len(calls):
        raise StageError('the search log repeats a call_id')
    if any(r['tool'] in DECISION_TOOLS or has_decision(r) for r in calls):
        raise StageError('step 1 already contains line-building decisions; use a fresh search log')
    works = []
    for call in calls:
        for work in call.get('works', []):
            types = sorted(set(search.pub_types(work)) |
                           {t.strip() for t in (work.get('type') or '').split(';') if t.strip()})
            works.append({'call_id': call['call_id'], **{k: work.get(k) for k in
                          ('source_id', 'doi', 'pmid', 'pmcid', 'title')}, 'publication_types': types})
    return calls, {'file': search.LOG, 'sha256': search.sha256(raw), 'call_count': len(calls), 'works': works}


def kit_identity():
    return {'version': ohfkit.CONVERTER['version'], 'rules_hash': ohfkit.rules_hash()}


def close_step(workdir):
    """Fix only the log. No card, verdict, screen or closeout is requested or run."""
    workdir = Path(workdir)
    with search.store_lock(workdir):
        search.search_open(workdir)
        _, log = log_snapshot(workdir)
        record = {'schema': 'ohf-search-step/1', 'closed_at': ohfkit.now(), 'kit': kit_identity(), 'log': log}
        with (workdir / STEP).open('xb') as file:
            file.write(encoded(record))
        return record


def fixed_log(workdir):
    """The exact closed log and its stop record; refuse missing, changed or differently built input."""
    path = Path(workdir) / STEP
    if not path.is_file():
        raise StageError('step-1.json is missing; close the search before building from its log')
    raw = path.read_bytes()
    record = json.loads(raw)
    calls, log = log_snapshot(workdir)
    if record.get('schema') != 'ohf-search-step/1' or record.get('log') != log:
        raise StageError('the search log or its stop record changed after close-step')
    if record.get('kit') != kit_identity():
        raise StageError('the closed step belongs to different kit rules; do not relabel a historical search')
    return calls, record, search.sha256(raw)


def draft_rights(card, workdir):
    """A draft may not carry text that the card's sources may not supply. No entailment pass runs."""
    import entailment

    docs = entailment.docs_for(card, workdir)
    main = next((d for d in docs.values() if d.sha == card['author']['source']['source_text_sha256']), None)
    if main is None or ohfkit.source_licence(card, main) != card['author']['source']['license']:
        raise StageError('draft main-source licence is not established from the article itself')
    # Reference-only records can name works without quoting them. Every document supplying text
    # must grant a licence the same kit accepts; this includes secondary sources, not just the main.
    for rec in card['added']['sources'].values():
        if ohfkit.REFERENCE_ONLY_MARK not in rec.get('tool', ''):
            if rec['source'] not in docs:
                raise StageError('draft has an unopened text source')
            docs[rec['source']].licence()

    def quotes(node, source=None):
        if isinstance(node, dict):
            source = node.get('src', source)
            if 'quote' in node or 'basis_quote' in node:
                rec = card['added']['sources'].get(source, {})
                if ohfkit.REFERENCE_ONLY_MARK in rec.get('tool', ''):
                    raise StageError('draft quotes a reference-only work')
            for value in node.values():
                quotes(value, source)
        elif isinstance(node, list):
            for value in node:
                quotes(value, source)
    quotes(card['added']['layers'])


def build_from_log(builder, workdir):
    """Run the ordinary builder on closed records, and atomically fix a separate first-draft bundle."""
    workdir, builder = Path(workdir).resolve(), Path(builder).resolve()
    with search.store_lock(workdir):
        if (workdir / DRAFT).exists():
            raise StageError('first draft already exists; critics must work on a copy')
        calls, step, step_hash = fixed_log(workdir)
        code = builder.read_bytes()
        attempts = []

        def forbidden(*args, **kwargs):
            attempts.append(True)
            raise search.StepClosedError('search/network call forbidden during --from-log build')

        with ExitStack() as guard:
            for target, method in (
                    (search.Searcher, 'call'), (search.Searcher, 'fetch'), (search, 'http_get'),
                    (urllib.request, 'urlopen'), (urllib.request.OpenerDirector, 'open'),
                    (http.client.HTTPConnection, 'connect'), (http.client.HTTPConnection, 'send'),
                    (http.client.HTTPSConnection, 'connect'), (socket, 'create_connection'),
                    (socket, 'SocketType'), (socket, 'socketpair'), (socket, 'fromfd'),
                    (socket.socket, '__new__'), (socket.socket, 'connect'), (socket.socket, 'connect_ex')) + tuple(
                        (socket.socket, name) for name in dir(socket.socket)
                        if name.startswith('send') and callable(getattr(socket.socket, name))):
                # Guard construction even through an already imported socket class, and guard all
                # send variants on sockets that already exist (sendmsg needs no connect/sendto).
                refusal = staticmethod(forbidden) if method == '__new__' else forbidden
                guard.enter_context(patch.object(target, method, refusal))
            namespace = {'__name__': 'ohf_draft_builder', '__file__': str(builder)}
            exec(compile(code, str(builder), 'exec'), namespace)
            if not callable(namespace.get('build')):
                raise StageError('builder must define build(calls, workdir) and return its card')
            card = namespace['build'](copy.deepcopy(calls), workdir)
            if attempts:
                raise StageError('builder attempted a search/network call, even though it caught the refusal')
            if fixed_log(workdir)[2] != step_hash:
                raise StageError('builder changed the closed step')
            card = copy.deepcopy(card)
            by = card['added']['by']
            if (by.get('converter_version') != ohfkit.CONVERTER['version'] or
                    by.get('converter_hash') != ohfkit.rules_hash()):
                raise StageError('builder card does not name the kit rules that built this draft')
            draft_rights(card, workdir)
            # Stage files are built off to the side and become visible together. Failed staging
            # directories are retained for diagnosis, never silently deleted or reused.
            staging = Path(tempfile.mkdtemp(prefix='.first-draft-', dir=workdir))
            ohfkit.finish(card, staging / 'card.json')
            raw = (staging / 'card.json').read_bytes()
            record = {'schema': 'ohf-first-draft/1', 'frozen_at': ohfkit.now(), 'kit': kit_identity(),
                      'step_1_sha256': step_hash, 'log_sha256': step['log']['sha256'],
                      'builder_sha256': search.sha256(code), 'card_sha256': search.sha256(raw),
                      'content_hash': card['content_hash']}
            (staging / 'record.json').write_bytes(encoded(record))
            for name in ('card.json', 'record.json'):
                (staging / name).chmod(0o444)
            os.rename(staging, workdir / DRAFT)
            return record


def check_draft(workdir):
    """Check frozen bytes against their record, also when inspecting a later version of the kit."""
    workdir = Path(workdir)
    record = json.loads((workdir / DRAFT / 'record.json').read_bytes())
    raw = (workdir / DRAFT / 'card.json').read_bytes()
    step_raw = (workdir / STEP).read_bytes()
    step = json.loads(step_raw)
    if (record.get('schema') != 'ohf-first-draft/1' or search.sha256(raw) != record.get('card_sha256') or
            search.sha256(step_raw) != record.get('step_1_sha256') or
            search.sha256((workdir / search.LOG).read_bytes()) != record.get('log_sha256') or
            step.get('kit') != record.get('kit')):
        raise StageError('the fixed draft, its search log, or its record changed')
    card = json.loads(raw)
    if ohfkit.content_hash(card) != record.get('content_hash') or card.get('content_hash') != record['content_hash']:
        raise StageError('the fixed draft content hash does not match its record')
    return record


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('command', choices=['close-step', 'build', 'check'])
    parser.add_argument('builder', nargs='?')
    parser.add_argument('--workdir', default='.')
    parser.add_argument('--from-log', action='store_true')
    args = parser.parse_args(argv)
    if args.command == 'build' and (not args.from_log or not args.builder):
        parser.error('build requires BUILDER.py and --from-log; it never performs a search')
    try:
        result = (close_step(args.workdir) if args.command == 'close-step' else
                  check_draft(args.workdir) if args.command == 'check' else build_from_log(args.builder, args.workdir))
    except (StageError, search.StepClosedError, ohfkit.LicenceError, OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
