"""Build a typed question/context packet OFFLINE. Structural grounding is not scientific adequacy.

No native CLI, inference, schema migration or changes to ordinary per-value ENT inputs/ledgers.
Only explicit pinned local artifacts are read. The shared negative-grounds implementation is unchanged.
"""
import argparse
import ast
import copy
import json
import os
from pathlib import Path
import re
import types
import xml.etree.ElementTree as ET

from jsonschema import Draft202012Validator
import negative_grounds as grounds

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / 'references/question-context.schema.json'
SCHEMA = grounds.strict_json(SCHEMA_PATH.read_bytes())
NATIVE_PINS = {'ohfkit.py': 'sha256:05795fa3ebc6f0880d2c679a193384facdeff60f8d071241868442ef7b6c391b',
               'check_ledger.py': 'sha256:b0ee463cf3bc74951a2b75ddc6f98d3be05dc718eb016a3d683d1a4f2ad99711'}
INSTRUCTIONS = {
 'scope': 'Assess the proposed scope for this exact claim using the supplied multi-paragraph context. Preserve stated restrictions; do not infer missing conditions or reduce this to quote occurrence.',
 'direction': 'Assess the correspondence of this selected finding to this exact target claim and proposed direction, using the supplied multi-paragraph context. Do not answer whether an isolated quotation is a substring or whether the whole paragraph sounds supportive.',
 'indirectness': 'Assess the distance between this study/finding and this exact target claim in system, endpoint, intervention and comparison, using the supplied multi-paragraph context. Do not substitute imprecision or quote occurrence for indirectness.',
}
LIMITS = [
 'grounded_input_contract_only is not entails, scientific adequacy, source completeness, direction truth, indirectness validity or wholecard acceptance.',
 'Reading, source completeness, selection relevance and supplied claims/entities/limits are unauthenticated attestations.',
 'Two distinct actual paragraphs and distinct normalized paragraph texts are a structural minimum, not a semantic sufficiency certificate.',
 'Only added core scope, added evidence direction/indirectness and added atom anchors in pinned unnamespaced main/evidence JATS are supported.',
 'Only explicit claim/property source roles are supported; no global context pool, implicit work aliases or automatic old-input repacking.',
 'Standalone packet only: current native per-value producer/schema/821 items/prompts/batches/ledgers remain unchanged.',
]


def fail(ok, code, detail, basis='invalid_binding'):
    if not ok:
        raise grounds.GroundError(code, detail, basis)


def value_hash(value):
    try:
        return grounds.sha(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode())
    except (UnicodeError, ValueError) as error:
        raise grounds.GroundError('VALUE_ENCODING', type(error).__name__) from error


def shape(value, name):
    errors = Draft202012Validator({'$ref':'#/$defs/'+name,'$defs':SCHEMA['$defs']}).iter_errors(value)
    error = next(errors, None)
    fail(error is None, 'CONTRACT_SHAPE', name + ': ' + (str(list(error.absolute_path))+' violates '+str(error.validator) if error else ''))
    return value


def native_helpers():
    """Compile exact pinned source, no ambient pyc and no native I/O constructor."""
    document = types.SimpleNamespace()
    namespace = {'re':re}
    constants = {'LOCATOR','EPMC','ABBREVIATIONS','_CLOSERS','_OPENERS'}
    functions = {'norm','_token_before','sentence_ends','sentences_of','whole_sentences'}
    methods = {'para','locator','src','item','check','check_sentences','author'}
    for name, expected in NATIVE_PINS.items():
        raw = (ROOT/'scripts'/name).read_bytes()
        fail(grounds.sha(raw) == expected, 'NATIVE_PIN', name)
        if name == 'ohfkit.py':
            nodes = []
            for node in ast.parse(raw).body:
                if isinstance(node, ast.FunctionDef) and node.name in functions:
                    nodes.append(node)
                elif isinstance(node, ast.Assign) and any(isinstance(t,ast.Name) and t.id in constants for t in node.targets):
                    nodes.append(node)
                elif isinstance(node, ast.ClassDef) and node.name == 'Document':
                    subset = [n for n in node.body if (isinstance(n,ast.FunctionDef) and n.name in methods) or isinstance(n,ast.Assign)]
                    nodes.append(ast.ClassDef(name='Document', bases=[], keywords=[], body=subset, decorator_list=[]))
            exec(compile(ast.fix_missing_locations(ast.Module(body=nodes,type_ignores=[])),str(ROOT/'scripts'/name),'exec'),namespace)
        else:
            module = types.ModuleType('context_native_checked_value');module.__file__=str(ROOT/'scripts'/name)
            exec(compile(raw,module.__file__,'exec'),module.__dict__)
            document.checked_value = module.checked_value
            document.target_statement = module.target_statement
    for name in ('Document','norm','sentences_of','LOCATOR','EPMC'):
        setattr(document,name,namespace[name])
    return document


def owner_of(card, reference):
    fail(isinstance(card,dict) and card.get('schema')=='ohf:hypothesis@1' and
         isinstance(card.get('id'),str) and card['id'].strip() and grounds.number(card.get('version'),1),
         'CARD_ID','Native card id/version required')
    identity=card.get('identity',{})
    fail(isinstance(identity,dict) and (not identity or (identity.get('proposition_id')==card['id'] and
         type(identity.get('version')) is int and identity['version']==card['version'])), 'CARD_ID','Contradictory identity')
    added=card.get('added')
    fail(isinstance(added,dict) and isinstance(added.get('sources'),dict) and isinstance(added.get('layers'),dict),
         'CARD_SHAPE','Native added sources/layers required')
    core=added['layers'].get('core')
    fail(isinstance(core,dict) and isinstance(core.get('atoms'),list),'CARD_SHAPE','Added atoms required')
    return {'card_id':card['id'],'card_version':card['version'],'card_sha256':reference['sha256']}


def check_owner(owner, expected):
    shape(owner,'owner')
    fail(type(owner['card_version']) is int and owner==expected, 'FOREIGN_OWNER','Exact card id/version/byte hash required')


def source_document(bundle, source, card, owner, native, made):
    check_owner(source['owner'],owner)
    grounds.source_id(source['work'])
    retrieved=grounds.instant(source['retrieved_at'])
    fail(retrieved<=made,'SOURCE_TIME',source['key'])
    raw=bundle.pinned(source)
    try:root=ET.fromstring(raw,parser=ET.XMLParser(target=grounds.NoDeclarations()))
    except (ET.ParseError, LookupError) as error:
        # ElementTree reports an unknown declared XML encoding as LookupError.
        raise grounds.GroundError('SOURCE_XML',type(error).__name__,'unavailable') from error
    fail(root.tag=='article','SOURCE_FORMAT','Unnamespaced JATS only','unavailable')
    ids={}
    for el in root.findall('./front/article-meta/article-id'):
        kind=el.get('pub-id-type');value=''.join(el.itertext()).strip()
        if kind=='pmc':kind,value='pmcid',value if value.startswith('PMC') else 'PMC'+value
        if kind not in ('pmcid','doi'):continue
        fail(kind not in ids or ids[kind]==value,'SOURCE_ID_CONFLICT',source['key'])
        grounds.source_id({'namespace':kind,'value':value})
        ids[kind]=value
    fail(ids.get(source['work']['namespace'])==source['work']['value'] and 'pmcid' in ids,
         'SOURCE_ID','Exact source namespace/value and native PMCID required')
    doc=native.Document.__new__(native.Document)
    doc.pmcid=ids['pmcid'];doc.url=native.EPMC.format(doc.pmcid);doc.file=doc.pmcid+'.xml'
    doc.sha=source['sha256'];doc.retrieved=source['retrieved_at'];doc.root=root
    doc.paragraphs=[native.norm(''.join(p.itertext())) for p in root.iter('p')]
    fail(doc.paragraphs,'SOURCE_EMPTY',source['key'],'unavailable')
    records=card.get('added',{}).get('sources',{})
    fail(isinstance(records,dict) and any(isinstance(r,dict) and r.get('source')==doc.url and
         r.get('accessed_at')==doc.retrieved for r in records.values()),'SOURCE_NOT_CARD_OWNED',source['key'])
    if source['role']=='main':
        author=card.get('author',{});main=author.get('source',{}) if isinstance(author,dict) else {}
        fail(isinstance(main,dict) and main.get('source_text_sha256')==doc.sha and
             main.get('retrieved_at')==doc.retrieved and main.get('doi')==ids.get('doi') and 'doi' in ids,
             'MAIN_SOURCE','Main card DOI/hash/version must match')
    return {'source':source,'doc':doc,'ids':set(ids.items())}


def binding(ref, sources, owner):
    shape(ref,'binding')
    fail(ref['key'] in sources,'SOURCE_REFERENCE',ref['key'])
    value=sources[ref['key']]
    src=value['source']
    fail(ref=={k:src[k] for k in ('key','work','sha256','retrieved_at')},'SOURCE_BINDING',ref['key'])
    check_owner(src['owner'],owner)
    fail(src['state']=='complete','SOURCE_NOT_COMPLETE',src['state'],src['state'])
    return value


def native_record(card,key,source,native):
    records=card.get('added',{}).get('sources',{})
    fail(isinstance(key,str) and key.strip() and isinstance(records,dict) and key in records,
         'NATIVE_SOURCE_REF','Source key must exist in this card')
    record=records[key];doc=source['doc']
    fail(isinstance(record,dict) and record.get('source')==doc.url and record.get('accessed_at')==doc.retrieved,
         'NATIVE_SOURCE_BINDING',key)
    match=re.fullmatch(re.escape(native.LOCATOR).replace(re.escape('{}'),r'([1-9][0-9]*)'),str(record.get('locator','')))
    fail(match is not None,'NATIVE_LOCATOR',key)
    number=int(match[1]);fail(1<=number<=len(doc.paragraphs),'NATIVE_PARAGRAPH',key)
    fail(record==doc.src(number),'NATIVE_SOURCE_SHAPE',key)
    return number


def anchor_value(card,ref,sources,owner,native):
    shape(ref,'anchor');check_owner(ref['owner'],owner)
    fail(re.fullmatch(r'/added/layers/core/atoms/(0|[1-9][0-9]*)',ref['pointer']), 'ANCHOR_TYPE','Only added atom anchors supported')
    node=grounds.pointer(card,ref['pointer'])
    fail(isinstance(node,dict) and node.get('id')==ref['id'] and value_hash(node)==ref['value_sha256'],
         'ANCHOR_VALUE','ID/value hash mismatch')
    layers=card.get('added',{}).get('layers',{})
    atoms=layers.get('core',{}).get('atoms',[]);predictions=layers.get('predictions',[])
    fail(isinstance(atoms,list) and isinstance(predictions,list) and
         sum(isinstance(n,dict) and n.get('id')==ref['id'] for n in atoms+predictions)==1,
         'AMBIGUOUS_TARGET','Anchor ID repeated across native targets')
    statement=node.get('statement')
    fail(isinstance(statement,dict) and isinstance(statement.get('value'),str) and statement['value'].strip(),
         'ANCHOR_STATEMENT','Nonempty native sourced atom statement required')
    source=binding(ref['source'],sources,owner)
    fail(source['source']['role']=='main','ANCHOR_ROLE','Atom must bind the main source')
    native_record(card,statement.get('src'),source,native)
    return node,statement['value'],source


def target_value(card,question,sources,owner,native,anchor):
    ref=question['target_ref'];shape(ref,'target');check_owner(ref['owner'],owner)
    typ=question['type']
    fail(ref['kind']==typ+'_field','TARGET_TYPE','Type and target kind must agree')
    source=binding(ref['source'],sources,owner)
    if typ=='scope':
        fail(ref['pointer']=='/added/layers/core/scope' and 'line_id' not in ref,'TARGET_PATH','Scope field only')
        line=None
    else:
        match=re.fullmatch(r'/added/layers/evidence/lines/(0|[1-9][0-9]*)/'+typ,ref['pointer'])
        fail(match is not None and isinstance(ref.get('line_id'),str),'TARGET_PATH','Exact native line field and ID required')
        line=grounds.pointer(card,'/added/layers/evidence/lines/'+match[1])
        lines=grounds.pointer(card,'/added/layers/evidence/lines')
        fail(isinstance(line,dict) and line.get('id')==ref['line_id'] and isinstance(lines,list) and
             sum(isinstance(x,dict) and x.get('id')==ref['line_id'] for x in lines)==1,'TARGET_LINE_ID','Missing/stale/ambiguous line ID')
        choice=line.get('target_ref');actual=choice.get('value') if isinstance(choice,dict) else choice
        if isinstance(choice,dict):
            records=card['added']['sources'];key=choice.get('src');record=records.get(key) if isinstance(key,str) else None
            candidates=[s for s in (source,anchor[2]) if isinstance(record,dict) and record.get('source')==s['doc'].url]
            fail(candidates,'NATIVE_TARGET_SOURCE','Sourced native target choice must bind claim/property work')
            native_record(card,key,candidates[0],native)
        fail(actual==anchor[0]['id'],'TARGET_ANCHOR','Native line target_ref differs from exact atom')
        fail(isinstance(line.get('quote'),str) and line['quote'].strip(),'LINE_FINDING','Native line quote required')
    node=grounds.pointer(card,ref['pointer'])
    fail(isinstance(node,dict) and 'value' in node and isinstance(node.get('src'),str),'TARGET_WRAPPER','Native sourced value required')
    fail(value_hash(node)==ref['value_sha256'],'TARGET_VALUE_HASH',ref['pointer'])
    para=native_record(card,node['src'],source,native)
    if typ=='scope':
        fail(source['source']['role']=='main' and isinstance(node['value'],str) and node['value'].strip(),'SCOPE_VALUE','Nonblank main-source scope required')
    else:
        items=line.get('items',[])
        fail(isinstance(items,list) and any(isinstance(i,dict) and (i.get('value',i))==source['doc'].item(para) for i in items),
             'LINE_WORK_VERSION','Native evidence item must bind exact artifact/hash/locator')
        item_paragraphs=set()
        locator_pattern=re.escape(native.LOCATOR).replace(re.escape('{}'),r'([1-9][0-9]*)')
        for item in items:
            item=item.get('value',item) if isinstance(item,dict) else None
            if not isinstance(item,dict) or not isinstance(item.get('locator'),str):continue
            match=re.fullmatch(locator_pattern,item['locator'])
            if match:
                n=int(match[1])
                if 1<=n<=len(source['doc'].paragraphs) and item==source['doc'].item(n):item_paragraphs.add(n)
        fail(any(line['quote'] in source['doc'].para(n) for n in item_paragraphs),
             'LINE_FINDING_SOURCE','Exact line finding must occur in a bound native item passage')
        if typ=='direction':fail(node['value'] in ('supports','disputes','neutral'),'DIRECTION_VALUE','Closed native direction required')
        else:
            dims=('system','endpoint','intervention','comparison');v=node['value']
            fail(isinstance(v,dict) and set(v)==set(dims) and all(isinstance(v[d],str) and v[d] in
                 ('none','some','serious','very_serious','unknown','not_assessed') for d in dims),
                 'INDIRECTNESS_VALUE','Four explicit native dimensions required')
            fail(not any(v[d] in ('unknown','not_assessed') for d in dims),'INDIRECTNESS_UNKNOWN','Assessment not supplied','unknown')
    try:checked=native.checked_value(card,ref['pointer'],node)
    except (ValueError,KeyError,TypeError) as error:raise grounds.GroundError('NATIVE_TARGET',type(error).__name__) from error
    if line is not None:
        fail(checked.get('target_statement')==anchor[1] and checked.get('line_quote')==line['quote'],
             'NATIVE_CONDITIONING','Native target statement/finding correspondence differs')
    fail(value_hash(checked)==ref['native_checked_sha256'],'CHECKED_VALUE_HASH',ref['pointer'])
    return checked,source


def contexts(card,question,sources,owner,native,made,anchor,prop):
    rows=question.get('context',[])
    fail(len(rows)>=2,'CONTEXT_MISSING','At least two explicit locators required','not_supplied')
    out=[];locators=set();paragraphs=set();texts=set();roles=set()
    for row in rows:
        fail(row['state']=='complete','CONTEXT_STATE',row['state'],row['state'])
        source=binding(row['source'],sources,owner)
        expected=anchor if row['role']=='claim' else prop
        fail(source['source']['key']==expected['source']['key'],'CONTEXT_ROLE','No unrelated context pool')
        read=grounds.instant(row['read_at'])
        fail(grounds.instant(source['source']['retrieved_at'])<=read<=made,'CONTEXT_TIME',row['source']['key'])
        loc=row['locator'];p=loc['paragraph'];numbers=loc['sentences']
        fail(type(p) is int and all(type(n) is int for n in numbers),'LOCATOR_INTEGER','Bool/float indices are unsupported')
        fail(1<=p<=len(source['doc'].paragraphs),'CONTEXT_PARAGRAPH',str(p))
        fail(native_record(card,row['native_source_ref'],source,native)==p,'CONTEXT_LOCATOR','Native source ref paragraph differs')
        paragraph=source['doc'].para(p);sentences=native.sentences_of(paragraph)
        fail(numbers==sorted(set(numbers)) and all(1<=n<=len(sentences) for n in numbers),'CONTEXT_SENTENCES','Existing unique ordered native sentences required')
        selected=' '.join(sentences[n-1] for n in numbers) if numbers else paragraph
        fail(selected.strip() and loc['paragraph_sha256']==grounds.sha(paragraph.encode()) and
             loc['selection_sha256']==grounds.sha(selected.encode()),'CONTEXT_HASH','Actual native paragraph/selection differs')
        key=(source['doc'].pmcid,p,tuple(numbers))
        fail(key not in locators,'DUPLICATE_LOCATOR','Alias or repeated locator does not add context','partial')
        locators.add(key);paragraphs.add((source['doc'].pmcid,p));texts.add(grounds.sha(paragraph.encode()));roles.add(row['role'])
        out.append({'role':row['role'],'source':row['source'],'native_source_ref':row['native_source_ref'],
                    'locator':{'native':source['doc'].locator(p),'paragraph':p,'sentences':numbers},
                    'paragraph_sha256':loc['paragraph_sha256'],'selection_sha256':loc['selection_sha256'],
                    'text':selected,'read_at':row['read_at'],'selection_reason':row['reason']})
    fail(len(paragraphs)>1 and len(texts)>1,'CONTEXT_PARAGRAPH_MINIMUM','Split spans/cloned paragraph text do not satisfy the minimum','partial')
    fail(roles=={'claim','property'},'CONTEXT_ROLES','Both claim and checked-property context roles required','not_supplied')
    return out


def error_record(error):return {'code':error.code,'detail':error.detail}

def basis(error):return 'invalid_binding' if error.status=='invalid' else error.status


def evaluate(card,question,index,sources,owner,native,made):
    result={'request_pointer':'/questions/'+str(index),'id':question.get('id','invalid'),
            'type':question.get('type','invalid'),'status':'cannot_assess','basis_state':'invalid_binding','issues':[],'packet':None}
    try:
        shape(question,'question')
        if question['state']!='ready':raise grounds.GroundError('QUESTION_STATE',question['state'],question['state'])
        fail('target_ref' in question and 'anchor_ref' in question,'TARGET_MISSING','Explicit property and atom targets required','not_supplied')
        anchor=anchor_value(card,question['anchor_ref'],sources,owner,native)
        checked,prop=target_value(card,question,sources,owner,native,anchor)
        ctx=contexts(card,question,sources,owner,native,made,anchor[2],prop)
        result.update(status='grounded_input_contract_only',basis_state='grounded_input_contract_only',
          packet={'question_type':question['type'],'instruction':INSTRUCTIONS[question['type']],
                  'target_ref':question['target_ref'],'anchor_ref':question['anchor_ref'],
                  'native_checked_value':checked,'target_claim':anchor[1],
                  'supplied_unverified':copy.deepcopy(question['supplied']),'context':ctx,
                  'scientific_adequacy_verified':False,'entailment_verdict':None})
    except grounds.GroundError as error:
        result['basis_state']=basis(error);result['issues']=[error_record(error)]
    except (UnicodeError,KeyError,TypeError,ValueError,OSError) as error:
        result['issues']=[{'code':'INVALID_INPUT','detail':type(error).__name__}]
    return result


def check(path):
    result={'schema':'ohf-question-context-diagnostic/1','status':'cannot_assess','questions':[],
            'issues':[],'input_pins':{},'limits':LIMITS,'contract_sha256':grounds.sha(SCHEMA_PATH.read_bytes())}
    bundle=None;request=None
    try:
        path=Path(grounds.os_path(os.fspath(path)));bundle=grounds.Bundle(path.parent)
        request=shape(grounds.strict_json(bundle.read(path.name)),'request')
        made=grounds.instant(request['made_at'])
        fail(len({q['id'] for q in request['questions']})==len(request['questions']),'QUESTION_ID','Repeated question ID')
        card=grounds.strict_json(bundle.pinned(request['card']));owner=owner_of(card,request['card'])
        native=native_helpers();sources={};ids=set();digests=set()
        for source in request['sources']:
            fail(source['key'] not in sources,'SOURCE_KEY','Duplicate source key')
            parsed=source_document(bundle,source,card,owner,native,made)
            fail(not (ids & parsed['ids']) and source['sha256'] not in digests,'SOURCE_ALIAS','Aliases/cloned files/competing versions cannot add paragraphs')
            ids.update(parsed['ids']);digests.add(source['sha256']);sources[source['key']]=parsed
        fail(sum(s['source']['role']=='main' for s in sources.values())==1,'MAIN_SOURCE','Exactly one main work required')
        result['questions']=[evaluate(card,q,i,sources,owner,native,made) for i,q in enumerate(request['questions'])]
        if all(q['status']=='grounded_input_contract_only' for q in result['questions']):result['status']='grounded_input_contract_only'
    except grounds.GroundError as error:
        result['issues']=[error_record(error)]
        if isinstance(request,dict) and isinstance(request.get('questions'),list):
            result['questions']=[{'request_pointer':'/questions/'+str(i),'id':q.get('id','invalid'),
              'type':q.get('type','invalid'),'status':'cannot_assess','basis_state':basis(error),'issues':[error_record(error)],'packet':None}
              for i,q in enumerate(request['questions'][:128]) if isinstance(q,dict)]
    except (UnicodeError,KeyError,TypeError,ValueError,OSError) as error:
        result['issues']=[{'code':'INVALID_INPUT','detail':type(error).__name__}]
    result['input_pins']=dict(bundle.pins) if bundle else {}
    try:shape(result,'diagnostic')
    except grounds.GroundError as error:
        result['status']='cannot_assess';result['issues'].append({'code':'OUTPUT_CONTRACT','detail':error.detail})
        result['questions']=[]
    return result


class ClosedParser(argparse.ArgumentParser):
    def error(self,message):raise grounds.GroundError('CLI_ARGUMENTS',message)

def main(argv=None):
    parser=ClosedParser(description=__doc__.split('\n')[0],allow_abbrev=False);parser.add_argument('request')
    try:
        args=parser.parse_args(argv);result=check(args.request)
    except grounds.GroundError as error:
        result={'schema':'ohf-question-context-diagnostic/1','status':'cannot_assess','questions':[],
                'issues':[error_record(error)],'input_pins':{},'limits':LIMITS,
                'contract_sha256':grounds.sha(SCHEMA_PATH.read_bytes())}
        print(json.dumps(result,ensure_ascii=True,allow_nan=False,indent=2))
        return 2
    print(json.dumps(result,ensure_ascii=True,allow_nan=False,indent=2))
    return 0 if result['status']=='grounded_input_contract_only' else 1


if __name__=='__main__':raise SystemExit(main())
