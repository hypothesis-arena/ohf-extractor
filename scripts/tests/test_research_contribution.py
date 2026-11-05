"""Invented contribution data and injected native readers; no external calls."""
from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess

import pytest

import research_contribution as rc
import search

TEXT = 'A toy blue lamp changes the invented fable marker.'
STAMP = '2030-01-01T01:02:03Z'
DUMP = lambda value: json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def denied(*args, **kwargs):
        pytest.fail('research tests forbid network/process dispatch')
    for name in ('socket', 'socketpair', 'fromfd', 'getaddrinfo', 'create_connection'):
        monkeypatch.setattr(socket, name, denied)
    monkeypatch.setattr(subprocess, 'Popen', denied)
    monkeypatch.setattr(os, 'system', denied)


@pytest.fixture
def standard():
    root = os.environ.get('OHF_RESEARCH_STANDARD')
    if not root:
        pytest.skip('Optional research companion tests require explicit OHF_RESEARCH_STANDARD')
    return Path(root)


def example(standard, mode='published_result', origin='ai_addition'):
    zone = 'author' if origin == 'author_proposal' else 'added'
    prefix = '/' + zone + '/layers'
    known = {'schema': 'ohf-extractor/known-result', 'schema_version': 1,
             'input': {'text_sha256': rc.sha(TEXT.encode())}, 'checked_at': STAMP,
             'result': 'known_result', 'works': [{'doi': '10.9999/invented-fable', 'pmid': '900001',
                 'verdict': 'tests_supports', 'quote_check': 'verified'}],
             'evidence': [{'kind': 'work', 'index': 0, 'decisive': True}],
             'searched': {'queries': [{'call_id': 'q1', 'query': 'toy blue lamp', 'source': 'europepmc',
                           'variant': 'as_given', 'probe': 'as_given', 'outcome': 'ok', 'hit_count': 1, 'found': 1}],
                          'failed_calls': [], 'per_query': 10, 'max_works': 60, 'completion': 'complete'}}
    w = lambda value: {'value': value, 'locator' if zone == 'author' else 'src': 'invented'}
    novelty = {'status': 'known_result' if mode == 'published_result' else 'bounded_search', 'as_of': STAMP}
    if mode == 'published_result':
        novelty['prior_claim_refs'] = [{'kind': 'card', 'pointer': prefix + '/evidence/lines/0/result_estimate'}]
    else:
        novelty['new_content'] = 'A prospective invented washout test.'
    core = {'statement': w(TEXT), 'uncertainties': w([{'id': 'q_toy', 'question': 'Does the toy response persist?'}]),
            'testability': w({'cheapest_test': {'kind': 'literal', 'text': 'Run an invented blinded washout.'}}),
            'novelty_assessment': w(novelty)}
    layers = {'core': core, 'predictions': [{'id': 'p_positive'}, {'id': 'p_negative'}],
              'evidence': {'lines': [{'result_estimate': w({'reported': 'An invented prior toy response.'})}],
                           'references': [{'identifier': w('10.9999/invented-fable')}]}}
    card = {'standard_version': '1.4', 'id': 'h_fable', 'version': 1,
            'author': {'layers': {}}, 'added': {'layers': {}}}
    card[zone]['layers'] = layers
    selections = {'proposal': prefix + '/core/statement', 'question': prefix + '/core/uncertainties/value/0',
                  'next_test': prefix + '/core/testability', 'novelty': prefix + '/core/novelty_assessment',
                  'positive_prediction': prefix + '/predictions/0', 'negative_prediction': prefix + '/predictions/1',
                  'known_results': [{'work_index': 0, 'result': prefix + '/evidence/lines/0/result_estimate',
                                     'reference': prefix + '/evidence/references/0/identifier'}]}
    request = {'format': 'ohf-extractor-research-request/1', 'origin': origin, 'actor': 'invented actor',
               'novelty_claim': 'not_new', 'selections': selections,
               'annotations': {'contribution_type': mode,
                  'replication_justification': {'reason': 'The toy result came from one site.',
                      'changed_conditions': 'Repeat blinded at an independent invented site.',
                      'prior_result_pointer': selections['known_results'][0]['result']} if mode == 'replication' else None,
                  'outcome_additions': {'positive': 'Persistence would distinguish durable from transient toy action.',
                                       'negative': 'Loss would bound the toy action to continued exposure.'}}}
    if mode == 'new_test':
        request['novelty_claim'] = 'unknown'
        selections['known_results'] = []
        selections['novelty'] = None
        known['searched'].update(completion='cards_only', queries=[])
        known['result'] = 'duplicate'
    else:
        novelty['search_scope_ref'] = {'kind': 'artifact', 'sha256': rc.sha(rc.search_scope(DUMP(known), standard))}
    return card, known, request


def run(data, standard):
    return rc.produce(*(DUMP(v) for v in data), standard)


def record(report):
    return report['components'][0]['records'][0]


@pytest.mark.parametrize('mode', ['published_result', 'replication', 'new_test'])
@pytest.mark.parametrize('origin', ['author_proposal', 'ai_addition', 'other_addition'])
def test_contribution_modes_and_zones_retain_existing_bytes(standard, mode, origin):
    data = example(standard, mode, origin)
    before = deepcopy(data)
    wire, artifacts, report = run(data, standard)
    api = rc.reference(standard)
    assert data == before
    assert artifacts['card'] == DUMP(data[0]) and artifacts['known_result'] == DUMP(data[1])
    assert artifacts['request'] == DUMP(data[2])
    assert report == api.api.evaluate(wire, artifacts, api.validation_context, required_profile=rc.PROFILE)
    row = record(report)
    assert row['zone'] == ('author' if origin == 'author_proposal' else 'added')
    assert row['source_truth'] == 'SUPPLIED_UNVERIFIED'
    assert row['novelty'] == ('unknown' if mode == 'new_test' else 'known_published')
    for outcome in ('positive', 'negative'):
        assert row['outcomes'][outcome]['addition'] == data[2]['annotations']['outcome_additions'][outcome]
    if mode == 'replication':
        assert row['replication_justification']['prior_result_binding'] == row['known_results'][0]['result_binding']
    comp = report['components'][0]
    assert comp['scientific_content'] == 'NOT_ASSESSED'
    assert comp['admitted_acceptances'] == comp['admitted_support_records'] == 0


def novel_example(standard, completion='complete'):
    card, known, request = example(standard, 'new_test')
    known['searched'].update(completion=completion, queries=[{'call_id': 'q1', 'query': 'toy new test', 'source': 'pubmed', 'outcome': 'ok'}])
    known['result'] = 'new'
    request['novelty_claim'] = 'novel'
    request['selections']['novelty'] = '/added/layers/core/novelty_assessment'
    n = card['added']['layers']['core']['novelty_assessment']['value']
    n['search_scope_ref'] = {'kind': 'artifact', 'sha256': rc.sha(rc.search_scope(DUMP(known), standard))}
    return card, known, request


def test_novel_requires_complete_retained_queries_and_stays_asserted(standard):
    wire, artifacts, report = run(novel_example(standard), standard)
    assert record(report)['novelty'] == 'asserted_novel_within_scope'
    assert record(report)['search_coverage'] == 'complete_within_scope'
    scope = rc.reference(standard).codec.loads(artifacts['search'])
    assert scope['queries'] == ['toy new test'] and 'not exhaustive' in scope['limitation']


@pytest.mark.parametrize('completion', ['partial', 'cards_only'])
def test_partial_missing_scope_stays_unknown_and_refuses_novel(standard, completion):
    data = novel_example(standard, completion)
    with pytest.raises(rc.Refusal, match='NOVEL_WITHOUT_COMPLETE_SEARCH'):
        run(data, standard)
    data[2]['novelty_claim'] = 'unknown'
    assert record(run(data, standard)[2])['novelty'] == 'unknown'


@pytest.mark.parametrize('change', [
    lambda d: d[1]['searched'].update(completion='failed'),
    lambda d: d[1].update(result='incomplete'),
    lambda d: d[1]['searched'].update(failed_calls=['q1'], completion='partial'),
    lambda d: d[1]['searched']['queries'][0].update(outcome='failed'),
])
def test_collection_failure_never_emits_an_unknown_success(standard, change):
    data = example(standard)
    change(data)
    with pytest.raises(rc.Refusal, match='COLLECTION_FAILED'):
        run(data, standard)


@pytest.mark.parametrize('change', [
    lambda d: d[1]['input'].update(text_sha256=rc.sha(b'another proposal')),
    lambda d: d[2].update(origin='author_proposal'),
    lambda d: d[2]['selections'].update(known_results=[]),
    lambda d: d[2]['selections']['known_results'][0].update(work_index=True),
    lambda d: d[2]['selections']['known_results'][0].update(work_index=1),
    lambda d: d[1].update(evidence=[]),
    lambda d: d[1]['works'][0].update(quote_check='not_found'),
    lambda d: d[0]['added']['layers']['evidence']['references'][0]['identifier'].update(value='10.9999/foreign'),
    lambda d: d[2]['selections'].update(proposal='/added/layers/core/missing'),
    lambda d: d[2]['annotations'].update(extra_text='unbound text'),
])
def test_target_zone_known_result_and_reference_refusals(standard, change):
    data = example(standard)
    change(data)
    with pytest.raises(rc.Refusal):
        run(data, standard)


@pytest.mark.parametrize('mutation', [
    lambda d: d[2]['annotations'].update(replication_justification=None),
    lambda d: d[2]['annotations']['replication_justification'].update(reason=' '),
    lambda d: d[2]['annotations']['replication_justification'].update(changed_conditions=''),
    lambda d: d[2]['annotations']['replication_justification'].update(prior_result_pointer='/added/layers/evidence/lines/9/result_estimate'),
])
def test_replication_needs_each_annotation_and_prior_binding(standard, mutation):
    data = example(standard, 'replication')
    mutation(data)
    with pytest.raises((rc.Refusal, rc.reference(standard).errors.ContractError)):
        run(data, standard)


@pytest.mark.parametrize('field', ['question', 'next_test', 'positive_prediction', 'negative_prediction'])
def test_no_question_test_or_outcome_reconstruction(standard, field):
    data = example(standard, 'replication')
    data[2]['selections'][field] = None
    with pytest.raises(rc.reference(standard).errors.ContractError):
        run(data, standard)


@pytest.mark.parametrize('change', [
    lambda n: n.update(search_scope_ref={'kind': 'artifact', 'sha256': rc.sha(b'stale')}),
    lambda n: n.update(as_of='2029-01-01T01:02:03Z'),
    lambda n: n.pop('new_content'),
    lambda n: n.update(status='claimed'),
])
def test_novel_assessment_already_binds_exact_scope(standard, change):
    data = novel_example(standard)
    change(data[0]['added']['layers']['core']['novelty_assessment']['value'])
    with pytest.raises(rc.reference(standard).errors.ContractError):
        run(data, standard)


def test_author_prior_context_with_ai_proposal_still_added(standard):
    card, known, req = example(standard, 'replication')
    card['author']['layers']['evidence'] = card['added']['layers'].pop('evidence')
    pair = req['selections']['known_results'][0]
    pair['result'] = pair['result'].replace('/added/', '/author/')
    pair['reference'] = pair['reference'].replace('/added/', '/author/')
    req['annotations']['replication_justification']['prior_result_pointer'] = pair['result']
    assert record(run((card, known, req), standard)[2])['zone'] == 'added'


def test_cli_export_exclusive_and_failure_leaves_no_envelope(standard, tmp_path, capsys):
    data = example(standard)
    names = ['card.json', 'known.json', 'request.json']
    for name, value in zip(names, data):
        (tmp_path/name).write_bytes(DUMP(value))
    argv = ['--standard-root', str(standard), 'produce', *(str(tmp_path/n) for n in names), str(tmp_path/'bundle')]
    assert rc.main(argv) == 0
    assert json.loads(capsys.readouterr().out)['required_profile'] == rc.PROFILE
    api = rc.reference(standard)
    assert api.retention.import_bundle(tmp_path/'bundle', api.validation_context, required_profile=rc.PROFILE)
    assert rc.main(argv) == 2
    data[1]['searched']['failed_calls'] = ['q1']
    (tmp_path/'known.json').write_bytes(DUMP(data[1]))
    capsys.readouterr()
    argv[-1] = str(tmp_path/'failed-bundle')
    assert rc.main(argv) == 2
    assert json.loads(capsys.readouterr().out)['code'] == 'COLLECTION_FAILED'
    assert not (tmp_path/'failed-bundle').exists()


def test_standard_pin_refuses_drift_before_import(standard, tmp_path):
    pin = json.loads(rc.PINS.read_bytes())
    for name in pin['files']:
        target = tmp_path/name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(standard/name, target)
    p = tmp_path/'tools/companions/research.py'
    p.write_bytes(p.read_bytes() + b'\nraise RuntimeError("must never execute")\n')
    with pytest.raises(rc.Refusal, match='STANDARD_PIN'):
        rc.reference(tmp_path)


def test_actual_native_known_producer_seam_and_default_classification(standard, tmp_path):
    rec = {'source': 'MED', 'id': '900001', 'pmid': '900001', 'doi': '10.9999/invented-fable',
           'title': 'Invented fable assay', 'abstractText': 'Toy cells showed a fable marker. Toy cells were examined.',
           'pubTypeList': {'pubType': ['JournalArticle']}}
    s = search.Searcher(tmp_path, get=lambda url: (200, DUMP({'resultList': {'result': [rec]}}), {}),
                        sleep=lambda _: None, clock=lambda: 0.0)
    s.log({'call_id': 'q1', 'tool': 'literature', 'outcome': 'ok', 'ask': {'query': 'toy fable',
           'source': 'europepmc', 'variant': 'as_given'}, 'hit_count': 1, 'found': 1,
           'works': [{'source_id': 'MED:900001', 'pmid': '900001', 'doi': rec['doi']}], 'responses': []})
    inp = search.known_input(TEXT, [], tmp_path, searcher=s)
    reader = {'checker': {'name': 'invented reader', 'model': 'fake', 'session': 'fake-one'},
              'works': [{'item': 1, 'verdict': 'tests_mixed', 'quote': 'Toy cells showed a fable marker.',
                         'population': 'Toy cells', 'population_match': 'same', 'locator': 'abstract'}], 'cards': []}
    known = search.known_merge(TEXT, inp, reader, 'invented query writer', tmp_path)
    assert known['result'] == 'tested_unresolved'
    assert known['works'][0]['quote_check'] == 'verified'
    assert known['searched'] == inp['searched']
    card, _, req = example(standard, 'replication')
    novelty = card['added']['layers']['core']['novelty_assessment']['value']
    novelty.update(as_of=known['checked_at'], search_scope_ref={'kind': 'artifact', 'sha256': rc.sha(rc.search_scope(DUMP(known), standard))})
    before = (tmp_path/search.LOG).read_bytes()
    assert record(run((card, known, req), standard)[2])['contribution_type'] == 'replication'
    assert (tmp_path/search.LOG).read_bytes() == before


@pytest.mark.parametrize('change', [
    lambda d: d[1].update(schema='foreign'),
    lambda d: d[1].update(schema_version=True),
    lambda d: d[1].update(result='foreign'),
    lambda d: d[1].pop('searched'),
    lambda d: d[1]['searched'].update(completion='foreign'),
    lambda d: d[1]['searched'].update(queries=[d[1]['searched']['queries'][0]]*33),
    lambda d: d[1]['searched'].update(queries=d[1]['searched']['queries']*2),
    lambda d: d[1]['searched']['queries'][0].update(query=' '),
    lambda d: d[1]['searched']['queries'][0].update(source='foreign'),
    lambda d: d[1]['searched'].update(per_query=0),
    lambda d: d[1]['searched'].update(max_works=61),
    lambda d: d[1]['searched'].update(max_works=True),
    lambda d: d[1].update(works=None),
    lambda d: d[1].update(checked_at='not a time'),
    lambda d: d[2].update(format='foreign'),
    lambda d: d[2].update(actor=' '),
    lambda d: d[2].update(novelty_claim='verified'),
    lambda d: d[2]['selections'].update(known_results=d[2]['selections']['known_results']*2),
    lambda d: d[2]['selections'].update(proposal=None),
    lambda d: d[2]['selections']['known_results'][0].update(result=None),
])
def test_specific_input_and_limit_refusals(standard, change):
    data = example(standard)
    change(data)
    with pytest.raises(rc.Refusal):
        run(data, standard)


def test_no_queries_means_no_novel_assertion_even_if_native_complete(standard):
    data = novel_example(standard)
    data[1]['searched']['queries'] = []
    with pytest.raises(rc.Refusal, match='NOVEL_WITHOUT_COMPLETE_SEARCH'):
        run(data, standard)


@pytest.mark.parametrize('change', [
    lambda c, r: c.update(standard_version='1.3'),
    lambda c, r: r['selections'].update(novelty=None),
    lambda c, r: c['added']['layers']['core']['novelty_assessment']['value'].update(new_content='extra'),
    lambda c, r: c['added']['layers']['core']['novelty_assessment']['value'].update(prior_claim_refs=[{'kind':'card','pointer':'/foreign'}]),
    lambda c, r: c['added']['layers']['core']['testability']['value'].update(cheapest_test={'kind':'reference','ref':'x'}),
])
def test_standard_owns_version_prior_claim_and_literal_test_boundaries(standard, change):
    c, k, r = example(standard)
    change(c, r)
    with pytest.raises(rc.reference(standard).errors.ContractError):
        run((c, k, r), standard)


def test_missing_outcomes_remain_not_supplied_with_no_annotation(standard):
    data = example(standard, 'new_test')
    for outcome in ('positive', 'negative'):
        data[2]['selections'][outcome+'_prediction'] = None
        data[2]['annotations']['outcome_additions'][outcome] = None
    assert all(v == {'status':'not_supplied'} for v in record(run(data, standard)[2])['outcomes'].values())


def test_scope_cli_and_nonblank_multibyte_annotations(standard, tmp_path, capsys):
    data = example(standard, 'replication')
    data[2]['annotations']['replication_justification']['reason'] = 'Вымышленное слепое повторение.'
    assert record(run(data, standard)[2])['replication_justification']['reason'].startswith('Вымышленное')
    p=tmp_path/'known.json';p.write_bytes(DUMP(data[1]))
    assert rc.main(['--standard-root',str(standard),'scope',str(p)]) == 0
    assert json.loads(capsys.readouterr().out)['coverage'] == 'complete_within_scope'


def test_bad_json_and_path_are_typed_and_no_export(standard, tmp_path, capsys):
    api=rc.reference(standard)
    with pytest.raises(api.errors.ContractError):
        rc.produce(b'{}', b'{', b'{}', standard)
    with pytest.raises(rc.Refusal, match='INPUT_FILE'):
        rc.read('invalid\x00path')
    assert rc.main(['--standard-root',str(standard),'produce',str(tmp_path/'missing'),'x','y',str(tmp_path/'none')]) == 2
    assert json.loads(capsys.readouterr().out)['status'] == 'REFUSE'
    assert not (tmp_path/'none').exists()


def test_non_test_known_work_refuses_with_known_binding(standard):
    data = example(standard)
    data[1]['works'][0]['verdict'] = 'proposes_or_discusses'
    with pytest.raises(rc.Refusal) as caught:
        run(data, standard)
    assert caught.value.code == 'KNOWN_BINDING'


def test_input_over_one_mib_refuses_with_input_limit(tmp_path):
    path = tmp_path/'over-limit.json'
    path.write_bytes(b' ' * (1024 * 1024 + 1))
    with pytest.raises(rc.Refusal) as caught:
        rc.read(path)
    assert caught.value.code == 'INPUT_LIMIT'


def test_symlinked_card_cli_refuses_with_input_file(standard, tmp_path, capsys):
    data = example(standard)
    for name, value in zip(('card.json', 'known.json', 'request.json'), data):
        (tmp_path/name).write_bytes(DUMP(value))
    (tmp_path/'linked-card.json').symlink_to(tmp_path/'card.json')
    output = tmp_path/'no-bundle'
    status = rc.main(['--standard-root', str(standard), 'produce', str(tmp_path/'linked-card.json'),
                      str(tmp_path/'known.json'), str(tmp_path/'request.json'), str(output)])
    assert status == 2
    assert json.loads(capsys.readouterr().out)['code'] == 'INPUT_FILE'
    assert not output.exists()
