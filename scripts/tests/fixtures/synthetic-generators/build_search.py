"""29 newly authored search/registry transport fixtures, constructed from unit contracts.

No recorded response is an input. Identifiers/short title fragments required by
the existing MIT test code are regression tokens, not facts about those works.
All other titles, descriptions and abstracts are invented here.
"""
import argparse
import copy
import gzip
import hashlib
import json
from pathlib import Path
from build_biodb import MARK, page, record, esearch

def build():
    outputs={}
    def put(name,obj):outputs['search/'+name]=obj if isinstance(obj,bytes) else (json.dumps(obj,ensure_ascii=False,indent=2)+'\n').encode()
    def work(pmid,pmcid=None,doi=None,year='2025',kind='Journal Article',licence='cc by'):
        row=record(pmid,doi,year+'-02-01');row.update(pubYear=year,license=licence,pubTypeList={'pubType':[kind]})
        if pmcid:row['pmcid']=pmcid
        return row
    target=work('34937938','PMC8755536','10.1038/s41586-021-04224-5','2022')
    target['commentCorrectionList']={'commentCorrection':[{'source':'MED','id':'35102282','type':'Comment in','reference':'Invented reply token'}]}
    put('target.json',page([target]))
    terms=copy.deepcopy(target)
    terms['meshHeadingList']={'meshHeading':[{'majorTopic_YN':'Y','descriptorName':'Neoplasms'},
                                            {'majorTopic_YN':'Y','descriptorName':'Mammals'},
                                            {'majorTopic_YN':'N','descriptorName':'Body Size'}]}
    terms['keywordList']={'keyword':['synthetic term']};put('target-terms.json',page([terms]))
    butler=work('39993196','PMC11892590','10.1073/pnas.2422861122')
    lynch=work('40163737','PMC12002202','10.1073/pnas.2502696122',kind='Commentary')
    dujon=work('99010003','PMC12308236','10.0000/synthetic-dujon')
    compton=work('40324092',doi='10.0000/synthetic-compton',kind='Letter')
    reply=work('40324086',doi='10.0000/synthetic-reply',kind='Reply')
    comment=work('35102282',doi='10.0000/synthetic-comment',kind='Comment')
    extra=work('37664965',doi='10.0000/synthetic-openalex-extra')
    lookup=[butler,lynch,dujon,compton,reply,comment,extra]
    # This contract deliberately has year metadata but no date evidence. It must
    # stay undetermined at a cutoff, not silently become a dated live record.
    for row in lookup:
        row.pop('firstPublicationDate',None);row.pop('journalInfo',None)
    put('lookup.json',page(lookup))
    put('citations.json',{'_fixture_origin':MARK,'hitCount':6,'citationList':{'citation':[{'source':'MED','id':r['id']} for r in lookup[:6]]}})
    put('elink.json',{'_fixture_origin':MARK,'linksets':[{'dbfrom':'pubmed','ids':['34937938'],'linksetdbs':[{'links':['40324092','99010003','40324086','99999999']}]}]})
    put('esearch.json',esearch(['42693106','42264491'],2))
    pmrows={uid:{'uid':uid,'title':'Invented PubMed token '+uid,'pubdate':'2026 Jan 01','pubtype':['Journal Article'],
                'articleids':[{'idtype':'pubmed','value':uid},{'idtype':'doi','value':'10.0000/synthetic-'+uid}]} for uid in ['42693106','42264491']}
    put('esummary.json',{'_fixture_origin':MARK,'result':{'uids':['42693106','42264491'],**pmrows}})
    put('crossref.json',{'_fixture_origin':MARK,'status':'ok','message':{'DOI':target['doi'],'title':['Invented cross-reference token'],
                         'relation':{'has-review':[{'id':'10.0000/synthetic-review','id-type':'doi'}]},'type':'journal-article'}})
    def oa(pmid,doi,date='2025-02-26'):
        return {'id':'https://openalex.org/W'+(pmid or '99000000'),'doi':'https://doi.org/'+doi,
                'ids':{'pmid':'https://pubmed.ncbi.nlm.nih.gov/'+pmid} if pmid else {},
                'title':'Invented OpenAlex token','publication_year':int(date[:4]),'publication_date':date,
                'type':'article','primary_location':{'license':'cc-by'}}
    put('openalex-target.json',{'_fixture_origin':MARK,'id':'https://openalex.org/W4200048313'})
    put('openalex-cites.json',{'_fixture_origin':MARK,'meta':{'count':3},'results':[oa('40324092',compton['doi']),oa('37664965',extra['doi']),oa(None,'10.3389/fevo.2025.1489294')]})
    retracted=work('9500320',doi='10.0000/synthetic-withdrawn',year='1998')
    retracted['pubTypeList']={'pubType':['Retracted Publication']}
    retracted['commentCorrectionList']={'commentCorrection':[{'source':'MED','id':'99020001','type':'Retraction in','reference':'Invented retraction token'},
                                                           {'source':'MED','id':'99020002','type':'Expression of concern in','reference':'Invented concern token'}]}
    put('retracted-epmc.json',page([retracted]))
    put('retracted-crossref.json',{'_fixture_origin':MARK,'status':'ok','message':{'DOI':retracted['doi'],'title':['Invented withdrawn token'],'type':'journal-article',
            'updated-by':[{'type':'correction','source':'retraction-watch','DOI':'10.1016/s0140-6736(04)15715-2','updated':{'date-parts':[[2004,3,6]]}},
                          {'type':'retraction','source':'retraction-watch','DOI':'10.1016/s0140-6736(10)60175-4','updated':{'date-parts':[[2010,2,6]]}}]}})
    put('similar-elink.json',{'_fixture_origin':MARK,'linksets':[{'dbfrom':'pubmed','ids':['34937938'],'linksetdbs':[{'linkname':'pubmed_pubmed','links':[{'id':'34937938','score':100},{'id':'99030001','score':90},{'id':'99030002','score':80},{'id':'99030003','score':70}]}]}]})
    put('similar-lookup.json',page([work('99030001'),work('99030002')]))
    wang=work('99040001',doi='10.1016/j.isci.2018.05.016',year='2018')
    wang.update(title='Invented lysosome reference token',authorString='Wang A, Invented B',journalTitle='iScience',abstractText='Invented abstract: a token changes its bin under a toy condition.')
    put('ref-wang-epmc.json',page([wang]));put('ref-none-epmc.json',page([]))
    put('ref-ambiguous-epmc.json',page([wang,dict(wang,id='99040002',pmid='99040002',doi='10.0000/synthetic-ambiguous',title='Another invented reference token')]))
    put('desc-epmc-precis.json',page([dict(work('99050001',year='2004'),title='Precis of an invented commentary token',authorString='Wegner DM')]))
    put('desc-epmc-none.json',page([]))
    put('desc-crossref-rescorla.json',{'_fixture_origin':MARK,'status':'ok','message':{'items':[
        {'DOI':'10.1037/0003-066X.42.2.119','title':['A Pavlovian analysis of goal-directed behavior.'],
         'author':[{'family':'Rescorla','given':'RA','sequence':'first'}],'container-title':['American Psychologist'],
         'issued':{'date-parts':[[1987,2,1]]},'type':'journal-article'},
        {'DOI':'10.0000/synthetic-other','title':['Invented unrelated token'],'author':[{'family':'Other'}], 'issued':{'date-parts':[[1987]]}}]}})
    def trial(nct,registered,updated,status='COMPLETED',has_results=True):
        return {'protocolSection':{
            'identificationModule':{'nctId':nct,'briefTitle':'Invented trial '+nct,'nctIdAliases':[]},
            'statusModule':{'overallStatus':status,'studyFirstPostDateStruct':{'date':registered},'resultsFirstPostDateStruct':{'date':'2014-09-15' if registered<'2014' else '2026-01-01'},
                            'lastUpdatePostDateStruct':{'date':updated},'statusVerifiedDate':'2016-11',
                            'startDateStruct':{'date':'2000-01-01','type':'ACTUAL'},'completionDateStruct':{'date':'2014-01-01','type':'ACTUAL'}},
            'designModule':{'phases':['PHASE3'],'studyType':'INTERVENTIONAL','enrollmentInfo':{'count':30,'type':'ACTUAL'}},
            'conditionsModule':{'conditions':['Invented condition']},
            'armsInterventionsModule':{'interventions':[{'type':'OTHER','name':'Invented toy intervention','description':'Do not copy this synthetic description into output'}]},
            'outcomesModule':{'primaryOutcomes':[{'measure':'First Occurrence of a Major Cardiovascular Event: invented test counter','timeFrame':'synthetic time window','description':'Do not copy this synthetic description'}]}},
            'hasResults':has_results}
    put('ctgov-study.json',{'_fixture_origin':MARK,**trial('NCT00000620','1999-10-28','2016-11-22')})
    put('ctgov-search.json',{'_fixture_origin':MARK,'totalCount':3,'studies':[trial('NCT01922167','2013-01-01','2020-01-01'),trial('NCT04608448','2020-01-01','2025-01-01'),trial('NCT06789900','2025-01-01','2025-01-01')]})
    put('ctgov-version.json',{'_fixture_origin':MARK,'apiVersion':'synthetic-v1','dataTimestamp':'2026-10-21T09:00:05'})
    preprint=work('99060001',doi='10.1101/2022.07.12.499088',year='2022');preprint['source']='PPR';put('text-preprint-epmc.json',page([preprint]))
    put('text-biorxiv.json',{'_fixture_origin':MARK,'messages':[{'status':'ok'}],'collection':[
        {'doi':'10.1101/2022.07.12.499088','title':'Invented preprint '+str(i),'date':date,'version':str(i),'license':'cc_by_nc_nd','server':'biorxiv',
         'jatsxml':f'https://www.biorxiv.org/content/early/{date.replace("-","/")}/2022.07.12.499088.source.xml'}
        for i,date in [(1,'2022-07-12'),(2,'2023-01-01'),(3,'2024-07-24')]]})
    pmc=work('99070001','PMC11726020','10.0000/synthetic-text','2025',licence='cc by-nc-nd');pmc['isOpenAccess']='Y';pmc['inEPMC']='Y'
    pmc['fullTextUrlList']={'fullTextUrl':[{'availability':'Open access','availabilityCode':'OA','documentStyle':'html','site':'synthetic','url':'https://example.org/synthetic-full-text','license':'cc by'}]}
    put('text-pmc-epmc.json',page([pmc]))
    put('text-unpaywall-synthetic.json',{'_fixture_origin':MARK,'doi':preprint['doi'],'is_oa':True,'oa_locations':[{'url':'https://example.org/synthetic-preprint','url_for_pdf':'https://example.org/synthetic-preprint.pdf','license':'cc-by-nc-nd','version':'submittedVersion','host_type':'repository'}]})
    broad=page([dict(work('99080001','PMC13664863','10.0000/synthetic-fallback-first'),title='Invented broad-search token one'),
                dict(work('41991987','PMC13243600','10.0000/synthetic-fallback-second'),title='Invented broad-search token two'),work('99080003')]);broad['hitCount']=91;put('fallback-skin/epmc-broad.json',broad)
    # This literal comes from the existing MIT compression test's assertion; no archived page is read.
    plain=b'<!doctype html><html><body>Invented compression fixture: distributed under the terms of the CC-BY&amp;nbsp;license. No article or archived page.</body></html>\n'
    put('wayback-cc-by-page.html.gz',gzip.compress(plain,mtime=0))
    assert len(outputs)==29,len(outputs)
    return outputs

def main():
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);args=p.parse_args();outputs=build();args.out.mkdir(parents=True,exist_ok=False);rows=[]
    for name,raw in outputs.items():
        dest=args.out/name;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(raw)
        rows.append({'path':'scripts/tests/fixtures/'+name,'artifact_path':name,'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw),'origin':'own_synthetic','basis':'build_search.py explicit constructors; no recorded source input. Public identifiers/short existing test-contract fragments are regression tokens, not assertions of service data.'})
    (args.out/'MANIFEST.json').write_text(json.dumps({'generator_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'recorded_response_inputs':0,'rows':rows},indent=2)+'\n');print(json.dumps({'paths':len(rows),'manifest':str(args.out/'MANIFEST.json')}))
if __name__=='__main__':main()
