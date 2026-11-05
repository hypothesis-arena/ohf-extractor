"""Invented glyph examples only. No historical issue, scientific dataset, inference or native CLI."""
from copy import deepcopy
import json
from pathlib import Path
import os
import types
import hashlib

import pytest
from jsonschema import Draft202012Validator
import question_context as qc


def full_native(name):
    path=Path(__file__).resolve().parents[1]/(name+'.py');raw=path.read_bytes()
    module=types.ModuleType('question_context_fixture_'+name);module.__file__=str(path)
    exec(compile(raw,str(path),'exec'),module.__dict__)
    module._fixture_source_sha256 = 'sha256:' + hashlib.sha256(raw).hexdigest()
    return module


# Read complete native sources instead of ambient bytecode. Their digest checks
# are ordinary tests so a source-pin mismatch cannot abort pytest collection.
ohfkit=full_native('ohfkit')
check_ledger=full_native('check_ledger')

T=lambda n:f'2026-02-02T00:00:{n:02d}Z'
DUMP=lambda value:(json.dumps(value,sort_keys=True)+'\n').encode()


def native_doc(pmcid,doi,paragraphs):
    raw=('<article><front><article-meta><article-id pub-id-type="pmc">'+pmcid[3:]+
         '</article-id><article-id pub-id-type="doi">'+doi+'</article-id></article-meta></front><body>'+
         ''.join('<p>'+p+'</p>' for p in paragraphs)+'</body></article>').encode()
    # Actual native class/methods; deliberately no constructor or fetch. Local invented bytes only.
    doc=ohfkit.Document.__new__(ohfkit.Document)
    doc.pmcid=pmcid;doc.url=ohfkit.EPMC.format(pmcid);doc.file=pmcid+'.xml';doc.sha=ohfkit.sha256(raw)
    doc.retrieved=T(0);doc.root=ohfkit.ET.fromstring(raw)
    doc.paragraphs=[ohfkit.norm(''.join(p.itertext())) for p in doc.root.iter('p')]
    return doc,raw


class Fixture:
    def __init__(self,root,typ='scope'):
        self.root=root;root.mkdir(exist_ok=True)
        main,raw=native_doc('PMC810001','10.9999/glyph-main',[
            'Dr. Ivo states that a square yields a circle in mode A. The claim concerns drawn glyphs.',
            'The mapping is stated only for mode A. Mode B remains an open question.',
            'A distant panel was not part of the setup.” Next a triangle was drawn.'])
        study,other=native_doc('PMC810002','10.9999/glyph-study',[
            'The panel yielded a circle after a square. A separate dot remained unchanged.',
            'The panel used mode A on a clay board. Another board was not tested.'])
        self.docs={'doc:claim':main,'doc:property':study}
        self.raws={main.file:raw,study.file:other}
        statement=main.author(1,ohfkit.sentences_of(main.para(1))[0])['value']
        self.card={'schema':'ohf:hypothesis@1','id':'h_glyph','version':1,
            'identity':{'proposition_id':'h_glyph','version':1},
            'author':{'source':{'doi':'10.9999/glyph-main','source_text_sha256':main.sha,'retrieved_at':T(0)}},
            'added':{'budget':{'model_calls':None,'http_requests':None},'sources':{
                'm1':main.src(1),'m2':main.src(2),'m3':main.src(3),'s1':study.src(1),'s2':study.src(2)},
             'layers':{'core':{'scope':{'value':'Mode A only.','src':'m2'},
                 'atoms':[{'id':'a_glyph','statement':{'value':statement,'src':'m1'}}]},
               'predictions':[], 'evidence':{'lines':[{'id':'e_panel','target_ref':{'value':'a_glyph','src':'s1'},
                 'quote':study.check(1,'The panel yielded a circle after a square.'),
                 'direction':{'value':'supports','src':'s1'},
                 'indirectness':{'value':{'system':'some','endpoint':'none','intervention':'none','comparison':'none'},'src':'s2'},
                 'items':[study.item(1),study.item(2)]}]}}}}
        self.owner={'card_id':self.card['id'],'card_version':1,'card_sha256':qc.grounds.sha(DUMP(self.card))}
        self.sources=[{'key':key,'file':doc.file,'sha256':doc.sha,'work':{'namespace':'pmcid','value':doc.pmcid},
            'retrieved_at':doc.retrieved,'state':'complete','role':'main' if key=='doc:claim' else 'evidence',
            'owner':deepcopy(self.owner)} for key,doc in self.docs.items()]
        anchor={'kind':'atom','owner':deepcopy(self.owner),'pointer':'/added/layers/core/atoms/0','id':'a_glyph',
                'value_sha256':qc.value_hash(self.card['added']['layers']['core']['atoms'][0]),'source':self.binding('doc:claim')}
        pointer='/added/layers/core/scope' if typ=='scope' else '/added/layers/evidence/lines/0/'+typ
        node=qc.grounds.pointer(self.card,pointer)
        self.question={'id':'q_glyph','type':typ,'state':'ready','target_ref':{
             'kind':typ+'_field','owner':deepcopy(self.owner),'pointer':pointer,'value_sha256':qc.value_hash(node),
             'native_checked_sha256':qc.value_hash(check_ledger.checked_value(self.card,pointer,node)),
             'source':self.binding('doc:claim' if typ=='scope' else 'doc:property')},
            'anchor_ref':anchor,'context':[self.context('m1','claim',[1]),
                self.context('m2' if typ=='scope' else 's1' if typ=='direction' else 's2','property')],
            'supplied':{'claims':['A declared glyph correspondence.'],'entities':['square','circle'],'limits':['mode A']}}
        if typ!='scope':self.question['target_ref']['line_id']='e_panel'
        self.request={'schema':'ohf-question-context/1','made_at':T(5),'card':{},'sources':self.sources,'questions':[self.question]}
        self.sync()

    def binding(self,key):
        source=next(s for s in self.sources if s['key']==key)
        return {k:deepcopy(source[k]) for k in ('key','work','sha256','retrieved_at')}

    def context(self,source_ref,role,sentences=None):
        record=self.card['added']['sources'][source_ref]
        key=next(k for k,d in self.docs.items() if d.url==record['source'])
        doc=self.docs[key];n=int(record['locator'].split('.//p[')[1].split(']')[0]);paragraph=doc.para(n)
        numbers=[] if sentences is None else sentences
        split=ohfkit.sentences_of(paragraph);selected=' '.join(split[i-1] for i in numbers) if numbers else paragraph
        return {'role':role,'source':self.binding(key),'native_source_ref':source_ref,
                'locator':{'paragraph':n,'sentences':numbers,'paragraph_sha256':ohfkit.sha256(paragraph.encode()),
                           'selection_sha256':ohfkit.sha256(selected.encode())},
                'state':'complete','read_at':T(3),'reason':'Invented declared selection, not a scientific relevance verdict.'}

    def sync(self):
        for name,raw in self.raws.items():(self.root/name).write_bytes(raw)
        raw=DUMP(self.card);(self.root/'card.json').write_bytes(raw)
        self.request['card']={'file':'card.json','sha256':qc.grounds.sha(raw)}
        (self.root/'request.json').write_bytes(DUMP(self.request));return self.root/'request.json'

    def rehash_card(self):
        self.owner['card_sha256']=qc.grounds.sha(DUMP(self.card))
        for source in self.sources:source['owner']=deepcopy(self.owner)
        for q in self.request['questions']:
            q['target_ref']['owner']=deepcopy(self.owner);q['anchor_ref']['owner']=deepcopy(self.owner)
            for key in ('target_ref','anchor_ref'):
                try:q[key]['value_sha256']=qc.value_hash(qc.grounds.pointer(self.card,q[key]['pointer']))
                except qc.grounds.GroundError:pass
        return self.sync()

    def check(self):return checked(self.sync())


def checked(path):
    result=qc.check(path)
    Draft202012Validator({'$ref':'#/$defs/diagnostic','$defs':qc.SCHEMA['$defs']}).validate(result)
    return result


def test_old_ledger_source_binding_refuses_in_question_context(tmp_path, monkeypatch):
    fixture = Fixture(tmp_path, 'scope')
    before = fixture.check()
    assert before['status'] == 'grounded_input_contract_only'
    source_before = (qc.ROOT / 'scripts/check_ledger.py').read_bytes()
    old_pin = 'sha256:50d814ea60e399edf16af71a1f304be662ef9cf6aa86c2ca3aa3ea87d38a314e'
    assert qc.grounds.sha(source_before) == qc.NATIVE_PINS['check_ledger.py'] != old_pin
    with monkeypatch.context() as patch:
        patch.setitem(qc.NATIVE_PINS, 'check_ledger.py', old_pin)
        result = fixture.check()
        assert result['status'] == 'cannot_assess'
        assert 'NATIVE_PIN' in codes(result)
        assert all(question['packet'] is None for question in result['questions'])
    assert (qc.ROOT / 'scripts/check_ledger.py').read_bytes() == source_before
    assert fixture.check()['status'] == 'grounded_input_contract_only'


def codes(result):return {i['code'] for i in result['issues']} | {i['code'] for q in result['questions'] for i in q['issues']}


def first(result):
    assert result['questions'],result
    return result['questions'][0]


@pytest.mark.parametrize('typ',['scope','direction','indirectness'])
def test_each_question_type_has_true_context_target_and_no_scientific_verdict(tmp_path,typ):
    f=Fixture(tmp_path,typ);before=(tmp_path/'card.json').read_bytes()
    result=f.check();q=first(result);packet=q['packet']
    assert result['status']==q['status']=='grounded_input_contract_only'
    assert packet['question_type']==typ and packet['instruction']==qc.INSTRUCTIONS[typ]
    assert packet['target_claim']==f.card['added']['layers']['core']['atoms'][0]['statement']['value']
    assert packet['supplied_unverified']==f.question['supplied']
    assert packet['scientific_adequacy_verified'] is False and packet['entailment_verdict'] is None
    assert len(packet['context'])>=2 and (tmp_path/'card.json').read_bytes()==before
    if typ!='scope':
        assert packet['native_checked_value']['target_statement']==packet['target_claim']
        assert 'line_quote' in packet['native_checked_value']


@pytest.mark.parametrize('state',['unknown','unavailable','partial','not_supplied'])
def test_unknown_and_unavailable_not_positive(tmp_path,state):
    f=Fixture(tmp_path);f.question['state']=state
    q=first(f.check());assert q['status']=='cannot_assess' and q['basis_state']==state and q['packet'] is None


@pytest.mark.parametrize('which',['target_ref','anchor_ref','context'])
def test_missing_target_or_context_cannot_assess(tmp_path,which):
    f=Fixture(tmp_path);f.question.pop(which)
    result=f.check();assert result['status']=='cannot_assess'
    assert codes(result)&{'TARGET_MISSING','CONTEXT_MISSING'}


@pytest.mark.parametrize('mode',['same','alias','split','paragraph_vs_sentence'])
def test_aliases_and_same_paragraph_splits_cannot_game_count(tmp_path,mode):
    f=Fixture(tmp_path)
    f.card['added']['sources']['m_alias']=deepcopy(f.card['added']['sources']['m1'])
    if mode=='same':second=f.context('m1','property',[1])
    elif mode=='alias':second=f.context('m_alias','property',[1])
    elif mode=='split':second=f.context('m1','property',[2])
    else:second=f.context('m1','property')
    f.question['context'][1]=second;f.rehash_card()
    result=f.check();assert result['status']=='cannot_assess'
    assert codes(result)&{'DUPLICATE_LOCATOR','CONTEXT_PARAGRAPH_MINIMUM'}


@pytest.mark.parametrize('mode',['copy','doi_alias','symlink','hardlink'])
def test_cloned_or_aliased_source_files_do_not_add_context(tmp_path,mode):
    f=Fixture(tmp_path);source=deepcopy(f.sources[0]);source['key']='doc:alias';source['file']='alias.xml'
    if mode=='symlink':(tmp_path/'alias.xml').symlink_to(tmp_path/'PMC810001.xml')
    elif mode=='hardlink':os.link(tmp_path/'PMC810001.xml',tmp_path/'alias.xml')
    else:(tmp_path/'alias.xml').write_bytes(f.raws['PMC810001.xml'])
    if mode=='doi_alias':source['work']={'namespace':'doi','value':'10.9999/glyph-main'}
    f.sources.append(source)
    result=f.check();assert result['status']=='cannot_assess'
    assert codes(result)&{'SOURCE_ALIAS','ARTIFACT_SYMLINK','ARTIFACT_TYPE'}


@pytest.mark.parametrize('where',['target','anchor','source'])
def test_foreign_card_owner_not_rescued_by_global_source_pool(tmp_path,where):
    f=Fixture(tmp_path)
    owner=f.question['target_ref']['owner'] if where=='target' else f.question['anchor_ref']['owner'] if where=='anchor' else f.sources[0]['owner']
    owner['card_id']='h_foreign'
    assert 'FOREIGN_OWNER' in codes(f.check())


@pytest.mark.parametrize('where',['target_value','checked_value','anchor_value','source_hash','source_version','source_work'])
def test_stale_or_wrong_target_bindings_fail(tmp_path,where):
    f=Fixture(tmp_path,'direction')
    if where=='target_value':f.question['target_ref']['value_sha256']=qc.grounds.sha(b'wrong')
    elif where=='checked_value':f.question['target_ref']['native_checked_sha256']=qc.grounds.sha(b'wrong')
    elif where=='anchor_value':f.question['anchor_ref']['value_sha256']=qc.grounds.sha(b'wrong')
    elif where=='source_hash':f.question['target_ref']['source']['sha256']=qc.grounds.sha(b'wrong')
    elif where=='source_version':f.question['target_ref']['source']['retrieved_at']=T(1)
    else:f.question['target_ref']['source']['work']['value']='PMC999999'
    assert codes(f.check())&{'TARGET_VALUE_HASH','CHECKED_VALUE_HASH','ANCHOR_VALUE','SOURCE_BINDING'}


@pytest.mark.parametrize('mode,code', [('wrong_kind','TARGET_TYPE'),('wrong_line_id','TARGET_LINE_ID'),
 ('dangling','ARTIFACT_UNUSED'),('wrong_atom','TARGET_ANCHOR'),('duplicate_atom','AMBIGUOUS_TARGET'),
 ('blank_scope','SCOPE_VALUE'),('bad_direction','DIRECTION_VALUE'),('unknown_indirectness','INDIRECTNESS_UNKNOWN'),
 ('missing_item','LINE_WORK_VERSION')])
def test_exact_question_target_conditioning_not_isolated_value(tmp_path,mode,code):
    typ='scope' if mode=='blank_scope' else 'indirectness' if mode=='unknown_indirectness' else 'direction'
    f=Fixture(tmp_path,typ);line=f.card['added']['layers']['evidence']['lines'][0]
    if mode=='wrong_kind':f.question['target_ref']['kind']='scope_field'
    elif mode=='wrong_line_id':f.question['target_ref']['line_id']='e_foreign'
    elif mode=='dangling':f.question['target_ref']['pointer']='/added/layers/evidence/lines/99/direction';code='CARD_POINTER'
    elif mode=='wrong_atom':line['target_ref']['value']='a_other'
    elif mode=='duplicate_atom':f.card['added']['layers']['core']['atoms'].append(deepcopy(f.card['added']['layers']['core']['atoms'][0]))
    elif mode=='blank_scope':f.card['added']['layers']['core']['scope']['value']=' '
    elif mode=='bad_direction':line['direction']['value']='sounds supportive'
    elif mode=='unknown_indirectness':line['indirectness']['value']['system']='unknown'
    else:line['items']=[]
    f.rehash_card();assert code in codes(f.check())


@pytest.mark.parametrize('value',[True,1.0,0,-1,999,'1'])
@pytest.mark.parametrize('field',['paragraph','sentence'])
def test_locator_indices_are_strict_actual_native_integers(tmp_path,value,field):
    f=Fixture(tmp_path)
    loc=f.question['context'][0]['locator']
    if field=='paragraph':loc['paragraph']=value
    else:loc['sentences']=[value]
    result=f.check();assert result['status']=='cannot_assess'
    assert codes(result)&{'CONTRACT_SHAPE','LOCATOR_INTEGER','CONTEXT_PARAGRAPH','CONTEXT_SENTENCES'}


@pytest.mark.parametrize('mode',['context_hash','native_alias','role','read_time','context_state','source_state','namespace'])
def test_source_role_locator_time_and_completeness_are_not_implicit(tmp_path,mode):
    f=Fixture(tmp_path,'direction');context=f.question['context'][1]
    if mode=='context_hash':context['locator']['selection_sha256']=qc.grounds.sha(b'wrong')
    elif mode=='native_alias':f.card['added']['sources']['s1']['locator']='paragraph 1';f.rehash_card()
    elif mode=='role':context['role']='claim'
    elif mode=='read_time':context['read_at']=T(9)
    elif mode=='context_state':context['state']='partial'
    elif mode=='source_state':f.sources[1]['state']='unknown'
    else:context['source']['work']['namespace']='pmid'
    result=f.check();assert result['status']=='cannot_assess'
    assert codes(result)&{'CONTEXT_HASH','NATIVE_LOCATOR','CONTEXT_ROLE','CONTEXT_TIME','CONTEXT_STATE','SOURCE_NOT_COMPLETE','CONTRACT_SHAPE'}


def test_duplicate_paragraph_text_at_distinct_indices_is_not_diverse_context(tmp_path):
    f=Fixture(tmp_path)
    f.docs['doc:claim'].paragraphs[1]=f.docs['doc:claim'].paragraphs[0]
    # Change only invented XML, repin source/card/owners explicitly; two indices still same normalized text.
    raw=f.raws['PMC810001.xml'].replace(b'The mapping is stated only for mode A. Mode B remains an open question.',f.docs['doc:claim'].para(1).encode())
    digest=qc.grounds.sha(raw);f.raws['PMC810001.xml']=raw;f.sources[0]['sha256']=digest
    f.card['author']['source']['source_text_sha256']=digest
    f.question['target_ref']['source']['sha256']=digest;f.question['anchor_ref']['source']['sha256']=digest
    f.question['context']=[f.context('m1','claim',[1]),f.context('m2','property')]
    f.rehash_card();assert 'CONTEXT_PARAGRAPH_MINIMUM' in codes(f.check())


@pytest.mark.parametrize('typ',['scope','direction','indirectness'])
def test_pinned_pure_native_producer_seam(tmp_path,typ):
    f=Fixture(tmp_path,typ);pure=qc.native_helpers();doc=f.docs['doc:claim']
    assert pure.sentences_of(doc.para(1))==ohfkit.sentences_of(doc.para(1))
    assert len(pure.sentences_of(doc.para(1)))==2  # Dr. is not its own sentence.
    assert len(pure.sentences_of(doc.para(3)))==2  # Closing quote ends the sentence.
    result=f.check();packet=first(result)['packet']
    target=f.question['target_ref'];node=qc.grounds.pointer(f.card,target['pointer'])
    assert packet['native_checked_value']==check_ledger.checked_value(f.card,target['pointer'],node)
    assert f.card['added']['sources']['m1']==doc.src(1)
    assert packet['context'][0]['locator']['native']==doc.locator(1)


def test_parent_one_passage_capability_is_preserved_but_not_new_context_minimum(tmp_path):
    f=Fixture(tmp_path,'direction');target=f.question['target_ref'];node=qc.grounds.pointer(f.card,target['pointer'])
    old=check_ledger.checked_value(f.card,target['pointer'],node)
    assert 'target_statement' in old and 'line_quote' in old
    f.question['context']=f.question['context'][:1]
    assert 'CONTEXT_MISSING' in codes(f.check())
    assert check_ledger.checked_value(f.card,target['pointer'],node)==old


@pytest.mark.parametrize('value',[True,1.0])
def test_card_version_owner_does_not_coerce_bool_or_float(tmp_path,value):
    f=Fixture(tmp_path);f.question['target_ref']['owner']['card_version']=value
    assert codes(f.check())&{'FOREIGN_OWNER','CONTRACT_SHAPE'}


def test_closed_cli_bad_paths_and_arguments(tmp_path,capsys):
    f=Fixture(tmp_path)
    assert qc.main([str(tmp_path/'request.json')])==0
    checked_output=json.loads(capsys.readouterr().out)
    Draft202012Validator({'$ref':'#/$defs/diagnostic','$defs':qc.SCHEMA['$defs']}).validate(checked_output)
    assert qc.main([str(tmp_path/'bad\x00path')])==1
    assert 'ARTIFACT_PATH' in codes(json.loads(capsys.readouterr().out))
    assert qc.main([])==2
    assert 'CLI_ARGUMENTS' in codes(json.loads(capsys.readouterr().out))
    assert qc.main(['--unknown',str(tmp_path/'request.json')])==2
    assert 'CLI_ARGUMENTS' in codes(json.loads(capsys.readouterr().out))


def test_no_free_prompt_or_substring_question_can_replace_type_contract(tmp_path):
    f=Fixture(tmp_path,'direction');f.question['prompt']='Is the quote a substring?'
    assert 'CONTRACT_SHAPE' in codes(f.check())


@pytest.mark.parametrize('mode,code',[('quote','LINE_FINDING_SOURCE'),('choice_source','NATIVE_TARGET_SOURCE'),('legacy_string',None)])
def test_actual_native_finding_and_target_choice_are_bound(tmp_path,mode,code):
    f=Fixture(tmp_path,'direction');line=f.card['added']['layers']['evidence']['lines'][0]
    if mode=='quote':line['quote']='Words from no bound glyph passage.'
    elif mode=='choice_source':line['target_ref']['src']='foreign_key'
    else:line['target_ref']='a_glyph'
    f.rehash_card()
    if code:assert code in codes(f.check())
    else:assert first(f.check())['status']=='grounded_input_contract_only'


@pytest.mark.parametrize('name',['card.json','PMC810001.xml','PMC810002.xml'])
def test_actual_pinned_file_hash_drift_cannot_be_rescued(tmp_path,name):
    f=Fixture(tmp_path,'direction');path=f.sync()
    with (tmp_path/name).open('ab') as stream:stream.write(b' ')
    assert 'HASH_DRIFT' in codes(checked(path))


def test_unavailable_source_and_native_pin_failure_are_closed(tmp_path,monkeypatch):
    f=Fixture(tmp_path);path=f.sync();(tmp_path/'PMC810001.xml').unlink()
    assert 'ARTIFACT_UNAVAILABLE' in codes(checked(path))
    f.sync()
    monkeypatch.setitem(qc.NATIVE_PINS,'ohfkit.py',qc.grounds.sha(b'foreign native code'))
    assert 'NATIVE_PIN' in codes(f.check())


def test_missing_conditions_remain_supplied_empty_not_inferred_from_passages(tmp_path):
    f=Fixture(tmp_path,'scope');f.question['supplied']={'claims':[],'entities':[],'limits':[]}
    packet=first(f.check())['packet']
    assert packet['supplied_unverified']=={'claims':[],'entities':[],'limits':[]}
    assert packet['scientific_adequacy_verified'] is False


def encoded_source(f, index, encoding):
    source=f.sources[index];name=source['file']
    text=f.raws[name].decode('utf-8')
    declared='<?xml version="1.0" encoding="'+encoding+'"?>'+text
    raw=declared.encode('utf-8' if encoding=='not-a-codec' else encoding)
    f.raws[name]=raw;digest=qc.grounds.sha(raw);source['sha256']=digest
    if source['role']=='main':f.card['author']['source']['source_text_sha256']=digest
    for ref in (f.question['target_ref'],f.question['anchor_ref'],*f.question['context']):
        if ref['source']['key']==source['key']:ref['source']['sha256']=digest
    return f.rehash_card()


@pytest.mark.parametrize('index',[0,1])
@pytest.mark.parametrize('entry',['check','CLI'])
@pytest.mark.parametrize('encoding',['not-a-codec','utf-8','utf-16'])
def test_xml_encoding_source_boundary_is_closed_and_supported_encodings_work(tmp_path,capsys,index,entry,encoding):
    f=Fixture(tmp_path);path=encoded_source(f,index,encoding)
    if entry=='check':result=checked(path)
    else:
        exit_code=qc.main([str(path)]);result=json.loads(capsys.readouterr().out)
        qc.shape(result,'diagnostic')
        assert exit_code==(1 if encoding=='not-a-codec' else 0)
    if encoding=='not-a-codec':
        assert result['status']=='cannot_assess' and first(result)['basis_state']=='unavailable'
        assert first(result)['packet'] is None and codes(result)=={'SOURCE_XML'}
        assert result['issues']==[{'code':'SOURCE_XML','detail':'LookupError'}]
    else:
        assert result['status']=='grounded_input_contract_only'
        assert first(result)['packet']['scientific_adequacy_verified'] is False
        assert first(result)['packet']['entailment_verdict'] is None


@pytest.mark.parametrize('entry',['check','CLI'])
def test_unrelated_lookup_error_outside_source_parser_is_not_swallowed(tmp_path,monkeypatch,entry):
    f=Fixture(tmp_path)
    def unexpected():raise LookupError('unrelated runtime failure')
    monkeypatch.setattr(qc,'native_helpers',unexpected)
    with pytest.raises(LookupError,match='unrelated runtime failure'):
        if entry=='check':qc.check(f.sync())
        else:qc.main([str(f.sync())])


def test_pre_quote_alignment_ledger_pin_is_refused(tmp_path, monkeypatch):
    fixture = Fixture(tmp_path, 'scope')
    old_pin = 'sha256:6e68de493a203587b5a11fe215eb8d27fc7698da2b388ad4d1ca1d6cd3c05b5b'
    assert fixture.check()['status'] == 'grounded_input_contract_only'
    assert qc.NATIVE_PINS['check_ledger.py'] != old_pin
    with monkeypatch.context() as patch:
        patch.setitem(qc.NATIVE_PINS, 'check_ledger.py', old_pin)
        result = fixture.check()
        assert result['status'] == 'cannot_assess'
        assert 'NATIVE_PIN' in codes(result)
        assert all(question['packet'] is None for question in result['questions'])
    assert fixture.check()['status'] == 'grounded_input_contract_only'


@pytest.mark.parametrize('name', ['ohfkit', 'check_ledger'])
def test_native_fixture_source_matches_declared_pin(name):
    module = {'ohfkit': ohfkit, 'check_ledger': check_ledger}[name]
    actual = module._fixture_source_sha256
    assert actual == qc.NATIVE_PINS[name + '.py'], 'Native fixture source differs: ' + name


def test_pre_catalogue_filter_ledger_pin_is_refused(tmp_path, monkeypatch):
    fixture = Fixture(tmp_path, 'scope')
    old_pin = 'sha256:37cc4d4ec802d0f7c9d96f2af4706ad63dcdd42bfa5d71ed17825eae03695c57'
    assert fixture.check()['status'] == 'grounded_input_contract_only'
    assert qc.NATIVE_PINS['check_ledger.py'] != old_pin
    with monkeypatch.context() as patch:
        patch.setitem(qc.NATIVE_PINS, 'check_ledger.py', old_pin)
        result = fixture.check()
        assert result['status'] == 'cannot_assess'
        assert 'NATIVE_PIN' in codes(result)
        assert all(question['packet'] is None for question in result['questions'])
    assert fixture.check()['status'] == 'grounded_input_contract_only'


@pytest.mark.parametrize('name', ['ohfkit', 'check_ledger'])
def test_native_fixture_pin_check_covers_the_loaded_snapshot(monkeypatch, name):
    module = {'ohfkit': ohfkit, 'check_ledger': check_ledger}[name]
    path = Path(module.__file__)
    assert 'sha256:' + hashlib.sha256(path.read_bytes()).hexdigest() == qc.NATIVE_PINS[name + '.py']
    monkeypatch.setattr(module, '_fixture_source_sha256', 'sha256:' + '0' * 64)
    with pytest.raises(AssertionError, match='Native fixture source differs: ' + name):
        test_native_fixture_source_matches_declared_pin(name)


@pytest.mark.parametrize('changed_name', ['ohfkit', 'check_ledger'])
def test_native_pin_drift_is_a_test_failure_without_aborting_collection(tmp_path, changed_name):
    import shutil
    import subprocess
    import sys

    root = Path(__file__).resolve().parents[2]
    copied = tmp_path / 'invented-source-drift'
    scripts = copied / 'scripts'
    tests = scripts / 'tests'
    tests.mkdir(parents=True)
    # Only source code and its reference files: no article/card/fixture payloads.
    for path in (root / 'scripts').glob('*.py'):
        shutil.copyfile(path, scripts / path.name)
    shutil.copytree(root / 'references', copied / 'references')
    shutil.copyfile(root / 'SKILL.md', copied / 'SKILL.md')
    shutil.copyfile(Path(__file__), tests / Path(__file__).name)
    (copied / 'pytest.ini').write_text('[pytest]\n')
    (tests / 'test_collection_sibling.py').write_text(
        'def test_collection_sibling_still_runs():\n    assert 1 + 1 == 2\n')
    child_code = '''import json, os, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
guards = dict(network=0, process=0, auth=0)
def audit(event, args):
    if event.startswith('socket.'):
        guards['network'] += 1
        raise RuntimeError('COLLECTION_REGRESSION_NETWORK_REFUSED')
    if event in ('subprocess.Popen', 'os.system', 'os.posix_spawn', 'os.posix_spawnp', 'os.fork', 'os.exec'):
        guards['process'] += 1
        raise RuntimeError('COLLECTION_REGRESSION_PROCESS_REFUSED')
    if event == 'open' and isinstance(args[0], (str, bytes)):
        name = os.fsdecode(args[0])
        if any(part in name for part in ('/.config/forgejo/', '/.codex/auth', '/.claude/.credentials')):
            guards['auth'] += 1
            raise RuntimeError('COLLECTION_REGRESSION_AUTH_REFUSED')
sys.addaudithook(audit)
import pytest
status = pytest.main(sys.argv[2:])
print('COLLECTION_REGRESSION_GUARDS ' + json.dumps(guards))
raise SystemExit(status if not any(guards.values()) else 99)
'''
    command = [sys.executable, '-I', '-B', '-c', child_code, str(scripts),
               '-vv', '--noconftest', '-p', 'no:cacheprovider', '-o', 'addopts=',
               str(tests / Path(__file__).name), str(tests / 'test_collection_sibling.py'),
               '-k', 'native_fixture_source_matches_declared_pin or collection_sibling_still_runs']
    env = {**os.environ, 'PYTEST_DISABLE_PLUGIN_AUTOLOAD': '1', 'PYTHONDONTWRITEBYTECODE': '1'}
    before = subprocess.run(command, cwd=copied, env=env, capture_output=True, text=True, timeout=30)
    assert before.returncode == 0, before.stdout + before.stderr
    assert '3 passed' in before.stdout
    changed = scripts / (changed_name + '.py')
    changed.write_bytes(changed.read_bytes() + b'\n# Invented harmless source drift.\n')
    after = subprocess.run(command, cwd=copied, env=env, capture_output=True, text=True, timeout=30)
    output = after.stdout + after.stderr
    assert after.returncode == 1, output
    assert '1 failed, 2 passed' in output
    assert f'test_native_fixture_source_matches_declared_pin[{changed_name}] FAILED' in output
    assert 'test_collection_sibling_still_runs PASSED' in output
    assert 'ERROR collecting' not in output and 'Interrupted' not in output
    for result in (before, after):
        line = next(line for line in result.stdout.splitlines()
                    if line.startswith('COLLECTION_REGRESSION_GUARDS '))
        assert json.loads(line.split(' ', 1)[1]) == dict(network=0, process=0, auth=0)


def test_pre_packaging_contract_ledger_pin_is_refused(tmp_path, monkeypatch):
    fixture = Fixture(tmp_path, 'scope')
    old_pin = 'sha256:d19f9c2c497e1b593ed0f4564aba81bdf3b645689f9da898819f00af848463dc'
    assert fixture.check()['status'] == 'grounded_input_contract_only'
    with monkeypatch.context() as patch:
        patch.setitem(qc.NATIVE_PINS, 'check_ledger.py', old_pin)
        result = fixture.check()
        assert result['status'] == 'cannot_assess'
        assert 'NATIVE_PIN' in codes(result)
        assert all(question['packet'] is None for question in result['questions'])
    assert fixture.check()['status'] == 'grounded_input_contract_only'


@pytest.mark.parametrize('missing', ['OHF_REPO', 'adapter', 'empty_OHF_REPO'])
def test_1_4_direction_records_missing_reader_refusal(tmp_path, monkeypatch, missing):
    fixture = Fixture(tmp_path / 'question', 'direction')
    assert fixture.check()['status'] == 'grounded_input_contract_only'
    fixture.card['standard_version'] = '1.4'
    fixture.rehash_card()
    # native_helpers still compiles and verifies both complete native sources.
    # Only the adjacent adapter is absent in this invented packaging copy.
    if missing == 'adapter':
        root = tmp_path / 'incomplete-kit'
        (root / 'scripts').mkdir(parents=True)
        for name in qc.NATIVE_PINS:
            (root / 'scripts' / name).write_bytes((qc.ROOT / 'scripts' / name).read_bytes())
        monkeypatch.setattr(qc, 'ROOT', root)
        monkeypatch.setenv('OHF_REPO', str(tmp_path / 'explicit-source'))
    elif missing == 'empty_OHF_REPO':
        monkeypatch.setenv('OHF_REPO', '')
    else:
        monkeypatch.delenv('OHF_REPO', raising=False)
    before = (fixture.root / 'card.json').read_bytes()
    result = fixture.check()
    question = first(result)
    assert result['status'] == question['status'] == 'cannot_assess'
    assert result['issues'] == []
    assert question['basis_state'] == 'invalid_binding' and question['packet'] is None
    assert question['issues'] == [{'code': 'NATIVE_TARGET', 'detail': 'PinnedReaderRequired'}]
    assert (fixture.root / 'card.json').read_bytes() == before


def test_pre_metadata_coverage_ledger_pin_is_refused(tmp_path, monkeypatch):
    fixture = Fixture(tmp_path, 'scope')
    old_pin = 'sha256:682e4b9e82148ce1dcf7b08680bbd4fadbaf3ed9c0537989b3c13386a07b9991'
    assert fixture.check()['status'] == 'grounded_input_contract_only'
    assert qc.NATIVE_PINS['check_ledger.py'] != old_pin
    with monkeypatch.context() as patch:
        patch.setitem(qc.NATIVE_PINS, 'check_ledger.py', old_pin)
        result = fixture.check()
        assert result['status'] == 'cannot_assess'
        assert 'NATIVE_PIN' in codes(result)
        assert all(question['packet'] is None for question in result['questions'])
    assert fixture.check()['status'] == 'grounded_input_contract_only'
