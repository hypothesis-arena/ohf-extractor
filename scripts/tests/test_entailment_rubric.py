"""Invented rubric/input controls only; supplied fake verdicts are not model evidence."""
from copy import deepcopy
import hashlib
import json
import socket
import subprocess
from types import SimpleNamespace
import urllib.request

import pytest
import entailment
import entailment_rubric as v2
import check_ledger
import checker_io as io

ATOM = '/added/layers/core/atoms/0'
SCOPES = {ATOM: {'atom_pointer': ATOM, 'statement_pointer': ATOM + '/statement', 'scope': 'whole_atom'}}
P = 'We propose that square precedes circle only on red boards.'


@pytest.fixture(autouse=True)
def deny_external_actions(monkeypatch):
    def deny(*a, **k):
        raise AssertionError('offline invented fixture: external action denied')
    for module, name in ((socket, 'socket'), (socket, 'create_connection'),
                         (subprocess, 'Popen'), (urllib.request, 'urlopen')):
        monkeypatch.setattr(module, name, deny)
    # No ambient auth/token lookups in the module; callbacks are not an API here.
    monkeypatch.setenv('OHF_MODEL', 'INVENTED_NOT_A_MODEL_CALL')


@pytest.fixture
def sample():
    def node(value, **extra):
        return {'value': value, 'src': 'p1', **extra}
    card = {'id': 'invented-square', 'version': 1, 'standard_version': '1.1',
            'added': {'sources': {'p1': {'source': 'https://fixture.invalid/invented',
                                       'locator': 'XML .//p[1]', 'retrieved_at': '2026-02-02T01:02:03Z'}},
                      'integrity': {'entailment': []}, 'layers': {'core': {
                          'scope': node('Red boards only.'), 'atoms': [{
                              'id': 'a_square', 'statement': node('Square precedes circle only on red boards.'),
                              'claim_type': node('mechanism'), 'role': node('core'),
                              'modality': node('proposed', basis_quote='We propose')}]}}}}
    doc = SimpleNamespace(sha='sha256:' + hashlib.sha256(P.encode()).hexdigest(), para=lambda n: P)
    return card, {'https://fixture.invalid/invented': doc}


def prepare(sample):
    card, docs = sample
    return v2.prepare(card, docs, mode='rubric-2', modality_scopes=SCOPES)


def fake(packet, verdict='entails', note=None):
    return {**{k: deepcopy(packet[k]) for k in ('checker','rubric','request_sha256','input_sha256')},
            'results': [{'id': x['id'], 'verdict': verdict,
             **({'note': note or 'Invented fake response; not a scientific judgement.'} if verdict != 'entails' else {})}
            for x in packet['items']]}


def test_M1_exact_visible_atom_scope_and_separate_quote(sample, tmp_path):
    card, docs = sample
    original = deepcopy(card)
    packet = v2.freeze(card, docs, tmp_path/'input.json', mode='rubric-2', modality_scopes=SCOPES)
    raw = io.encoded(packet['items'])
    assert packet['request_utf8'].encode() == v2.prompt() + b'\n\n' + raw
    visible = json.loads(packet['request_utf8'][len(v2.prompt().decode())+2:])
    rows = [x for x in visible if x['pointer'] == ATOM+'/modality']
    assert len(rows) == 2
    assert rows[0]['source_passage'] == P and rows[1]['source_passage'] == 'We propose'
    assert rows[0]['value'] == rows[1]['value']
    assert rows[0]['value']['atomic_claim']['atom']['statement']['value'].endswith('only on red boards.')
    assert rows[0]['value']['modality_scope'] == SCOPES[ATOM]
    assert all(set(x) == {'id','pointer','basis','value','source_passage'} for x in visible)
    assert card == original
    with pytest.raises(ValueError):
        v2.freeze(card, docs, tmp_path/'input.json', mode='rubric-2', modality_scopes=SCOPES)


@pytest.mark.parametrize('mutation', ['missing', 'blank', 'identifier_only', 'foreign_field'])
def test_M2_missing_atomic_context_refuses(sample, mutation):
    card, docs = sample
    a = card['added']['layers']['core']['atoms'][0]
    if mutation == 'missing': a.pop('statement')
    elif mutation == 'blank': a['statement']['value'] = ' '
    elif mutation == 'identifier_only': a['statement'] = {'value': None, 'src': 'p1'}
    else: a['invented_condition_not_rendered'] = 'Do not discard me'
    with pytest.raises(v2.InputRefused, match='INPUT_REFUSED_MISSING_ATOM_CONTEXT'):
        prepare(sample)


@pytest.mark.parametrize('scopes', [{}, {ATOM: {'scope':'proper_clause'}},
                                   {ATOM: {**SCOPES[ATOM], 'statement_pointer':'/foreign'}}])
def test_M3_explicit_whole_atom_scope_required(sample, scopes):
    with pytest.raises(v2.InputRefused, match='INPUT_REFUSED_MODALITY_SCOPE'):
        v2.prepare(*sample, mode='rubric-2', modality_scopes=scopes)


def test_M3_conditional_not_mechanically_split_and_parent_context_preserved(sample):
    card, docs = sample
    core = card['added']['layers']['core']
    child = core['atoms'][0]; child['parent_ref'] = 'parent'
    core['atoms'].append({'id':'parent', 'statement':{'value':'No circle without a red board.', 'src':'p1'}})
    rows = prepare(sample)['items']
    value = next(x['value'] for x in rows if x['pointer']==ATOM+'/modality')
    assert value['atomic_claim']['parents'][0]['statement']['value'] == 'No circle without a red board.'
    assert 'only on red boards' in value['atomic_claim']['atom']['statement']['value']
    assert sum(x['pointer']==ATOM+'/modality' for x in rows)==2


@pytest.mark.parametrize('field', ['operator','requires','parent_ref'])
def test_S1_explicit_compound_and_unsupported_context_refuse(sample, field):
    card, docs = sample
    atom = card['added']['layers']['core']['atoms'][0]
    atom[field] = {'operator':'AND','requires':{'value':['other'], 'src':'p1'},'parent_ref':'foreign'}[field]
    code = 'INPUT_REFUSED_COMPOUND_TARGET' if field=='operator' else 'INPUT_REFUSED_MISSING_ATOM_CONTEXT'
    with pytest.raises(v2.InputRefused, match=code): prepare(sample)


def test_S1_rule_is_scoped_direction_not_hypothesis_proof():
    text = v2.prompt().decode()
    assert '`supports` records positive direction' in text
    assert 'not whether it proves the\nhypothesis' in text
    assert 'A child answer does not authorize an unsplit parent' in text
    assert 'Do not mechanically split on “and”' in text


@pytest.mark.parametrize('passage,verdict,note', [
    ('We propose that square precedes circle on red boards. It might also apply elsewhere.', 'partial',
     'Invented: proposal supports red boards; blue boards are not identified by the ambiguous elsewhere.'),
    ('We propose it.', 'no', 'Invented: no identifiable supported atom; unresolved antecedent alone is not partial support.')])
def test_C1_L1_pair_records_explicit_fake_answers_without_semantic_oracle(sample, passage, verdict, note):
    card, docs = sample
    docs['https://fixture.invalid/invented'].para = lambda n: passage
    card['added']['layers']['core']['atoms'][0]['statement']['value'] = 'Square precedes circle on red or blue boards.'
    packet = prepare(sample); ledger = v2.new_ledger(card)
    result = v2.merge(card, docs, packet, fake(packet, verdict, note), ledger, mode='rubric-2')
    assert all(r['verdict']==verdict and r['note']==note for r in result['records'])
    assert result['scientific_truth_evaluated'] is False
    text = v2.prompt().decode()
    assert 'identifiable partial or qualified\nsupport' in text
    assert 'An unresolved antecedent alone is not partial support' in text
    assert 'without such\nsupport use `no`' in text


def test_C1_C2_no_sidecar_cross_item_or_provenance_evidence(sample):
    packet = prepare(sample)
    assert 'Only this item\'s `source_passage` supplies evidential premises' in packet['request_utf8']
    assert 'They do not\nestablish that a finding used a particular dataset/cohort' in packet['request_utf8']
    assert 'another item' in packet['request_utf8'] and 'sidecar' in packet['request_utf8']
    quotes = [x for x in packet['items'] if x['basis']=='basis_quote']
    assert all(x['source_passage']=='We propose' for x in quotes)
    assert 'card' not in packet['sources']  # source binding is metadata, not an extra evidence passage


@pytest.mark.parametrize('field', ['checker','rubric','value_sha256','passage_sha256',
                                   'source_binding_sha256','question_card_sha256','request_sha256','input_sha256'])
def test_B1_every_model_field_requires_complete_identity(sample, field):
    card, docs = sample; packet=prepare(sample); ledger=v2.new_ledger(card)
    v2.merge(card, docs, packet, fake(packet), ledger, mode='rubric-2')
    for history in ledger['entries'].values(): history[0].pop(field)
    result=v2.carry(card, docs, ledger, mode='rubric-2', modality_scopes=SCOPES)
    assert result['records']==[] and len(result['rest'])==len(packet['items'])
    # Includes plain scope, statement, claim_type and role; not just modality.
    assert any(x['pointer'].endswith('/scope') for x in result['rest'])


@pytest.mark.parametrize('change', ['atom','core_scope','source_record','source_version','rubric','checker','passage'])
def test_B1_stale_packet_refused_before_any_history_write(sample, change):
    card, docs = sample; packet=prepare(sample); ledger=v2.new_ledger(card)
    if change=='atom': card['added']['layers']['core']['atoms'][0]['statement']['value']='Circle precedes square.'
    elif change=='core_scope': card['added']['layers']['core']['scope']['value']='Blue boards.'
    elif change=='source_record': card['added']['sources']['p1']['locator']='XML .//p[2]'
    elif change=='source_version': docs['https://fixture.invalid/invented'].sha='sha256:'+'0'*64
    elif change=='rubric': packet['rubric']='foreign'
    elif change=='checker': packet['checker']['version']='foreign'
    else: docs['https://fixture.invalid/invented'].para=lambda n:'Different passage.'
    with pytest.raises(v2.InputRefused,match='INPUT_REFUSED_STALE_INPUT'):
        v2.merge(card,docs,packet,fake(packet),ledger,mode='rubric-2')
    assert ledger['entries']=={}


def test_B1_worst_history_restore_carry_check_export(sample,tmp_path):
    card, docs=sample;packet=prepare(sample);ledger=v2.new_ledger(card)
    v2.merge(card,docs,packet,fake(packet,'no'),ledger,mode='rubric-2')
    v2.merge(card,docs,packet,fake(packet,'entails'),ledger,mode='rubric-2')
    history=deepcopy(ledger)
    fresh=v2.new_ledger(card)
    result=v2.restore(card,docs,fresh,history,mode='rubric-2',modality_scopes=SCOPES)
    assert fresh==history and all(r['verdict']=='no' for r in result['records'])
    exported=v2.export(card,docs,fresh,tmp_path/'v2-ledger.json',mode='rubric-2',modality_scopes=SCOPES)
    assert exported['status']=='BOUND_ATTESTATIONS_ONLY' and exported['full_card_validated'] is False
    assert json.loads((tmp_path/'v2-ledger.json').read_text())==history
    card['added']['layers']['core']['atoms'][0]['statement']['value']='A different atom.'
    result=v2.carry(card,docs,fresh,mode='rubric-2',modality_scopes=SCOPES)
    assert result['rest'] and fresh==history
    with pytest.raises(v2.InputRefused):
        v2.export(card,docs,fresh,tmp_path/'stale.json',mode='rubric-2',modality_scopes=SCOPES)


def test_H1_default_and_invented_old_snapshot_remain_unchanged(sample):
    card,docs=sample; old=deepcopy(card)
    olditems=entailment.build(card,docs);oldledger=check_ledger.new_ledger(card)
    oldbytes=io.encoded(oldledger)
    packet=prepare(sample);v2.merge(card,docs,packet,fake(packet),v2.new_ledger(card),mode='rubric-2')
    assert card==old and entailment.build(card,docs)==olditems and io.encoded(oldledger)==oldbytes
    assert next(x['value'] for x in olditems if x['pointer']==ATOM+'/modality')=='proposed'
    with pytest.raises(v2.InputRefused,match='INPUT_REFUSED_LEDGER'):
        v2.restore(card,docs,v2.new_ledger(card),oldledger,mode='rubric-2',modality_scopes=SCOPES)


@pytest.mark.parametrize('version', ['1.3','1.4','unknown'])
def test_native_activation_explicit_hold(sample,version):
    sample[0]['standard_version']=version
    with pytest.raises(v2.InputRefused,match='INPUT_REFUSED_NATIVE_HOLD'):prepare(sample)


def test_mode_and_result_shape_are_closed(sample):
    card,docs=sample
    with pytest.raises(v2.InputRefused,match='INPUT_REFUSED_MODE'):
        v2.prepare(card,docs,mode='default',modality_scopes=SCOPES)
    packet=prepare(sample);ledger=v2.new_ledger(card)
    bad=fake(packet);bad['results'][-1]['verdict']='not_assessed'
    with pytest.raises(ValueError):v2.merge(card,docs,packet,bad,ledger,mode='rubric-2')
    assert ledger['entries']=={}


def test_S1_actual_ordinary_direction_retains_target_and_quote(sample):
    card, docs=sample
    line={'id':'e_square','target_ref':'a_square','quote':'Square precedes circle.',
          'direction':{'value':'supports','src':'p1'}}
    card['added']['layers']['evidence']={'lines':[line]}
    items=prepare(sample)['items']
    direction=next(x for x in items if x['pointer'].endswith('/lines/0/direction'))
    assert direction['value']==check_ledger.checked_value(card,direction['pointer'],line['direction'])
    assert direction['value']['target_statement']=='Square precedes circle only on red boards.'
    assert direction['value']['line_quote']=='Square precedes circle.'
    line['quote']='Circle precedes square.'
    assert prepare(sample)['input_sha256'] != v2.sha(io.encoded(items))


def test_C1_inside_passage_definition_stays_separate_from_other_item(sample):
    card, docs=sample
    paragraph='Square precedes circle on red boards. We propose this relation.'
    docs['https://fixture.invalid/invented'].para=lambda n:paragraph
    packet=prepare(sample)
    pair=[x for x in packet['items'] if x['pointer']==ATOM+'/modality']
    assert pair[0]['source_passage']==paragraph
    assert pair[1]['source_passage']=='We propose'
    # Configuration/another row never expands the basis_quote. This tests input
    # visibility only; there is no simulated scientific interpretation here.
    assert 'Square precedes circle' not in pair[1]['source_passage']


@pytest.mark.parametrize('source_hash', ['', 'unknown', None])
def test_C2_unknown_source_version_refuses(sample,source_hash):
    sample[1]['https://fixture.invalid/invented'].sha=source_hash
    with pytest.raises(v2.InputRefused,match='INPUT_REFUSED_SOURCE_BINDING'):prepare(sample)


def test_B1_foreign_checker_never_becomes_current_by_restore(sample):
    card, docs=sample; packet=prepare(sample); original=v2.new_ledger(card)
    v2.merge(card,docs,packet,fake(packet),original,mode='rubric-2')
    for history in original['entries'].values():history[0]['checker']['version']='1.0.0'
    before=deepcopy(original);restored=v2.new_ledger(card)
    result=v2.restore(card,docs,restored,original,mode='rubric-2',modality_scopes=SCOPES)
    assert restored==before and original==before and result['records']==[] and result['rest']


@pytest.mark.parametrize('field', ['bare_output','checker','rubric','input_sha256','request_sha256'])
def test_B1_old_output_ids_cannot_acquire_new_request_identity(sample,field):
    card,docs=sample;packet=prepare(sample);ledger=v2.new_ledger(card)
    response=fake(packet)
    if field=='bare_output':response=response['results']
    elif field=='checker':response['checker']['version']='old-checker'
    else:response[field]='old-request-or-rubric'
    with pytest.raises(v2.InputRefused,match='INPUT_REFUSED_RESULT_BINDING'):
        v2.merge(card,docs,packet,response,ledger,mode='rubric-2')
    assert ledger['entries']=={}


# R1 controls exercise public entrypoints on invented JSON trees. The interval
# field mirrors the reviewer's distinguishing producer path; whole-card schema
# or model/scientific validity is not asserted by these protocol controls.
def interval_sample(sample, lower=1):
    card, docs = sample
    card['added']['layers']['evidence'] = {'lines': [{'id': 'invented_interval',
        'confidence_interval': {'value': {'level': '95%', 'lower': lower, 'upper': 2,
            'contrast': 'square versus circle', 'scale': 'invented units'}, 'src': 'p1'}}]}
    return card, docs


@pytest.mark.parametrize('lower', [1, 1.0, 0])
def test_R1_unchanged_numeric_packet_merge_check_consistent(sample, lower):
    card, docs = interval_sample(sample, lower)
    packet = prepare(sample); before = deepcopy(packet); ledger = v2.new_ledger(card)
    result = v2.merge(card, docs, packet, fake(packet), ledger, mode='rubric-2')
    current = v2.check(card, docs, ledger, mode='rubric-2', modality_scopes=SCOPES)
    assert not result['rest'] and current['status'] == 'BOUND_ATTESTATIONS_ONLY'
    assert len(result['records']) == 7
    assert packet == before


@pytest.mark.parametrize('lower,poison', [(1, True), (1, 1.0), (1, '1'),
                                         (0, False), (0, 0.0), (1.0, 1)])
def test_R1_scalar_alias_packet_refuses_before_append(sample, lower, poison):
    card, docs = interval_sample(sample, lower)
    original = prepare(sample); packet = deepcopy(original)
    item = next(x for x in packet['items'] if x['pointer'].endswith('/confidence_interval'))
    item['value']['lower'] = poison
    assert io.encoded(packet['items']) != io.encoded(original['items'])
    assert packet['input_sha256'] == original['input_sha256']
    assert packet['request_utf8'] == original['request_utf8']
    ledger = v2.new_ledger(card); before = deepcopy(ledger)
    with pytest.raises(v2.InputRefused, match='INPUT_REFUSED_STALE_INPUT'):
        v2.merge(card, docs, packet, fake(original), ledger, mode='rubric-2')
    assert ledger == before


@pytest.mark.parametrize('poison', [True, 1.0, '1'])
def test_R1_nested_alias_packet_refuses_before_append(sample, poison):
    card, docs = sample
    card['added']['layers']['core']['atoms'][0]['context_override'] = {
        'value': {'invented_bounds': [0, {'threshold': 1}]}, 'src': 'p1'}
    original = prepare(sample); packet = deepcopy(original)
    item = next(x for x in packet['items'] if x['pointer'] == ATOM+'/modality')
    item['value']['atomic_claim']['atom']['context_override']['value']['invented_bounds'][1]['threshold'] = poison
    ledger = v2.new_ledger(card)
    with pytest.raises(v2.InputRefused, match='INPUT_REFUSED_STALE_INPUT'):
        v2.merge(card, docs, packet, fake(original), ledger, mode='rubric-2')
    assert ledger['entries'] == {}


def test_R1_reordered_value_keys_cannot_differ_from_unchanged_wire(sample):
    card, docs = interval_sample(sample)
    original = prepare(sample); packet = deepcopy(original)
    item = next(x for x in packet['items'] if x['pointer'].endswith('/confidence_interval'))
    item['value'] = dict(reversed(list(item['value'].items())))
    assert packet == original  # Same JSON values, but different actual wire bytes.
    assert io.encoded(packet['items']) != io.encoded(original['items'])
    ledger = v2.new_ledger(card)
    with pytest.raises(v2.InputRefused, match='INPUT_REFUSED_STALE_INPUT'):
        v2.merge(card, docs, packet, fake(original), ledger, mode='rubric-2')
    assert ledger['entries'] == {}


def test_R1_outer_metadata_order_preserves_same_request(sample):
    card, docs = interval_sample(sample)
    original = prepare(sample); packet = dict(reversed(list(original.items())))
    assert io.encoded(packet['items']) == io.encoded(original['items'])
    ledger = v2.new_ledger(card)
    assert not v2.merge(card, docs, packet, fake(original), ledger, mode='rubric-2')['rest']
    assert v2.check(card, docs, ledger, mode='rubric-2', modality_scopes=SCOPES)['status'] == 'BOUND_ATTESTATIONS_ONLY'


@pytest.mark.parametrize('poison', [True, 1.0, '1'])
def test_R1_response_identity_has_no_numeric_alias(sample, monkeypatch, poison):
    # An invented numeric identity component tests the generic identity reader;
    # it does not add a production checker field or claim a native schema profile.
    monkeypatch.setitem(v2.CHECKER, 'invented_revision', 1)
    card, docs = sample; packet = prepare(sample); response = fake(packet)
    response['checker']['invented_revision'] = poison
    ledger = v2.new_ledger(card)
    with pytest.raises(v2.InputRefused, match='INPUT_REFUSED_RESULT_BINDING'):
        v2.merge(card, docs, packet, response, ledger, mode='rubric-2')
    assert ledger['entries'] == {}


@pytest.mark.parametrize('poison', [True, 1.0, '1'])
def test_R1_stored_identity_has_no_numeric_alias(sample, monkeypatch, poison):
    monkeypatch.setitem(v2.CHECKER, 'invented_revision', 1)
    card, docs = sample; packet = prepare(sample); ledger = v2.new_ledger(card)
    v2.merge(card, docs, packet, fake(packet), ledger, mode='rubric-2')
    for history in ledger['entries'].values():
        history[0]['checker']['invented_revision'] = poison
    before = deepcopy(ledger)
    result = v2.carry(card, docs, ledger, mode='rubric-2', modality_scopes=SCOPES)
    assert result['records'] == [] and len(result['rest']) == len(packet['items'])
    assert ledger == before


@pytest.mark.parametrize('poison', [True, 1.0])
def test_R1_history_dedup_does_not_conflate_identity(sample, monkeypatch, poison):
    monkeypatch.setitem(v2.CHECKER, 'invented_revision', 1)
    monkeypatch.setattr(v2.io, 'now', lambda: '2026-02-02T01:02:03Z')
    card, docs = sample; packet = prepare(sample); ledger = v2.new_ledger(card)
    v2.merge(card, docs, packet, fake(packet), ledger, mode='rubric-2')
    for history in ledger['entries'].values():
        history[0]['checker']['invented_revision'] = poison
    result = v2.merge(card, docs, packet, fake(packet), ledger, mode='rubric-2')
    assert not result['rest']
    assert all(len(history) == 2 for history in ledger['entries'].values())
    assert all(type(history[0]['checker']['invented_revision']) is type(poison)
               and type(history[1]['checker']['invented_revision']) is int
               for history in ledger['entries'].values())
