"""Invented synthetic grounds only; no scientific articles, search, labels or native CLI."""
from copy import deepcopy
import json
from pathlib import Path
from urllib.parse import urlencode

import pytest
from jsonschema import Draft202012Validator

import negative_grounds as ng

T = lambda n: f'2026-01-01T00:00:{n:02d}Z'
DUMP = lambda value: (json.dumps(value, sort_keys=True) + '\n').encode()


class Fixture:
    def __init__(self, root, kind='not_found_by_agent', work=False):
        self.root = root
        root.mkdir(exist_ok=True)
        self.kind = kind
        self.paras = ['Fable grows slowly under a blue lamp.', 'The method remains uncertain.']
        self.xml = ('<article><front><article-meta><article-id pub-id-type="pmc">900001</article-id>'
                    '<article-id pub-id-type="doi">10.9999/synthetic</article-id></article-meta></front>'
                    '<body>' + ''.join('<p>' + p + '</p>' for p in self.paras) + '</body></article>').encode()
        self.source = {'file': 'source.xml', 'sha256': ng.sha(self.xml),
                       'id': {'namespace': 'pmcid', 'value': 'PMC900001'}, 'retrieved_at': T(0), 'state': 'complete'}
        self.card = {'schema': 'ohf:hypothesis@1', 'id': 'h_invented', 'version': 1,
                     'identity': {'proposition_id': 'h_invented', 'version': 1},
                     'author': {'source': {'doi': '10.9999/synthetic', 'source_text_sha256': self.source['sha256'],
                                           'retrieved_at': T(0)}},
                     'added': {'gaps': [{'path': 'core.falsification_condition',
                       'disposition': 'not_supplied' if kind == 'absent_from_the_article' else 'searched_not_found',
                       'reason': 'Synthetic declared question.', 'query_ids': ['call:c1'], 'inspected_artifacts': []}],
                       'budget': {'model_calls': None, 'http_requests': None}}}
        owner = {'card_id': 'h_invented', 'card_version': 1, 'card_sha256': ng.sha(DUMP(self.card)),
                 'source_id': self.source['id'], 'source_sha256': self.source['sha256'], 'source_retrieved_at': T(0), 'source_state': 'complete'}
        self.owner = deepcopy(owner)
        works = [{'source_id': 'MED:123', 'pmid': '123', 'pmcid': None, 'doi': None,
                  'title': 'Invented work', 'type': 'JournalArticle'}] if work else []
        self.calls = [{'call_id': 'c1', 'tool': 'literature', 'kit': 'ohf-extractor/0.9.12',
                       'ask': {'query': 'synthetic', 'source': 'europepmc',
                               'variant': 'as_given', 'limit': 10},
                       'started_at': T(2), 'finished_at': T(3), 'outcome': 'ok', 'hit_count': len(works),
                       'found': len(works), 'works': works,
                       'responses': [{'url': 'https://www.ebi.ac.uk/europepmc/webservices/rest/search?' + urlencode({'query': 'synthetic'}),
                                      'at': T(2), 'status': 200, 'sha256': ng.sha(b'invented response')}]}]
        self.step = {'schema': 'ohf-search-step/1', 'closed_at': T(5), 'kit': deepcopy(ng.BASE), 'log': {}}
        self.claim = {'id': 'negative1', 'kind': kind,
                      'epistemic_state': 'not_found' if kind == 'not_found_by_agent' else 'claimed_absent',
                      'card_pointer': '/added/gaps/0', 'proposition': 'Fable does not double under a blue lamp.',
                      'scope': 'This invented source and explicitly named search runs.'}
        judgements = [{'call_id': 'call:c1', 'work_id': {'namespace': 'pmid', 'value': '123'},
                       'decision': 'not_matching', 'reason': 'Invented reader judgement, not a machine entailment.',
                       'assessed_at': T(6)}] if work else []
        self.runs = {'schema': 'ohf-negative-runs/1', 'recorded_at': T(7), 'owner': deepcopy(owner),
                     'log_sha256': '', 'scope': self.claim['scope'], 'proposition_sha256': ng.sha(self.claim['proposition'].encode()),
                     'runs': [{'id': 'run:r1', 'owner': deepcopy(owner),
                               'scope': {'query': 'synthetic', 'service': 'europepmc', 'as_of': None},
                               'state': 'completed', 'started_at': T(1), 'finished_at': T(4),
                               'stop': {'reason': 'exhausted', 'at': T(4)}, 'call_ids': ['call:c1'],
                               'conclusion': 'not_found', 'assessed_at': T(6), 'judgements': judgements}],
                     'call_bindings': [{'call_id': 'call:c1', 'run_id': 'run:r1', 'owner': deepcopy(owner)}]}
        self.inventory = {'article': {'id': 'PMC900001', 'source_text_sha256': self.source['sha256']},
                          'read_at': T(7), 'items': [{'id': 'i1', 'type': 'claim', 'paragraph': 1,
                            'text': 'Fable grows slowly.', 'quote': self.paras[0], 'hedge': None}]}
        self.coverage = {'schema': 'ohf-negative-article-coverage/1', 'recorded_at': T(8), 'owner': deepcopy(owner),
                         'inventory_sha256': '', 'scope': self.claim['scope'],
                         'proposition_sha256': ng.sha(self.claim['proposition'].encode()), 'state': 'complete',
                         'paragraphs': [
                            {'paragraph': 1, 'sha256': ng.sha(self.paras[0].encode()), 'read_at': T(6),
                             'inventory_ids': ['i1'], 'disposition': 'items_recorded', 'reason': 'Invented item read.'},
                            {'paragraph': 2, 'sha256': ng.sha(self.paras[1].encode()), 'read_at': T(6),
                             'inventory_ids': [], 'disposition': 'inspected_no_inventory_item', 'reason': 'Invented inspection attestation.'}]}
        self.request = {'schema': 'ohf-negative-grounds/1', 'made_at': T(10), 'card': {},
                        'source': deepcopy(self.source), 'claims': [self.claim]}
        self.sync()

    def put(self, filename, value):
        raw = value if isinstance(value, bytes) else DUMP(value)
        (self.root / filename).write_bytes(raw)
        return {'file': filename, 'sha256': ng.sha(raw)}

    def sync(self, step_update=True):
        self.put('source.xml', self.xml)
        self.request['card'] = self.put('card.json', self.card)
        log = self.put('search-log.jsonl', b''.join(DUMP(c) for c in self.calls))
        self.runs['log_sha256'] = log['sha256']
        if step_update:
            self.step['log'] = {'file': 'search-log.jsonl', 'sha256': log['sha256'],
                                'call_count': len(self.calls), 'works': [
                {'call_id': c['call_id'], **{k: w.get(k) for k in ('source_id', 'doi', 'pmid', 'pmcid', 'title')},
                 'publication_types': ['JournalArticle']} for c in self.calls for w in c['works']]}
        step = self.put('step-1.json', self.step)
        runs = self.put('runs.json', self.runs)
        inv = self.put('inventory.json', self.inventory)
        self.coverage['inventory_sha256'] = inv['sha256']
        cov = self.put('coverage.json', self.coverage)
        if self.kind == 'absent_from_the_article':
            self.claim['article'] = {'inventory': inv, 'coverage': cov}
        else:
            self.claim['search'] = {'log': log, 'step': step, 'runs': runs, 'required_run_ids': ['run:r1']}
        self.put('request.json', self.request)
        return self.root / 'request.json'

    def check(self):
        return ng.check(self.sync())


def row(result):
    assert not result['scientific_absence_verified']
    assert result['claims'], result
    assert not result['claims'][0]['scientific_absence_verified']
    return result['claims'][0]


def codes(result):
    return {e['code'] for e in result['issues']} | {e['code'] for r in result['claims'] for e in r['issues']}


@pytest.mark.parametrize('kind,work', [('not_found_by_agent', False), ('not_found_by_agent', True),
                                     ('absent_from_the_article', False)])
def test_minimal_own_grounding_contract_not_scientific_absence(tmp_path, kind, work):
    f = Fixture(tmp_path, kind, work)
    before = (tmp_path / 'card.json').read_bytes()
    result = f.check()
    assert result['contract_status'] == row(result)['status'] == 'grounded_contract_only'
    assert (tmp_path / 'card.json').read_bytes() == before
    assert result['limits']


@pytest.mark.parametrize('state', ['unknown', 'unavailable', 'not_searched', 'partial'])
def test_epistemic_states_are_retained_not_promoted(tmp_path, state):
    f = Fixture(tmp_path)
    f.claim['epistemic_state'] = state
    result = f.check()
    assert row(result)['status'] == state and result['contract_status'] != 'grounded_contract_only'


def test_finite_literature_search_never_verifies_universal_and_keeps_original(tmp_path):
    f = Fixture(tmp_path, 'absent_from_the_literature')
    result = f.check()
    r = row(result)
    assert r['kind'] == 'absent_from_the_literature' and r['status'] == 'unsupported_universal'
    assert r['basis_status'] == 'grounded_contract_only' and r['basis']['call_ids'] == ['call:c1']
    assert 'FINITE_SEARCH_NOT_UNIVERSAL' in codes(result)


@pytest.mark.parametrize('field', ['proposition', 'scope'])
def test_blank_claim_is_invalid(tmp_path, field):
    f = Fixture(tmp_path)
    f.claim[field] = '   '
    assert 'CONTRACT_SHAPE' in codes(f.check())


@pytest.mark.parametrize('filename', ['search-log.jsonl', 'runs.json', 'step-1.json'])
def test_missing_evidence_is_unavailable_not_not_found(tmp_path, filename):
    f = Fixture(tmp_path)
    path = f.sync()
    (tmp_path / filename).unlink()
    result = ng.check(path)
    assert row(result)['status'] == 'unavailable' and 'ARTIFACT_UNAVAILABLE' in codes(result)


@pytest.mark.parametrize('filename', ['card.json', 'source.xml', 'search-log.jsonl', 'runs.json'])
def test_hash_drift_never_rescues_grounding(tmp_path, filename):
    f = Fixture(tmp_path)
    path = f.sync()
    with (tmp_path / filename).open('ab') as out:
        out.write(b' ')
    assert 'HASH_DRIFT' in codes(ng.check(path))


@pytest.mark.parametrize('which', ['envelope', 'run', 'call_binding', 'native_call'])
def test_foreign_owner_cannot_be_rescued_by_top_owner(tmp_path, which):
    f = Fixture(tmp_path)
    if which == 'envelope':
        owner = f.runs['owner']
    elif which == 'run':
        owner = f.runs['runs'][0]['owner']
    elif which == 'call_binding':
        owner = f.runs['call_bindings'][0]['owner']
    else:
        f.calls[0]['owner'] = deepcopy(f.owner)
        owner = f.calls[0]['owner']
    owner['card_id'] = 'h_other'
    assert 'FOREIGN_OWNER' in codes(f.check())


@pytest.mark.parametrize('state,expected', [('partial','partial'), ('failed','unavailable'),
    ('unavailable','unavailable'), ('unknown','unknown'), ('not_searched','not_searched')])
def test_each_run_status_not_top_completion_controls_result(tmp_path, state, expected):
    f = Fixture(tmp_path)
    f.runs['runs'][0]['state'] = state
    assert row(f.check())['status'] == expected


def test_top_completed_cannot_substitute_for_missing_run(tmp_path):
    f = Fixture(tmp_path)
    path = f.sync()
    f.claim['search']['required_run_ids'].append('run:missing')
    f.put('request.json', f.request)
    assert 'REQUIRED_RUNS' in codes(ng.check(path))
    f.runs['completed'] = True
    f.sync()
    assert 'CONTRACT_SHAPE' in codes(ng.check(path))


@pytest.mark.parametrize('mutation,code', [
    ('failure','CALL_NOT_OK'), ('unavailable','CALL_NOT_OK'), ('unknown','CALL_NOT_OK'),
    ('capped','CALL_CAPPED_OR_PARTIAL'), ('partialflag','CALL_PARTIAL'),
    ('boolcount','CALL_COUNTS'), ('error','CALL_CONTRADICTION'),
    ('foreignquery','CALL_SCOPE'), ('wrongendpoint','RESPONSE_SERVICE'), ('wrongqueryurl','RESPONSE_QUERY'),
    ('status500','RESPONSE_STATUS'), ('response_missing','CALL_RESPONSES'),
])
def test_native_failure_partial_scope_and_status_are_not_zero_results(tmp_path, mutation, code):
    f = Fixture(tmp_path)
    call = f.calls[0]
    if mutation in ('failure','unavailable','unknown'):
        call['outcome'] = mutation
    elif mutation == 'capped':
        call['hit_count'] = 100
    elif mutation == 'partialflag':
        call['partial'] = True
    elif mutation == 'boolcount':
        call['found'] = False
    elif mutation == 'error':
        call['error'] = 'contradictory error'
    elif mutation == 'foreignquery':
        call['ask']['query'] = 'other question'
    elif mutation == 'wrongendpoint':
        call['responses'][0]['url'] = 'https://other.invalid/search'
    elif mutation == 'wrongqueryurl':
        call['responses'][0]['url'] = 'https://www.ebi.ac.uk/europepmc/webservices/rest/search?query=other'
    elif mutation == 'status500':
        call['responses'][0]['status'] = 500
    else:
        call['responses'] = []
    assert code in codes(f.check())


@pytest.mark.parametrize('mutation,code', [
    ('empty','LOG_EMPTY_OR_LIMIT'), ('duplicate','CALL_ID'), ('foreign_call','CALL_REFERENCE'),
    ('foreign_run','CALL_RUN_OWNER'), ('missingbinding','CONTRACT_SHAPE'),
    ('unownedpool','CALL_OWNERSHIP'), ('run_stop','RUN_STOP'), ('unknownconclusion','RUN_NO_NOT_FOUND_CONCLUSION'),
])
def test_named_calls_runs_and_stops_are_required(tmp_path, mutation, code):
    f = Fixture(tmp_path)
    if mutation == 'empty': f.calls = []
    elif mutation == 'duplicate': f.calls.append(deepcopy(f.calls[0]))
    elif mutation == 'foreign_call': f.runs['runs'][0]['call_ids'] = ['call:other']
    elif mutation == 'foreign_run': f.runs['call_bindings'][0]['run_id'] = 'run:other'
    elif mutation == 'missingbinding': f.runs['call_bindings'] = []
    elif mutation == 'unownedpool':
        foreign = deepcopy(f.calls[0]); foreign['call_id']='other'; f.calls.append(foreign)
    elif mutation == 'run_stop': f.runs['runs'][0]['stop']['reason'] = 'capped'
    else: f.runs['runs'][0]['conclusion'] = 'unknown'
    assert code in codes(f.check())


@pytest.mark.parametrize('mutation,code', [('nojudgement','WORK_JUDGEMENTS'), ('foreignwork','WORK_JUDGEMENTS'),
    ('alias','SOURCE_ID'), ('nativeconflict','WORK_ID_CONFLICT'), ('duplicate','WORK_JUDGEMENTS')])
def test_own_returned_works_require_explicit_scoped_attestations(tmp_path, mutation, code):
    f = Fixture(tmp_path, work=True)
    js = f.runs['runs'][0]['judgements']
    if mutation == 'nojudgement': js.clear()
    elif mutation == 'foreignwork': js[0]['work_id']['value'] = '456'
    elif mutation == 'alias': js[0]['work_id']['value'] = 'PMID:123'
    elif mutation == 'nativeconflict': f.calls[0]['works'][0]['pmid'] = '456'
    else: js.append(deepcopy(js[0])); js[-1]['reason'] = 'A duplicate with different words.'
    assert code in codes(f.check())


@pytest.mark.parametrize('where', ['request','call','run','response','stop'])
def test_timezone_and_event_order_fail_explicitly(tmp_path, where):
    f = Fixture(tmp_path)
    if where == 'request': f.request['made_at'] = '2026-01-01T00:00:10'
    elif where == 'call': f.calls[0]['finished_at'] = T(1)
    elif where == 'run': f.runs['runs'][0]['finished_at'] = T(0)
    elif where == 'response': f.calls[0]['responses'][0]['at'] = T(9)
    else: f.step['closed_at'] = T(0)
    assert row(f.check())['status'] != 'grounded_contract_only' if where != 'request' else 'CONTRACT_SHAPE' in codes(f.check())


@pytest.mark.parametrize('mutation,code', [('nonexistent','INVENTORY_PARAGRAPH'), ('wrongquote','INVENTORY_QUOTE'),
    ('missingparagraph','PARAGRAPH_COVERAGE'), ('wrongparagraphhash','PARAGRAPH_HASH'),
    ('wrongitem','PARAGRAPH_INVENTORY'), ('emptyinventory','CONTRACT_SHAPE'),
    ('partial','ARTICLE_NOT_COMPLETE'), ('foreignsource','INVENTORY_SOURCE'),
    ('foreignowner','FOREIGN_OWNER'), ('wrongproposition','ARTICLE_BINDING'), ('staleversion','FOREIGN_OWNER')])
def test_article_absence_needs_actual_bound_source_inventory_and_paragraphs(tmp_path, mutation, code):
    f = Fixture(tmp_path, 'absent_from_the_article')
    if mutation == 'nonexistent': f.inventory['items'][0]['paragraph'] = 900
    elif mutation == 'wrongquote': f.inventory['items'][0]['quote'] = 'Not words of this source.'
    elif mutation == 'missingparagraph': f.coverage['paragraphs'].pop()
    elif mutation == 'wrongparagraphhash': f.coverage['paragraphs'][0]['sha256'] = ng.sha(b'wrong')
    elif mutation == 'wrongitem': f.coverage['paragraphs'][0]['inventory_ids'] = ['elsewhere']
    elif mutation == 'emptyinventory': f.inventory['items'] = []
    elif mutation == 'partial': f.coverage['state'] = 'partial'
    elif mutation == 'foreignsource': f.inventory['article']['id'] = 'PMC800001'
    elif mutation == 'foreignowner': f.coverage['owner']['card_id'] = 'h_other'
    elif mutation == 'wrongproposition': f.coverage['proposition_sha256'] = ng.sha(b'other')
    else: f.coverage['owner']['source_retrieved_at'] = T(1)
    assert code in codes(f.check())


def test_article_contract_does_not_infer_absence_from_substring_nonmatch_or_match(tmp_path):
    f = Fixture(tmp_path, 'absent_from_the_article')
    f.claim['proposition'] = f.paras[0]  # Deliberately present. Contract is not a semantic judge.
    f.coverage['proposition_sha256'] = ng.sha(f.claim['proposition'].encode())
    result = f.check()
    assert row(result)['status'] == 'grounded_contract_only'
    assert result['scientific_absence_verified'] is False


@pytest.mark.parametrize('mutation,code', [('sourceid','SOURCE_ID_MISMATCH'),('carddoi','CARD_SOURCE_ID'),
    ('version','SOURCE_VERSION'),('cardhash','CARD_SOURCE_HASH'),('identity','CARD_ID'),('author_shape','CARD_SOURCE_SHAPE')])
def test_strict_card_source_identity_and_version(tmp_path, mutation, code):
    f = Fixture(tmp_path)
    if mutation == 'sourceid': f.request['source']['id']['value'] = 'PMC800001'
    elif mutation == 'carddoi': f.card['author']['source']['doi'] = '10.9999/other'
    elif mutation == 'version': f.card['author']['source']['retrieved_at'] = T(1)
    elif mutation == 'cardhash': f.card['author']['source']['source_text_sha256'] = ng.sha(b'other')
    elif mutation == 'identity': f.card['identity'] = {'proposition_id':'h_other','version':1}
    else: f.card['author'] = None
    assert code in codes(f.check())


@pytest.mark.parametrize('pointer', ['/added/gaps/99', '/added/gaps/00', '/added/gaps/~2'])
def test_actual_card_pointer_required_no_alias_guessing(tmp_path, pointer):
    f = Fixture(tmp_path); f.claim['card_pointer'] = pointer
    assert codes(f.check()) & {'CARD_POINTER','CONTRACT_SHAPE'}


def test_artifact_path_symlink_duplicate_key_and_size_fail_closed(tmp_path):
    f = Fixture(tmp_path); path=f.sync()
    original = (tmp_path/'runs.json').read_bytes()
    (tmp_path/'alias.json').symlink_to(tmp_path/'runs.json')
    f.claim['search']['runs']['file']='alias.json'; f.put('request.json',f.request)
    assert 'ARTIFACT_SYMLINK' in codes(ng.check(path))
    f.claim['search']['runs']['file']='../runs.json'; f.put('request.json',f.request)
    assert 'ARTIFACT_PATH' in codes(ng.check(path))
    f.sync(); f.claim['search']['runs'] = f.put('runs.json', b'{"schema":"one","schema":"two"}')
    f.put('request.json',f.request)
    assert 'DUPLICATE_JSON_KEY' in codes(ng.check(path))
    f.sync(); (tmp_path/'runs.json').write_bytes(b'x'*(ng.MAX_BYTES+1))
    assert 'ARTIFACT_SIZE' in codes(ng.check(path))


def test_missing_search_is_not_searched_and_native_kind_mismatch_rejected(tmp_path):
    f=Fixture(tmp_path); path=f.sync(); del f.claim['search']; f.put('request.json',f.request)
    assert row(ng.check(path))['status']=='not_searched'
    f.claim['kind']='absent_from_the_article';f.claim['epistemic_state']='claimed_absent'
    f.put('request.json',f.request)
    assert 'NATIVE_KIND_MISMATCH' in codes(ng.check(path))


def test_stop_hash_and_native_works_projection_bind_actual_log(tmp_path):
    f=Fixture(tmp_path,work=True)
    f.step['log']['sha256']=ng.sha(b'other')
    result=ng.check(f.sync(step_update=False))
    assert 'STOP_LOG' in codes(result)
    f.sync();f.step['log']['works'][0]['pmid']='456'
    assert 'STOP_WORKS' in codes(ng.check(f.sync(step_update=False)))


def test_offline_entry_point_emits_diagnostic_and_never_edits_card(tmp_path,capsys):
    f=Fixture(tmp_path); before=(tmp_path/'card.json').read_bytes()
    assert ng.main([str(tmp_path/'request.json')])==0
    result=json.loads(capsys.readouterr().out)
    assert result['scientific_absence_verified'] is False and result['input_pins']
    assert (tmp_path/'card.json').read_bytes()==before


@pytest.mark.parametrize('kind', ['not_found_by_agent','absent_from_the_article'])
def test_parent_native_gap_shape_is_not_successor_grounding_check(tmp_path,kind):
    """Capability distinction, not a claim that the parent schema proves semantic absence."""
    import os
    native=json.loads((Path(os.environ['OHF_REPO'])/'schema/hypothesis-1.schema.json').read_text())
    gap=Fixture(tmp_path,kind).card['added']['gaps'][0]
    validator=Draft202012Validator({'$ref':'#/$defs/Gap','$defs':native['$defs']})
    assert not list(validator.iter_errors(gap))
    # Existing gap query/artifact strings satisfy syntax even with no grounded lookup or coverage.
    f=Fixture(tmp_path,kind); path=f.sync()
    if kind=='not_found_by_agent': (tmp_path/'search-log.jsonl').unlink()
    else: (tmp_path/'coverage.json').unlink()
    assert row(ng.check(path))['status']=='unavailable'


@pytest.mark.parametrize('second_state,expected', [('completed','grounded_contract_only'),
    ('unknown','unknown'),('failed','unavailable'),('partial','partial')])
def test_all_required_runs_checked_even_after_first_success(tmp_path,second_state,expected):
    f=Fixture(tmp_path)
    other=deepcopy(f.calls[0]);other['call_id']='c2';other['ask']['query']='other'
    other['responses'][0]['url']='https://www.ebi.ac.uk/europepmc/webservices/rest/search?query=other'
    f.calls.append(other)
    second=deepcopy(f.runs['runs'][0]);second['id']='run:r2';second['call_ids']=['call:c2']
    second['scope']['query']='other';second['state']=second_state
    f.runs['runs'].append(second)
    f.runs['call_bindings'].append({'call_id':'call:c2','run_id':'run:r2','owner':deepcopy(f.owner)})
    path=f.sync();f.claim['search']['required_run_ids']=['run:r1','run:r2'];f.put('request.json',f.request)
    result=ng.check(path)
    assert row(result)['status']==expected
    if second_state=='completed': assert row(result)['basis']['call_ids']==['call:c1','call:c2']


@pytest.mark.parametrize('value', [None, 1, 'https://[bad'])
def test_malformed_response_url_is_structured_diagnostic(tmp_path,value):
    f=Fixture(tmp_path);f.calls[0]['responses'][0]['url']=value
    assert 'RESPONSE_URL' in codes(f.check())


def test_global_failure_keeps_each_original_claim_pointer(tmp_path):
    f=Fixture(tmp_path)
    second=deepcopy(f.claim);second['id']='negative2';second['kind']='absent_from_the_literature'
    second['epistemic_state']='claimed_absent';second['proposition']=' '
    f.request['claims'].append(second)
    result=f.check()
    assert result['contract_status']=='invalid'
    assert [r['request_pointer'] for r in result['claims']]==['/claims/0','/claims/1']
    assert result['claims'][1]['kind']=='absent_from_the_literature'


def test_snapshot_limits_are_explicit_unavailable_not_not_found(tmp_path,monkeypatch):
    f=Fixture(tmp_path)
    monkeypatch.setattr(ng,'MAX_TOTAL',10)
    assert 'ARTIFACT_TOTAL_SIZE' in codes(f.check())


@pytest.mark.parametrize('value', ['2026-01-01T00:00:01+00:99','2026-01-01T00:00:01-00:00',
    '2026-01-01T00:00:01.1234567Z'])
def test_unknown_invalid_or_overprecision_time_cannot_be_normalized_to_known(value):
    with pytest.raises(ng.GroundError): ng.instant(value)


def test_pubmed_summary_without_actual_search_cannot_establish_zero_hits(tmp_path):
    f=Fixture(tmp_path)
    f.runs['runs'][0]['scope']['service']='pubmed';f.calls[0]['ask']['source']='pubmed'
    f.calls[0]['responses'][0]['url']='https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?id=123'
    assert 'RESPONSE_SEARCH_MISSING' in codes(f.check())
    f.calls[0]['responses'][0]['url']='https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?term=synthetic'
    assert row(f.check())['status']=='grounded_contract_only'


@pytest.mark.parametrize('state',['partial','unknown','unavailable'])
def test_source_completeness_is_not_inferred_from_all_provided_paragraphs(tmp_path,state):
    f=Fixture(tmp_path,'absent_from_the_article')
    f.request['source']['state']=state
    result=f.check()
    assert row(result)['status']==state and 'SOURCE_NOT_COMPLETE' in codes(result)


@pytest.mark.parametrize('ident,accepted', [({'namespace':'pmcid','value':'PMC900001'},True),
    ({'namespace':'pmcid','value':'900001'},False),
    ({'namespace':'doi','value':'10.9999/part:1'},True),
    ({'namespace':'doi','value':'https://doi.org/10.9999/test'},False)])
def test_typed_identifier_forms_do_not_guess_aliases(ident,accepted):
    if accepted: assert ng.source_id(ident)==(ident['namespace'],ident['value'])
    else:
        with pytest.raises(ng.GroundError): ng.source_id(ident)


@pytest.mark.parametrize('native_state,grounded', [('ok',True),('failed',False),('capped',False)])
def test_parent_native_log_snapshot_is_not_successor_negative_grounding(tmp_path,native_state,grounded):
    """Same invented native log: old step fixes metadata; new form checks negative grounds.
    Parent behavior is intentional, not an assertion that its stop grants a negative verdict.
    """
    import ast
    import search
    path=Path(__file__).resolve().parents[1]/'stages.py'
    raw=path.read_bytes()
    assert ng.sha(raw)=='sha256:addaa22c90d927258828d0b8ae90bf463f86d36cddfaab92ed4577483a6fc77e'
    names={'StageError','has_decision','log_snapshot'}
    nodes=[n for n in ast.parse(raw).body if isinstance(n,(ast.FunctionDef,ast.ClassDef)) and n.name in names]
    env={'json':json,'Path':Path,'search':search,'DECISION_KEYS':{'verdict','verdicts','direction'},
         'DECISION_TOOLS':{'not_cited','relevance','known_result'}}
    exec(compile(ast.Module(body=nodes,type_ignores=[]),str(path),'exec'),env)
    f=Fixture(tmp_path)
    if native_state=='failed': f.calls[0]['outcome']='failed'
    if native_state=='capped': f.calls[0]['hit_count']=100
    f.sync()
    calls,snapshot=env['log_snapshot'](tmp_path)
    assert len(calls)==snapshot['call_count']==1
    assert (row(ng.check(tmp_path/'request.json'))['status']=='grounded_contract_only') is grounded


def released_zero_hit_calls(f, monkeypatch, service='europepmc', cutoff=None):
    """Pinned release producer definitions with stub transport, without native CLI.

    The integrated locate/closeout and opt-in fallback do not change the
    released literature producer. Invert only the added methods before checking
    its original definitions pin; fallback behavior has its own regression tests.
    The complete definitions pin below includes the accepted closeout/status changes.
    No invented query fields are attached to returned native calls.
    """
    import ast
    import types
    path=Path(__file__).resolve().parents[1]/'search.py'
    raw=path.read_bytes()
    definitions=[]
    for node in ast.parse(raw).body:
        if isinstance(node,(ast.FunctionDef,ast.ClassDef)) and node.name!='main':
            if isinstance(node,ast.ClassDef) and node.name=='Searcher':
                node.body=[part for part in node.body if not isinstance(part,ast.FunctionDef)
                           or part.name not in ('locate', 'literature_fallback')]
            definitions.append(ast.dump(node,include_attributes=False))
    assert ng.sha('\n'.join(definitions).encode())=='sha256:033c28140a86dd17851c93d142ffd612da60abf96c18c5b8053d9b84b096ce44'
    parent=types.ModuleType('released_v0912_search');parent.__file__=str(path)
    exec(compile(raw,str(path),'exec'),parent.__dict__)
    # Literature producer definitions match the release; bind its historical log version explicitly.
    parent.VERSION='0.9.12'
    monkeypatch.setattr(parent,'now',lambda:T(2))
    urls=[]
    def transport(url):
        urls.append(url)
        payload={'hitCount':0,'resultList':{'result':[]}} if service=='europepmc' else {
            'esearchresult':{'count':'0','idlist':[]}}
        return 200,DUMP(payload),{}
    native_dir=f.root/'native-producer'
    calls=parent.Searcher(native_dir,get=transport,sleep=lambda *_:None,clock=lambda:0).literature(
        'synthetic',limit=10,sources=(service,),as_of=cutoff)
    assert len(calls)==2 and len(urls)==2
    assert all('sent_query' not in call['ask'] for call in calls)
    before=(native_dir/'search-log.jsonl').read_bytes()
    f.calls=deepcopy(calls)
    run=f.runs['runs'][0]
    run['scope'].update(service=service,as_of=cutoff)
    run['call_ids']=['call:'+c['call_id'] for c in calls]
    f.runs['call_bindings']=[{'call_id':'call:'+c['call_id'],'run_id':'run:r1','owner':deepcopy(f.owner)} for c in calls]
    f.sync()
    assert (f.root/'search-log.jsonl').read_bytes()==before, 'native log bytes must not be rewritten into another form'
    return calls,native_dir,before


@pytest.mark.parametrize('service',['europepmc','pubmed'])
@pytest.mark.parametrize('cutoff',[None,'2025-12-31'])
def test_real_parent_producer_zero_hits_supported_without_log_rewriting(tmp_path,monkeypatch,service,cutoff):
    f=Fixture(tmp_path)
    calls,native_dir,raw=released_zero_hit_calls(f,monkeypatch,service,cutoff)
    assert 'sent' not in calls[0]['ask'] if cutoff is None else 'sent' in calls[0]['ask']
    assert 'sent' in calls[1]['ask'] and calls[1]['ask']['variant']=='no_reviews'
    assert row(ng.check(tmp_path/'request.json'))['status']=='grounded_contract_only'
    assert (native_dir/'search-log.jsonl').read_bytes()==raw


@pytest.mark.parametrize('mutation,code', [
    ('drop_sent','CALL_QUERY_BINDING'), ('wrong_sent','CALL_QUERY_BINDING'),
    ('invented_sent_query','CALL_QUERY_BINDING'), ('wrong_variant','CALL_QUERY_BINDING'),
    ('untransformed_url','RESPONSE_QUERY'), ('wrong_cutoff_url','RESPONSE_QUERY'),
    ('missing_cutoff_metadata','CALL_SCOPE'), ('redundant_as_given_sent','CALL_QUERY_BINDING'),
])
def test_real_parent_transformed_variant_and_cutoff_cannot_be_substituted(tmp_path,monkeypatch,mutation,code):
    f=Fixture(tmp_path)
    cutoff=None if mutation=='redundant_as_given_sent' else '2025-12-31'
    _,native_dir,raw=released_zero_hit_calls(f,monkeypatch,cutoff=cutoff)
    call=f.calls[1]
    if mutation=='drop_sent': del call['ask']['sent']
    elif mutation=='wrong_sent':call['ask']['sent']='synthetic'
    elif mutation=='invented_sent_query':call['ask']['sent_query']=call['ask']['sent']
    elif mutation=='wrong_variant':call['ask']['variant']='as_given'
    elif mutation=='untransformed_url':
        call['responses'][0]['url']='https://www.ebi.ac.uk/europepmc/webservices/rest/search?query=synthetic'
    elif mutation=='wrong_cutoff_url':
        call['responses'][0]['url']='https://www.ebi.ac.uk/europepmc/webservices/rest/search?'+urlencode({
            'query':call['ask']['sent'].replace('2025-12-31','2024-12-31')})
    elif mutation=='missing_cutoff_metadata':del call['ask']['as_of']
    else:f.calls[0]['ask']['sent']=f.calls[0]['ask']['query']
    assert code in codes(f.check())
    assert (native_dir/'search-log.jsonl').read_bytes()==raw


def encoded_source(f, raw):
    """Rebind only invented source/card fixture pins after deliberate test encoding changes."""
    f.xml=raw
    digest=ng.sha(raw)
    f.source['sha256']=digest;f.request['source']['sha256']=digest
    f.card['author']['source']['source_text_sha256']=digest
    owner=deepcopy(f.owner);owner.update(source_sha256=digest,card_sha256=ng.sha(DUMP(f.card)))
    f.owner=owner
    f.runs['owner']=deepcopy(owner)
    for run in f.runs['runs']:run['owner']=deepcopy(owner)
    for call in f.runs['call_bindings']:call['owner']=deepcopy(owner)
    f.coverage['owner']=deepcopy(owner)
    f.inventory['article']['source_text_sha256']=digest


@pytest.mark.parametrize('encoding',['utf-8','utf-8-sig','utf-16','utf-16-le','utf-16-be'])
def test_ordinary_xml_encodings_use_same_source_grounding_contract(tmp_path,encoding):
    f=Fixture(tmp_path,'absent_from_the_article')
    encoded_source(f,f.xml.decode().encode(encoding))
    assert row(f.check())['status']=='grounded_contract_only'


@pytest.mark.parametrize('encoding',['utf-8','utf-16','utf-16-le','utf-16-be'])
@pytest.mark.parametrize('declaration',[
    '<!DOCTYPE article [<!ENTITY injected "SYNTHETIC_ENTITY">]>',
    '<!DOCTYPE article SYSTEM "https://example.invalid/forbidden.dtd">',
])
def test_xml_declarations_rejected_before_expansion_in_every_encoding(tmp_path,encoding,declaration):
    f=Fixture(tmp_path)
    text=f.xml.decode().replace('<article>',declaration+'<article>',1)
    if 'ENTITY' in declaration:text=text.replace('Fable grows slowly','&injected; grows slowly')
    encoded_source(f,text.encode(encoding))
    result=f.check()
    assert 'SOURCE_XML_DECLARATION' in codes(result)
    assert result['contract_status']!='grounded_contract_only'


def test_declaration_text_inside_comment_is_not_a_dtd(tmp_path):
    f=Fixture(tmp_path)
    raw=f.xml.replace(b'<article>',b'<!-- <!DOCTYPE article> --><article>',1)
    encoded_source(f,raw)
    assert row(f.check())['status']=='grounded_contract_only'


@pytest.mark.parametrize('raw',[b'{"x":1e9999}',b'{"x":-1e9999}',b'{"x":Infinity}',b'{"x":NaN}'])
def test_all_nonfinite_json_forms_raise_structured_error(raw):
    with pytest.raises(ng.GroundError) as exc:ng.strict_json(raw)
    assert exc.value.code=='NONFINITE_JSON'


@pytest.mark.parametrize('literal,value', [('1.25',1.25),('1e308',1e308),('-1e308',-1e308),('1.5e-10',1.5e-10)])
def test_finite_json_float_positive_controls(literal,value):
    assert ng.strict_json(('{"x":'+literal+'}').encode())['x']==value


def test_nonfinite_exponent_is_structured_in_actual_check_and_cli(tmp_path,capsys):
    f=Fixture(tmp_path)
    raw=DUMP(f.card).replace(b'"model_calls": null',b'"model_calls": 1e9999')
    f.request['card']=f.put('card.json',raw);f.put('request.json',f.request)
    result=ng.check(tmp_path/'request.json')
    assert 'NONFINITE_JSON' in codes(result)
    assert ng.main([str(tmp_path/'request.json')])==1
    assert 'NONFINITE_JSON' in codes(json.loads(capsys.readouterr().out))


@pytest.mark.parametrize('bad',['bad\x00name','bad\ud800name','bad\udcffname'])
def test_invalid_os_artifact_paths_are_check_and_cli_diagnostics(tmp_path,capsys,bad):
    f=Fixture(tmp_path)
    f.claim['search']['runs']['file']=bad;f.put('request.json',f.request)
    result=ng.check(tmp_path/'request.json')
    assert row(result)['status']=='invalid' and 'ARTIFACT_PATH' in codes(result)
    assert ng.main([str(tmp_path/'request.json')])==1
    assert 'ARTIFACT_PATH' in codes(json.loads(capsys.readouterr().out))


def test_bounded_open_valueerror_becomes_grounderror(tmp_path,monkeypatch,capsys):
    f=Fixture(tmp_path)
    original=ng.os.open
    def opened(path,*args,**kwargs):
        if Path(path).name=='runs.json':raise ValueError('invalid path form')
        return original(path,*args,**kwargs)
    with monkeypatch.context() as patcher:
        patcher.setattr(ng.os,'open',opened)
        assert 'ARTIFACT_PATH' in codes(ng.check(tmp_path/'request.json'))
        assert ng.main([str(tmp_path/'request.json')])==1
    assert 'ARTIFACT_PATH' in codes(json.loads(capsys.readouterr().out))


def test_invalid_request_path_is_cli_diagnostic_before_any_read(tmp_path,capsys):
    assert ng.main([str(tmp_path/'bad\x00request.json')])==1
    result=json.loads(capsys.readouterr().out)
    assert 'ARTIFACT_PATH' in codes(result) and result['input_pins']=={}


@pytest.mark.parametrize('entrypoint',['check','cli'])
def test_unknown_xml_codec_is_structured_unavailable(tmp_path,capsys,entrypoint):
    f=Fixture(tmp_path,'absent_from_the_article')
    encoded_source(f,b'<?xml version="1.0" encoding="not-a-codec"?>'+f.xml)
    f.sync()
    if entrypoint=='check':
        result=ng.check(tmp_path/'request.json')
    else:
        assert ng.main([str(tmp_path/'request.json')])==1
        result=json.loads(capsys.readouterr().out)
    assert 'SOURCE_XML' in codes(result)
    assert result['contract_status']!='grounded_contract_only'
    assert result['scientific_absence_verified'] is False


def test_unrelated_programming_lookup_error_propagates(tmp_path,monkeypatch):
    f=Fixture(tmp_path)
    def unrelated(*args,**kwargs):raise LookupError('invented unrelated programmer error')
    monkeypatch.setattr(ng,'expected_owner',unrelated)
    with pytest.raises(LookupError,match='unrelated programmer'):
        ng.check(tmp_path/'request.json')
