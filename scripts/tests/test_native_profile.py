"""Exact local schema/profile contract on one invented fixture, fake IO only."""
import json
from copy import deepcopy
import xml.etree.ElementTree as ET
import pytest

import native_profile as profile
import ohfkit
if ohfkit.standard_line() != '1.4':
    pytest.skip('Native profile conformance requires its explicit OHF 1.4 checkout', allow_module_level=True)

import checker_io as io
import native_entailment as entailment
import projection_binding as projection
import ohfkit

from profile_fixture import ProfileFixture


@pytest.mark.parametrize('epoch',[True,2.0])
def test_selector_json_types_cannot_alias_integer_epoch(tmp_path,epoch):
    f=ProfileFixture(tmp_path);f.merge_profile()
    selected=deepcopy(f.selected);selected['epoch']=epoch
    with pytest.raises(ValueError,match='UNSUPPORTED_PROFILE'):
        profile.require_profile(selected)
    assert profile.validate_bundle(f.card,f.ledger,f.docs,selected)['status']=='REFUSE'
    assert f.validate_profile()['status']=='PASS'


@pytest.mark.parametrize('epoch',[True,2.0])
def test_ledger_marker_json_types_cannot_alias_integer_epoch(tmp_path,epoch):
    f=ProfileFixture(tmp_path);f.merge_profile()
    f.ledger['renderer_profile']['epoch']=epoch
    assert f.validate_profile()['status']=='REFUSE'


@pytest.mark.parametrize('epoch',[True,2.0])
def test_original_frozen_configuration_requires_integer_epoch(tmp_path,epoch):
    f=ProfileFixture(tmp_path);items,_=profile.build(f.card,f.docs,f.selected)
    selected=deepcopy(f.selected);selected['epoch']=epoch
    config={'kind':'injected_fake','renderer_profile':selected,
            'item_roster_sha256':projection.value_sha256(profile.roster(items))}
    inp,out=tmp_path/'typed.json',tmp_path/'typed-result.json'
    io.freeze(items,inp,entailment.PROMPT.read_bytes(),entailment.current_checker(),config,entailment.input_envelope(f.card))
    def fake(request,configuration):
        return {'request_sha256':projection.sha(request),'configuration_sha256':projection.value_sha256(configuration),
                'result_bytes':io.encoded([{'id':x['id'],'verdict':'entails'} for x in items])}
    io.run(inp,out,fake)
    before=deepcopy(f.card)
    with pytest.raises(ValueError,match='PROFILE_PROOF'):
        profile.merge(f.card,f.docs,f.selected,inp,out,f.ledger)
    assert f.card==before and f.ledger['entries']=={}


@pytest.mark.parametrize('poison',['validate','strict_dates','strict_json','package','ambient'])
def test_pinned_source_namespace_never_executes_ambient_cache_or_package(tmp_path,monkeypatch,poison):
    import importlib.util
    import importlib._bootstrap_external as bootstrap
    import os
    from pathlib import Path
    import shutil
    import sys
    import types
    f=ProfileFixture(tmp_path);f.merge_profile()
    # Copy only the pinned public validation closure. A full checkout also
    # contains article examples and Git history, which are not test inputs.
    source_root=Path(os.environ['OHF_REPO']);clone=tmp_path/'standard-copy'
    required={**profile.dependency_pins(),
              'tools/__init__.py':'sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
              'examples/cards/ENTAILMENT-PROMPT.md':entailment.CHECKER['prompt_sha256']}
    for name,digest in required.items():
        source=source_root/name;raw=source.read_bytes();assert projection.sha(raw)==digest
        destination=clone/name;destination.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(source,destination)
    marker=tmp_path/'poison-executed'
    code_text=f'open({str(marker)!r},"w").write("executed")\n'
    if poison=='ambient':
        source=clone/'tools/validate.py'
        module=types.ModuleType('tools.validate');module.__file__=str(source)
        module.validation_errors=lambda schema,card:[];module.pointer=lambda error:''
        monkeypatch.setitem(sys.modules,'tools.validate',module)
    elif poison=='package':
        init=clone/'tools/__init__.py';init.chmod(0o600);init.write_text(code_text)
    else:
        source=clone/('tools/'+poison+'.py');st=source.stat()
        if poison=='validate':code_text+='def validation_errors(schema,card): return []\ndef pointer(error): return ""\n'
        elif poison=='strict_dates':code_text+='def self_check(): pass\ndef format_checker(): return None\n'
        else:code_text+='def load(path): return {}\n'
        cache=Path(importlib.util.cache_from_source(str(source)));cache.parent.mkdir(parents=True,exist_ok=True)
        cache.write_bytes(bootstrap._code_to_timestamp_pyc(compile(code_text,str(source),'exec'),int(st.st_mtime),st.st_size))
    # Remove ordinary loaded tools/helpers so a poisoned timestamp cache is eligible.
    for name in ('tools','tools.validate','strict_dates','strict_json'):
        if not (poison=='ambient' and name=='tools.validate'):
            monkeypatch.delitem(sys.modules,name,raising=False)
    monkeypatch.setenv('OHF_REPO',str(clone))
    prior_path=sys.path[:]
    bad=deepcopy(f.card);bad['invented_forbidden_extension']='outside schema'
    bad['content_hash']=ohfkit.content_hash(bad)
    ledger=deepcopy(f.ledger);ledger['content_hash']=bad['content_hash']
    result=profile.validate_bundle(bad,ledger,f.docs,f.selected)
    assert result['status']=='REFUSE' and result['schema_valid'] is False,result
    assert not marker.exists() and sys.path==prior_path
    assert profile.validate_bundle(f.card,f.ledger,f.docs,f.selected)['status']=='PASS'


def test_fixture_is_full_normative_schema_valid_before_and_after_fake_merge(tmp_path):
    f=ProfileFixture(tmp_path)
    assert profile.schema_errors(f.card,f.selected)==[]
    assert 'integrity' not in f.card['added']
    f.merge_profile()
    assert profile.schema_errors(f.card,f.selected)==[]
    result=f.validate_profile()
    assert result['status']=='PASS',result
    assert result['scientific_truth_evaluated'] is False


def test_positive_single_entrypoint_export_and_inprocess_ci(tmp_path):
    f=ProfileFixture(tmp_path);inp,out=f.merge_profile()
    assert all('derives_from_atom_refs' not in x['pointer'] for x in io.strict_json(inp.read_bytes()))
    assert any('derives_from_atom_refs' in x['pointer'] for x in entailment.build(f.card,f.docs))
    exported=tmp_path/'exported.json'
    assert profile.export(f.card,f.ledger,f.docs,f.selected,exported)['status']=='PASS'
    card=tmp_path/'card.json';selected=tmp_path/'profile.json'
    card.write_bytes(io.encoded(f.card));selected.write_bytes(io.encoded(f.selected))
    source=ET.tostring(f.doc.root,encoding='utf-8')
    assert projection.sha(source)==f.doc.sha
    (tmp_path/'source.xml').write_bytes(source)
    assert profile.validate_files(card,exported,selected,f.docs)['status']=='PASS'


def rebind_root(f):
    """Even an explicit new root cannot retrofit old per-entry checker evidence."""
    f.rehash();f.ledger['content_hash']=f.card['content_hash']
    items,conditions=profile.build(f.card,f.docs,f.selected)
    f.ledger['item_roster']=profile.roster(items);f.ledger['card_conditions']=conditions
    f.ledger['source_bindings']=profile.source_bindings(f.card,f.docs,items)


def test_bare_normative_reader_unchanged_and_unsupported_for_valid_native_fixture(tmp_path):
    f=ProfileFixture(tmp_path);f.merge_profile()
    assert profile.schema_errors(f.card,f.selected)==[]
    items,_=profile.build(f.card,f.docs,f.selected)
    bare=projection.reference()
    errors=bare.check(f.card,f.ledger)
    assert errors and f.validate_profile()['status']=='PASS'
    assert any('direction' in e for e in errors)
    direction=next(x for x in items if x['pointer'].endswith('/lines/0/direction'))
    assert direction['value']['target_statement']==bare.target_statement(f.card,f.line)
    assert direction['value']!=bare.checked_value(f.card,direction['pointer'],f.line['direction'])
    (tmp_path/'bare-versus-profile.json').write_bytes(io.encoded({'bare_errors':errors,
        'native_item_count':len(items),'normative_item_count':len(bare.value_items(f.card)),
        'target_digest_equal':True,'full_value_equal':False,'schema_valid':True}))


@pytest.mark.parametrize('selected',[None,{'id':'unknown'},
    {'id':profile.PROFILE_ID,'epoch':0,'definition_sha256':profile.DEFINITION_SHA256}])
def test_missing_unknown_and_stale_profile_never_default_to_pass(tmp_path,selected):
    f=ProfileFixture(tmp_path);f.merge_profile()
    result=profile.validate_bundle(f.card,f.ledger,f.docs,selected)
    assert result['status']=='REFUSE' and any('UNSUPPORTED_PROFILE' in e for e in result['errors'])


@pytest.mark.parametrize('change',['null-budget','extra-card-field','invalid-date'])
def test_full_schema_constraints_are_never_waived(tmp_path,change):
    f=ProfileFixture(tmp_path);f.merge_profile()
    if change=='null-budget':f.card['added']['budget']['model_calls']=None
    elif change=='extra-card-field':f.card['invented_extension']='not permitted'
    else:f.card['added']['at']='2026-02-30T00:00:00Z'
    f.rehash();f.ledger['content_hash']=f.card['content_hash']
    result=f.validate_profile()
    assert result['status']=='REFUSE' and result['schema_valid'] is False
    with pytest.raises(ValueError):profile.export(f.card,f.ledger,f.docs,f.selected,tmp_path/'refused.json')
    assert not (tmp_path/'refused.json').exists()


@pytest.mark.parametrize('change',['scope','horizon','passage','term'])
def test_current_conditions_passage_and_term_cannot_reuse_old_proof(tmp_path,change):
    f=ProfileFixture(tmp_path);f.merge_profile();history=deepcopy(f.ledger['entries'])
    if change=='scope':f.card['added']['layers']['core']['scope']['value']='Red boards only.'
    elif change=='horizon':f.card['added']['layers']['predictions'][0]['horizon']['value']='two days'
    elif change=='term':f.line['endpoint_kind']['term']='biomarker';f.line['endpoint_kind'].pop('note')
    else:
        changed=f.doc.profile_xml_bytes.replace(b'Eight panels were used.',b'Eight panels were used. Additional invented context.')
        f.doc=profile.document_from_bytes(changed,f.doc.pmcid,f.doc.retrieved)
        f.docs={f.doc.url:f.doc}
        f.card['author']['source']['source_text_sha256']=f.doc.sha
    rebind_root(f);result=f.validate_profile()
    assert result['schema_valid'] is True and result['status']=='REFUSE',result
    assert f.ledger['entries']==history


@pytest.mark.parametrize('change',['missing-proof','wrong-roster','extra-record','extra-ledger-item',
                                 'legacy','newhash-oldverdict','checker-label','foreign-card'])
def test_proof_roster_and_legacy_refusals_through_same_full_entry(tmp_path,change):
    f=ProfileFixture(tmp_path);f.merge_profile()
    pointer='/added/layers/evidence/lines/0/direction';entry=f.ledger['entries'][pointer+'|src'][0]
    if change=='missing-proof':f.ledger['checker_io_proofs'].clear()
    elif change=='wrong-roster':f.ledger['item_roster'].pop()
    elif change=='extra-record':f.card['added']['integrity']['entailment'].append(deepcopy(f.card['added']['integrity']['entailment'][0]))
    elif change=='extra-ledger-item':f.ledger['entries']['/added/layers/core/explanandum|src']=[deepcopy(entry)]
    elif change=='legacy':entry.pop('checker_binding')
    elif change=='checker-label':f.card['added']['integrity']['entailment'][0]['checker']['name']='wrong'
    elif change=='foreign-card':
        f.card['id']='h_other';f.card['identity']['proposition_id']='h_other';f.ledger['card_id']='h_other'
    else:
        f.line['direction']['value']='disputes';f.rehash()
        item=next(x for x in profile.build(f.card,f.docs,f.selected)[0] if x['pointer']==pointer)
        entry['value_sha256']=projection.value_sha256(item['value'])
        entry['target_sha256']=projection.value_sha256(item['value']['target_statement'])
        entry['checker_binding']['item_identity']=projection.item_identity(item,entry['passage_sha256'])
        record=next(r for r in f.card['added']['integrity']['entailment'] if r['pointer']==pointer)
        record['verdict']='entails'
    f.rehash();f.ledger['content_hash']=f.card['content_hash']
    f.ledger['card_conditions']=profile.card_conditions(f.card)
    result=f.validate_profile()
    assert result['schema_valid'] is True and result['status']=='REFUSE',result


@pytest.mark.parametrize('change',['missing-atom','foreign-zone','duplicate-id','missing-target'])
def test_card_only_references_are_exact_conditions_not_fake_passage_entailment(tmp_path,change):
    f=ProfileFixture(tmp_path);f.merge_profile()
    prediction=f.card['added']['layers']['predictions'][0]
    if change=='missing-atom':prediction['derives_from_atom_refs']['value']=['missing']
    elif change=='foreign-zone':
        f.card['author']['layers']['core']['atoms']=[{'id':'author_only'}]
        prediction['derives_from_atom_refs']['value']=['author_only']
    elif change=='duplicate-id':prediction['id']='a_main'
    else:f.line['target_ref']='absent'
    f.rehash();f.ledger['content_hash']=f.card['content_hash']
    result=f.validate_profile()
    assert result['schema_valid'] is True and result['status']=='REFUSE',result
    assert any('CARD_CONDITION' in e or 'REFS:' in e for e in result['errors'])
    with pytest.raises(ValueError,match='CARD_CONDITION'):
        profile.card_conditions(f.card)


@pytest.mark.parametrize('change',['missing-item','extra-item','stale-epoch'])
def test_actual_frozen_wrong_roster_or_epoch_refuses_before_profile_merge(tmp_path,change):
    f=ProfileFixture(tmp_path);items,_=profile.build(f.card,f.docs,f.selected)
    if change=='missing-item':items.pop()
    elif change=='extra-item':items.append({**deepcopy(items[0]),'id':'extra',
        'pointer':'/added/layers/core/atoms/99/statement'})
    selected=deepcopy(f.selected)
    if change=='stale-epoch':selected['epoch']=0
    config={'kind':'injected_fake','renderer_profile':selected,
            'item_roster_sha256':projection.value_sha256(profile.roster(items))}
    inp,out=tmp_path/'wrong.json',tmp_path/'wrong-result.json'
    io.freeze(items,inp,entailment.PROMPT.read_bytes(),entailment.current_checker(),config,entailment.input_envelope(f.card))
    def fake(request,configuration):
        return {'request_sha256':projection.sha(request),'configuration_sha256':projection.value_sha256(configuration),
                'result_bytes':io.encoded([{'id':x['id'],'verdict':'entails'} for x in items])}
    io.run(inp,out,fake)
    before=deepcopy(f.card)
    with pytest.raises(ValueError):profile.merge(f.card,f.docs,f.selected,inp,out,f.ledger)
    assert f.ledger['entries']=={} and f.card==before


def test_worst_history_survives_new_entails_and_export(tmp_path):
    f=ProfileFixture(tmp_path);f.merge_profile('first','no');f.merge_profile('second','entails')
    assert f.validate_profile()['status']=='PASS'
    assert all(r['verdict']=='no' for r in f.card['added']['integrity']['entailment'])
    original=deepcopy(f.ledger)
    profile.export(f.card,f.ledger,f.docs,f.selected,tmp_path/'worst-ledger.json')
    for record in f.card['added']['integrity']['entailment']:
        record['verdict']='entails';record.pop('note',None)
    f.rehash();f.ledger['content_hash']=f.card['content_hash']
    assert f.validate_profile()['status']=='REFUSE'
    original['content_hash']=f.ledger['content_hash']
    assert f.ledger==original


def test_missing_binding_cannot_hide_an_earlier_no_with_later_entails(tmp_path):
    f=ProfileFixture(tmp_path);f.merge_profile('first','no');f.merge_profile('second','entails')
    pointer='/added/layers/evidence/lines/0/direction'
    history=f.ledger['entries'][pointer+'|src'];assert [e['verdict'] for e in history]==['no','entails']
    history[0].pop('checker_binding')
    record=next(r for r in f.card['added']['integrity']['entailment'] if r['pointer']==pointer)
    record.update(verdict='entails',checked_at=history[1]['checked_at']);record.pop('note')
    f.rehash();f.ledger['content_hash']=f.card['content_hash']
    before=deepcopy(f.ledger)
    assert f.validate_profile()['status']=='REFUSE'
    assert f.ledger==before


def test_unsupported_scientific_field_or_foreign_document_pool_never_skips(tmp_path):
    f=ProfileFixture(tmp_path);f.merge_profile()
    f.card['added']['layers']['core']['explanandum']={'value':'Outside supported shape','src':'p1'}
    f.rehash();f.ledger['content_hash']=f.card['content_hash']
    assert f.validate_profile()['status']=='REFUSE'
    f.card['added']['layers']['core'].pop('explanandum');rebind_root(f)
    f.docs['https://example.invalid/foreign']=f.doc
    assert f.validate_profile()['status']=='REFUSE'
