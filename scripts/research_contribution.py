"""Explicit, offline research-contribution companion production.

Consumes existing card and known-merge bytes. It never searches, reads sources,
judges novelty or changes a card. The selected standard checks its own envelope.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import threading
import types

PROFILE = 'ohf-research-contribution/1'
STANDARD_COMMIT = '0b6f5ef1003f696220d8bb0b8316260825e4a10c'
PINS = Path(__file__).resolve().parents[1] / 'references/research-standard.json'
CAP = 1048576
_lock = threading.RLock()
_references = {}


class Refusal(ValueError):
    def __init__(self, code, detail):
        self.code, self.detail = code, detail
        super().__init__(code + ': ' + detail)


def require(condition, code, detail):
    if not condition:
        raise Refusal(code, detail)


def sha(raw):
    return 'sha256:' + hashlib.sha256(raw).hexdigest()


def read(path):
    try:
        with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), 'rb') as f:
            require(stat.S_ISREG(os.fstat(f.fileno()).st_mode), 'INPUT_FILE', 'regular file required')
            raw = f.read(CAP + 1)
        require(len(raw) <= CAP, 'INPUT_LIMIT', 'each input is at most 1 MiB')
        return raw
    except (OSError, ValueError) as e:
        if isinstance(e, Refusal):
            raise
        raise Refusal('INPUT_FILE', 'file unavailable or unsafe') from e


def reference(root):
    """Hash the explicit S-A closure, then execute captured modules privately.

    No ambient tools package, bytecode cache, subprocess, or latest checkout.
    Git association is recorded separately from the byte-verified source set.
    """
    pins = json.loads(PINS.read_bytes())
    require(pins['commit'] == STANDARD_COMMIT, 'STANDARD_PIN', 'unsupported standard identity')
    root = Path(root).resolve()
    captured = {name: read(root / name) for name in pins['files']}
    require(all(sha(raw) == pins['files'][name] for name, raw in captured.items()),
            'STANDARD_PIN', 'selected standard source bytes differ')
    key = str(root)
    with _lock:
        if key in _references:
            return _references[key]
        prefix = '_ohf_research_' + hashlib.sha256(key.encode()).hexdigest()
        package = types.ModuleType(prefix)
        package.__path__ = []
        sys.modules[prefix] = package
        order = ('__init__', 'errors', 'codec', 'bindings', 'envelope', 'coverage',
                 'execution', 'quantities', 'dependence', 'research', 'api', 'retention', 'context')
        try:
            for name in order:
                path = 'tools/companions/' + name + '.py'
                fullname = prefix if name == '__init__' else prefix + '.' + name
                module = package if name == '__init__' else types.ModuleType(fullname)
                module.__file__ = str(root / path)
                module.__package__ = prefix
                sys.modules[fullname] = module
                if name != '__init__':
                    setattr(package, name, module)
                exec(compile(captured[path], module.__file__, 'exec'), module.__dict__)
            package.validation_context = package.context.Context.from_repo(root)
        except BaseException:
            for name in list(sys.modules):
                if name == prefix or name.startswith(prefix + '.'):
                    del sys.modules[name]
            raise
        _references[key] = package
        return package


def exact(value, keys, code='REQUEST_SHAPE'):
    require(type(value) is dict and set(value) == set(keys.split()), code, 'missing or extra members')


def nonblank(value):
    return type(value) is str and bool(value.strip())


def _known(raw, api):
    known = api.codec.loads(raw)
    require(type(known) is dict and known.get('schema') == 'ohf-extractor/known-result'
            and type(known.get('schema_version')) is int and known['schema_version'] == 1,
            'KNOWN_FORMAT', 'existing known-merge output required')
    require(known.get('result') in ('known_result', 'tested_unresolved', 'duplicate', 'new', 'incomplete'),
            'KNOWN_FORMAT', 'unknown detector result')
    searched = known.get('searched')
    require(type(searched) is dict, 'KNOWN_COLLECTION', 'search coverage unavailable')
    completion = searched.get('completion')
    require(completion in ('complete', 'partial', 'cards_only', 'failed'),
            'KNOWN_COLLECTION', 'unknown completion state')
    queries, failed = searched.get('queries'), searched.get('failed_calls')
    require(type(queries) is list and len(queries) <= 32 and type(failed) is list,
            'KNOWN_COLLECTION', 'bounded queries and failed-call inventory required')
    require(completion != 'failed' and known.get('result') != 'incomplete' and not failed,
            'COLLECTION_FAILED', 'no companion is emitted from a failed collection')
    ids = set()
    for q in queries:
        require(type(q) is dict and nonblank(q.get('call_id')) and q['call_id'] not in ids
                and nonblank(q.get('query')) and q.get('source') in ('europepmc', 'pubmed'),
                'KNOWN_COLLECTION', 'query identity/source is missing or duplicate')
        ids.add(q['call_id'])
        require(q.get('outcome') == 'ok', 'COLLECTION_FAILED', 'query collection did not complete')
    for field, limit in (('per_query', 60), ('max_works', 60)):
        require(type(searched.get(field)) is int and 0 < searched[field] <= limit,
                'KNOWN_SCOPE', 'unsupported retained selection depth')
    require(type(known.get('works')) is list and len(known['works']) <= searched['max_works']
            and type(known.get('evidence')) is list and type(known.get('input')) is dict,
            'KNOWN_FORMAT', 'known-result members missing')
    require(api.validation_context.date_time(known.get('checked_at')),
            'KNOWN_SCOPE', 'native checked_at timestamp required')
    return known


def _scope(known, api):
    s = known['searched']
    complete = s['completion'] == 'complete' and bool(s['queries'])
    return api.codec.canonical({
        'scope': f"Recorded known-result queries; first {s['per_query']} works per query, at most {s['max_works']} distinct works.",
        'as_of': known['checked_at'], 'queries': [q['query'] for q in s['queries']],
        'coverage': 'complete_within_scope' if complete else 'partial' if s['completion'] == 'partial' else 'unknown',
        'limitation': 'Supplied collection/selection metadata only; not exhaustive literature coverage, relevance, or verified novelty.'})


def search_scope(known_bytes, standard_root):
    """Deterministic retained scope for a future card's search_scope_ref.

    Calling this does not edit the card or turn the old detector's `new` into
    scientific novelty. An existing assessment must already bind these bytes.
    """
    api = reference(standard_root)
    return _scope(_known(known_bytes, api), api)


def _identifiers(work):
    def doi(value):
        v = value.strip().lower()
        for prefix in ('https://doi.org/', 'http://doi.org/', 'doi:'):
            if v.startswith(prefix):
                v = v[len(prefix):]
        return v
    result = set()
    if nonblank(work.get('doi')):
        result.add(doi(work['doi']))
    if nonblank(work.get('pmid')):
        result.update(('pmid:' + work['pmid'], 'https://pubmed.ncbi.nlm.nih.gov/' + work['pmid'] + '/'))
    if nonblank(work.get('pmcid')):
        result.add(work['pmcid'].lower())
    return result


def produce(card_bytes, known_bytes, request_bytes, standard_root):
    """Return envelope/artifacts/report only after standard api.evaluate passes.

    Request pointers reuse card values; only contribution_type,
    replication_justification and outcome_additions introduce annotations.
    Supplied metadata/attribution are not authenticated or scientifically judged.
    """
    api = reference(standard_root)
    known = _known(known_bytes, api)
    request = api.codec.loads(request_bytes)
    exact(request, 'format origin actor novelty_claim selections annotations')
    require(request['format'] == 'ohf-extractor-research-request/1', 'REQUEST_VERSION', 'unsupported request')
    selection = request['selections']
    exact(selection, 'proposal question next_test novelty positive_prediction negative_prediction known_results')
    annotations = request['annotations']
    exact(annotations, 'contribution_type replication_justification outcome_additions')
    require(request['origin'] in ('author_proposal', 'ai_addition', 'other_addition')
            and nonblank(request['actor']), 'ORIGIN', 'explicit attribution required')
    zone = 'author' if request['origin'] == 'author_proposal' else 'added'
    doc = api.codec.parse(card_bytes)
    require(type(doc.value) is dict, 'CARD_FORMAT', 'card object required')
    bindings = []
    def bind(pointer, role, same_zone=True):
        if pointer is None:
            return None
        require(type(pointer) is str, 'CARD_BINDING', 'explicit pointer required')
        import re
        match = re.fullmatch(r'/(author|added)/layers/' + api.research.PATHS[role][1], pointer)
        require(match is not None, 'CARD_BINDING', 'pointer does not select this field class')
        require(not same_zone or match[1] == zone, 'ORIGIN', 'addition cannot select author content or conversely')
        try:
            b = api.bindings.make_binding(doc, 'card', 'record', pointer, api.research.PATHS[role][0], pointer)
        except KeyError as error:
            raise Refusal('CARD_BINDING', 'selected card member does not exist') from error
        if b not in bindings:
            bindings.append(b)
        return b['id']
    proposal = bind(selection['proposal'], 'proposal')
    require(proposal is not None, 'CARD_BINDING', 'proposal required')
    text = api.research.unwrap(doc.resolve(selection['proposal']))
    require(nonblank(text) and known['input'].get('text_sha256') == sha(text.encode('utf-8')),
            'KNOWN_TARGET', 'known search targets another proposal')
    scope = _scope(known, api)
    claim = request['novelty_claim']
    require(claim in ('unknown', 'not_new', 'novel'), 'NOVELTY', 'unsupported assertion')
    require(claim != 'novel' or api.codec.loads(scope)['coverage'] == 'complete_within_scope',
            'NOVEL_WITHOUT_COMPLETE_SEARCH', 'missing or partial coverage remains unknown')
    selected = selection['known_results']
    require(type(selected) is list and len(selected) <= 32, 'KNOWN_BINDING', 'bounded prior results required')
    known_pairs, indices = [], set()
    for item in selected:
        exact(item, 'work_index result reference')
        index = item['work_index']
        require(type(index) is int and 0 <= index < len(known['works']) and index not in indices,
                'KNOWN_BINDING', 'unknown, duplicate or non-integer work index')
        indices.add(index)
        work = known['works'][index]
        require(type(work) is dict and work.get('quote_check') == 'verified'
                and work.get('verdict') in ('tests_supports', 'tests_refutes', 'tests_mixed')
                and any(type(e) is dict and e.get('kind') == 'work'
                        and type(e.get('index')) is int and e['index'] == index for e in known['evidence']),
                'KNOWN_BINDING', 'selected work is not a recorded known-result evidence item')
        rb = bind(item['result'], 'result', False)
        cb = bind(item['reference'], 'reference', False)
        require(rb is not None and cb is not None, 'KNOWN_BINDING', 'prior result and identifier required')
        ident = api.research.unwrap(doc.resolve(item['reference']))
        require(nonblank(ident) and bool(_identifiers({'doi': ident}) & _identifiers(work)),
                'KNOWN_REFERENCE', 'card identifier does not name the selected known work')
        known_pairs.append({'result_binding': rb, 'reference_binding': cb})
    require(claim != 'not_new' or bool(known_pairs), 'KNOWN_BINDING', 'not_new needs bound known results')
    row = {'id': 'contribution', 'origin': request['origin'], 'proposal_binding': proposal,
           'known_results': known_pairs, 'assertion_ref': {'artifact': 'declaration', 'selector': '/contribution'}}
    for key, role in (('question', 'question'), ('next_test', 'test'), ('novelty', 'novelty'),
                      ('positive_prediction', 'prediction'), ('negative_prediction', 'prediction')):
        row[key + '_binding'] = bind(selection[key], role)
    justification = annotations['replication_justification']
    if justification is not None:
        exact(justification, 'reason changed_conditions prior_result_pointer')
        matches = [p['result_binding'] for p, i in zip(known_pairs, selected)
                   if i['result'] == justification['prior_result_pointer']]
        require(len(matches) == 1, 'REPLICATION', 'justification must select one bound prior result')
        justification = {k: justification[k] for k in ('reason', 'changed_conditions')} | {'prior_result_binding': matches[0]}
    declaration = api.codec.canonical({'contribution': {
        'origin': request['origin'], 'actor': request['actor'], 'novelty_claim': claim,
        'contribution_type': annotations['contribution_type'], 'replication_justification': justification,
        'outcome_additions': annotations['outcome_additions']}})
    artifacts = {'card': card_bytes, 'known_result': known_bytes, 'request': request_bytes,
                 'search': scope, 'declaration': declaration}
    release = doc.value
    for key in ('added', 'by', 'standard_release', 'version'):
        release = release.get(key) if type(release) is dict else None
    records = [api.envelope.artifact(k, 'card' if k == 'card' else 'declaration', v,
                                    doc.value.get('standard_version') if k == 'card' else None,
                                    release if k == 'card' else None) for k, v in artifacts.items()]
    ctx = api.validation_context
    component = {'id': 'research', 'profile': PROFILE, 'policy_id': ctx.policy(PROFILE)['id'],
                 'policy_sha256': ctx.policy_digest(PROFILE), 'binding_ids': [b['id'] for b in bindings],
                 'provenance': {'artifact': 'request', 'selector': '/annotations'}, 'payload': {'records': [row]}}
    wire = api.codec.canonical(api.envelope.new(ctx, records, bindings, [component]))
    report = api.api.evaluate(wire, artifacts, ctx, required_profile=PROFILE, require_retention=True)
    return wire, artifacts, report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--standard-root', required=True, type=Path)
    commands = parser.add_subparsers(dest='mode', required=True)
    scope = commands.add_parser('scope', help='derive retained bounded scope; no card edits')
    scope.add_argument('known_result', type=Path)
    build = commands.add_parser('produce', help='validate and exclusively export one opt-in companion')
    for name in ('card', 'known_result', 'request', 'output'):
        build.add_argument(name, type=Path)
    args = parser.parse_args(argv)
    try:
        api = reference(args.standard_root)
        if args.mode == 'scope':
            print(search_scope(read(args.known_result), args.standard_root).decode('utf-8'))
        else:
            wire, artifacts, report = produce(read(args.card), read(args.known_result), read(args.request), args.standard_root)
            api.retention.export_bundle(args.output, wire, artifacts, api.validation_context, required_profile=PROFILE)
            print(api.codec.canonical(report).decode('utf-8'))
        return 0
    except Refusal as error:
        print(json.dumps({'status': 'REFUSE', 'code': error.code, 'detail': error.detail}))
        return 2
    except Exception as error:
        # Only the selected standard's expected typed refusals are translated.
        if 'api' in locals() and isinstance(error, api.errors.ContractError):
            print(json.dumps({'status': 'REFUSE', **error.record()}))
            return 2
        raise


if __name__ == '__main__':
    sys.exit(main())
