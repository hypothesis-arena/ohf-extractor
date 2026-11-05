"""OHF 1.4 selected profile: invented sources and injected fake results only."""
from copy import deepcopy
import json
import os
from pathlib import Path
import pytest
import ohfkit
if ohfkit.standard_line() != '1.4':
    pytest.skip('Explicit OHF 1.4 native profile checkout required', allow_module_level=True)

import native_profile as profile
import native_entailment as entailment
import native_ledger as ledger
import checker_io as io
import projection_binding as projection
from profile_fixture import ProfileFixture
import native_profile_ci_driver as driver


def test_epoch2_full_entrypoint_and_exact_bare_boundary(tmp_path):
    f=ProfileFixture(tmp_path);inp,out=f.merge_profile()
    result=f.validate_profile();assert result['status']=='PASS',result
    assert result['schema_valid'] and result['native_binding_valid']
    assert result['scientific_truth_evaluated'] is False
    assert f.selected=={'id':'ohf-native-relational@1','epoch':2,
        'definition_sha256':'sha256:c964ce88b31374062cbebf6e801259f3f85533244633d3d5642cc7bab9124db7'}
    assert f.card['added']['by']['converter_version']==ohfkit.CONVERTER['version']=='0.9.14-dev'
    assert f.card['added']['by']['converter_hash']==ohfkit.rules_hash()
    native,conditions=profile.build(f.card,f.docs,f.selected)
    bare=projection.reference();ordinary=bare.value_items(f.card)
    assert {(x['pointer'],x['basis']) for x in native}=={(x['pointer'],x['basis']) for x in ordinary}
    assert all('derives_from_atom_refs' not in x['pointer'] for x in native)
    assert any('derives_from_atom_refs' in x['pointer'] for x in conditions)
    errors=bare.check(f.card,f.ledger,{ledger.key_of(x):x['source_passage'] for x in native})
    fields=['direction','indirectness','sample_size','endpoint_kind']
    assert len(errors)==4,errors
    for field in fields:
        assert sum('/lines/0/'+field+'|' in e for e in errors)==1,errors
    direction=next(x for x in native if x['pointer'].endswith('/lines/0/direction'))
    target=bare.target_statement(f.card,f.line)
    assert direction['value']['target_statement']==target
    assert projection.value_sha256(target)==bare.value_sha256(target)
    assert direction['value']!=bare.checked_value(f.card,direction['pointer'],f.line['direction'])
    assert profile.stale_items(f.card,f.docs,f.selected,inp,out)==[]
    profile.export(f.card,f.ledger,f.docs,f.selected,tmp_path/'export.json')
    (tmp_path/'card.json').write_bytes(io.encoded(f.card));(tmp_path/'selector.json').write_bytes(io.encoded(f.selected))
    assert profile.validate_files(tmp_path/'card.json',tmp_path/'export.json',tmp_path/'selector.json',f.docs)['status']=='PASS'
    assert ohfkit.content_hash(f.card)==f.card['content_hash']


def test_native_condition_changes_cannot_be_rescued_by_new_root_or_roster(tmp_path):
    f=ProfileFixture(tmp_path);f.merge_profile();original_card=deepcopy(f.card);original_ledger=deepcopy(f.ledger)
    changes={
        'scope':lambda c:c['added']['layers']['core']['scope'].update(value='Only red boards.'),
        'horizon':lambda c:c['added']['layers']['predictions'][0]['horizon'].update(value='two days'),
        'atom':lambda c:c['added']['layers']['core']['atoms'][0]['statement'].update(value='Circle precedes square.'),
        'direction':lambda c:c['added']['layers']['evidence']['lines'][0]['direction'].update(value='disputes'),
        'indirectness':lambda c:c['added']['layers']['evidence']['lines'][0]['indirectness']['value'].update(system='none'),
        'sample':lambda c:c['added']['layers']['evidence']['lines'][0]['sample_size'].update(value=9),
        'term':lambda c:c['added']['layers']['evidence']['lines'][0]['endpoint_kind'].update(note='changed invented term'),
        'quote':lambda c:c['added']['layers']['evidence']['lines'][0].update(quote='Eight panels were used.'),
    }
    for name,change in changes.items():
        card=deepcopy(original_card);led=deepcopy(original_ledger);change(card)
        card['content_hash']=ohfkit.content_hash(card);led['content_hash']=card['content_hash']
        items,conditions=profile.build(card,f.docs,f.selected)
        led['card_conditions']=conditions;led['item_roster']=profile.roster(items)
        result=profile.validate_bundle(card,led,f.docs,f.selected)
        assert result['schema_valid'] and result['status']=='REFUSE',(name,result)
    assert f.validate_profile()['status']=='PASS'


def test_carry_restore_share_full_contract_and_preserve_worst_history(tmp_path):
    f=ProfileFixture(tmp_path);f.merge_profile('no','no');f.merge_profile('later','entails')
    original_card=deepcopy(f.card);original_ledger=deepcopy(f.ledger)
    rebuilt=deepcopy(f.card);rebuilt['version']+=1;rebuilt['content_hash']=ohfkit.content_hash(rebuilt)
    assert profile.carry(f.card,rebuilt,f.docs,f.selected,f.ledger)['status']=='PASS'
    assert all(x['verdict']=='no' for x in rebuilt['added']['integrity']['entailment'])
    assert f.ledger['entries']==original_ledger['entries']
    fresh=ledger.new_ledger(original_card);restored=deepcopy(original_card)
    assert profile.restore(restored,f.docs,f.selected,fresh,[(original_card,original_ledger)])['status']=='PASS'
    assert fresh['entries']==original_ledger['entries']
    with pytest.raises(ValueError,match='original card and ledger'):
        profile.restore(restored,f.docs,f.selected,fresh,[])
    broken=deepcopy(original_ledger);broken.pop('checker_io_proofs')
    with pytest.raises(ValueError,match='archived selected pair'):
        profile.restore(restored,f.docs,f.selected,fresh,[(original_card,broken)])
    changed=deepcopy(restored);changed['added']['layers']['core']['scope']['value']='Red boards.'
    changed['content_hash']=ohfkit.content_hash(changed)
    outcome=profile.carry(restored,changed,f.docs,f.selected,fresh)
    assert outcome['status']=='NEEDS_CHECK' and outcome['rest']
    assert profile.validate_bundle(changed,fresh,f.docs,f.selected)['status']=='REFUSE'


def test_refs_gaps_and_content_hash_are_required_not_schema_only(tmp_path):
    f=ProfileFixture(tmp_path);f.merge_profile()
    card=deepcopy(f.card);card['content_hash']='sha256:'+'0'*64
    result=profile.validate_bundle(card,f.ledger,f.docs,f.selected)
    assert result['schema_valid'] and result['status']=='REFUSE'
    assert any('CONTENT_HASH' in e for e in result['errors'])
    card=deepcopy(f.card);card['added']['by']['standard_release']['version']='1.3.1'
    card['added']['budget'].pop('unknown_reasons')  # isolate the release refusal under the old budget shape
    card['content_hash']=ohfkit.content_hash(card)
    result=profile.validate_bundle(card,f.ledger,f.docs,f.selected)
    assert result['schema_valid'] and any('REFS:' in e for e in result['errors']),result
    card=deepcopy(f.card);card['added']['gaps']=[{'path':'core.atoms[].id','disposition':'not_applicable','reason':'Invented malformed contract choice.'}]
    card['content_hash']=ohfkit.content_hash(card)
    checks=profile.card_checks(card,f.selected)
    assert checks['errors'],checks


def test_version_gate_does_not_relabel_released_projection(tmp_path):
    f=ProfileFixture(tmp_path)
    assert profile.schema_errors(f.card,f.selected)==[]
    for version in ['1.3','1.1',None]:
        card=deepcopy(f.card);card['standard_version']=version
        with pytest.raises(ValueError,match='UNSUPPORTED_VERSION'):
            projection.target_statement(card,f.line)
        with pytest.raises(ValueError,match='UNSUPPORTED_VERSION'):
            profile.build(card,f.docs,f.selected)


def test_ci_recipe_binds_exact_asserted_pair_and_same_complete_entrypoint(tmp_path):
    from native_profile_ci import run
    pair={'extractor_commit':'e'*40,'extractor_tree':'d'*40,
          'standard_commit':'a'*40,'standard_tree':'b'*40,'rules_sha256':ohfkit.rules_hash()}
    result=run(tmp_path,pair)
    assert result['status']=='PASS_SYNTHETIC_NATIVE_PROFILE'
    assert result['pair']==pair and result['validation']['schema_valid']
    assert not result['scientific_acceptance']
    assert result['validation']['profile_contract']==profile.contract_identity()
    _items,metadata,_bytes,_pins=io.load_input(tmp_path/'check.json')
    assert metadata['configuration']['ci_pair']==pair
    assert metadata['configuration']['profile_contract']==profile.contract_identity()
    with pytest.raises((OSError,ValueError)):
        run(tmp_path,pair)  # exclusive outputs; no automatic replay
    with pytest.raises(ValueError,match='CI_PAIR'):
        run(tmp_path,{**pair,'rules_sha256':'sha256:'+'0'*64})


def test_released_main_seams_and_selected_context_have_distinguishing_controls(tmp_path):
    import check_ledger as released_ledger
    f=ProfileFixture(tmp_path)
    pointer='/added/layers/evidence/lines/0/direction'
    legacy=deepcopy(f.card)
    legacy['standard_version']='1.3'
    old=released_ledger.checked_value(legacy,pointer,f.line['direction'])
    ordinary_current=released_ledger.checked_value(f.card,pointer,f.line['direction'])
    current=ledger.checked_value(f.card,pointer,f.line['direction'])
    f.card['added']['layers']['core']['scope']['value']='Different invented scope.'
    legacy['added']['layers']['core']['scope']['value']='Different invented scope.'
    assert released_ledger.checked_value(legacy,pointer,f.line['direction'])==old
    assert released_ledger.checked_value(f.card,pointer,f.line['direction'])!=ordinary_current
    assert ledger.checked_value(f.card,pointer,f.line['direction'])!=current
    pointer='/added/layers/evidence/lines/0/indirectness'
    old=released_ledger.checked_value(f.card,pointer,f.line['indirectness'])
    current=ledger.checked_value(f.card,pointer,f.line['indirectness'])
    f.line['direction']['value']='disputes'
    assert released_ledger.checked_value(f.card,pointer,f.line['indirectness'])==old
    assert ledger.checked_value(f.card,pointer,f.line['indirectness'])!=current


def test_original_xml_bytes_stamp_and_parsed_native_state_are_bound(tmp_path):
    f=ProfileFixture(tmp_path);f.merge_profile()
    original=f.doc.profile_xml_bytes
    f.doc.profile_xml_bytes=original.replace(b'Eight',b'Seven')
    result=f.validate_profile();assert result['status']=='REFUSE'
    assert any('SOURCE_BINDING' in e for e in result['errors'])
    f.doc.profile_xml_bytes=original
    f.doc.paragraphs[0]+=' Added unbound text.'
    assert f.validate_profile()['status']=='REFUSE'
    f.doc.paragraphs[0]=ohfkit.norm(''.join(f.doc.root.find('.//p').itertext()))
    assert f.validate_profile()['status']=='PASS'
    f.doc.retrieved='2026-02-03T01:02:03Z'
    assert f.validate_profile()['status']=='REFUSE'
    for data in [b'<article>',b'<?xml version="1.0" encoding="not-a-codec"?><article/>']:
        with pytest.raises(ValueError,match='SOURCE_BINDING'):
            profile.document_from_bytes(data,'PMC810055','2026-02-02T00:00:00Z')


def test_converter_identity_unknown_fields_and_unsupported_sources_are_not_positive(tmp_path):
    f=ProfileFixture(tmp_path);f.merge_profile()
    for field,value in [('converter_version','other'),('converter_hash','sha256:'+'0'*64)]:
        card=deepcopy(f.card);card['added']['by'][field]=value;card['content_hash']=ohfkit.content_hash(card)
        result=profile.validate_bundle(card,f.ledger,f.docs,f.selected)
        assert result['status']=='REFUSE' and any('PROFILE_CONVERTER_BINDING' in x for x in result['errors']),result
    for mutation in ['extra-current-item','missing-proof','wrong-contract','missing-current-item']:
        led=deepcopy(f.ledger)
        if mutation=='extra-current-item':led['item_roster'].append({'pointer':'/added/layers/core/scope','basis':'invented'})
        elif mutation=='missing-current-item':led['item_roster'].pop()
        elif mutation=='wrong-contract':led['profile_contract']['target_module_sha256']='sha256:'+'0'*64
        else:led['checker_io_proofs']={}
        assert profile.validate_bundle(f.card,led,f.docs,f.selected)['status']=='REFUSE',mutation
    with pytest.raises(ValueError,match='UNSUPPORTED_SOURCE'):
        profile.build(f.card,{},f.selected)
    card=deepcopy(f.card);card['added']['layers']['profile']['domain']=['pharmacology']
    with pytest.raises(ValueError,match='UNSUPPORTED_SHAPE'):
        profile.build(card,f.docs,f.selected)


def test_source_version_change_cannot_hide_same_value_passage_worst_history(tmp_path):
    f=ProfileFixture(tmp_path);f.merge_profile('original','no')
    before=deepcopy(f.ledger['entries'])
    raw=f.doc.profile_xml_bytes.replace(b'<article>',b'<article version="invented-two">',1)
    f.doc=profile.document_from_bytes(raw,f.doc.pmcid,f.doc.retrieved);f.docs={f.doc.url:f.doc}
    f.card['author']['source']['source_text_sha256']=f.doc.sha
    f.rehash()
    assert f.validate_profile()['status']=='REFUSE'
    assert profile.stale_items(f.card,f.docs,f.selected,tmp_path/'original.json',tmp_path/'original-result.json')
    # A new fake response cannot silently retire the original same-text 'no'.
    inp,out=f.prepare_profile('different-source','entails')
    card_before,ledger_before=deepcopy(f.card),deepcopy(f.ledger)
    with pytest.raises(ValueError,match='SOURCE_BINDING'):
        profile.merge(f.card,f.docs,f.selected,inp,out,f.ledger)
    assert f.card==card_before and f.ledger==ledger_before
    assert f.ledger['entries']==before


@pytest.mark.parametrize('version',['1.3','1.1',None,'1.4'])
def test_relational_api_requires_version_before_standard_dispatch(monkeypatch,version):
    class DispatchReached(Exception):
        pass
    def reference():
        raise DispatchReached('standard API boundary reached')
    monkeypatch.setattr(projection,'reference',reference)
    node={'value':'supports','src':'invented'}
    card={'standard_version':version,'added':{'layers':{'evidence':{'lines':[{'direction':node}]}}}}
    if version=='1.4':
        with pytest.raises(DispatchReached):
            projection.checked_relation(card,'/added/layers/evidence/lines/0/direction',node)
    else:
        with pytest.raises(ValueError,match='UNSUPPORTED_VERSION'):
            projection.checked_relation(card,'/added/layers/evidence/lines/0/direction',node)


@pytest.fixture(scope='module')
def completed_json_boundary_profile(tmp_path_factory):
    fixture=ProfileFixture(tmp_path_factory.mktemp('completed-json-boundary'))
    fixture.merge_profile()
    return fixture


def malformed_json_ledger(original,case):
    root_cases={'ledger_root_null':None,'ledger_root_array':[],
                'ledger_root_string':'INVENTED','ledger_root_number':1,
                'validate_files_null':None,'validate_files_array':[]}
    if case in root_cases:
        return deepcopy(root_cases[case])
    changed=deepcopy(original)
    key=next(iter(changed['entries']))
    proof_id=next(iter(changed['checker_io_proofs']))
    if case=='ledger_nested_entries_array':changed['entries']=[]
    elif case=='ledger_nested_proofs_array':changed['checker_io_proofs']=[]
    elif case=='ledger_nested_history_object':changed['entries']={key:{'INVENTED':{}}}
    elif case=='ledger_nested_history_null_element':changed['entries']={key:[None]}
    elif case=='notes_array':changed['notes']=[]
    elif case=='entry_binding_array':changed['entries'][key][0]['checker_binding']=[]
    elif case=='proof_null':changed['checker_io_proofs'][proof_id]=None
    elif case=='proof_input_null':changed['checker_io_proofs'][proof_id]['input']=None
    elif case=='proof_configuration_array':changed['checker_io_proofs'][proof_id]['input']['configuration']=[]
    elif case=='proof_envelope_null':changed['checker_io_proofs'][proof_id]['input']['envelope']=None
    elif case=='input_manifest_null_element':changed['checker_io_proofs'][proof_id]['input']['item_manifest']=[None]
    elif case=='result_manifest_object':changed['checker_io_proofs'][proof_id]['result']['result_manifest']={}
    else:raise AssertionError('unknown invented JSON boundary case')
    return changed


@pytest.mark.parametrize('case',[
    'ledger_root_null','ledger_root_array','ledger_root_string','ledger_root_number',
    'ledger_nested_entries_array','ledger_nested_proofs_array','ledger_nested_history_object',
    'ledger_nested_history_null_element','validate_files_null','validate_files_array',
    'notes_array','entry_binding_array','proof_null','proof_input_null',
    'proof_configuration_array','proof_envelope_null','input_manifest_null_element','result_manifest_object'])
def test_public_files_refuse_malformed_ledger_json_containers(tmp_path,completed_json_boundary_profile,case):
    f=completed_json_boundary_profile
    card=tmp_path/'card.json';selector=tmp_path/'selector.json';ledger_path=tmp_path/'ledger.json'
    io.write_once(card,io.encoded(f.card));io.write_once(selector,io.encoded(f.selected))
    io.write_once(ledger_path,io.encoded(malformed_json_ledger(f.ledger,case)))
    before=(card.read_bytes(),selector.read_bytes(),ledger_path.read_bytes())
    result=profile.validate_files(card,ledger_path,selector,f.docs)
    assert result['status']=='REFUSE' and result['schema_valid']
    assert result['native_binding_valid'] is False and result['scientific_truth_evaluated'] is False
    assert any(error.startswith('PROFILE_LEDGER_JSON:') for error in result['errors']),result
    assert before==(card.read_bytes(),selector.read_bytes(),ledger_path.read_bytes())


def test_complete_entrypoint_retains_unchanged_structural_completeness(tmp_path,completed_json_boundary_profile):
    f=completed_json_boundary_profile
    expected=profile.card_checks(f.card,f.selected)['completeness']
    card=tmp_path/'card.json';selector=tmp_path/'selector.json';ledger_path=tmp_path/'ledger.json'
    for path,value in [(card,f.card),(selector,f.selected),(ledger_path,f.ledger)]:
        io.write_once(path,io.encoded(value))
    result=profile.validate_files(card,ledger_path,selector,f.docs)
    assert result['status']=='PASS' and result['schema_valid'] and result['native_binding_valid']
    assert result['completeness']==expected
    assert io.encoded(result['completeness'])==io.encoded(expected)
    assert result['scientific_truth_evaluated'] is False


def test_unrelated_programming_attribute_error_is_not_swallowed(tmp_path,completed_json_boundary_profile,monkeypatch):
    f=completed_json_boundary_profile
    card=tmp_path/'card.json';selector=tmp_path/'selector.json';ledger_path=tmp_path/'ledger.json'
    for path,value in [(card,f.card),(selector,f.selected),(ledger_path,f.ledger)]:
        io.write_once(path,io.encoded(value))
    def unrelated_bug(*args):
        raise AttributeError('INVENTED unrelated implementation error')
    monkeypatch.setattr(profile,'card_checks',unrelated_bug)
    with pytest.raises(AttributeError,match='unrelated implementation error'):
        profile.validate_files(card,ledger_path,selector,f.docs)


# Explicit source-snapshot successor controls, collected by the existing epoch2 batch.
STANDARD = 'bf1f582f977c2ac65e5537ebd9f1b1b19ae328d3'
SELECTOR = {'id': 'ohf-native-relational@1', 'epoch': 2,
            'definition_sha256': 'sha256:c964ce88b31374062cbebf6e801259f3f85533244633d3d5642cc7bab9124db7'}
OLD_SELECTOR = {**SELECTOR,
                'definition_sha256': 'sha256:29a28cbbabddcf398cec0d5cc226b511453d44dd92e276e768b243cc75d97a88'}
REFERENCES = Path(__file__).resolve().parents[2] / 'references'


def test_successor_selection_accepts_current_source_and_contract():
    try:
        root = profile.require_profile(SELECTOR)
    except ValueError as error:
        pytest.fail('Current successor binding must be admitted: ' + str(error))
    assert root == Path(os.environ['OHF_REPO']).resolve()
    assert profile.selection() == SELECTOR
    assert profile.DEFINITION.name == 'native-renderer-profile-4.json'
    assert profile.DEPENDENCIES.name == 'native-profile-dependencies-4.json'
    record = json.loads(profile.DEPENDENCIES.read_bytes())
    assert projection.STANDARD_COMMIT == record['standard_commit'] == STANDARD
    assert profile.contract_identity()['standard_commit'] == STANDARD
    assert len(record['files']) == 24
    assert profile.dependency_pins() == record['files']
    assert record['files']['schema/hypothesis-1.schema.json'] == (
        'sha256:ae1769a44c19bb575d2e4c7c903e756386b1831945b3bd788028c71f36c5c951')
    assert record['files']['spec/field-catalogue.json'] == (
        'sha256:8b88dad50daf24a7f17e35e5d24147a7d0b9a68ab7f4134564179cc790138ca1')
    assert projection.sha(profile.DEFINITION.read_bytes()) == profile.DEFINITION_RAW_SHA256
    assert projection.value_sha256(json.loads(profile.DEFINITION.read_bytes())) == SELECTOR['definition_sha256']


@pytest.mark.parametrize('digest', [OLD_SELECTOR['definition_sha256'],
    'sha256:3cd40193d4c1ec178f801f511f045a7e958a66e9a9d06e6dfe786b82bac07747'])
def test_old_selector_refuses_before_loading_runtime(monkeypatch, digest):
    def forbidden():
        pytest.fail('Old selector must refuse before runtime/source loading')
    monkeypatch.setattr(profile, 'runtime_identity', forbidden)
    with pytest.raises(ValueError, match='UNSUPPORTED_PROFILE'):
        profile.require_profile({**SELECTOR, 'definition_sha256': digest})


@pytest.mark.parametrize('name,value', [
    ('DEFINITION', REFERENCES / 'native-renderer-profile.json'),
    ('DEFINITION_RAW_SHA256', 'sha256:10e98d179c8006b34b2c921c922ffc36afd38ee4ab24a7379513e71b05e23590'),
    ('DEFINITION_SHA256', OLD_SELECTOR['definition_sha256']),
    ('DEPENDENCIES', REFERENCES / 'native-profile-dependencies.json'),
    ('DEPENDENCIES_SHA256', 'sha256:a4ca3178b58b737ddfc45b4cbcd1ea418ef07aabd79779db73820001024d172a'),
    ('DEFINITION', REFERENCES / 'native-renderer-profile-2.json'),
    ('DEFINITION_RAW_SHA256', 'sha256:6bc6cdf9fef659c1ece9734d1b2a6b0e90408357666d25f13769396b4ae79d9b'),
    ('DEFINITION_SHA256', 'sha256:3cd40193d4c1ec178f801f511f045a7e958a66e9a9d06e6dfe786b82bac07747'),
    ('DEPENDENCIES', REFERENCES / 'native-profile-dependencies-2.json'),
    ('DEPENDENCIES_SHA256', 'sha256:237579bd8d1c248a41f0ee39ead9dcdb10647bb7aaaab1102a8bb2e0990bad61'),
])
def test_one_rolled_back_binding_refuses_current_selection(monkeypatch, name, value):
    assert profile.require_profile(SELECTOR)
    monkeypatch.setattr(profile, name, value)
    with pytest.raises(ValueError, match='PROFILE|UNSUPPORTED_PROFILE'):
        profile.require_profile(SELECTOR)


def test_ci_reader_selects_actual_successor_dependency_record():
    root = Path(os.environ['OHF_REPO']).resolve()
    try:
        pins = driver.verify_standard(root)
    except ValueError as error:
        pytest.fail('CI must validate the current successor dependency record: ' + str(error))
    assert len(pins) == 26
    assert pins[str(root / 'schema/hypothesis-1.schema.json')] == (
        'sha256:ae1769a44c19bb575d2e4c7c903e756386b1831945b3bd788028c71f36c5c951')
    assert str(root / 'spec/renderer-profiles/native-relational-4.json') in pins
    assert str(root / 'spec/renderer-profiles/native-relational-1.json') not in pins


def test_historical_reference_records_remain_byte_exact():
    assert projection.sha((REFERENCES / 'native-renderer-profile.json').read_bytes()) == (
        'sha256:10e98d179c8006b34b2c921c922ffc36afd38ee4ab24a7379513e71b05e23590')
    assert projection.sha((REFERENCES / 'native-profile-dependencies.json').read_bytes()) == (
        'sha256:a4ca3178b58b737ddfc45b4cbcd1ea418ef07aabd79779db73820001024d172a')
    assert projection.sha((REFERENCES / 'native-renderer-profile-2.json').read_bytes()) == (
        'sha256:6bc6cdf9fef659c1ece9734d1b2a6b0e90408357666d25f13769396b4ae79d9b')
    assert projection.sha((REFERENCES / 'native-profile-dependencies-2.json').read_bytes()) == (
        'sha256:237579bd8d1c248a41f0ee39ead9dcdb10647bb7aaaab1102a8bb2e0990bad61')
    previous = json.loads((REFERENCES / 'native-renderer-profile.json').read_bytes())
    assert projection.sha((REFERENCES / 'native-renderer-profile-3.json').read_bytes()) == ('sha256:bba03f5f2f517e7b5a3c406d3660c4ba43d63b1267856daec940e3985d78170d')
    assert projection.sha((REFERENCES / 'native-profile-dependencies-3.json').read_bytes()) == ('sha256:d90dee02f5623ea203df2ca92efc2fba73d502afb73f73678a3b0215e625bc35')
    current = json.loads((REFERENCES / 'native-renderer-profile-3.json').read_bytes())
    assert previous['standard_release'] == '1.4.0'
    assert current['standard_release'] == '1.4.1'
    assert {k: v for k, v in previous.items() if k not in ('dependencies', 'standard_release')} == {
        k: v for k, v in current.items() if k not in ('dependencies', 'standard_release')}


def test_production_and_ci_bootstrap_preserve_distinct_main_populations():
    historical = json.loads((REFERENCES / 'native-profile-dependencies.json').read_bytes())
    expected_production = {
        path.replace('spec/renderer-profiles/native-relational-1.json',
                     'spec/renderer-profiles/native-relational-4.json')
        for path in historical['files']}
    production = profile.dependency_pins()
    assert len(expected_production) == 24
    assert set(production) == expected_production, 'production membership differs from main'
    expected_bootstrap = {
        'tools/__init__.py': 'sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
        'examples/cards/ENTAILMENT-PROMPT.md': 'sha256:46716d7b4fc070b952d7ace5ae597c64b9414e63b15e38a94e719a2eb4fae146'}
    assert driver.BOOTSTRAP_PINS == expected_bootstrap, 'CI bootstrap membership or values differ'
    assert not set(production) & set(driver.BOOTSTRAP_PINS)
    root = Path(os.environ['OHF_REPO']).resolve()
    actual = driver.verify_standard(root)
    assert len(actual) == 26
    assert actual == {str(root / path): value for path, value in
                      {**production, **expected_bootstrap}.items()}


@pytest.mark.parametrize('changed', sorted(json.loads(profile.DEPENDENCIES.read_bytes())['files']))
def test_require_profile_refuses_each_production_dependency(tmp_path, monkeypatch, changed):
    import re

    selected = profile.selection()
    original_root = profile.require_profile(selected)
    verified_reference = projection.reference()
    for relative in profile.dependency_pins():
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((original_root / relative).read_bytes())
    (tmp_path / changed).write_text('raise RuntimeError("UNPINNED_SOURCE_MUST_NOT_EXECUTE")')
    monkeypatch.setenv('OHF_REPO', str(tmp_path))
    # Isolate this pin loop from the earlier projection-module guard: a drift in
    # check_ledger.py must also be refused by require_profile's own independent check.
    monkeypatch.setattr(projection, 'reference', lambda: verified_reference)
    with pytest.raises(ValueError, match='PROFILE dependency pin differs: '+re.escape(changed)):
        profile.require_profile(selected)


SNAPSHOT_DEPENDENCIES = tuple(sorted(json.loads(profile.DEPENDENCIES.read_bytes())['files']))


def test_snapshot_rehash_parameters_cover_all_production_dependencies():
    parameters = next(mark.args[1] for mark in
                      test_validator_snapshot_rehash_refuses_drift_between_reads.pytestmark
                      if mark.name == 'parametrize' and mark.args[0] == 'changed')
    assert tuple(parameters) == SNAPSHOT_DEPENDENCIES
    assert len(parameters) == len(set(parameters)) == 24
    assert set(parameters) == set(profile.dependency_pins())


@pytest.mark.parametrize('changed', SNAPSHOT_DEPENDENCIES)
def test_validator_snapshot_rehash_refuses_drift_between_reads(monkeypatch, changed):
    target = Path(os.environ['OHF_REPO']).resolve() / changed
    original_read = io.read
    target_reads = []

    def changed_second_read(path):
        raw = original_read(path)
        if Path(path).resolve() == target:
            target_reads.append(raw)
            if len(target_reads) == 2:
                return raw + b'\n# Invented changed captured snapshot.\n'
        return raw

    monkeypatch.setattr(io, 'read', changed_second_read)
    with pytest.raises(ValueError, match='PROFILE dependency snapshot differs'):
        profile._validators(profile.selection())
    assert len(target_reads) == 2
    assert target_reads[0] == target_reads[1]


def test_successor_full_entrypoint_keeps_original_history_and_condition_checks(tmp_path):
    fixture = ProfileFixture(tmp_path)
    fixture.merge_profile()
    result = fixture.validate_profile()
    assert result['status'] == 'PASS', result
    assert result['schema_valid'] and result['native_binding_valid']
    assert result['profile'] == SELECTOR
    assert result['profile_contract']['standard_commit'] == STANDARD
    assert result['scientific_truth_evaluated'] is False
    fixture.line['quote'] = 'A different invented quotation.'
    refused = fixture.validate_profile()
    assert refused['status'] == 'REFUSE'
    assert refused['native_binding_valid'] is False


def _ordinary_direction_case(workdir):
    """An invented ordinary card, without the selected native profile."""
    from conftest import build_card, PMCID
    path = build_card(workdir)
    card = json.loads(path.read_bytes())
    card['standard_version'] = '1.4'
    core = card['added']['layers']['core']
    core.update(statement={'value': 'X causes Y when recombination stops.', 'src': 'p1'},
                kind={'value': 'mechanism', 'src': 'p1'},
                context=[{'value': 'Only after recombination stops.', 'src': 'p1'}],
                assumptions=[{'id': 'premise', 'text': {'value': 'Recombination stops.', 'src': 'p1'}}],
                atoms=[{'id': 'a_x', 'statement': {'value': 'X causes Y.', 'src': 'p1'},
                        'claim_type': {'value': 'causal_effect', 'src': 'p1'},
                        'role': {'value': 'core', 'src': 'p1'},
                        'modality': {'value': 'proposed', 'src': 'p1'}}])
    line = {'id': 'e_x', 'target_ref': 'a_x', 'src': 'p2',
            'quote': 'In mice, X may cause Y.',
            'direction': {'value': 'supports', 'src': 'p2'}}
    card['added']['layers']['evidence'] = {'lines': [line]}
    doc = ohfkit.Document(PMCID, workdir)
    card['content_hash'] = ohfkit.content_hash(card)
    return card, {doc.url: doc}, line


def test_ordinary_direction_uses_normative_complete_projection(xml_workdir):
    import check_ledger as ordinary
    card, _docs, line = _ordinary_direction_case(xml_workdir)
    pointer = '/added/layers/evidence/lines/0/direction'
    actual = ordinary.checked_value(card, pointer, line['direction'])
    assert actual == projection.reference().checked_value(card, pointer, line['direction'])
    assert actual['target_statement']['format'] == 'ohf-target-projection/1'
    assert actual['evidence_conditions']['quote'] == line['quote']


def test_ordinary_direction_ignores_ambient_projection_module(xml_workdir, monkeypatch):
    import sys
    import types
    import check_ledger as ordinary
    card, _docs, line = _ordinary_direction_case(xml_workdir)
    def unpinned():
        pytest.fail('ambient projection module must not participate')
    monkeypatch.setitem(sys.modules, 'projection_binding', types.SimpleNamespace(reference=unpinned))
    actual = ordinary.checked_value(card, '/added/layers/evidence/lines/0/direction', line['direction'])
    assert actual['target_statement']['format'] == 'ohf-target-projection/1'


def test_ordinary_direction_refuses_changed_projection_adapter(xml_workdir, tmp_path, monkeypatch):
    import check_ledger as ordinary
    card, _docs, line = _ordinary_direction_case(xml_workdir)
    root = tmp_path / 'changed-adapter'
    root.mkdir()
    source = Path(ordinary.__file__).read_bytes()
    (root / 'check_ledger.py').write_bytes(source)
    monkeypatch.setattr(ordinary, '__file__', str(root / 'check_ledger.py'))
    (root / 'projection_binding.py').write_bytes(
        Path(projection.__file__).read_bytes() + b'\n# Invented dependency drift.\n')
    with pytest.raises(ValueError, match='ordinary projection source pin differs'):
        ordinary.checked_value(card, '/added/layers/evidence/lines/0/direction', line['direction'])


@pytest.mark.parametrize('changed', ['scope', 'context', 'assumption', 'modality', 'quote'])
def test_ordinary_direction_condition_changes_invalidate_frozen_input(xml_workdir, changed):
    import entailment as ordinary
    card, docs, line = _ordinary_direction_case(xml_workdir)
    frozen = ordinary.checker_items(ordinary.build(card, docs))
    core = card['added']['layers']['core']
    if changed == 'scope': core['scope']['value'] = 'Only in another invented system.'
    elif changed == 'context': core['context'][0]['value'] = 'Only before recombination stops.'
    elif changed == 'assumption': core['assumptions'][0]['text']['value'] = 'Recombination continues.'
    elif changed == 'modality': core['atoms'][0]['modality']['value'] = 'likely'
    else: line['quote'] = 'A different invented result.'
    assert any('/direction ' in message for message in ordinary.stale_items(card, docs, frozen))


def _ordinary_merge(card, docs, verdict='entails', current=None):
    import entailment as ordinary
    import check_ledger as ordinary_ledger
    current = current if current is not None else ordinary_ledger.new_ledger(card)
    items = ordinary.checker_items(ordinary.build(card, docs))
    results = [{'id': item['id'], 'verdict': verdict,
                **({'note': 'Invented behavioural control only.'} if verdict != 'entails' else {})}
               for item in items]
    ordinary.merge(card, items, results, docs, current)
    card['content_hash'] = ohfkit.content_hash(card)
    current['content_hash'] = card['content_hash']
    return current


def test_ordinary_direction_merge_is_accepted_by_standard_ledger_reader(xml_workdir):
    import check_ledger as ordinary
    import entailment as ordinary_entailment
    card, docs, _line = _ordinary_direction_case(xml_workdir)
    current = _ordinary_merge(card, docs)
    passages = {ordinary.key_of(x): x['source_passage'] for x in ordinary_entailment.build(card, docs)}
    assert current.get('target_projection') == 'ohf-target-projection/1'
    assert ordinary.check(card, current, passages) == []
    assert projection.reference().check(card, current, passages) == []


def test_ordinary_1_4_refuses_legacy_v1_ledger_without_promoting_old_checks(xml_workdir):
    import check_ledger as ordinary
    import entailment as ordinary_entailment
    card, docs, _line = _ordinary_direction_case(xml_workdir)
    current = _ordinary_merge(card, docs)
    legacy = {'format': 'ohf-entailment-ledger/1', 'canonicalisation': 'as /1',
              'card_id': current['card_id'], 'content_hash': current['content_hash'],
              'entries': {key: {name: entry[name] for name in
                               ('value_sha256', 'passage_sha256', 'checked_at', 'verdict')}
                          for key, [entry] in current['entries'].items()}}
    before = deepcopy(legacy)
    errors = ordinary.check(card, legacy)
    assert 'ledger direction projection version is missing or stale' in errors
    assert any('direction projection binding' in error for error in errors)
    # The CLI reader upgrades /1 storage into list-valued in-memory history before carry.
    upgraded = ordinary.upgrade(legacy)
    upgraded_before = deepcopy(upgraded)
    _kept, rest = ordinary_entailment.carry(card, card, docs, upgraded)
    assert any(item['pointer'].endswith('/direction') for item in rest)
    assert legacy == before  # Old checks remain history; no projection metadata is fabricated.
    assert upgraded == upgraded_before


def test_ordinary_direction_entry_retains_the_target_binding(xml_workdir):
    import check_ledger as ordinary
    import entailment as ordinary_entailment
    card, docs, _line = _ordinary_direction_case(xml_workdir)
    item = next(x for x in ordinary_entailment.build(card, docs) if x['pointer'].endswith('/direction'))
    record = {'checked_at': '2026-02-02T01:02:03Z', 'verdict': 'entails'}
    entry = ordinary.entry(item, record)
    assert entry.get('target_projection') == 'ohf-target-projection/1'
    assert entry.get('target_sha256') == ordinary.value_sha256(item['value']['target_statement'])


@pytest.mark.parametrize('header', ['projection', 'card-version', 'proposition-version'])
def test_ordinary_direction_ledger_envelope_refuses_stale_identity(xml_workdir, header):
    import check_ledger as ordinary
    card, docs, _line = _ordinary_direction_case(xml_workdir)
    current = _ordinary_merge(card, docs)
    if header == 'projection': current.pop('target_projection')
    elif header == 'card-version': current['card_version'] = card['version'] + 1
    else: current['proposition_version'] = card['identity']['version'] + 1
    assert any('ledger ' in error for error in ordinary.check(card, current))


@pytest.mark.parametrize('binding', ['missing', 'stale'])
def test_ordinary_direction_unbound_history_is_not_carried_or_retagged(xml_workdir, binding):
    import check_ledger as ordinary
    import entailment as ordinary_entailment
    card, docs, _line = _ordinary_direction_case(xml_workdir)
    current = _ordinary_merge(card, docs)
    key = '/added/layers/evidence/lines/0/direction|src'
    if binding == 'missing': current['entries'][key][0].pop('target_projection')
    else: current['entries'][key][0]['target_sha256'] = 'sha256:' + '0' * 64
    before = deepcopy(current)
    assert any('direction projection binding' in e for e in ordinary.check(card, current))
    assert any('projection' in e for e in projection.reference().check(card, current))
    _kept, rest = ordinary_entailment.carry(card, card, docs, current)
    assert any(x['pointer'].endswith('/direction') for x in rest)
    assert current == before


def test_ordinary_direction_worst_history_and_archive_refusal(xml_workdir):
    import entailment as ordinary
    import check_ledger as ordinary_ledger
    card, docs, _line = _ordinary_direction_case(xml_workdir)
    current = _ordinary_merge(card, docs, 'no')
    _ordinary_merge(card, docs, 'entails', current)
    assert all(r['verdict'] == 'no' for r in card['added']['integrity']['entailment'])
    before = deepcopy(current)
    empty = ordinary_ledger.new_ledger(card)
    with pytest.raises(ValueError, match='original ledger target bindings'):
        ordinary.restore(card, [card], lambda old: docs, empty)
    assert empty['entries'] == {}
    assert ordinary.restore(card, [deepcopy(card)], lambda old: docs, current)[0] == 0
    assert current == before


def test_ordinary_direction_never_grandfathers_a_statement_only_check(xml_workdir):
    import check_ledger as ordinary
    import entailment as ordinary_entailment
    card, docs, line = _ordinary_direction_case(xml_workdir)
    current = _ordinary_merge(card, docs)
    key = '/added/layers/evidence/lines/0/direction|src'
    old_value = {'direction': 'supports', 'target_statement': ordinary.target_statement(card, line)}
    old_entry = current['entries'][key][0]
    old_entry['value_sha256'] = ordinary.value_sha256(old_value)
    old_entry.pop('target_projection')
    old_entry.pop('target_sha256')
    history = deepcopy(current['entries'])
    assert ordinary.check(card, current), 'A statement-only verdict cannot back a full target'
    _kept, rest = ordinary_entailment.carry(card, card, docs, current)
    assert any(x['pointer'].endswith('/direction') for x in rest)
    assert current['entries'] == history


@pytest.mark.parametrize('version', ['1.0', '1.1', '1.2', '1.3'])
def test_ordinary_older_direction_rendering_stays_unchanged(xml_workdir, version):
    import check_ledger as ordinary
    card, _docs, line = _ordinary_direction_case(xml_workdir)
    card['standard_version'] = version
    assert ordinary.checked_value(card, '/added/layers/evidence/lines/0/direction', line['direction']) == {
        'direction': 'supports', 'target_statement': 'X causes Y.', 'line_quote': line['quote']}


@pytest.mark.parametrize('route', ['checked_value', 'build'])
def test_ordinary_direction_refuses_unresolved_target_before_checker_input(xml_workdir, route):
    import check_ledger as ordinary
    import entailment as ordinary_entailment
    card, docs, line = _ordinary_direction_case(xml_workdir)
    pointer = '/added/layers/evidence/lines/0/direction'
    assert ordinary.checked_value(card, pointer, line['direction'])['target_statement']['kind'] == 'atom'
    line['target_ref'] = 'invented-external-proposition@1'
    with pytest.raises(ValueError, match='unresolved external scientific target'):
        if route == 'checked_value':
            ordinary.checked_value(card, pointer, line['direction'])
        else:
            ordinary_entailment.build(card, docs)


def test_ordinary_active_directly_refuses_an_unresolved_direction_history(xml_workdir):
    import check_ledger as ordinary
    import entailment as ordinary_entailment
    card, docs, _line = _ordinary_direction_case(xml_workdir)
    item = next(x for x in ordinary_entailment.build(card, docs) if x['pointer'].endswith('/direction'))
    record = {'checked_at': '2026-02-02T01:02:03Z', 'verdict': 'entails'}
    original = ordinary.entry(item, record)
    assert ordinary.active([original], original['value_sha256'], original['passage_sha256'], item=item) == [original]
    item['value']['target_statement'] = {'format': 'ohf-target-projection/1',
        'kind': 'external_unresolved', 'reference': 'invented-external-proposition@1'}
    historical = ordinary.entry(item, record)
    with pytest.raises(ValueError, match='unresolved external scientific target'):
        ordinary.active([historical], historical['value_sha256'], historical['passage_sha256'], item=item)


@pytest.mark.parametrize('format_value', [None, 'invented-other-projection/1'])
@pytest.mark.parametrize('route', ['recogniser', 'legacy_active'])
def test_ordinary_projection_recogniser_does_not_reclassify_another_target_format(xml_workdir, format_value, route):
    import check_ledger as ordinary
    import entailment as ordinary_entailment
    card, docs, _line = _ordinary_direction_case(xml_workdir)
    item = next(x for x in ordinary_entailment.build(card, docs) if x['pointer'].endswith('/direction'))
    assert ordinary.direction_projection(item) is item['value']['target_statement']
    if format_value is None:
        item['value']['target_statement'].pop('format')
    else:
        item['value']['target_statement']['format'] = format_value
    if route == 'recogniser':
        assert ordinary.direction_projection(item) is None
        return
    record = {'checked_at': '2026-02-02T01:02:03Z', 'verdict': 'entails'}
    legacy = ordinary.entry(item, record)
    assert 'target_projection' not in legacy and 'target_sha256' not in legacy
    # This direct API is a format recogniser; it does not grant whole-card validity.
    assert ordinary.active([legacy], legacy['value_sha256'], legacy['passage_sha256'], item=item) == [legacy]


@pytest.mark.parametrize('route', ['active', 'shown_record', 'carry'])
def test_ordinary_direction_does_not_reuse_a_check_of_another_passage(xml_workdir, route):
    import check_ledger as ordinary
    import entailment as ordinary_entailment
    card, docs, _line = _ordinary_direction_case(xml_workdir)
    current = _ordinary_merge(card, docs)
    item = next(x for x in ordinary_entailment.build(card, docs) if x['pointer'].endswith('/direction'))
    key = ordinary.key_of(item)
    correct = deepcopy(current['entries'][key][0])
    assert ordinary.active([correct], correct['value_sha256'], correct['passage_sha256'], item=item) == [correct]
    foreign = deepcopy(correct)
    foreign['passage_sha256'] = ordinary.passage_sha256('A different invented paragraph, never the current passage.')
    current['entries'][key] = [foreign]
    before = deepcopy(current)
    old_card = deepcopy(card)
    if route == 'active':
        assert ordinary.active([foreign], correct['value_sha256'], correct['passage_sha256'], item=item) == []
    elif route == 'shown_record':
        assert ordinary_entailment.shown_record(item, current, card['added']['integrity']['entailment']) is None
    else:
        _kept, rest = ordinary_entailment.carry(old_card, card, docs, current)
        assert any(x['pointer'] == item['pointer'] and x['basis'] == item['basis'] for x in rest)
        assert not any(r['pointer'] == item['pointer'] for r in card['added']['integrity']['entailment'])
    assert current == before


def test_ordinary_restore_preserves_the_original_extended_ledger_entry(xml_workdir):
    import check_ledger as ordinary
    import entailment as ordinary_entailment
    card, docs, _line = _ordinary_direction_case(xml_workdir)
    current = _ordinary_merge(card, docs)
    key = '/added/layers/evidence/lines/0/direction|src'
    # Opaque invented retention metadata, not a claimed native IO proof or authentication.
    current['entries'][key][0]['checker_binding'] = {
        'contract': 'invented-retained-binding/1',
        'input_sha256': ordinary.value_sha256({'fixture': 'original ordinary input'})}
    before = deepcopy(current)
    added, skipped, _times = ordinary_entailment.restore(card, [deepcopy(card)], lambda old: docs, current)
    assert (added, skipped) == (0, 0)
    assert current == before
    assert current['entries'][key][0]['checker_binding'] == before['entries'][key][0]['checker_binding']


@pytest.mark.parametrize('order', ['foreign-first', 'valid-then-foreign'])
def test_ordinary_foreign_archive_refusal_leaves_all_history_unchanged(xml_workdir, order):
    import check_ledger as ordinary
    import entailment as ordinary_entailment
    card, docs, _line = _ordinary_direction_case(xml_workdir)
    original = _ordinary_merge(card, docs)
    valid = deepcopy(card)
    foreign = deepcopy(card)
    foreign['id'] = 'invented-foreign-card'
    foreign_ledger = _ordinary_merge(foreign, docs)
    key = '/added/layers/evidence/lines/0/direction|src'
    # Both projected entries are present, so a missing binding cannot hide the ID guard.
    current = ordinary.new_ledger(card, {key: [deepcopy(original['entries'][key][0]),
                                              deepcopy(foreign_ledger['entries'][key][0])]})
    assert any(r['pointer'] != '/added/layers/evidence/lines/0/direction'
               for r in valid['added']['integrity']['entailment'])
    # A valid-only archive really can fill the missing non-direction entries.
    positive = deepcopy(current)
    assert ordinary_entailment.restore(deepcopy(card), [valid], lambda old: docs, positive)[0] > 0
    before, card_before = deepcopy(current), deepcopy(card)
    archives = [foreign] if order == 'foreign-first' else [valid, foreign]
    disk_before = {str(p.relative_to(xml_workdir)): p.read_bytes()
                   for p in xml_workdir.rglob('*') if p.is_file()}
    with pytest.raises(ValueError, match='is not card'):
        ordinary_entailment.restore(card, archives, lambda old: docs, current)
    assert {str(p.relative_to(xml_workdir)): p.read_bytes()
            for p in xml_workdir.rglob('*') if p.is_file()} == disk_before
    assert current == before
    assert card == card_before


@pytest.mark.parametrize('changed', ['value_sha256', 'passage_sha256', 'checked_at',
                                     'verdict', 'target_projection', 'target_sha256'])
def test_ordinary_restore_requires_every_original_direction_binding(xml_workdir, changed):
    import entailment as ordinary
    card, docs, _line = _ordinary_direction_case(xml_workdir)
    current = _ordinary_merge(card, docs)
    key = '/added/layers/evidence/lines/0/direction|src'
    # The exact original entry is admissible without reconstructing its binding.
    positive = deepcopy(current)
    assert ordinary.restore(deepcopy(card), [deepcopy(card)], lambda old: docs, positive)[0] == 0
    assert positive == current
    original = deepcopy(current['entries'][key][0])
    assert set(original) == {'value_sha256', 'passage_sha256', 'checked_at',
                             'verdict', 'target_projection', 'target_sha256'}
    replacements = {'value_sha256': 'sha256:' + '0' * 64,
                    'passage_sha256': 'sha256:' + '1' * 64,
                    'checked_at': '2000-01-01T00:00:00Z', 'verdict': 'partial',
                    'target_projection': 'invented-other-projection/1',
                    'target_sha256': 'sha256:' + '2' * 64}
    current['entries'][key][0][changed] = replacements[changed]
    assert sum(current['entries'][key][0][name] == value
               for name, value in original.items()) == len(original) - 1
    before, card_before = deepcopy(current), deepcopy(card)
    with pytest.raises(ValueError, match='original ledger target bindings'):
        ordinary.restore(card, [deepcopy(card)], lambda old: docs, current)
    assert current == before
    assert card == card_before


@pytest.mark.parametrize('field', ['study_type', 'study_system', 'indirectness',
                                   'sample', 'sample_size', 'multi_site_program',
                                   'result_estimate', 'endpoint_kind'])
def test_ordinary_projection_recogniser_requires_the_direction_field(xml_workdir, field):
    import check_ledger as ordinary
    import entailment as ordinary_entailment
    card, docs, _line = _ordinary_direction_case(xml_workdir)
    item = next(x for x in ordinary_entailment.build(card, docs)
                if x['pointer'].endswith('/direction'))
    assert ordinary.direction_projection(item) is item['value']['target_statement']
    item['pointer'] = '/added/layers/evidence/lines/0/' + field
    assert ordinary.LINE_FIELD.fullmatch(item['pointer'])
    # Direct classifier input, not a claim that this object is a schema-valid card field.
    assert item['value']['target_statement']['format'] == 'ohf-target-projection/1'
    assert ordinary.direction_projection(item) is None
    record = {'checked_at': '2026-02-02T01:02:03Z', 'verdict': 'entails'}
    legacy = ordinary.entry(item, record)
    assert 'target_projection' not in legacy and 'target_sha256' not in legacy
    assert ordinary.active([legacy], legacy['value_sha256'], legacy['passage_sha256'], item=item) == [legacy]


N2_TOTALS = ('model_calls', 'http_requests', 'input_tokens', 'output_tokens')


@pytest.mark.parametrize('field', N2_TOTALS)
@pytest.mark.parametrize('reason', ['producer_runtime_does_not_expose', 'partial_count',
                                    'counter_failed', 'count_origin_unestablished'])
def test_n2_selected_release_accepts_explicit_unknown_totals(tmp_path, field, reason):
    f = ProfileFixture(tmp_path)
    f.card['added']['budget'] = dict.fromkeys(N2_TOTALS, 7)
    f.card['added']['budget'][field] = None
    f.card['added']['budget']['unknown_reasons'] = {field: reason}
    f.rehash()
    assert f.card['added']['by']['standard_release']['version'] == '1.4.2'
    assert profile.card_checks(f.card, f.selected)['errors'] == []
    # Declaration validation does not certify a complete counter or import provenance.
    assert f.card['added']['budget'][field] is None


@pytest.mark.parametrize('field', N2_TOTALS)
@pytest.mark.parametrize('invalid', ['missing-reason', 'unknown-reason', 'reason-for-known-total'])
def test_n2_unknown_reason_contract_refuses_incomplete_declarations(tmp_path, field, invalid):
    f = ProfileFixture(tmp_path)
    f.card['added']['budget'] = dict.fromkeys(N2_TOTALS, 7)
    if invalid != 'reason-for-known-total':
        f.card['added']['budget'][field] = None
    if invalid != 'missing-reason':
        f.card['added']['budget']['unknown_reasons'] = {
            field: 'invented-unsupported-reason' if invalid == 'unknown-reason' else 'partial_count'}
    f.rehash()
    report = profile.card_checks(f.card, f.selected)
    assert report['schema_valid'] is False
    assert any(error.startswith('SCHEMA: ') for error in report['errors'])


@pytest.mark.parametrize('field', N2_TOTALS)
@pytest.mark.parametrize('value', [-1, True, '0', 0.5])
def test_n2_known_totals_refuse_invalid_counter_types(tmp_path, field, value):
    f = ProfileFixture(tmp_path)
    f.card['added']['budget'] = dict.fromkeys(N2_TOTALS, 7)
    f.card['added']['budget'][field] = value
    f.rehash()
    assert profile.schema_errors(f.card, f.selected)


@pytest.mark.parametrize('field', N2_TOTALS)
@pytest.mark.parametrize('model', ['none', 'INVENTED_FAKE_ONLY_NOT_SCIENCE'])
def test_n2_token_inapplicability_is_not_unknown_calls(tmp_path, field, model):
    f = ProfileFixture(tmp_path)
    f.card['added']['by']['model'] = model
    f.card['added']['budget'] = dict.fromkeys(N2_TOTALS, 0)
    f.card['added']['budget'][field] = None
    f.card['added']['budget']['unknown_reasons'] = {field: 'not_applicable_no_language_model'}
    f.rehash()
    assert (profile.schema_errors(f.card, f.selected) == []) is (
        field in ('input_tokens', 'output_tokens') and model == 'none')


@pytest.mark.parametrize('release', [None, '1.4.0'])
def test_n2_budget_rule_needs_explicit_release_not_selected_tool_version(tmp_path, release):
    f = ProfileFixture(tmp_path)
    if release is None:
        f.card['added']['by'].pop('standard_release')
    else:
        f.card['added']['by']['standard_release'] = {'version': release}
    f.card['added']['budget'] = dict.fromkeys(N2_TOTALS, 0)
    f.card['added']['budget']['input_tokens'] = None
    f.card['added']['budget']['output_tokens'] = None
    f.rehash()
    assert profile.schema_errors(f.card, f.selected) == []
    f.card['added']['budget']['model_calls'] = None
    f.card['added']['budget']['unknown_reasons'] = {'model_calls': 'partial_count'}
    f.rehash()
    assert profile.schema_errors(f.card, f.selected)


@pytest.mark.parametrize('total', [0, None])
def test_n2_complete_selected_entrypoint_preserves_unknown_or_known_zero(tmp_path, total):
    f = ProfileFixture(tmp_path)
    f.card['added']['budget'] = dict.fromkeys(N2_TOTALS, total)
    if total is None:
        f.card['added']['budget']['unknown_reasons'] = dict.fromkeys(N2_TOTALS, 'partial_count')
    before = deepcopy(f.card['added']['budget'])
    f.rehash()
    f.merge_profile()
    report = f.validate_profile()
    assert report['status'] == 'PASS', report
    assert report['scientific_truth_evaluated'] is False
    assert f.card['added']['budget'] == before
