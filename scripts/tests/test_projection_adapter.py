"""Invented glyphs only. Fake checker IO, never scientific/model/HTTP/native-CLI execution."""
from copy import deepcopy
import json
from pathlib import Path
import os
import xml.etree.ElementTree as ET

import pytest

import ohfkit
if ohfkit.standard_line() != '1.4':
    pytest.skip('Native profile conformance requires its explicit OHF 1.4 checkout', allow_module_level=True)

import checker_io as io
import projection_binding as projection
import native_ledger as ledger_module
import native_entailment as entailment
import ohfkit
from conftest import invented_budget_counter


CONFIG = {'kind': 'injected_fake', 'name': 'glyph-unit-checker', 'version': '1'}


class Glyph:
    def __init__(self, root):
        self.root = root
        paragraphs = ['A square is followed by a circle in blue mode.',
                      'Only blue boards are considered. The interval is one day.',
                      'The square is followed by a circle. Eight panels were used.']
        raw = ('<article><front><article-meta><permissions><license><license-p>'
               'This work is licensed under the Creative Commons Attribution 4.0 License.'
               '</license-p></license></permissions></article-meta></front><body>' +
               ''.join('<p>'+p+'</p>' for p in paragraphs) + '</body></article>').encode()
        import native_profile
        doc = native_profile.document_from_bytes(raw, 'PMC810055', '2026-02-02T00:00:00Z')
        self.doc, self.docs = doc, {doc.url: doc}
        self.card = ohfkit.skeleton(budget_counter=invented_budget_counter, ident='h_glyph', doc=doc, citation='Invented glyph fixture.',
                                   doi='10.9999/glyph', topic=['test'], sources={f'p{i}':doc.src(i) for i in (1,2,3)},
                                   author_names='Invented author')
        s = lambda value, src='p2': {'value': value, 'src': src}
        self.card['author']['layers']['core']['statement'] = doc.author(1, paragraphs[0])
        core = self.card['added']['layers']['core']
        core.update(statement=s(paragraphs[0], 'p1'), scope=s('Blue boards only.'), kind=s('mechanism'),
                    atoms=[{'id':'a_root','statement':s('Square precedes circle.'),'operator':'AND'},
                           {'id':'a_child','parent_ref':'a_root','statement':s('Circle follows square.'),
                            'scope':s('Small blue boards.'),'context_override':[{'duration':'one day'}],
                            'requires':['a_dep']},
                           {'id':'a_dep','statement':s('A board is present.')}])
        self.card['added']['layers']['predictions'] = [
            {'id':'pr_glyph','population':s('blue panels'),'endpoint':s('circle count'),
             'direction':s('increase'),'horizon':s('one day'),'comparator':s('blank panel'),
             'intervention':{'agent':s('chalk'),'dose':s('one unit'),'duration':s('one day')},
             'derives_from_atom_refs':s(['a_child'])}]
        self.card['added']['layers']['evidence']['lines'] = [
            {'id':'e_glyph','target_ref':'a_child','src':'p3',
             'quote':doc.check(3, 'The square is followed by a circle.'),
             'direction':s('supports','p3'),
             'indirectness':s({'system':'some','endpoint':'none','intervention':'none','comparison':'none'},'p3'),
             'sample_size':s(8,'p3'),'endpoint_kind':{'value':'glyph shape','term':'other','note':'invented', 'src':'p3'}}]
        self.ledger = ledger_module.new_ledger(self.card)
        self.calls = []
        self.rehash()

    @property
    def line(self):return self.card['added']['layers']['evidence']['lines'][0]

    def rehash(self):
        self.card['content_hash'] = ohfkit.content_hash(self.card)

    def stamp_ledger(self):
        self.rehash()
        self.ledger = ledger_module.new_ledger(self.card, self.ledger['entries'], self.ledger['notes'],
                                                self.ledger.get('checker_io_proofs'))

    def items(self):return entailment.checker_items(entailment.build(self.card, self.docs))

    def target_item(self, field='direction'):
        return next(x for x in self.items() if x['pointer']==f'/added/layers/evidence/lines/0/{field}')

    def prepare(self, name, verdict='entails'):
        self.rehash()
        inp, out = self.root/(name+'.json'), self.root/(name+'-result.json')
        entailment.freeze_checker_input(self.card, self.docs, inp, CONFIG)
        def fake(request, config):
            assert request == io.paths(inp)[1].read_bytes()
            assert request.startswith(entailment.PROMPT.read_bytes()+b'\n\n')
            raw = request[len(entailment.PROMPT.read_bytes())+2:]
            actual_items = io.strict_json(raw)
            self.calls.append({'request_sha256':projection.sha(request),'items':deepcopy(actual_items)})
            results = [{'id':x['id'],'verdict':verdict, **({'note':'Invented fake result, not science.'} if verdict!='entails' else {})}
                       for x in actual_items]
            return {'request_sha256':projection.sha(request), 'configuration_sha256':projection.value_sha256(config),
                    'result_bytes':io.encoded(results)}
        entailment.run_frozen_checker(inp, out, fake)
        return inp, out

    def merge(self, name='first', verdict='entails'):
        inp, out = self.prepare(name, verdict)
        records = entailment.merge_frozen(self.card, self.docs, inp, out, self.ledger)
        self.stamp_ledger()
        return inp, out, records

    def errors(self):
        items = entailment.build(self.card, self.docs)
        passages = {ledger_module.key_of(x):x['source_passage'] for x in items if x['basis']=='src'}
        return ledger_module.check(self.card, self.ledger, passages)


def replace_file(path, raw):
    path.chmod(0o600);path.write_bytes(raw)


def test_actual_build_frozen_request_fake_result_merge_check_export(tmp_path):
    f=Glyph(tmp_path);inp,out,records=f.merge()
    assert len(f.calls)==1 and f.calls[0]['items']==f.items()
    assert not f.errors()
    entry=f.ledger['entries']['/added/layers/evidence/lines/0/direction|src'][0]
    target=f.target_item()['value']['target_statement']
    assert target==projection.reference().target_statement(f.card,f.line)
    assert entry['target_sha256']==projection.reference().value_sha256(target)
    assert entry['target_projection']==projection.TARGET_PROJECTION
    assert entry['checker_binding']['request_sha256']==f.calls[0]['request_sha256']
    assert entry['checker_binding']['result_sha256']==projection.sha(out.read_bytes())
    assert all('checker_binding' not in r for r in records)  # native card record schema unchanged
    exported=tmp_path/'exported-ledger.json'
    entailment.export_ledger(f.card,f.docs,f.ledger,exported)
    assert io.strict_json(exported.read_bytes())==f.ledger
    assert io.paths(inp)[1].read_bytes()==entailment.PROMPT.read_bytes()+b'\n\n'+inp.read_bytes()


@pytest.mark.parametrize('field',['direction','indirectness'])
def test_native_relational_fields_quotes_and_other_conditioning_retained(tmp_path,field):
    f=Glyph(tmp_path);item=f.target_item(field);value=item['value']
    assert value[field]==f.line[field]['value'] and value['line_quote']==f.line['quote']
    assert value['target_statement']==ledger_module.target_statement(f.card,f.line)
    assert field not in value['evidence_conditions']
    assert ('indirectness' if field=='direction' else 'direction') in value['evidence_conditions']
    sample=f.target_item('sample_size')['value'];term=f.target_item('endpoint_kind')['value']
    assert sample=={'sample_size':8,'line_quote':f.line['quote']}
    assert term=={'endpoint_kind':'glyph shape','term':'other','note':'invented','line_quote':f.line['quote']}


@pytest.mark.parametrize('change',['scope','parent','override','requires','horizon','dose','comparator','quote','paraphrase','term'])
def test_changed_scientific_conditions_cannot_carry_or_export_old_verdict(tmp_path,change):
    f=Glyph(tmp_path)
    if change in ('horizon','dose','comparator'):f.line['target_ref']='pr_glyph'
    if change=='paraphrase':
        f.line.pop('quote');f.line['quote_withheld']={'value':{'paraphrase':'An invented logical objection.',
            'locator':'a declared locator','record_ref':'10.9999/objection'},'src':'p3'}
    f.merge();old=deepcopy(f.card);history=deepcopy(f.ledger['entries']);before=f.target_item()['value']
    core=f.card['added']['layers']['core'];prediction=f.card['added']['layers']['predictions'][0]
    if change=='scope':core['scope']['value']='Red boards only.'
    elif change=='parent':core['atoms'][0]['operator']='OR'
    elif change=='override':core['atoms'][1]['context_override'][0]['duration']='two days'
    elif change=='requires':core['atoms'][2]['statement']['value']='A different board is present.'
    elif change=='horizon':prediction['horizon']['value']='two days'
    elif change=='dose':prediction['intervention']['dose']['value']='two units'
    elif change=='comparator':prediction['comparator']['value']='painted panel'
    elif change=='quote':f.line['quote']='Eight panels were used.'
    elif change=='paraphrase':f.line['quote_withheld']['value']['paraphrase']='The invented objection is different.'
    else:f.line['endpoint_kind']['term']='survival'
    f.rehash();assert f.target_item()['value']!=before
    kept,rest=entailment.carry(old,f.card,f.docs,f.ledger)
    assert all(not projection.is_projected(r) for r in kept)
    assert any(projection.is_projected(x) for x in rest)
    f.stamp_ledger();assert f.ledger['entries']==history
    with pytest.raises(ValueError,match='export refused'):entailment.export_ledger(f.card,f.docs,f.ledger,tmp_path/'bad-export.json')
    assert not (tmp_path/'bad-export.json').exists()


def test_budget_only_revision_keeps_scientific_digest_with_explicit_new_envelope(tmp_path):
    f=Glyph(tmp_path);f.merge();old=deepcopy(f.card);target=projection.value_sha256(f.target_item()['value']['target_statement'])
    histories=deepcopy(f.ledger['entries']);old_hash=f.card['content_hash']
    f.card['added']['budget']['http_requests']=2;f.card['version']=2;f.card['identity']['version']=2;f.rehash()
    assert f.card['content_hash']!=old_hash
    assert projection.value_sha256(f.target_item()['value']['target_statement'])==target
    kept,rest=entailment.carry(old,f.card,f.docs,f.ledger)
    assert any(r['pointer'].endswith('/direction') for r in kept) and not rest
    f.stamp_ledger();assert not f.errors() and f.ledger['card_version']==2
    assert histories==f.ledger['entries'] and len(f.calls)==1


@pytest.mark.parametrize('mode',['raw_merge','entry','old_receipt_new_input','alter_result','wrong_request','wrong_config','config_drift'])
def test_new_hash_old_verdict_and_unbound_results_refuse_before_history_append(tmp_path,mode):
    f=Glyph(tmp_path);inp,out=f.prepare('old');before=deepcopy(f.ledger)
    items,results=io.strict_json(inp.read_bytes()),io.strict_json(out.read_bytes())
    if mode=='raw_merge':
        with pytest.raises(ValueError,match='requires frozen'):entailment.merge(f.card,items,results,f.docs,f.ledger)
    elif mode=='entry':
        x=next(x for x in items if projection.is_projected(x))
        with pytest.raises(ValueError,match='requires frozen'):ledger_module.entry(x,{'verdict':'entails','checked_at':ohfkit.now()})
    elif mode=='old_receipt_new_input':
        f.card['added']['layers']['core']['scope']['value']='Red boards only.';f.rehash()
        new=tmp_path/'new-input.json';entailment.freeze_checker_input(f.card,f.docs,new,CONFIG)
        with pytest.raises(ValueError):entailment.merge_frozen(f.card,f.docs,new,out,f.ledger)
    elif mode=='alter_result':
        results[0]['note']='tampered';replace_file(out,io.encoded(results))
        with pytest.raises(ValueError,match='differs'):entailment.merge_frozen(f.card,f.docs,inp,out,f.ledger)
    elif mode in ('wrong_request','wrong_config'):
        inp=tmp_path/'wrong-input.json';entailment.freeze_checker_input(f.card,f.docs,inp,CONFIG)
        newout=tmp_path/'wrong.json'
        def wrong(request,config):
            return {'request_sha256':projection.sha(b'old') if mode=='wrong_request' else projection.sha(request),
                    'configuration_sha256':projection.sha(b'old') if mode=='wrong_config' else projection.value_sha256(config),
                    'result_bytes':io.encoded(results)}
        with pytest.raises(ValueError,match='another request'):entailment.run_frozen_checker(inp,newout,wrong)
        assert not newout.exists()
    else:
        meta=io.strict_json(io.paths(inp)[2].read_bytes());meta['configuration']['version']='2'
        replace_file(io.paths(inp)[2],io.encoded(meta))
        with pytest.raises(ValueError,match='binding differs'):entailment.merge_frozen(f.card,f.docs,inp,out,f.ledger)
    assert f.ledger==before


@pytest.mark.parametrize('remove',['target_projection','target_sha256','checker_binding'])
def test_per_entry_missing_binding_stays_inert_despite_new_root_and_rehash(tmp_path,remove):
    f=Glyph(tmp_path);f.merge();key='/added/layers/evidence/lines/0/direction|src'
    f.ledger['entries'][key][0].pop(remove);f.stamp_ledger()
    errors=f.errors();assert any('missing/stale target projection' in x for x in errors)
    item=f.target_item();record=next(r for r in f.card['added']['integrity']['entailment'] if ledger_module.key_of(r)==key)
    assert not ledger_module.rendered_before({},item,record,f.ledger['entries'][key],f.card,item['pointer'])


def test_worst_verdict_history_preserved_for_same_full_context_and_passage(tmp_path):
    f=Glyph(tmp_path);f.merge('negative','no');f.merge('positive','entails')
    assert not f.errors()
    key='/added/layers/evidence/lines/0/direction|src'
    assert [e['verdict'] for e in f.ledger['entries'][key]]==['no','entails']
    shown=next(r for r in f.card['added']['integrity']['entailment'] if ledger_module.key_of(r)==key)
    assert shown['verdict']=='no' and shown['note']=='Invented fake result, not science.'


@pytest.mark.parametrize('changed',[False,True])
def test_restore_copies_exact_source_entries_not_rehashed_old_verdict(tmp_path,changed):
    f=Glyph(tmp_path);f.merge();old=deepcopy(f.card);source=deepcopy(f.ledger)
    f.card['added']['integrity']['entailment']=[]
    if changed:f.card['added']['layers']['core']['scope']['value']='Changed scope.'
    f.rehash();f.ledger=ledger_module.new_ledger(f.card)
    added,skipped,_=entailment.restore(f.card,[old],lambda _:f.docs,f.ledger,{old['content_hash']:source})
    key='/added/layers/evidence/lines/0/direction|src'
    assert added and f.ledger['entries'][key]==source['entries'][key]
    f.stamp_ledger()
    assert bool(f.errors())==changed
    if changed:assert not any(projection.is_projected(r) for r in f.card['added']['integrity']['entailment'])


def test_restore_without_archive_ledger_never_synthesizes_target_io_proof(tmp_path):
    f=Glyph(tmp_path);f.merge();old=deepcopy(f.card)
    f.card['added']['integrity']['entailment']=[];f.rehash();f.ledger=ledger_module.new_ledger(f.card)
    _,skipped,_=entailment.restore(f.card,[old],lambda _:f.docs,f.ledger)
    assert skipped>=2 and '/added/layers/evidence/lines/0/direction|src' not in f.ledger['entries']
    assert not any(projection.is_projected(r) for r in f.card['added']['integrity']['entailment'])


@pytest.mark.parametrize('kind',['external','partial','duplicate','cycle','wrong_entity'])
def test_external_partial_ambiguous_and_unresolved_inputs_refuse_before_callback(tmp_path,kind):
    f=Glyph(tmp_path);core=f.card['added']['layers']['core']
    if kind=='external':f.line['target_ref']='h_external@1'
    elif kind=='partial':f.line['target_ref']={'kind':'card','pointer':'/added/layers/core/atoms/1/statement'}
    elif kind=='duplicate':core['atoms'].append(deepcopy(core['atoms'][1]))
    elif kind=='cycle':core['atoms'][0]['parent_ref']='a_child'
    else:core['atoms'][1]['triples']=[{'entity_ref':'not_defined'}]
    f.rehash()
    with pytest.raises(ValueError):entailment.freeze_checker_input(f.card,f.docs,tmp_path/'bad.json',CONFIG)
    assert not f.calls and not (tmp_path/'bad.json').exists()


def test_optional_id_prediction_pointer_and_unknown_core_conditions(tmp_path):
    f=Glyph(tmp_path);prediction=f.card['added']['layers']['predictions'][0];prediction.pop('id')
    f.line['target_ref']={'kind':'card','pointer':'/added/layers/predictions/0'}
    target=f.target_item()['value']['target_statement']
    assert target['kind']=='prediction' and set(target['targets'])=={'added'}
    assert 'assumptions' in target['card_conditions']['added']['not_recorded_core_conditions']
    f.merge();assert not f.errors()


@pytest.mark.parametrize('zone',['author','added'])
def test_cross_zone_alternative_entity_context_equals_direct_and_stales(tmp_path,zone):
    f=Glyph(tmp_path)
    for z in ('author','added'):
        layers=f.card[z]['layers'];layers['mechanism']['entities']=[{'id':'ent','label':{'value':z+' glyph','src':'p1'}}]
    if zone=='author':
        f.card['author']['layers']['core']['atoms']=[{'id':'a_author','statement':{'value':'An author glyph relation.','locator':'p1'},'triples':[{'entity_ref':'ent'}]}]
        pointer='/author/layers/core/atoms/0'
    else:
        f.card['added']['layers']['core']['atoms'][1]['triples']=[{'entity_ref':'ent'}];pointer='/added/layers/core/atoms/1'
    direct=ledger_module.target_statement(f.card,{'target_ref':{'kind':'card','pointer':pointer}})
    f.card['added']['layers']['core']['alternative_explanations']={'value':[{'id':'alt','claim_or_ref':{'kind':'reference','ref':{'kind':'card','pointer':pointer}}}],'src':'p2'}
    f.line['target_ref']='alt';target=f.target_item()['value']['target_statement']
    assert target['targets']['added']['referent']==direct
    f.merge();old=deepcopy(f.card);before=f.target_item()['value']
    f.card[zone]['layers']['mechanism']['entities'][0]['label']['value']='Changed own glyph.'
    f.rehash();assert before!=f.target_item()['value']
    kept,rest=entailment.carry(old,f.card,f.docs,f.ledger)
    assert any(projection.is_projected(x) for x in rest)


@pytest.mark.parametrize('artifact',['input','request','metadata','result','receipt','dispatch'])
def test_immutable_artifact_drift_refuses_merge_before_mutation(tmp_path,artifact):
    f=Glyph(tmp_path);inp,out=f.prepare('bound');before=deepcopy(f.ledger)
    paths={'input':inp,'request':io.paths(inp)[1],'metadata':io.paths(inp)[2],
           'result':out,'receipt':io.result_paths(out)[1],'dispatch':io.dispatch_path(inp)}
    p=paths[artifact];replace_file(p,p.read_bytes()+b' ')
    with pytest.raises(ValueError):entailment.merge_frozen(f.card,f.docs,inp,out,f.ledger)
    assert f.ledger==before


@pytest.mark.parametrize('kind',['symlink','hardlink','existing','missing_config','api_pin'])
def test_refusal_and_dependency_file_safety_without_transport(tmp_path,kind,monkeypatch):
    f=Glyph(tmp_path);inp=tmp_path/'freeze.json'
    if kind in ('symlink','hardlink','existing'):
        f.rehash();entailment.freeze_checker_input(f.card,f.docs,inp,CONFIG)
        alias=tmp_path/'alias.json'
        if kind=='symlink':alias.symlink_to(inp)
        elif kind=='hardlink':os.link(inp,alias)
        else:alias=inp
        with pytest.raises(ValueError):entailment.freeze_checker_input(f.card,f.docs,alias,CONFIG)
    elif kind=='missing_config':
        with pytest.raises(ValueError,match='configuration'):entailment.freeze_checker_input(f.card,f.docs,inp,None)
    else:
        root=tmp_path/'wrong-api';(root/'tools').mkdir(parents=True)
        (root/'tools/check_ledger.py').write_text('raise AssertionError("must never execute")')
        monkeypatch.setenv('OHF_REPO',str(root))
        with pytest.raises(ValueError,match='API pin differs'):f.items()
    assert not f.calls


@pytest.mark.parametrize('raw',[b'{"a":1,"a":2}',b'1e9999',b'NaN',b'Infinity'])
def test_strict_checker_json_rejects_ambiguous_or_nonfinite_input(raw):
    with pytest.raises(ValueError):io.strict_json(raw)


def test_explicit_archive_manifest_and_envelope_refusals(tmp_path):
    f=Glyph(tmp_path);f.merge();old=deepcopy(f.card)
    source=tmp_path/'source-ledger.json';source.write_bytes(io.encoded(f.ledger))
    manifest=tmp_path/'archive.json';manifest.write_bytes(io.encoded({'format':'ohf-native-archive-ledgers/1',
        'ledgers':[{'card_content_hash':old['content_hash'],'file':'source-ledger.json'}]}))
    mapping=entailment.archive_ledger_sources(manifest);assert mapping[old['content_hash']]==f.ledger
    mapping[old['content_hash']]['card_id']='h_foreign'
    with pytest.raises(ValueError,match='envelope mismatch'):entailment.restore(f.card,[old],lambda _:f.docs,f.ledger,mapping)
    manifest.write_bytes(io.encoded({'format':'ohf-native-archive-ledgers/1','ledgers':[{'card_content_hash':'x','file':'../secret'}]}))
    with pytest.raises(ValueError):entailment.archive_ledger_sources(manifest)


def test_callback_failure_preserves_durable_dispatch_and_refuses_another_output(tmp_path):
    f=Glyph(tmp_path);inp=tmp_path/'failure-input.json';f.rehash()
    entailment.freeze_checker_input(f.card,f.docs,inp,CONFIG);calls=[]
    def fail(request,config):
        calls.append(projection.sha(request));raise RuntimeError('invented checker failure')
    with pytest.raises(RuntimeError,match='invented checker failure'):
        entailment.run_frozen_checker(inp,tmp_path/'failure-result.json',fail)
    dispatch=io.dispatch_path(inp).read_bytes()
    assert len(calls)==1 and not (tmp_path/'failure-result.json').exists()
    with pytest.raises(ValueError,match='no replacement'):
        entailment.run_frozen_checker(inp,tmp_path/'different-result.json',fail)
    assert len(calls)==1 and io.dispatch_path(inp).read_bytes()==dispatch


@pytest.mark.parametrize('which',['items','results','meta','receipt'])
def test_public_pair_objects_cannot_be_mutated_into_new_input_old_result(tmp_path,which):
    f=Glyph(tmp_path);inp,out=f.prepare('pair');before=deepcopy(f.ledger)
    pair=io.load_pair(inp,out,entailment.CHECKER,entailment.input_envelope(f.card))
    if which=='items':pair.items[0]['value']='changed'
    elif which=='results':pair.results[0]['verdict']='no';pair.results[0]['note']='changed'
    elif which=='meta':pair.meta['envelope']['content_hash']='sha256:'+'0'*64
    else:pair.receipt['returned_at']='2000-01-01T00:00:00Z'
    with pytest.raises(ValueError,match='differs from frozen'):
        entailment.merge(f.card,pair.items,pair.results,f.docs,f.ledger,io_pair=pair)
    assert f.ledger==before


@pytest.mark.parametrize('kind',['prediction','step','alternative'])
def test_optional_id_whole_target_pointers_do_not_guess_counterparts(tmp_path,kind):
    f=Glyph(tmp_path)
    if kind=='prediction':
        f.card['added']['layers']['predictions'][0].pop('id');pointer='/added/layers/predictions/0'
    elif kind=='step':
        f.card['added']['layers']['mechanism']={'entities':[{'id':'s','label':'square'},{'id':'o','label':'circle'}],
            'steps':[{'subject_ref':'s','relation':'precedes','object_ref':'o'}]}
        pointer='/added/layers/mechanism/steps/0'
    else:
        f.card['added']['layers']['core']['alternative_explanations']={'value':[{'claim_or_ref':{'kind':'literal','text':'An invented alternative.'}}],'src':'p2'}
        pointer='/added/layers/core/alternative_explanations/value/0'
    f.line['target_ref']={'kind':'card','pointer':pointer}
    target=f.target_item()['value']['target_statement']
    assert target['kind']==kind and set(target['targets'])=={'added'}
    f.merge();assert not f.errors()


def test_wrapper_paraphrase_metadata_excluded_but_logical_withheld_paraphrase_bound(tmp_path):
    f=Glyph(tmp_path);f.line.pop('quote')
    f.line['quote_withheld']={'value':{'paraphrase':'A logical invented objection.','locator':'declared location'},
                             'src':'p3','paraphrase':'wrapper annotation'}
    before=f.target_item()['value']
    f.line['quote_withheld']['paraphrase']='changed wrapper annotation'
    assert f.target_item()['value']==before
    f.line['quote_withheld']['value']['paraphrase']='A different logical objection.'
    assert f.target_item()['value']!=before


def test_wrong_zone_duplicate_entity_is_unrelated_to_typed_author_referent(tmp_path):
    f=Glyph(tmp_path)
    f.card['author']['layers']['mechanism']['entities']=[{'id':'e','label':'own author glyph'}]
    f.card['author']['layers']['core']['atoms']=[{'id':'auth','statement':'Author glyph claim.','triples':[{'entity_ref':'e'}]}]
    f.card['added']['layers']['core']['alternative_explanations']={'value':[{'id':'alt','claim_or_ref':{'kind':'reference','ref':{'kind':'card','pointer':'/author/layers/core/atoms/0'}}}],'src':'p2'}
    f.line['target_ref']='alt';before=f.target_item()['value']
    f.card['added']['layers']['mechanism']['entities']=[{'id':'e','label':'unrelated'},{'id':'e','label':'also unrelated'}]
    assert f.target_item()['value']==before
    f.merge();assert not f.errors()
    f.card['author']['layers']['mechanism']['entities'].append({'id':'e','label':'ambiguous own namespace'})
    with pytest.raises(ValueError,match='unresolved/ambiguous'):f.items()


@pytest.mark.parametrize('mode',['id_order','duplicate_id','bad_verdict','no_note','unknown_field','nonfinite'])
def test_fake_checker_invalid_responses_refuse_without_publishing_result(tmp_path,mode):
    f=Glyph(tmp_path);f.rehash();inp=tmp_path/'invalid-in.json';out=tmp_path/'invalid-out.json'
    entailment.freeze_checker_input(f.card,f.docs,inp,CONFIG)
    def invalid(request,config):
        rows=[{'id':x['id'],'verdict':'entails'} for x in f.items()]
        if mode=='id_order':rows.reverse()
        elif mode=='duplicate_id':rows[1]['id']=rows[0]['id']
        elif mode=='bad_verdict':rows[0]['verdict']='probably'
        elif mode=='no_note':rows[0]['verdict']='partial'
        elif mode=='unknown_field':rows[0]['extra']='not allowed'
        raw=b'1e9999' if mode=='nonfinite' else io.encoded(rows)
        return {'request_sha256':projection.sha(request),'configuration_sha256':projection.value_sha256(config),'result_bytes':raw}
    with pytest.raises(ValueError):entailment.run_frozen_checker(inp,out,invalid)
    assert not out.exists() and io.dispatch_path(inp).exists()


def test_changed_card_after_freeze_rejects_result_before_mutating_history(tmp_path):
    f=Glyph(tmp_path);inp,out=f.prepare('old-card');before=deepcopy(f.ledger)
    f.card['added']['layers']['core']['scope']['value']='changed inherited conditions';f.rehash()
    with pytest.raises(ValueError,match='envelope differs'):entailment.merge_frozen(f.card,f.docs,inp,out,f.ledger)
    assert f.ledger==before


def test_entry_only_rehash_cannot_change_membership_in_frozen_input_manifest(tmp_path):
    f=Glyph(tmp_path);f.merge();key='/added/layers/evidence/lines/0/direction|src'
    original_proofs=deepcopy(f.ledger['checker_io_proofs'])
    f.card['added']['layers']['core']['scope']['value']='A different scope.';f.rehash()
    item=f.target_item();entry=f.ledger['entries'][key][0]
    entry['value_sha256']=projection.value_sha256(item['value'])
    entry['target_sha256']=projection.value_sha256(item['value']['target_statement'])
    entry['checker_binding']['item_identity']=projection.item_identity(item,entry['passage_sha256'])
    f.stamp_ledger()
    active,error=ledger_module._active_for({},key,item,None,[entry],{key:item['source_passage']},
                                          card=f.card,proofs=f.ledger['checker_io_proofs'])
    assert not active and 'missing/stale' in error
    assert original_proofs==f.ledger['checker_io_proofs']


@pytest.mark.parametrize('what',['proof_removed','input_membership','result_membership','returned_verdict'])
def test_export_verifies_hash_linked_header_membership_not_only_entry_hashes(tmp_path,what):
    f=Glyph(tmp_path);f.merge('negative','no');key='/added/layers/evidence/lines/0/direction|src'
    e=f.ledger['entries'][key][0];b=e['checker_binding'];proof=f.ledger['checker_io_proofs'][b['result_binding_sha256']]
    if what=='proof_removed':f.ledger['checker_io_proofs'].clear()
    elif what=='input_membership':proof['input']['item_manifest'][0]['value_sha256']=projection.sha(b'wrong')
    elif what=='result_membership':proof['result']['result_manifest'][0]['verdict']='entails'
    else:e['verdict']='entails';e.pop('note_sha256');b['result']={'verdict':'entails','note_sha256':None}
    f.stamp_ledger()
    with pytest.raises(ValueError,match='export refused'):
        entailment.export_ledger(f.card,f.docs,f.ledger,tmp_path/'not-exported.json')
    assert not (tmp_path/'not-exported.json').exists()


def test_verified_handles_cannot_be_publicly_constructed_from_arbitrary_verdicts(tmp_path):
    f=Glyph(tmp_path);item=f.target_item()
    with pytest.raises(ValueError,match='must be loaded'):
        io.VerifiedPair([],[],{},{},{},{},projection.sha(b'none'))
    with pytest.raises(ValueError,match='must originate'):
        io.ItemBinding({}, {})
    with pytest.raises(ValueError,match='arbitrary dictionary'):
        ledger_module.entry(item,{'verdict':'entails','checked_at':ohfkit.now()},binding={})


def test_new_source_lineage_header_never_embeds_scientific_passage_or_target_text(tmp_path):
    f=Glyph(tmp_path);f.merge();proofs=f.ledger['checker_io_proofs'];raw=io.encoded(proofs)
    assert f.doc.paragraphs[0].encode() not in raw and f.doc.paragraphs[2].encode() not in raw
    assert b'Square precedes circle.' not in raw
    assert b'item_manifest' in raw and b'result_manifest' in raw
    f.card['added']['integrity']['entailment'][0]['checker']['version']='wrong'
    assert f.errors()


def test_native_resolver_identity_source_inputs_and_history_still_gate_reuse(tmp_path):
    f=Glyph(tmp_path)
    f.line['items']=[{'value':{'artifact':f.doc.file, 'sha256':f.doc.sha,
                             'locator':'XML .//p[3]'}, 'src':'p3'}]
    f.rehash()
    item=next(x for x in entailment.build(f.card,f.docs) if entailment.is_resolved(x))
    assert item not in f.items()  # not sent to the injected checker
    key=ledger_module.key_of(item)
    assert entailment.resolve_references(f.card,f.docs,f.ledger)[0]['verdict']=='entails'
    first=deepcopy(f.ledger['entries'][key][0])
    assert first['resolver_inputs']=={f.doc.file:f.doc.sha}
    assert entailment.resolve_references(f.card,f.docs,f.ledger)==[]
    f.ledger['entries'][key][0]['resolver']['version']='1.0.0'
    old=deepcopy(f.ledger['entries'][key][0])
    assert entailment.resolve_references(f.card,f.docs,f.ledger)[0]['verdict']=='entails'
    assert f.ledger['entries'][key][0]==old and len(f.ledger['entries'][key])==2
    f.doc.sha='f'*64
    assert entailment.resolve_references(f.card,f.docs,f.ledger)[0]['verdict']=='no'
    history=f.ledger['entries'][key]
    assert len(history)==3 and history[-1]['resolver_inputs']=={f.doc.file:'f'*64}
    current=ledger_module.active(history,ledger_module.value_sha256(item['value']),
                                ledger_module.passage_sha256(item['source_passage']),resolved=True,
                                inputs=entailment.resolution_inputs(f.card,item,f.docs))
    assert current==[history[-1]]
    assert ledger_module.choose(current)['verdict']=='no'


def test_native_resolver_refuses_unbound_and_wrong_source_pairs(tmp_path):
    f=Glyph(tmp_path)
    pointer='/added/layers/evidence/lines/0/items/0'
    def resolve(artifact,sha):
        return entailment.resolve({'pointer':pointer,'basis':'src',
                                  'value':{'artifact':artifact,'sha256':sha,'locator':'XML .//p[3]'},
                                  'source_passage':f.doc.para(3)},f.card,f.docs)[0]
    assert resolve(f.doc.file,f.doc.sha)=='entails'
    assert resolve(f.doc.file,'e'*64)=='no'
    assert resolve('foreign.xml','a'*64)=='partial'
    assert resolve('foreign.xml','')=='no'


def test_ordinary_nonrelational_native_merge_remains_backward_compatible(tmp_path):
    f=Glyph(tmp_path);f.card['added']['layers']['evidence']['lines']=[];f.rehash()
    items=f.items();results=[{'id':x['id'],'verdict':'entails'} for x in items]
    assert not any(projection.is_projected(x) for x in items)
    entailment.merge(f.card,items,results,f.docs,f.ledger)
    f.stamp_ledger()
    assert not f.errors() and f.ledger['entries']
    assert all('checker_binding' not in e for history in f.ledger['entries'].values() for e in history)
