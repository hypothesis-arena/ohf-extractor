"""Construct 32 EXCLUDE service fixtures from test contracts, not recorded responses.

Identifiers and names below are regression tokens, not live database assertions.
The three explicitly licensed input files supply citation IDs/cohort multiplicity
only. No excluded response is opened; prose is newly authored and marked synthetic.
"""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import urllib.parse
import xml.etree.ElementTree as ET

MARK='Project-authored synthetic transport input; no live service record or scientific assessment.'
def page(rows):
    return {'_fixture_origin':MARK,'hitCount':len(rows),'resultList':{'result':rows}}
def record(pmid,doi=None,date='2010-01-01',print_only=False):
    row={'source':'MED','id':str(pmid),'pmid':str(pmid),'title':'Invented citation token '+str(pmid),
         'pubYear':date[:4],'pubTypeList':{'pubType':['Journal Article']}}
    if doi:row['doi']=doi
    row['journalInfo']={'printPublicationDate':date} if print_only else {}
    if not print_only:row['firstPublicationDate']=date
    return row
def esearch(ids,count=None):
    return {'_fixture_origin':MARK,'esearchresult':{'count':str(len(ids) if count is None else count),'idlist':list(map(str,ids))}}
def summary(rows):
    return {'_fixture_origin':MARK,'result':{'uids':[r['uid'] for r in rows],**{r['uid']:r for r in rows}}}
def identifier(cids):return {'IdentifierList':{'CID':cids}}
def property_row(cid,title,inchikey='SYNTHETIC-INCHIKEY-TOKEN',formula='C2H4'):
    return {'CID':cid,'Title':title,'InChIKey':inchikey,'MolecularFormula':formula}
def taxon(ident,name,rank='species',rung='mammal',synonyms=()):
    node=ET.Element('Taxon')
    for key,value in [('TaxId',ident),('ScientificName',name),('Rank',rank),('Division','Synthetic fixture'),
                      ('PubDate','1992-09-16'),('UpdateDate','2026-01-01')]:ET.SubElement(node,key).text=str(value)
    others=ET.SubElement(node,'OtherNames')
    for name2 in synonyms:ET.SubElement(others,'GenbankCommonName').text=name2
    # Preserve the negative filtering witness, not merely the positive names.
    ET.SubElement(others,'Includes').text='C57BL synthetic strain must be excluded'
    misspelling=ET.SubElement(others,'Name')
    ET.SubElement(misspelling,'ClassCDE').text='misspelling'
    ET.SubElement(misspelling,'DispName').text='nude synthetic typo must be excluded'
    lineage=ET.SubElement(node,'LineageEx')
    ancestors=[]
    if rung!='not_animal':ancestors.append(('33208','Metazoa','kingdom'))
    if rung in ('mammal','vertebrate'):ancestors.append(('7742','Vertebrata','clade'))
    if rung=='mammal' and str(ident)!='40674':ancestors.append(('40674','Mammalia','class'))
    ancestors.append(('999000','Synthetic genus','genus'))
    for aid,label,arank in ancestors:
        child=ET.SubElement(lineage,'Taxon')
        for k,v in [('TaxId',aid),('ScientificName',label),('Rank',arank)]:ET.SubElement(child,k).text=v
    ET.SubElement(node,'Lineage').text='; '.join(x[1] for x in ancestors)
    return node
def xml_taxa(rows):
    root=ET.Element('TaxaSet');root.append(ET.Comment(MARK))
    for row in rows:root.append(taxon(*row))
    return ET.tostring(root,encoding='utf-8',xml_declaration=True)+b'\n'

def build(root):
    outputs={}
    def put(name,obj):
        if isinstance(obj,dict):obj={'_fixture_origin':MARK,**obj}
        outputs['biodb/'+name]=obj if isinstance(obj,bytes) else (json.dumps(obj,ensure_ascii=False,indent=2)+'\n').encode()
    gene=lambda uid,name,tax,loc:{'uid':uid,'name':name,'description':'Invented gene label '+name,
        'otheraliases':'KOG1, '+name,'otherdesignations':'Invented designation',
        'organism':{'taxid':tax,'scientificname':'Homo sapiens' if tax==9606 else 'Mus musculus'},
        'maplocation':loc,'chromosome':'17','summary':'SUMMARY: invented text must be withheld'}
    put('ncbi-gene-57521.json',summary([gene('57521','RPTOR',9606,'17q25.3')]))
    put('ncbi-gene-78757.json',summary([gene('78757','Rictor',10090,'synthetic location')]))
    put('ncbi-gene-search-Rictor-10090.json',esearch(['78757']))
    uniprot={'_fixture_origin':MARK,'entryType':'UniProtKB reviewed (Swiss-Prot)','primaryAccession':'Q8N122','uniProtkbId':'RPTOR_HUMAN',
       'entryAudit':{'entryVersion':9,'firstPublicDate':'2004-04-26','lastAnnotationUpdateDate':'2026-09-02'},
       'organism':{'taxonId':9606},'genes':[{'geneName':{'value':'RPTOR'}}],
       'proteinDescription':{'recommendedName':{'fullName':{'value':'Invented protein label'}}},
       'comments':[{'commentType':kind,'texts':[{'value':text,'evidences':[{'source':'PubMed','id':pmid}]}]}
                   for kind,text,pmid in [('FUNCTION','Invented function for a parsing exercise.','99000001'),
                                          ('SUBUNIT','Invented mTORC1 component relation, a test token only.','99000002'),
                                          ('UNSELECTED COMMENT','Invented comment outside the permitted kinds.','99000003')]],
       'keywords':[{'name':'synthetic fixture'}]}
    put('uniprot-Q8N122.json',uniprot);put('uniprot-search-RPTOR.json',{'_fixture_origin':MARK,'results':[{'primaryAccession':'Q8N122','uniProtkbId':'RPTOR_HUMAN'}]})
    ids=['200272972']+[str(200800000+i) for i in range(19)]
    geo=[]
    for i,uid in enumerate(ids):
        geo.append({'uid':uid,'accession':'GSE272972' if i==0 else 'GSE'+str(800000+i),'title':'Invented series '+str(i),
                    'summary':'SUMMARY: invented submitted text must be withheld','gpl':'18573','taxon':'Homo sapiens',
                    'gdstype':'synthetic study type','n_samples':18 if i==0 else i+1,'pubmedids':[42685210] if i==0 else [],
                    'pdat':'2026-07-21','ftplink':'ftp://ftp.ncbi.nlm.nih.gov/geo/synthetic-test-token','bioproject':''})
    put('geo-esearch-GSE272972.json',esearch(ids[:1]));put('geo-esearch-mtorc2.json',esearch(ids,26));put('geo-esearch-none.json',esearch([]))
    put('geo-esummary-GSE272972.json',summary(geo[:1]));put('geo-esummary-mtorc2.json',summary(geo))
    compound=property_row(5284616,'Sirolimus','QFJCIRLUMZQUOT-HPLJOQBZSA-N')
    syn=['Sirolimus','rapamycin','Rapamycin','Synthetic synonym', 'x'*61]
    put('pubchem-name-rapamycin.json',identifier([5284616]));put('pubchem-name-rapamycin-parent.json',identifier([5284616]))
    put('pubchem-5284616-property.json',{'_fixture_origin':MARK,'PropertyTable':{'Properties':[compound]}})
    put('pubchem-5284616-synonyms.json',{'_fixture_origin':MARK,'InformationList':{'Information':[{'CID':5284616,'Synonym':syn}]}})
    answers={}
    def answer(path,obj,status=200):answers[path]=[status,json.dumps(obj,separators=(',',':'))]
    for name,own,parent in [('sirolimus',5284616,5284616),('Rapamycin',5284616,5284616),('rapamycin',5284616,5284616),
                            ('Promethazine',4927,4927),('promethazine',4927,4927),
                            ('Promethazine hydrochloride',6014,4927),('Zinc acetate',11192,176),('acetic acid',176,176)]:
        q=urllib.parse.quote(name,safe='');answer(f'name/{q}/cids/JSON',identifier([own]));answer(f'name/{q}/cids/JSON?cids_type=parent',identifier([parent]))
    answer('name/notacompoundxyz/cids/JSON',{'Fault':{'Message':'invented missing compound'}},404)
    for cid,title,key in [(5284616,'Sirolimus','QFJCIRLUMZQUOT-HPLJOQBZSA-N'),(4927,'Promethazine','SYNTHETIC-PARENT'),(176,'Acetic acid','SYNTHETIC-ACID'),(11192,'Zinc acetate','SYNTHETIC-METAL')]:
        answer(f'cid/{cid}/property/Title,InChIKey,MolecularFormula/JSON',{'PropertyTable':{'Properties':[property_row(cid,title,key)]}})
        answer(f'cid/{cid}/synonyms/JSON',{'InformationList':{'Information':[{'CID':cid,'Synonym':syn if cid==5284616 else [title]}]}})
    answers['_fixture_origin']=MARK;put('pubchem-recorded.json',answers)
    mouse=('10090','Mus musculus','species','mammal',('mouse','mice','house mouse'))
    mus=('10088','Mus','genus','mammal',('mouse',))
    mammal=('40674','Mammalia','class','mammal',('mammals',))
    human_genus=('9605','Homo','genus','mammal',('humans',))
    fly=('7215','Drosophila','genus','invertebrate',('flies',))
    groups=[('1294634','Invented amphibian','species','vertebrate',()),('8504','Invented squamate','species','vertebrate',()),('8505','Invented reptile','species','vertebrate',())]
    for name,rows in [('10090',[mouse]),('mouse',[mouse,mus]),('40674',[mammal]),('9605',[human_genus]),('7215',[fly]),('amphibians-squamates',groups)]:put('taxonomy-efetch-'+name+'.xml',xml_taxa(rows))
    taxa=[('9606','Homo sapiens','species','mammal',()),mouse]
    for ident in ['10116','10141','9544','9541','9483','9615','10181']:taxa.append((ident,'Synthetic taxon '+ident,'species','mammal',()))
    for ident in ['7955','105023','8355','9031']:taxa.append((ident,'Synthetic taxon '+ident,'species','vertebrate',()))
    for ident in ['6239','7227','7159']:taxa.append((ident,'Synthetic taxon '+ident,'species','invertebrate',()))
    taxa.extend([('8932','Columba livia','species','vertebrate',()),('4932','Synthetic yeast','species','not_animal',())])
    put('taxonomy-efetch-terms-1.xml',xml_taxa(taxa))
    for name,found in [('mouse',['10090','10088']),('mus-musculus',['10090']),('mammalia',['40674']),('mammals',['40674']),('humans',['9605']),('amphibians-squamates',['1294634','8504','8505'])]:put('taxonomy-esearch-'+name+'.json',esearch(found))
    # Literal identifiers from licensed Open Genes, not an excluded EPMC response.
    data=json.loads((root/'opengenes-MTOR.json').read_text());dois={};pmids={}
    for vals in data['researches'].values():
        if not isinstance(vals,list):continue
        for row in vals:
            if not isinstance(row,dict):continue
            if row.get('doi'):dois[row['doi']]=row.get('pmid')
            elif row.get('pmid'):pmids[row['pmid']]=True
    early={'10.1016/j.celrep.2013.07.030','10.2353/ajpath.2010.091050','10.1038/nature02661','10.1074/jbc.M611782200'}
    doirecords=[];pmidrecords=[]
    for i,(doi,pmid) in enumerate(dois.items()):
        date='2004-06-01' if doi=='10.1038/nature02661' else '2014-12-01' if doi=='10.1126/scitranslmed.3009892' else '2010-01-01' if doi in early or pmid else '2020-01-01'
        row=record(pmid or str(99100000+i),doi,date,print_only=doi=='10.1038/nature02661')
        (pmidrecords if pmid else doirecords).append(row)
    put('epmc-doi-opengenes-MTOR.json',page(doirecords));put('epmc-pmid-opengenes-MTOR.json',page(pmidrecords))
    # Licensed DrugAge's study IDs/cohort multiplicity; dates are deliberately constructed cutoff test values.
    csvrows=list(csv.DictReader((root/'hagr-drugage.csv').open()))
    studies=list(dict.fromkeys(x['pubmed_id'] for x in csvrows if x['compound_name'].lower()=='rapamycin'))
    put('epmc-pmid-drugage-rapamycin.json',page([record(pmid,date='2009-07-01' if pmid=='19587680' else '2010-01-01' if i<9 else '2020-01-01') for i,pmid in enumerate(studies)]))
    # Reactome CC0's four cited IDs, no article text.
    react=json.loads((root/'reactome-R-HSA-165159.json').read_text());refs=[]
    def walk(n):
        if isinstance(n,dict):
            for k,v in n.items():
                if k=='pubMedIdentifier':refs.append(str(v))
                else:walk(v)
        elif isinstance(n,list):
            for v in n:walk(v)
    walk(react);put('epmc-pmid-R-HSA-165159.json',page([record(x) for x in dict.fromkeys(refs)]))
    assert len(outputs)==32, len(outputs)
    return outputs

def main():
    p=argparse.ArgumentParser();p.add_argument('--licensed-inputs',type=Path,required=True);p.add_argument('--out',type=Path,required=True);args=p.parse_args()
    outputs=build(args.licensed_inputs);args.out.mkdir(parents=True,exist_ok=False)
    rows=[]
    for name,raw in outputs.items():
        dest=args.out/name;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(raw)
        rows.append({'path':'scripts/tests/fixtures/'+name,'artifact_path':name,'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw),'origin':'own_synthetic','basis':'build_biodb.py explicit constructed response; existing tests retain assertions, names/IDs are regression tokens, not live service claims'})
    inputs=[{'path':n,'sha256':hashlib.sha256((args.licensed_inputs/n).read_bytes()).hexdigest(),'scope':'licensed identifiers and cohort cardinality only'} for n in ['opengenes-MTOR.json','hagr-drugage.csv','reactome-R-HSA-165159.json']]
    (args.out/'MANIFEST.json').write_text(json.dumps({'generator_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'licensed_inputs':inputs,'rows':rows},indent=2)+'\n')
    print(json.dumps({'paths':len(rows),'manifest':str(args.out/'MANIFEST.json')}))
if __name__=='__main__':main()
