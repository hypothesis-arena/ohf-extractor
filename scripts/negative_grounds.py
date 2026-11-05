"""Check pinned negative-claim grounds OFFLINE; never establish scientific absence.

Standalone development sidecar. No card changes, search, native converter, entailment or model.
Only explicit relative artifact references beneath a trusted local bundle root are read.
"""
import argparse
import datetime as dt
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import xml.etree.ElementTree as ET
from urllib.parse import urlsplit, parse_qs

from jsonschema import Draft202012Validator
from search import VARIANTS, epmc_until, pubmed_until

SCHEMA_PATH = Path(__file__).resolve().parents[1] / 'references/negative-grounds.schema.json'
CONTRACT = json.loads(SCHEMA_PATH.read_text())
BASE = {'version': '0.9.12', 'rules_hash': 'sha256:7617c9401cff1948f9cf8e50ce4e8e522e21cd27a0948bcc27817fdc254da0b3'}
MAX_BYTES = 8 * 1024 * 1024
MAX_CALLS = 2048
MAX_TOTAL = 32 * 1024 * 1024
MAX_FILES = 64
RETAINED_STATES = {'unknown', 'unavailable', 'not_searched', 'partial'}
HASH = re.compile(r'sha256:[0-9a-f]{64}')
CLOCK = re.compile(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})')
LIMITS = [
    'Grounded contract only: no scientific entailment, truth, absence or inventory-completeness verdict.',
    'Finite search cannot establish universal literature absence; original kind is retained.',
    'Owner/completion/reading/judgement sidecars are supplied attestations, not authenticated observations.',
    'Main JATS XML with exact DOI/card binding and paragraph inventory only; no automatic legacy adapter.',
    'Paragraph coverage does not independently certify tables, figures, non-paragraph content or actual reading.',
    'No HTTP/model/production conversion/scoring; no change to the card or historical budget.',
]


class GroundError(ValueError):
    def __init__(self, code, detail, status='invalid'):
        super().__init__(detail)
        self.code, self.detail, self.status = code, detail, status


def require(ok, code, detail, status='invalid'):
    if not ok:
        raise GroundError(code, detail, status)


def sha(raw):
    return 'sha256:' + hashlib.sha256(raw).hexdigest()


def strict_json(raw):
    def pairs(items):
        out = {}
        for key, value in items:
            require(key not in out, 'DUPLICATE_JSON_KEY', key)
            out[key] = value
        return out
    def bad_number(value):
        raise GroundError('NONFINITE_JSON', value)
    def finite_float(value):
        number = float(value)
        require(math.isfinite(number), 'NONFINITE_JSON', value)
        return number
    try:
        return json.loads(raw, object_pairs_hook=pairs, parse_constant=bad_number,
                          parse_float=finite_float)
    except (ValueError, UnicodeError, RecursionError) as error:
        if isinstance(error, GroundError):
            raise
        raise GroundError('MALFORMED_JSON', type(error).__name__) from error


def shape(value, definition):
    validator = Draft202012Validator({'$ref': '#/$defs/' + definition, '$defs': CONTRACT['$defs']})
    errors = sorted(validator.iter_errors(value), key=lambda e: str(list(e.absolute_path)))
    require(not errors, 'CONTRACT_SHAPE', definition + ': ' +
            ('/'.join(map(str, errors[0].absolute_path)) + ': ' + errors[0].message if errors else ''))
    return value


def instant(value):
    require(isinstance(value, str) and CLOCK.fullmatch(value), 'TIMEZONE_REQUIRED', str(value))
    if not value.endswith('Z'):
        offset = value[-6:]
        require(offset != '-00:00' and int(offset[1:3]) < 24 and int(offset[4:]) < 60,
                'INVALID_TIMEZONE', value)
    try:
        return dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError as error:
        raise GroundError('INVALID_TIME', value) from error


def number(value, minimum=0):
    return type(value) is int and value >= minimum


def source_id(value, work=False):
    shape(value, 'work_id' if work else 'source_id')
    pattern = {'pmcid': r'PMC[1-9][0-9]*', 'pmid': r'[1-9][0-9]*',
               'doi': r'10\.[0-9]{4,9}/[^\s]+'}[value['namespace']]
    require(re.fullmatch(pattern, value['value']) is not None, 'SOURCE_ID', str(value))
    return value['namespace'], value['value']


def pointer(document, path):
    require(isinstance(path, str) and path.startswith('/') and not re.search(r'~(?![01])', path),
            'CARD_POINTER', str(path))
    value = document
    try:
        for token in path[1:].split('/'):
            token = token.replace('~1', '/').replace('~0', '~')
            if isinstance(value, list):
                require(re.fullmatch(r'0|[1-9][0-9]*', token), 'CARD_POINTER', path)
                value = value[int(token)]
            else:
                require(isinstance(value, dict), 'CARD_POINTER', path)
                value = value[token]
    except (KeyError, IndexError) as error:
        raise GroundError('CARD_POINTER', path) from error
    return value


def os_path(value):
    """Validate OS path text before Path/stat/open; keep malformed input in diagnostics."""
    require(isinstance(value, str) and '\x00' not in value and
            not any(0xD800 <= ord(c) <= 0xDFFF for c in value), 'ARTIFACT_PATH', repr(value))
    try:
        os.fsencode(value)
    except (UnicodeError, ValueError) as error:
        raise GroundError('ARTIFACT_PATH', repr(value)) from error
    return value


class Bundle:
    """Bounded explicit reads, no fallback discovery. Input directory itself is trusted local context."""
    def __init__(self, root):
        try:
            self.root = Path(os_path(os.fspath(root))).resolve()
        except GroundError:
            raise
        except (OSError, ValueError) as error:
            raise GroundError('ARTIFACT_PATH', type(error).__name__) from error
        self.snapshot = {}
        self.pins = {}
        self.total = 0

    def read(self, name):
        name = os_path(name)
        path = Path(name)
        require(not path.is_absolute() and name == path.as_posix() and
                all(p not in ('', '.', '..') for p in name.split('/')), 'ARTIFACT_PATH', name)
        if name in self.snapshot:
            return self.snapshot[name]
        require(len(self.snapshot) < MAX_FILES, 'ARTIFACT_COUNT', 'Snapshot file cap', 'unavailable')
        current = self.root
        try:
            for part in path.parts:
                current = current / part
                require(not current.is_symlink(), 'ARTIFACT_SYMLINK', name)
            fd = os.open(current, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(fd, 'rb') as stream:
                info = os.fstat(stream.fileno())
                require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1, 'ARTIFACT_TYPE', name)
                raw = stream.read(MAX_BYTES + 1)
            require(len(raw) <= MAX_BYTES, 'ARTIFACT_SIZE', name, 'unavailable')
        except GroundError:
            raise
        except ValueError as error:
            raise GroundError('ARTIFACT_PATH', repr(name) + ': ' + type(error).__name__) from error
        except OSError as error:
            raise GroundError('ARTIFACT_UNAVAILABLE', name + ': ' + type(error).__name__, 'unavailable') from error
        require(self.total + len(raw) <= MAX_TOTAL, 'ARTIFACT_TOTAL_SIZE', 'Snapshot byte cap', 'unavailable')
        self.total += len(raw)
        self.snapshot[name] = raw
        self.pins[name] = sha(raw)
        return raw

    def pinned(self, reference, definition=None):
        raw = self.read(reference['file'])
        require(sha(raw) == reference['sha256'], 'HASH_DRIFT', reference['file'])
        if definition is None:
            return raw
        return shape(strict_json(raw), definition)


class NoDeclarations(ET.TreeBuilder):
    def doctype(self, name, pubid, system):
        # Parser callback before entity expansion, independent of UTF-8/UTF-16 byte encoding.
        raise GroundError('SOURCE_XML_DECLARATION', 'DTD/entities unsupported')


def main_source(card, source, raw):
    try:
        root = ET.fromstring(raw, parser=ET.XMLParser(target=NoDeclarations()))
    except (ET.ParseError, LookupError) as error:
        raise GroundError('SOURCE_XML', type(error).__name__, 'unavailable') from error
    require(root.tag == 'article', 'SOURCE_FORMAT', 'Only unnamespaced JATS article supported', 'unavailable')
    ids = {}
    for element in root.findall('./front/article-meta/article-id'):
        kind = element.get('pub-id-type')
        if kind not in ('doi', 'pmc'):
            continue
        value = ''.join(element.itertext()).strip()
        if kind == 'pmc':
            kind, value = 'pmcid', value if value.startswith('PMC') else 'PMC' + value
        require(kind not in ids or ids[kind] == value, 'SOURCE_ID_CONFLICT', kind)
        ids[kind] = value
    author = card.get('author')
    require(isinstance(author, dict) and isinstance(author.get('source'), dict), 'CARD_SOURCE_SHAPE', 'Native main source object')
    native = author['source']
    ns, value = source_id(source['id'])
    require(ids.get(ns) == value, 'SOURCE_ID_MISMATCH', 'JATS main article identifiers')
    require(isinstance(native.get('doi'), str) and native['doi'] == ids.get('doi'),
            'CARD_SOURCE_ID', 'Card main DOI must equal JATS main DOI; no guessed aliases')
    require(native.get('source_text_sha256') == source['sha256'], 'CARD_SOURCE_HASH', 'Main source hash')
    require(native.get('retrieved_at') == source['retrieved_at'], 'SOURCE_VERSION', 'Exact retrieved_at differs')
    instant(source['retrieved_at'])
    require(source['state'] == 'complete', 'SOURCE_NOT_COMPLETE', source['state'], source['state'])
    paragraphs = [' '.join(''.join(p.itertext()).split()) for p in root.iter('p')]
    require(paragraphs, 'SOURCE_EMPTY', 'No native paragraph addresses', 'unavailable')
    return paragraphs


def expected_owner(card, request):
    require(card.get('schema') == 'ohf:hypothesis@1' and isinstance(card.get('id'), str) and
            card['id'].strip() and number(card.get('version'), 1), 'CARD_ID', 'Native id/version required')
    identity = card.get('identity', {})
    require(isinstance(identity, dict) and (not identity or (identity.get('proposition_id') == card['id'] and
                            identity.get('version') == card['version'])), 'CARD_ID', 'Contradictory identity')
    return {'card_id': card['id'], 'card_version': card['version'], 'card_sha256': request['card']['sha256'],
            'source_id': request['source']['id'], 'source_sha256': request['source']['sha256'],
            'source_retrieved_at': request['source']['retrieved_at'], 'source_state': request['source']['state']}


def same_owner(value, owner):
    shape(value, 'owner')
    require(value == owner, 'FOREIGN_OWNER', 'Card/source/version owner binding differs')


def native_work(work):
    value = work.get('source_id')
    require(isinstance(value, str) and ':' in value, 'WORK_ID', 'Namespaced native source_id required')
    ns, ident = value.split(':', 1)
    namespace = {'MED': 'pmid', 'PMC': 'pmcid', 'DOI': 'doi'}.get(ns)
    require(namespace is not None, 'WORK_NAMESPACE', str(ns))
    key = source_id({'namespace': namespace, 'value': ident}, work=True)
    for field, actual in (('pmid', 'MED'), ('pmcid', 'PMC'), ('doi', 'DOI')):
        if ns == actual and work.get(field) is not None:
            require(work[field] == ident, 'WORK_ID_CONFLICT', field)
    return key


def sent_query(ask, scope, ident):
    """Render the exact native v0.9.12 query/sent/variant/as_of producer contract."""
    require(isinstance(ask, dict) and ask.get('source') == scope['service'] and
            ask.get('query') == scope['query'] and ask.get('as_of') == scope['as_of'] and
            ('as_of' in ask) == (scope['as_of'] is not None) and number(ask.get('limit'), 1),
            'CALL_SCOPE', ident)
    variant = ask.get('variant')
    require(isinstance(variant, str) and variant in VARIANTS and 'sent_query' not in ask,
            'CALL_QUERY_BINDING', ident)
    sent = VARIANTS[variant][scope['service']].format(ask['query'])
    if scope['as_of'] is not None:
        sent = (epmc_until if scope['service'] == 'europepmc' else pubmed_until)(sent, scope['as_of'])
    require(('sent' in ask) == (sent != ask['query']) and ask.get('sent', ask['query']) == sent,
            'CALL_QUERY_BINDING', ident)
    return sent


def search_basis(bundle, evidence, claim, owner, made):
    if evidence is None:
        raise GroundError('NO_SEARCH_GROUNDS', 'No log/run/stop references', 'not_searched')
    raw = bundle.pinned(evidence['log'])
    try:
        calls = [strict_json(line) for line in raw.decode().splitlines() if line.strip()]
    except UnicodeError as error:
        raise GroundError('LOG_ENCODING', 'UTF-8 required') from error
    require(0 < len(calls) <= MAX_CALLS, 'LOG_EMPTY_OR_LIMIT', 'Nonempty bounded log required', 'insufficient')
    require(all(isinstance(c, dict) for c in calls), 'LOG_SHAPE', 'Native call objects required')
    ids = [c.get('call_id') for c in calls]
    require(all(isinstance(i, str) and re.fullmatch(r'[A-Za-z0-9_.-]+', i) for i in ids) and
            len(set(ids)) == len(ids), 'CALL_ID', 'Unique native call IDs required')
    by_id = {'call:' + c['call_id']: c for c in calls}
    step = strict_json(bundle.pinned(evidence['step']))
    require(isinstance(step, dict) and step.get('schema') == 'ohf-search-step/1' and step.get('kit') == BASE,
            'STOP_IDENTITY', 'Native v0.9.12 exact rules stop required')
    fixed = step.get('log', {})
    require(isinstance(fixed, dict), 'STOP_LOG', 'Native log object')
    require(fixed.get('file') == Path(evidence['log']['file']).name == 'search-log.jsonl' and
            fixed.get('sha256') == evidence['log']['sha256'] and
            type(fixed.get('call_count')) is int and fixed['call_count'] == len(calls),
            'STOP_LOG', 'Stop does not bind this exact nonempty log')
    close_time = instant(step.get('closed_at'))
    runs = bundle.pinned(evidence['runs'], 'runs')
    same_owner(runs['owner'], owner)
    require(runs['log_sha256'] == evidence['log']['sha256'] and runs['scope'] == claim['scope'] and
            runs['proposition_sha256'] == sha(claim['proposition'].encode()), 'SEARCH_BINDING', 'Run scope/proposition/log')
    require(close_time <= instant(runs['recorded_at']) <= made, 'SEARCH_TIME', 'Run sidecar or stop time')
    required = evidence['required_run_ids']
    run_ids = [r['id'] for r in runs['runs']]
    require(len(set(run_ids)) == len(run_ids) and set(run_ids) == set(required),
            'REQUIRED_RUNS', 'Exactly all explicitly required runs, no global pool rescue')
    bindings = runs['call_bindings']
    require(len({x['call_id'] for x in bindings}) == len(bindings) and
            {x['call_id'] for x in bindings} == set(by_id), 'CALL_OWNERSHIP', 'Every local call exactly once')
    owners = {x['call_id']: x for x in bindings}
    for binding in bindings:
        same_owner(binding['owner'], owner)
    used = set()
    source_at = instant(owner['source_retrieved_at'])
    for run in runs['runs']:
        same_owner(run['owner'], owner)
        start, finish, stop_at = map(instant, (run['started_at'], run['finished_at'], run['stop']['at']))
        assessed = instant(run['assessed_at'])
        require(source_at <= start <= finish <= stop_at <= close_time <= assessed <= instant(runs['recorded_at']),
                'RUN_TIME', run['id'])
        if run['state'] != 'completed':
            state = {'failed': 'unavailable', 'not_searched': 'not_searched'}.get(run['state'], run['state'])
            raise GroundError('RUN_NOT_COMPLETED', run['id'] + ': ' + run['state'], state)
        require(run['stop']['reason'] == 'exhausted', 'RUN_STOP', run['id'] + ': ' + run['stop']['reason'], 'partial')
        require(run['conclusion'] == 'not_found', 'RUN_NO_NOT_FOUND_CONCLUSION', run['id'], run['conclusion'])
        if run['scope']['as_of'] is not None:
            try:
                dt.date.fromisoformat(run['scope']['as_of'])
            except ValueError as error:
                raise GroundError('SEARCH_CUTOFF', run['id']) from error
        expected_judgements = set()
        for ident in run['call_ids']:
            require(ident in by_id and ident not in used, 'CALL_REFERENCE', ident)
            require(owners[ident]['run_id'] == run['id'], 'CALL_RUN_OWNER', ident)
            used.add(ident)
            call = by_id[ident]
            if 'owner' in call:
                same_owner(call['owner'], owner)
            require(call.get('tool') == 'literature' and call.get('kit') == 'ohf-extractor/0.9.12',
                    'CALL_TOOL_KIT', ident)
            cstart, cfinish = instant(call.get('started_at')), instant(call.get('finished_at'))
            require(start <= cstart <= cfinish <= finish, 'CALL_TIME', ident)
            if call.get('outcome') != 'ok':
                raise GroundError('CALL_NOT_OK', ident + ': ' + str(call.get('outcome')), 'unavailable')
            require(not call.get('error'), 'CALL_CONTRADICTION', ident)
            require(not any(call.get(k) for k in ('truncated', 'capped', 'partial')) and
                    call.get('completion', 'complete') == 'complete', 'CALL_PARTIAL', ident, 'partial')
            ask = call.get('ask', {})
            actual_query = sent_query(ask, run['scope'], ident)
            works = call.get('works')
            require(isinstance(works, list) and all(isinstance(w, dict) for w in works) and
                    number(call.get('found')) and call['found'] == len(works) and number(call.get('hit_count')),
                    'CALL_COUNTS', ident)
            require(call['hit_count'] >= call['found'], 'CALL_COUNTS', ident)
            require(call['hit_count'] == call['found'] and call['found'] <= ask['limit'],
                    'CALL_CAPPED_OR_PARTIAL', ident, 'partial')
            responses = call.get('responses')
            require(isinstance(responses, list) and responses, 'CALL_RESPONSES', ident, 'unavailable')
            saw_search_response = False
            for response in responses:
                require(isinstance(response, dict) and type(response.get('status')) is int and response['status'] == 200
                        and isinstance(response.get('sha256'), str) and HASH.fullmatch(response['sha256']),
                        'RESPONSE_STATUS', ident, 'unavailable')
                require(cstart <= instant(response.get('at')) <= cfinish, 'RESPONSE_TIME', ident)
                require(isinstance(response.get('url'), str) and response['url'], 'RESPONSE_URL', ident)
                try:
                    url = urlsplit(response['url'])
                except ValueError as error:
                    raise GroundError('RESPONSE_URL', ident) from error
                host = 'www.ebi.ac.uk' if run['scope']['service'] == 'europepmc' else 'eutils.ncbi.nlm.nih.gov'
                require(url.scheme == 'https' and url.netloc == host, 'RESPONSE_SERVICE', ident)
                params = parse_qs(url.query)
                if run['scope']['service'] == 'europepmc':
                    require(url.path == '/europepmc/webservices/rest/search' and params.get('query') == [actual_query],
                            'RESPONSE_QUERY', ident)
                    saw_search_response = True
                else:
                    require(url.path in ('/entrez/eutils/esearch.fcgi', '/entrez/eutils/esummary.fcgi'),
                            'RESPONSE_SERVICE', ident)
                    if url.path.endswith('/esearch.fcgi'):
                        require(params.get('term') == [actual_query], 'RESPONSE_QUERY', ident)
                        saw_search_response = True
            require(saw_search_response, 'RESPONSE_SEARCH_MISSING', ident, 'unavailable')
            work_keys = [native_work(w) for w in works]
            require(len(set(work_keys)) == len(work_keys), 'DUPLICATE_WORK', ident)
            expected_judgements.update((ident, *key) for key in work_keys)
        actual = []
        for judgement in run['judgements']:
            require(finish <= instant(judgement['assessed_at']) <= assessed, 'JUDGEMENT_TIME', run['id'])
            actual.append((judgement['call_id'], *source_id(judgement['work_id'], work=True)))
        require(len(set(actual)) == len(actual) and set(actual) == expected_judgements,
                'WORK_JUDGEMENTS', run['id'] + ': all and only own returned work occurrences need grounds', 'insufficient')
    require(used == set(by_id), 'UNASSIGNED_CALLS', 'No unrelated/global log rows accepted')
    # Native stop work projection must refer to these same occurrences, not a different pool.
    projection = fixed.get('works')
    fields = ('call_id', 'source_id', 'doi', 'pmid', 'pmcid', 'title')
    expected = [tuple(({'call_id': c['call_id'], **w}).get(k) for k in fields) for c in calls for w in c['works']]
    require(isinstance(projection, list) and all(isinstance(w, dict) for w in projection) and
            [tuple(w.get(k) for k in fields) for w in projection] == expected,
            'STOP_WORKS', 'Native stop projection differs')
    return {'status': 'grounded_contract_only', 'required_runs': required,
            'call_ids': sorted(used), 'log_sha256': evidence['log']['sha256'],
            'judgements_are_attestations': True}


def article_basis(bundle, evidence, claim, owner, paragraphs, made):
    require(evidence is not None, 'NO_ARTICLE_COVERAGE', 'Pinned inventory/coverage missing', 'insufficient')
    inventory = bundle.pinned(evidence['inventory'], 'inventory')
    coverage = bundle.pinned(evidence['coverage'], 'coverage')
    same_owner(coverage['owner'], owner)
    require(inventory['article'] == {'id': owner['source_id']['value'], 'source_text_sha256': owner['source_sha256']},
            'INVENTORY_SOURCE', 'Exact typed source/version required; no alias guessing')
    require(coverage['inventory_sha256'] == evidence['inventory']['sha256'] and
            coverage['scope'] == claim['scope'] and coverage['proposition_sha256'] == sha(claim['proposition'].encode()),
            'ARTICLE_BINDING', 'Inventory/scope/proposition')
    read_at, recorded = instant(inventory['read_at']), instant(coverage['recorded_at'])
    require(instant(owner['source_retrieved_at']) <= read_at <= recorded <= made, 'ARTICLE_TIME', 'Inventory/coverage')
    if coverage['state'] != 'complete':
        raise GroundError('ARTICLE_NOT_COMPLETE', coverage['state'], coverage['state'])
    by_para = {n: [] for n in range(1, len(paragraphs) + 1)}
    items = inventory['items']
    require(len({i['id'] for i in items}) == len(items), 'INVENTORY_ID', 'Duplicate item')
    for item in items:
        locators = [item['paragraph']] + item.get('also_in', [])
        require(len(set(locators)) == len(locators) and all(n in by_para for n in locators),
                'INVENTORY_PARAGRAPH', item['id'])
        require(any(item['quote'] in paragraphs[n - 1] for n in locators), 'INVENTORY_QUOTE', item['id'])
        for n in locators:
            by_para[n].append(item['id'])
    rows = coverage['paragraphs']
    numbers = [r['paragraph'] for r in rows]
    require(len(set(numbers)) == len(numbers) and set(numbers) == set(by_para),
            'PARAGRAPH_COVERAGE', 'Every native source paragraph exactly once', 'partial')
    for row in rows:
        n = row['paragraph']
        require(row['sha256'] == sha(paragraphs[n - 1].encode()), 'PARAGRAPH_HASH', str(n))
        require(instant(owner['source_retrieved_at']) <= instant(row['read_at']) <= read_at,
                'PARAGRAPH_TIME', str(n))
        require(set(row['inventory_ids']) == set(by_para[n]) and len(set(row['inventory_ids'])) == len(row['inventory_ids']),
                'PARAGRAPH_INVENTORY', str(n))
        require(row['disposition'] == ('items_recorded' if by_para[n] else 'inspected_no_inventory_item'),
                'PARAGRAPH_DISPOSITION', str(n))
    return {'status': 'grounded_contract_only', 'inventory_sha256': evidence['inventory']['sha256'],
            'paragraphs': numbers, 'item_ids': [i['id'] for i in items], 'reading_is_attested_only': True}


def issue(error):
    return {'code': error.code, 'detail': error.detail}


def evaluate_claim(bundle, claim, card, owner, paragraphs, made):
    result = {k: claim[k] for k in ('id', 'kind', 'epistemic_state', 'card_pointer', 'proposition', 'scope')}
    result.update(scientific_absence_verified=False, issues=[],
                  evidence={key: claim[key] for key in ('search', 'article') if key in claim})
    try:
        target = pointer(card, claim['card_pointer'])
        result['target_sha256'] = sha(json.dumps(target, ensure_ascii=False, sort_keys=True).encode())
        if claim['epistemic_state'] in RETAINED_STATES:
            result['status'] = claim['epistemic_state']
            result['issues'] = [{'code': 'STATE_NOT_UPGRADED', 'detail': 'Original uncertainty/non-search retained'}]
            return result
        expected = 'not_found' if claim['kind'] == 'not_found_by_agent' else 'claimed_absent'
        require(claim['epistemic_state'] == expected, 'EPISTEMIC_CONTRADICTION', claim['id'])
        if isinstance(target, dict) and 'disposition' in target and claim['kind'] != 'absent_from_the_literature':
            expected_gap = 'searched_not_found' if claim['kind'] == 'not_found_by_agent' else 'not_supplied'
            require(target['disposition'] == expected_gap, 'NATIVE_KIND_MISMATCH', claim['card_pointer'])
        if claim['kind'] == 'absent_from_the_article':
            basis = article_basis(bundle, claim.get('article'), claim, owner, paragraphs, made)
        else:
            basis = search_basis(bundle, claim.get('search'), claim, owner, made)
        result['basis'] = basis
        result['status'] = 'grounded_contract_only'
    except GroundError as error:
        result['status'] = error.status
        result['issues'].append(issue(error))
    if claim['kind'] == 'absent_from_the_literature':
        result['basis_status'] = result['status']
        result['status'] = 'unsupported_universal'
        result['issues'].append({'code': 'FINITE_SEARCH_NOT_UNIVERSAL',
                                 'detail': 'Original universal claim retained; no silent bounded relabel'})
    return result


def check(request_path):
    result = {'schema': 'ohf-negative-grounds-diagnostic/1', 'contract_status': 'invalid',
              'scientific_absence_verified': False, 'claims': [], 'issues': [], 'limits': LIMITS}
    bundle = None
    try:
        path = Path(os_path(os.fspath(request_path)))
        bundle = Bundle(path.parent)
        request = strict_json(bundle.read(path.name))
        shape(request, 'request')
        require(len(request['claims']) <= 128 and len({c['id'] for c in request['claims']}) == len(request['claims']),
                'CLAIM_IDS_OR_LIMIT', 'Unique claims, at most128')
        made = instant(request['made_at'])
        card = strict_json(bundle.pinned(request['card']))
        require(isinstance(card, dict), 'CARD_SHAPE', 'Object required')
        source = bundle.pinned(request['source'])
        paragraphs = main_source(card, request['source'], source)
        require(instant(request['source']['retrieved_at']) <= made, 'SOURCE_TIME', 'Source after request')
        owner = expected_owner(card, request)
        result['owner'] = owner
        result['claims'] = [dict(evaluate_claim(bundle, c, card, owner, paragraphs, made),
                                 request_pointer='/claims/' + str(i)) for i, c in enumerate(request['claims'])]
        statuses = {r['status'] for r in result['claims']}
        result['contract_status'] = 'grounded_contract_only' if statuses == {'grounded_contract_only'} else 'not_grounded'
    except GroundError as error:
        result['contract_status'] = error.status
        result['issues'].append(issue(error))
        # Shared-envelope failure invalidates all claims, with explicit original input pointers.
        if isinstance(locals().get('request'), dict) and isinstance(request.get('claims'), list):
            result['claims'] = [
                {'request_pointer': '/claims/' + str(i),
                 **{k: c[k] for k in ('id', 'kind', 'card_pointer')
                    if isinstance(c.get(k), str) and len(c[k]) <= 4096},
                 'status': error.status, 'issues': [issue(error)], 'scientific_absence_verified': False}
                for i, c in enumerate(request['claims'][:128]) if isinstance(c, dict)]
    result['input_pins'] = dict(bundle.pins) if bundle is not None else {}
    result['contract_sha256'] = sha(SCHEMA_PATH.read_bytes())
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('request', help='explicit local sidecar request; no discovery or search')
    args = parser.parse_args(argv)
    result = check(args.request)
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return 0 if result['contract_status'] == 'grounded_contract_only' else 1


if __name__ == '__main__':
    raise SystemExit(main())
