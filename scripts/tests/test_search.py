# Export fixture provenance: inputs named in SYNTHETIC-FIXTURES.json are
# constructed test data; their identifiers and dates are regression tokens.
# Recorded-response descriptions below identify the replaced source snapshots,
# not live-service provenance for those synthetic replacement inputs.
"""Literature search: recorded responses of Europe PMC, NCBI and Crossref, no network.

The fixtures are trimmed real responses (abstracts removed) for Vincze et al. 2022, "Cancer risk
across mammals" (PMC8755536), whose answers are known, and for a retracted Lancet article."""
import gzip
import hashlib
import json
import tempfile
import os
import stat
import time
import sys
import subprocess
import zlib
from pathlib import Path

import pytest

import search
from conftest import SCRIPTS

FIX = Path(__file__).resolve().parent / 'fixtures' / 'search'


def body(name):
    return (FIX / name).read_bytes()


class Net:
    """A transport that answers from fixtures by route and records each URL it was asked."""

    def __init__(self, routes, fail=None):
        self.routes, self.fail, self.urls = routes, fail or {}, []

    def __call__(self, url):
        self.urls.append(url)
        for key, answers in self.fail.items():
            if key in url and answers:
                return answers.pop(0), b'busy', {'Retry-After': '1'}
        for key, name in self.routes:
            if key in url:
                return 200, body(name), {}
        return 404, b'{}', {}


PILOT = [('PMCID%3APMC8755536', 'target.json'), ('citations', 'citations.json'), ('elink', 'elink.json'),
         ('EXT_ID', 'lookup.json'), ('api.crossref.org', 'crossref.json'),
         ('esearch', 'esearch.json'), ('esummary', 'esummary.json'),
         ('api.openalex.org/works/doi', 'openalex-target.json'), ('api.openalex.org/works?', 'openalex-cites.json')]
# A literature query is sent as given and without reviews, "(peto ...) NOT ...": both answered by one fixture.
LITERATURE = [('search?query=peto', 'lookup.json'), ('search?query=%28peto', 'lookup.json')] + PILOT
RETRACTED = [('EXT_ID%3A9500320', 'retracted-epmc.json'), ('api.crossref.org', 'retracted-crossref.json')]


def searcher(tmp_path, routes, **kw):
    sleeps = []
    s = search.Searcher(tmp_path, get=Net(routes, **kw), sleep=sleeps.append, clock=lambda: 0.0)
    return s, sleeps


def test_cited_by_finds_the_known_answers_with_identifiers_and_licence(tmp_path):
    s, _ = searcher(tmp_path, PILOT)
    r = s.cited_by('PMC8755536')
    assert r['outcome'] == 'ok'
    by_pmcid = {w['pmcid']: w for w in r['works'] if w['pmcid']}
    # Butler et al. 2025, Lynch 2025 and Dujon et al. 2025 answer the pilot; the accepted card cites them.
    butler, lynch, dujon = by_pmcid['PMC11892590'], by_pmcid['PMC12002202'], by_pmcid['PMC12308236']
    assert butler['doi'] == '10.1073/pnas.2422861122' and butler['pmid'] == '39993196'
    assert (butler['licence'], butler['licence_from']) == ('cc by', 'europepmc license field')
    assert lynch['found_by'] == ['europepmc'] and dujon['found_by'] == ['europepmc', 'pubmed']
    # A PubMed citing work Europe PMC does not return is kept and marked, not dropped.
    lost = [w for w in r['works'] if w['source_id'] == 'MED:99999999']
    assert lost and lost[0]['note'] and lost[0]['licence'] is None
    assert r['counts'] == {'europepmc': 6, 'pubmed': 4, 'openalex': 3}


def test_cited_by_adds_the_citing_works_only_openalex_sees(tmp_path):
    s, _ = searcher(tmp_path, PILOT)
    r = s.cited_by('PMC8755536')
    works = {w['source_id']: w for w in r['works']}
    # Compton et al.'s letter: in all three, one work.
    assert works['MED:40324092']['found_by'] == ['europepmc', 'openalex', 'pubmed']
    # A Zoo Biology paper (PMID 37664965) neither Europe PMC nor PubMed lists as citing the pilot.
    assert works['MED:37664965']['found_by'] == ['openalex']
    # A work with no PMID is recorded from OpenAlex, with its licence as OpenAlex reads it.
    oa = works['DOI:10.3389/fevo.2025.1489294']
    assert oa['found_by'] == ['openalex'] and (oa['licence'], oa['licence_from']) == (
        'cc-by', 'openalex primary_location license')
    assert oa['dates'] == {'first': '2025-02-26'}
    assert any('filter=cites%3AW4200048313' in x['url'] for x in r['responses'])


def test_cited_by_stands_on_europe_pmc_and_pubmed_when_openalex_fails(tmp_path):
    s, _ = searcher(tmp_path, [x for x in PILOT if 'openalex' not in x[0]])
    r = s.cited_by('PMC8755536')
    assert r['outcome'] == 'ok' and r['counts'] == {'europepmc': 6, 'pubmed': 4, 'openalex': None}
    assert 'HTTP 404' in r['openalex_error']


def test_every_response_is_hashed_kept_and_logged(tmp_path):
    s, _ = searcher(tmp_path, PILOT)
    r = s.cited_by('PMC8755536')
    for resp in r['responses']:
        assert resp['status'] == 200 and resp['at'].endswith('Z')
        kept = tmp_path / search.RESPONSES / (resp['sha256'].split(':')[1] + '.body')
        assert search.sha256(kept.read_bytes()) == resp['sha256']
    logged = search.read_log(tmp_path)
    assert logged == [json.loads(json.dumps(r))]


def test_records_carry_no_abstract(tmp_path):
    s, _ = searcher(tmp_path, PILOT)
    s.cited_by('PMC8755536')
    text = (tmp_path / search.LOG).read_text()
    assert 'abstractText' not in text and 'abstract' not in json.loads(text.splitlines()[0])['works'][0]


def test_responses_are_comments_replies_and_letters(tmp_path):
    s, _ = searcher(tmp_path, PILOT)
    r = s.responses('PMC8755536')
    rel = {w['source_id']: w['relation'] for w in r['works']}
    assert rel['MED:35102282'] == 'Comment in'                    # linked by Europe PMC on the work
    assert rel['MED:40163737'].startswith('cites it; type')        # Lynch, a commentary
    assert 'MED:40324092' in rel and 'MED:40324086' in rel         # Compton et al. letter; Butler reply
    assert any(r == 'has-review' for r in rel.values())            # a Crossref relation
    assert 'MED:39993196' not in rel   # a research article that disagrees is found by cited_by, not here
    assert [x['tool'] for x in search.read_log(tmp_path)] == ['cited_by', 'responses']


def test_status_of_a_clean_work_is_none_found_with_what_was_checked(tmp_path):
    s, _ = searcher(tmp_path, PILOT)
    r = s.status('PMC8755536')
    assert (r['status'], r['notices'], r['checked']) == ('none_found', [], ['europepmc', 'crossref'])


def test_status_of_a_retracted_work_lists_each_notice_and_its_source(tmp_path):
    s, _ = searcher(tmp_path, RETRACTED)
    r = s.status('9500320')
    assert r['status'] == 'retracted'
    rw = [n for n in r['notices'] if n['from'] == 'crossref retraction-watch']
    assert {(n['kind'], n['notice'], n['date']) for n in rw} == {
        ('correction', '10.1016/s0140-6736(04)15715-2', '2004-03-06'),
        ('retraction', '10.1016/s0140-6736(10)60175-4', '2010-02-06')}
    assert {n['status'] for n in r['notices'] if n['from'] == 'europepmc'} == {'retracted', 'concern'}
    assert any(n['kind'] == 'Retracted Publication' for n in r['notices'])


def test_literature_searches_both_services_and_records_pubmed_without_licence(tmp_path):
    s, _ = searcher(tmp_path, LITERATURE)
    epmc, _, pubmed, _ = s.literature('peto paradox body size', limit=6)
    assert epmc['ask']['source'] == 'europepmc' and epmc['found'] == 6
    assert pubmed['hit_count'] >= pubmed['found'] == 2
    assert all(w['licence'] is None and w['pmid'] for w in pubmed['works'])
    assert 'tool=ohf-extractor' in pubmed['responses'][0]['url']


def test_a_busy_service_is_retried_after_its_wait_then_answers(tmp_path):
    s, sleeps = searcher(tmp_path, RETRACTED, fail={'api.crossref.org': [429, 503]})
    r = s.status('9500320')
    assert r['outcome'] == 'ok' and 1 in sleeps


def test_a_failed_search_is_logged_as_failed_not_as_nothing_found(tmp_path):
    s, _ = searcher(tmp_path, RETRACTED, fail={'api.crossref.org': [500] * (search.RETRIES + 1)})
    r = s.status('9500320')
    assert r['outcome'] == 'failed' and 'HTTP 500' in r['error'] and r['hit_count'] is None
    assert 'FAILED' in search.report(tmp_path)


def test_requests_to_one_host_are_spaced(tmp_path):
    t = [0.0]
    sleeps = []
    s = search.Searcher(tmp_path, get=Net(PILOT), sleep=lambda d: (sleeps.append(d), t.__setitem__(0, t[0] + d)),
                        clock=lambda: t[0])
    resp = []
    s.fetch(search.EUTILS + 'esearch.fcgi?x', resp)
    s.fetch(search.EUTILS + 'esearch.fcgi?y', resp)
    assert sleeps == [pytest.approx(search.MIN_INTERVAL['eutils.ncbi.nlm.nih.gov'])]


def test_report_without_a_search_refuses_nothing_against(tmp_path):
    assert 'cannot be claimed' in search.report(tmp_path)


@pytest.mark.parametrize('ident,query', [('34937938', 'EXT_ID:34937938 AND SRC:MED'),
                                         ('pmc8755536', 'PMCID:PMC8755536'),
                                         ('10.1038/s41586-021-04224-5', 'DOI:"10.1038/s41586-021-04224-5"')])
def test_an_identifier_becomes_one_europe_pmc_query(ident, query):
    assert search.id_query(ident) == query


def test_an_unknown_identifier_is_refused():
    with pytest.raises(search.SearchError):
        search.id_query('Vincze 2022')


# Recorded 22.10 from web.archive.org/web/20260928031855id_/https://jamanetwork.com/pages/cc-by-license-permissions,
# which answered gzip with Content-Encoding: gzip though no Accept-Encoding was sent (decoded body sha256:14282a52...):
# its title and description, gzipped again. Kept as received, the page read as having no licence statement.
ARCHIVED = 'https://web.archive.org/web/20260928031855id_/https://jamanetwork.com/pages/cc-by-license-permissions'


def encoded(data, encoding):
    def get(url):
        return 200, data, {'Content-Encoding': encoding}
    return get


def test_a_compressed_response_is_kept_hashed_and_read_decoded(tmp_path):
    raw = body('wayback-cc-by-page.html.gz')
    s = search.Searcher(tmp_path, get=encoded(raw, 'gzip'), sleep=lambda d: None, clock=lambda: 0.0)
    resp = []
    page = s.fetch(ARCHIVED, resp)
    assert b'distributed under the terms of the CC-BY&amp;nbsp;license' in page
    assert resp[0]['sha256'] == search.sha256(page) != search.sha256(raw) and resp[0]['decoded_from'] == 'gzip'
    assert (tmp_path / search.RESPONSES / (resp[0]['sha256'].split(':')[1] + '.body')).read_bytes() == page
    # deflate, zlib-wrapped or raw; a body sent as is records no encoding
    for data in (zlib.compress(page), zlib.compress(page)[2:-4]):
        s.get = encoded(data, 'Deflate')
        assert s.fetch(ARCHIVED, resp) == page and resp[-1]['decoded_from'] == 'deflate'
    s.get = lambda url: (200, page, {})
    assert s.fetch(ARCHIVED, resp) == page and 'decoded_from' not in resp[-1]


@pytest.mark.parametrize('encoding,data', [('br', b'\x8b\x00'), ('gzip', b'not gzip at all')])
def test_a_body_the_kit_cannot_decode_is_a_failed_call_and_is_not_kept(tmp_path, encoding, data):
    s = search.Searcher(tmp_path, get=encoded(data, encoding), sleep=lambda d: None, clock=lambda: 0.0)
    r = s.call('page', {'id': 'x'}, lambda resp: (1, [s.fetch(ARCHIVED, resp)], {}))
    assert r['outcome'] == 'failed' and encoding in r['error']
    assert r['responses'] == [{'url': ARCHIVED, 'at': r['responses'][0]['at'], 'status': 200,
                               'content_encoding': encoding, 'kept': False}]
    assert not (tmp_path / search.RESPONSES).exists()


def test_a_post_records_and_keeps_its_body_so_the_request_repeats(tmp_path):
    seen = []

    def get(url, body=None):
        seen.append((url, body))
        return 200, b'{"data": {"target": null}}', {}
    s = search.Searcher(tmp_path, get=get, sleep=lambda d: None, clock=lambda: 0.0)
    resp = []
    query = {'query': '{ target(ensemblId: "ENSG0") { id } }', 'variables': {}}
    assert s.json('https://api.example.org/graphql', resp, body=query) == {'data': {'target': None}}
    sent = seen[0][1]
    assert json.loads(sent) == query
    assert resp[0]['request_sha256'] == search.sha256(sent)
    kept = tmp_path / search.RESPONSES / (resp[0]['request_sha256'].split(':')[1] + '.body')
    assert kept.read_bytes() == sent
    # A GET sends and records no request body.
    s.json('https://api.example.org/x', resp)
    assert seen[1] == ('https://api.example.org/x', None) and 'request_sha256' not in resp[1]


def cited_card(*urls, doi='10.1038/s41586-021-04224-5'):
    return {'author': {'source': {'doi': doi}},
            'added': {'sources': {f's{n}': {'source': u} for n, u in enumerate(urls)}}}


def test_attribution_names_the_calls_that_found_each_cited_work(tmp_path):
    s, _ = searcher(tmp_path, PILOT)
    cites = s.cited_by('PMC8755536')
    status = s.status('PMC8755536')
    card = cited_card(search.EPMC + 'PMC8755536/fullTextXML',             # the article itself
                      search.EPMC + 'PMC11892590/fullTextXML',            # Butler, found by cited_by
                      'https://doi.org/10.1073/pnas.2502696122',          # Lynch, cited by DOI
                      search.EPMC + 'PMC9999999/fullTextXML')             # known to the converter only
    a = search.attribute(card, tmp_path)
    by = {x['id']: x for x in a['sources']}
    assert by['pmc8755536']['main'] and not by['pmc8755536']['found_by']
    assert [h['call_id'] for h in by['pmc11892590']['found_by']] == [cites['call_id']]
    assert [h['call_id'] for h in by['10.1073/pnas.2502696122']['found_by']] == [cites['call_id']]
    assert a['not_found_by_search'] == ['pmc9999999']
    assert [c['call_id'] for c in a['calls_without_card_source']] == [status['call_id']]
    text = search.attribution_text(a)
    assert 'NOT found by a logged search' in text and 'the article converted' in text
    assert f"status none_found" in text


def test_attribution_matches_a_pmcid_to_a_record_that_found_the_work_by_doi(tmp_path):
    s = search.Searcher(tmp_path)
    s.log({'call_id': 'a1', 'tool': 'literature', 'ask': {'query': 'q', 'source': 'pubmed'}, 'outcome': 'ok',
           'started_at': 't', 'works': [{'doi': '10.1/X', 'pmid': '5'}]})
    s.log({'call_id': 'b2', 'tool': 'cited_by', 'ask': {'id': 'x'}, 'outcome': 'ok', 'started_at': 't',
           'works': [{'doi': '10.1/x', 'pmcid': 'PMC7'}]})
    a = search.attribute(cited_card('https://pubmed.ncbi.nlm.nih.gov/5/', doi='10.9/main'), tmp_path)
    assert {h['call_id'] for h in a['sources'][0]['found_by']} == {'a1', 'b2'}


def test_every_call_has_its_own_id(tmp_path):
    s, _ = searcher(tmp_path, PILOT)
    ids = [s.status('PMC8755536')['call_id'] for _ in range(3)]
    assert len(set(ids)) == 3


SIMILAR = [('PMCID%3APMC8755536', 'target.json'), ('linkname=pubmed_pubmed&', 'similar-elink.json'),
           ('EXT_ID', 'similar-lookup.json')]


def test_similar_keeps_pubmeds_order_and_score_and_leaves_out_the_article(tmp_path):
    s, _ = searcher(tmp_path, SIMILAR)
    r = s.similar('PMC8755536')
    assert r['outcome'] == 'ok' and 'cmd=neighbor_score' in r['responses'][1]['url']
    assert [w['rank'] for w in r['works']] == [1, 2, 3]
    assert all(w['pmid'] != '34937938' for w in r['works'])
    assert all(isinstance(w['score'], int) for w in r['works'])
    assert sum(1 for w in r['works'] if w.get('note')) == 1     # kept, though Europe PMC returned no record


def test_terms_are_the_articles_mesh_headings_and_keywords(tmp_path):
    s, _ = searcher(tmp_path, [('PMCID%3APMC8755536', 'target-terms.json')])
    r = s.terms('PMC8755536')
    assert r['outcome'] == 'ok' and r['works'] == []
    major = {m['heading'] for m in r['mesh'] if m['major']}
    assert {'Neoplasms', 'Mammals'} <= major and 'Body Size' in {m['heading'] for m in r['mesh']}


def test_literature_sorted_by_citations_asks_each_service_in_its_own_terms(tmp_path):
    s, _ = searcher(tmp_path, LITERATURE)
    epmc, _, pubmed, _ = s.literature('peto paradox body size', limit=6, sort='cited')
    assert (epmc['ask']['sort'], pubmed['ask']['sort']) == ('CITED desc', 'relevance')
    assert 'sort=CITED+desc' in epmc['responses'][0]['url'] and 'sort=relevance' in pubmed['responses'][0]['url']
    assert [w['rank'] for w in epmc['works']] == list(range(1, 7))
    text = search.report(tmp_path)
    assert 'order: CITED desc' in text and 'order: Best Match (not repeatable' in text


def test_literature_by_default_sends_no_order(tmp_path):
    s, _ = searcher(tmp_path, LITERATURE)
    epmc, _, pubmed, _ = s.literature('peto paradox body size', limit=6)
    assert epmc['ask']['sort'] is None and 'sort=' not in epmc['responses'][0]['url']
    assert 'sort=' not in pubmed['responses'][0]['url']
    with pytest.raises(search.SearchError):
        s.literature('x', sort='newest')


# -- references in a submitted text (U2) ------------------------------------------------------------

REFS_TEXT = ('A claim of our own.\n\n'
             'Soft substrates gather lysosomes [Wang et al., *iScience*, 2018](https://doi.org/10.1016/j.isci.2018.05.016).\n\n'
             'A made-up year [Wang et al., *iScience*, 2016](https://doi.org/10.1016/j.isci.2018.05.016).\n\n'
             'A made-up work [Lee et al., *iScience*, 2099](https://doi.org/10.1016/j.isci.2099.01.001).\n\n'
             'A wrong title [*Lysosomes and the moon*](https://doi.org/10.1016/j.isci.2018.05.016).\n\n'
             'Named only, Wang et al., *iScience*, 2018, with no link.\n')


def ref_net(tmp_path):
    routes = [('10.1016%2Fj.isci.2018.05.016', 'ref-wang-epmc.json'), ('10.1016%2Fj.isci.2099.01.001', 'ref-none-epmc.json'),
              ('AUTH%3A%22Wang%22', 'ref-ambiguous-epmc.json')]
    s, _ = searcher(tmp_path, routes)
    return s


def test_references_are_read_with_what_they_claim(tmp_path):
    refs = search.references_in(REFS_TEXT)
    assert [r['paragraph'] for r in refs] == [2, 3, 4, 5, 6]
    assert refs[0]['ids'] == {'doi': '10.1016/j.isci.2018.05.016'}
    assert refs[0]['claimed'] == {'first_author': 'Wang', 'year': '2018', 'journal': 'iScience'}
    assert refs[3]['claimed'] == {'title': 'Lysosomes and the moon'}
    assert refs[4]['ids'] == {} and refs[4]['claimed']['first_author'] == 'Wang'


def test_existence_correspondence_and_relevance_are_three_answers(tmp_path):
    out = ref_net(tmp_path).check_refs(REFS_TEXT)
    by = {r['ask']['paragraph']: r for r in out}
    assert all(r['outcome'] == 'ok' and r['relevance'] == 'not_assessed' for r in out)
    assert (by[2]['exists'], by[2]['matches']) == ('verified', 'match')
    # The work exists, but the reference says something else of it: a made-up year, a wrong title.
    assert (by[3]['exists'], by[3]['matches']) == ('verified', 'mismatch')
    assert by[3]['differences'] == [{'field': 'year', 'reference': '2016', 'record': '2018'}]
    assert (by[5]['exists'], by[5]['matches']) == ('verified', 'mismatch')
    assert by[5]['differences'][0]['field'] == 'title'
    # No such work in Europe PMC or Crossref (404).
    assert (by[4]['exists'], by[4]['matches']) == ('not_found', 'not_checked')
    # A reference with no identifier that a search cannot pin to one work is not a verified source.
    assert by[6]['exists'] == 'ambiguous' and by[6]['found_by'] == 'author, year and journal'


def test_a_verified_reference_is_a_found_work_and_the_others_are_not(tmp_path):
    out = ref_net(tmp_path).check_refs(REFS_TEXT)
    assert [len(r['works']) for r in out] == [1, 1, 0, 1, 0]
    text = search.refs_text(out)
    assert 'relevance not_assessed' in text and "year: '2016' vs '2018'" in text and 'exists not_found' in text


# -- the state of a source on a cutoff date ---------------------------------------------------------

def test_a_work_known_online_before_print_is_dated_by_its_online_date():
    assert search.earliest({'online': '2021-02-03', 'print': '2021-03', 'record': None}) == ('online', '2021-02-03')
    assert search.earliest({'print': '2021', 'record': '2021-05-01'}) == ('print', '2021')
    assert search.earliest({'online': None}) == (None, None)


@pytest.mark.parametrize('dated,release,value,basis,reason', [
    ('2019-04', '2026-09-30', 'Phase 3', 'dated', None),
    ('2021-03-02', None, None, None, 'after_cutoff'),
    ('2021-03', None, None, None, 'straddles_cutoff'),
    ('2021', None, None, None, 'straddles_cutoff'),
    (None, '2020-12-31', 'Phase 3', 'release', None),
    (None, '2026-09-30', None, None, 'undated'),
    (None, None, None, None, 'undated'),
])
def test_a_value_that_changes_with_time_is_kept_only_when_known_by_the_cutoff(dated, release, value, basis, reason):
    r = search.as_of('Phase 3', dated, '2021-03-01', release)
    assert (r['value'], r['basis'], r['reason']) == (value, basis, reason)
    assert (r['stated'], r['dated'], r['release'], r['cutoff']) == ('Phase 3', dated, release, '2021-03-01')
    assert reason is None or reason in search.AS_OF_REASONS


def test_the_cutoff_is_inclusive():
    assert search.as_of('Recruiting', '2021-03-01', '2021-03-01')['value'] == 'Recruiting'


@pytest.mark.parametrize('bad', ['2021-03-01T00:00:00Z', '2021-03', '2021-02-30', 20210301, None])
def test_the_cutoff_is_a_day_not_a_time_or_a_month(bad):
    with pytest.raises(search.SearchError):
        search.as_of('x', None, bad)


def test_a_date_that_is_not_a_date_is_refused():
    with pytest.raises(search.SearchError):
        search.earliest({'online': '3 March 2021'})


@pytest.mark.parametrize('text,iso', [
    ('2024-10-24', '2024-10-24'), ('2024/10/24 08:22', '2024-10-24'), ('2025 Jan 13', '2025-01-13'),
    ('2025 Jan', '2025-01'), ('2025 Jan-Feb', '2025-01'), ('2025 Spring', '2025'), ('2025', '2025'),
    ('', None), (None, None),
])
def test_a_service_date_is_kept_to_the_precision_it_states(text, iso):
    assert search.iso_date(text) == iso


def test_a_work_indexed_online_before_its_publication_date_is_dated_by_the_index():
    # Compton et al. 2025, Cancer Discov: published 2025-01-01, in Europe PMC and PubMed from 2024-10-24.
    epmc = {'source': 'MED', 'id': '39445720', 'firstPublicationDate': '2025-01-01', 'firstIndexDate': '2024-10-24',
            'journalInfo': {'printPublicationDate': '2025-01-01'}}
    pubmed = {'uid': '39445720', 'pubdate': '2025 Jan 13', 'epubdate': '',
              'history': [{'pubstatus': 'accepted', 'date': '2024/09/24 00:00'},
                          {'pubstatus': 'entrez', 'date': '2024/10/24 08:22'}]}
    assert search.work_epmc(epmc)['dates'] == {'online': None, 'first': '2025-01-01', 'print': '2025-01-01',
                                               'record': '2024-10-24'}
    assert search.work_pubmed(pubmed)['dates'] == {'online': None, 'print': '2025-01-13', 'record': '2024-10-24'}
    assert search.earliest(search.work_epmc(epmc)['dates']) == ('record', '2024-10-24')
    assert search.earliest(search.work_pubmed(pubmed)['dates']) == ('record', '2024-10-24')


def test_works_are_cut_at_the_cutoff_by_their_earliest_date():
    works = [{'source_id': 'A', 'dates': {'online': None, 'print': '2021-04', 'record': '2021-02-20'}},
             {'source_id': 'B', 'dates': {'online': '2021-03-02', 'print': '2021-05-01'}},
             {'source_id': 'C', 'dates': {'print': '2021'}},
             {'source_id': 'D'}]
    kept, left = search.cut(works, '2021-03-01')
    assert [w['source_id'] for w in kept] == ['A', 'C', 'D']
    assert [w['cutoff'] for w in kept] == [{'by': 'record', 'date': '2021-02-20', 'before': True},
                                           {'by': 'print', 'date': '2021', 'before': None},
                                           {'by': None, 'date': None, 'before': None}]
    assert left == [{'source_id': 'B', 'title': None, 'by': 'online', 'date': '2021-03-02', 'before': False}]


def test_literature_as_of_asks_each_service_for_what_it_had_by_then(tmp_path):
    s, _ = searcher(tmp_path, [('search?query=', 'lookup.json')] + PILOT)
    epmc, _, pubmed, _ = s.literature('peto paradox body size', limit=6, as_of='2021-03-01')
    assert epmc['ask']['as_of'] == pubmed['ask']['as_of'] == '2021-03-01'
    assert 'FIRST_IDATE%3A%5B1000-01-01+TO+2021-03-01%5D' in epmc['responses'][0]['url']
    assert '%222021%2F03%2F01%22%5BEDAT%5D' in pubmed['responses'][0]['url']
    assert epmc['ask']['query'] == 'peto paradox body size' and 'FIRST_PDATE' in epmc['ask']['sent']
    # The trimmed Europe PMC records carry no dates: kept, marked undetermined, not dropped unseen.
    assert epmc['found'] == 6 and {w['cutoff']['before'] for w in epmc['works']} == {None}
    # The PubMed summaries are of 2026 works: both left out, each with the date that dropped it.
    assert pubmed['found'] == 0 and [(w['by'], w['date'][:4]) for w in pubmed['left_out']] == [('print', '2026')] * 2
    text = search.report(tmp_path)
    assert 'as of 2021-03-01' in text and 'left out as later than the cutoff' in text
    assert "order: the service's default, most recent first" in text


def test_status_as_of_counts_only_the_notices_dated_by_then(tmp_path):
    s, _ = searcher(tmp_path, RETRACTED)
    r = s.status('9500320', as_of='2005-01-01')
    assert r['status'] == 'corrected'
    assert [n['notice'] for n in r['left_out']] == ['10.1016/s0140-6736(10)60175-4']
    assert {n['from'] for n in r['undetermined']} == {'europepmc', 'europepmc pubType'}
    assert search.Searcher(tmp_path / 'b', get=Net(RETRACTED), sleep=lambda _: None,
                           clock=lambda: 0.0).status('9500320', as_of='2003-01-01')['status'] == 'none_found'


def test_cited_by_as_of_keeps_the_ask_and_the_works_dropped(tmp_path):
    s, _ = searcher(tmp_path, PILOT)
    r = s.cited_by('PMC8755536', as_of='2022-06-30')
    assert r['ask'] == {'id': 'PMC8755536', 'limit': 2000, 'as_of': '2022-06-30'}
    assert r['hit_count'] == r['found'] + len(r['left_out'])


@pytest.mark.parametrize('argv', [['terms', 'PMC1', '--as-of', '2021-01-01'],
                                  ['check-refs', 'x.md', '--as-of', '2021-01-01']])
def test_as_of_is_refused_where_it_does_not_apply(argv):
    with pytest.raises(SystemExit):
        search.main(argv)


def test_a_cutoff_that_is_not_a_day_stops_the_search_before_any_request(tmp_path):
    s, _ = searcher(tmp_path, PILOT)
    with pytest.raises(search.SearchError):
        s.literature('x', as_of='2021-03')
    assert not (tmp_path / search.LOG).exists()


# -- ClinicalTrials.gov -------------------------------------------------------------------------------
# NCT00000620 (ACCORD): registered 1999-10-28, results posted 2014-09-15, last updated 2016-11-22.
CTGOV = [('studies/NCT', 'ctgov-study.json'), ('v2/version', 'ctgov-version.json'), ('v2/studies?', 'ctgov-search.json')]


def test_a_trial_is_recorded_with_its_status_phases_dates_and_primary_outcomes(tmp_path):
    s, sleeps = searcher(tmp_path, CTGOV)
    r = s.trial('NCT00000620')
    t = r['trial']
    assert (r['outcome'], t['status'], t['phases'], t['has_results']) == ('ok', 'COMPLETED', ['PHASE3'], True)
    assert t['dates'] == {'registered': '1999-10-28', 'results': '2014-09-15', 'last_update': '2016-11-22'}
    assert t['primary_outcomes'][0]['measure'].startswith('First Occurrence of a Major Cardiovascular Event')
    assert 'description' not in json.dumps(t) and r['release'] == '2026-10-21T09:00:05'
    assert sleeps and min(sleeps) > 1.0


@pytest.mark.parametrize('cutoff,status,results,registered,reason', [
    ('2020-01-01', 'COMPLETED', True, True, None),
    ('2016-11-22', 'COMPLETED', True, True, None),
    ('2010-01-01', None, False, True, 'undated'),
    ('1999-01-01', None, False, False, 'undated'),
])
def test_a_trial_as_of_a_day_keeps_its_fields_only_if_the_record_was_last_updated_by_then(
        tmp_path, cutoff, status, results, registered, reason):
    r = search.Searcher(tmp_path, get=Net(CTGOV), sleep=lambda _: None, clock=lambda: 0.0).trial('NCT00000620', cutoff)
    t = r['trial']
    assert (t['status'], t['has_results'], t['as_of']['registered'], t['as_of']['reason']) == (
        status, results, registered, reason)
    assert all(t[k] is None for k in search.TRIAL_CHANGING) == (status is None)
    assert r['stated']['status'] == 'COMPLETED' and r['ask']['as_of'] == cutoff


def test_trials_as_of_asks_only_for_studies_registered_by_then(tmp_path):
    s, _ = searcher(tmp_path, CTGOV)
    r = s.trials('rapamycin aging', limit=3, as_of='2021-03-01')
    assert 'AREA%5BStudyFirstPostDate%5DRANGE%5BMIN%2C2021-03-01%5D' in r['responses'][0]['url']
    # The fixture answers without the filter: the 2025 study is left out by its own date all the same.
    assert [w['nct'] for w in r['works']] == ['NCT01922167', 'NCT04608448']
    assert [w['source_id'] for w in r['left_out']] == ['NCT:NCT06789900']
    first, second = r['works']
    assert first['status'] == 'COMPLETED' and first['as_of']['basis'] == 'release'
    assert second['status'] is None and second['has_results'] is False


def test_a_trial_id_that_is_not_an_nct_number_is_a_failed_call(tmp_path):
    s, _ = searcher(tmp_path, CTGOV)
    r = s.trial('NCT123')
    assert r['outcome'] == 'failed' and r['responses'] == []


# -- where a full text can be read ----------------------------------------------------------------------
PREPRINT = [('DOI%3A%2210.1101', 'text-preprint-epmc.json'), ('api.biorxiv.org/details/biorxiv', 'text-biorxiv.json')]


def test_text_of_a_preprint_is_the_latest_jats_of_biorxiv_with_its_licence(tmp_path, monkeypatch):
    monkeypatch.setattr(search, 'CONTACT', None)
    s, _ = searcher(tmp_path, PREPRINT)
    r = s.text('10.1101/2022.07.12.499088')
    jats = [p for p in r['places'] if p['kind'] == 'jats']
    assert jats == [{'kind': 'jats', 'from': 'biorxiv', 'licence': 'cc_by_nc_nd', 'licence_from': 'biorxiv api license field',
                     'version': '3', 'date': '2024-07-24', 'published': None,
                     'url': 'https://www.biorxiv.org/content/early/2024/07/24/2022.07.12.499088.source.xml'}]
    assert r['skipped'] == ['unpaywall: it asks for a contact address; set OHF_CONTACT'] and r['errors'] == {}
    assert 'abstract' not in json.dumps(r).lower()


def test_text_of_a_pmc_article_is_its_jats_and_bioc_under_the_records_licence(tmp_path):
    s, _ = searcher(tmp_path, [('PMCID%3APMC11726020', 'text-pmc-epmc.json')])
    r = s.text('PMC11726020')
    first = r['places'][0]
    assert (first['kind'], first['url'], first['licence']) == (
        'jats', 'https://www.ebi.ac.uk/europepmc/webservices/rest/PMC11726020/fullTextXML', 'cc by-nc-nd')
    assert len({p['url'] for p in r['places']}) == len(r['places'])
    assert all(p['licence'] is None for p in r['places'] if p['from'].startswith('europepmc fullTextUrlList'))


def test_text_of_an_arxiv_paper_is_its_pdf_with_the_licence_arxiv_records(tmp_path):
    s, _ = searcher(tmp_path, [('oaipmh.arxiv.org', 'text-arxiv.xml')])
    r = s.text('10.48550/arXiv.1706.03762')
    assert r['places'] == [{'kind': 'pdf', 'url': 'https://arxiv.org/pdf/1706.03762', 'from': 'arxiv',
                            'licence': 'http://arxiv.org/licenses/nonexclusive-distrib/1.0/',
                            'licence_from': 'arxiv oai-pmh license'}]
    assert 'identifier=oai%3AarXiv.org%3A1706.03762' in r['responses'][0]['url']


def test_text_asks_unpaywall_only_with_a_contact_and_survives_its_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(search, 'CONTACT', 'curator@example.org')
    s, _ = searcher(tmp_path, PREPRINT + [('api.unpaywall.org', 'text-unpaywall-synthetic.json')])
    r = s.text('10.1101/2022.07.12.499088')
    up = [p for p in r['places'] if p['from'].startswith('unpaywall')]
    assert up and up[0]['licence'] == 'cc-by-nc-nd' and r['skipped'] == []
    assert 'email=curator%40example.org' in [x['url'] for x in r['responses'] if 'unpaywall' in x['url']][0]
    s2, _ = searcher(tmp_path / 'b', PREPRINT)
    r2 = s2.text('10.1101/2022.07.12.499088')
    assert r2['outcome'] == 'ok' and 'HTTP 404' in r2['errors']['unpaywall']


# -- literature without reviews; works read and not cited (audit items 11 and 7) --------------------

def test_literature_sends_each_query_again_without_reviews(tmp_path):
    s, _ = searcher(tmp_path, LITERATURE)
    out = s.literature('peto paradox body size', limit=6)
    assert [(r['ask']['source'], r['ask']['variant']) for r in out] == [
        ('europepmc', 'as_given'), ('europepmc', 'no_reviews'), ('pubmed', 'as_given'), ('pubmed', 'no_reviews')]
    assert all(r['outcome'] == 'ok' for r in out)
    assert out[1]['ask']['sent'] == '(peto paradox body size) NOT PUB_TYPE:review'
    assert 'NOT+PUB_TYPE%3Areview' in out[1]['responses'][0]['url']
    assert out[3]['ask']['sent'] == '(peto paradox body size) NOT review[pt]'
    assert 'NOT+review%5Bpt%5D' in out[3]['responses'][0]['url']
    assert 'sent' not in out[0]['ask'] and 'PUB_TYPE' not in out[0]['responses'][0]['url']
    text = search.report(tmp_path)
    assert text.count('reviews excluded') == 2 and 'CHECK' not in text


def test_literature_without_reviews_keeps_the_cutoff(tmp_path):
    s, _ = searcher(tmp_path, [('search?query=', 'lookup.json')] + PILOT)
    out = s.literature('peto paradox body size', limit=6, as_of='2021-03-01')
    epmc, pubmed = out[1]['ask']['sent'], out[3]['ask']['sent']
    assert epmc.startswith('((peto paradox body size) NOT PUB_TYPE:review) AND (FIRST_IDATE')
    assert pubmed.startswith('((peto paradox body size) NOT review[pt]) AND ("1000/01/01"[EDAT]')


def test_report_flags_a_literature_query_never_run_without_reviews(tmp_path):
    s, _ = searcher(tmp_path, LITERATURE)
    s.literature('peto paradox body size', limit=6, sources=('europepmc',))
    log = tmp_path / search.LOG
    as_given, no_reviews = [json.loads(x) for x in log.read_text().splitlines()]
    # The mutant: the variant dropped (as a log from before the variants has it), the query as given alone.
    log.write_text(json.dumps(as_given) + '\n')
    assert "CHECK: literature europepmc 'peto paradox body size' has no successful run without reviews" \
        in search.report(tmp_path)
    # The mutant: a record marked without reviews whose query does not exclude them.
    no_reviews['ask']['sent'] = 'peto paradox body size'
    log.write_text(json.dumps(as_given) + '\n' + json.dumps(no_reviews) + '\n')
    text = search.report(tmp_path)
    assert 'is marked without reviews, but its query does not exclude them' in text
    assert 'has no successful run without reviews' in text


def test_a_work_read_and_not_cited_is_logged_with_its_reason_and_locator(tmp_path):
    s, _ = searcher(tmp_path, PILOT)
    r = s.not_cited('PMC8755536', 'other_species', 'Methods, cohort', atom='a2')
    assert r['outcome'] == 'ok' and r['tool'] == 'not_cited' and r['works'] == []
    assert r['ask'] == {'id': 'PMC8755536', 'reason': 'other_species', 'locator': 'Methods, cohort', 'atom': 'a2'}
    assert r['work']['pmcid'] == 'PMC8755536' and 'abstract' not in json.dumps(r).lower()
    text = search.report(tmp_path)
    assert "read, not cited 'PMC8755536' [other_species; at Methods, cohort]" in text
    assert 'Read, not cited: 1 (other_species 1)' in text and 'INVALID' not in text


def test_a_reason_outside_the_closed_list_is_refused_and_nothing_is_logged(tmp_path):
    s, _ = searcher(tmp_path, PILOT)
    # The mutants: a free reason, an empty locator. Neither reaches the log.
    with pytest.raises(search.SearchError, match='reason: one of'):
        s.not_cited('PMC8755536', 'weak study', 'Results')
    with pytest.raises(search.SearchError, match='locator'):
        s.not_cited('PMC8755536', 'off_topic', '  ')
    assert not (tmp_path / search.LOG).exists()
    with pytest.raises(SystemExit):
        search.main(['not-cited', 'PMC8755536', '--reason', 'weak', '--locator', 'x', '--workdir', str(tmp_path)])
    # A log edited by hand past the list is caught by the report.
    s.not_cited('PMC8755536', 'off_topic', 'Abstract')
    log = tmp_path / search.LOG
    rec = json.loads(log.read_text())
    rec['ask']['reason'] = 'not convincing'
    log.write_text(json.dumps(rec) + '\n')
    assert 'INVALID: the reason must be one of other_species' in search.report(tmp_path)


def test_attribution_flags_a_work_both_cited_and_logged_as_not_cited(tmp_path):
    s, _ = searcher(tmp_path, PILOT)
    cites = s.cited_by('PMC8755536')
    s.not_cited('PMC11892590', 'subgroup_only', 'Table 2')       # Butler: no record of it in these fixtures
    kept = s.not_cited('PMC9999999', 'off_topic', 'Abstract')
    card = cited_card(search.EPMC + 'PMC8755536/fullTextXML', search.EPMC + 'PMC11892590/fullTextXML')
    a = search.attribute(card, tmp_path)
    assert [c['call_id'] for c in a['calls_without_card_source']] == []
    assert [(r['id'], r['cited_as']) for r in a['read_not_cited']] == [('PMC11892590', ['pmc11892590']),
                                                                      ('PMC9999999', [])]
    text = search.attribution_text(a)
    assert 'read, not cited: PMC11892590 (subgroup_only; at Table 2' in text
    assert text.count('CONFLICT') == 1 and kept['call_id'] in text and cites['call_id'] in text


# -- relevance of a reference, by a separate checker (U2) ------------------------------------------

def relevance_setup(tmp_path):
    ref_net(tmp_path).check_refs(REFS_TEXT)
    inp = search.relevance_input(REFS_TEXT, tmp_path)
    good = {'checker': {'name': 'relevance-checker', 'model': 'm2'},
            'verdicts': [{'item': 1, 'cited_in_sha256': inp['items'][0]['cited_in_sha256'],
                          'outcome': 'related_not_claim', 'locator': 'abstract'}]}
    return inp, good


def relevance_records(tmp_path):
    return [r for r in search.read_log(tmp_path) if r['tool'] == 'relevance']


def test_only_a_verified_matching_reference_goes_to_the_relevance_checker(tmp_path):
    inp, _ = relevance_setup(tmp_path)
    assert [(i['paragraph'], i['work']['doi']) for i in inp['items']] == [(2, '10.1016/j.isci.2018.05.016')]
    assert inp['items'][0]['cited_in'].startswith('Soft substrates gather lysosomes')
    assert 'https://doi.org/10.1016/j.isci.2018.05.016' in inp['items'][0]['read_at']
    # Mismatched year and title, a made-up work and an ambiguous one are not sent: never a source.
    assert sorted((n['paragraph'], n['why']) for n in inp['not_sent']) == [
        (3, 'matches mismatch'), (4, 'not_found'), (5, 'matches mismatch'), (6, 'ambiguous')]
    assert inp['prompt'] == 'relevance.md' and inp['outcomes'] == sorted(search.RELEVANCE)


def test_relevance_verdicts_are_logged_with_checker_extractor_and_locator(tmp_path):
    inp, good = relevance_setup(tmp_path)
    out = search.relevance_merge(REFS_TEXT, inp, good, 'converter-a', tmp_path, extractor_model='m1')
    assert [(r['relevance'], r['locator'], r['checker']['name'], r['extractor'], r['same_model']) for r in out] == [
        ('related_not_claim', 'abstract', 'relevance-checker', 'converter-a', False)]
    text = search.report(tmp_path)
    assert 'relevance p2' in text and 'related_not_claim at abstract (checker relevance-checker, m2; extractor converter-a)' in text
    same = dict(good, checker={'name': 'relevance-checker', 'model': 'm1'})
    search.relevance_merge(REFS_TEXT, inp, same, 'converter-a', tmp_path, extractor_model='m1')
    assert '(the same model, a separate run)' in search.report(tmp_path)


@pytest.mark.parametrize('mutate, message', [
    (lambda v, inp: v.update(checker={'name': 'converter-a'}), 'must not be the extractor'),
    (lambda v, inp: v.update(checker={}), 'name of the separate checker'),
    (lambda v, inp: v['verdicts'][0].update(outcome='partly'), 'outcome one of'),
    (lambda v, inp: v['verdicts'][0].update(locator=' '), 'locator'),
    (lambda v, inp: v['verdicts'][0].update(note='The abstract says: ...'), 'only item, cited_in_sha256'),
    (lambda v, inp: v['verdicts'][0].update(cited_in_sha256='sha256:0'), 'not on the paragraph the input showed'),
    (lambda v, inp: v['verdicts'].clear(), 'items without a verdict'),
    (lambda v, inp: v['verdicts'].append(dict(v['verdicts'][0], item=9)), 'which the input does not have'),
])
def test_a_relevance_verdict_out_of_form_is_refused_and_nothing_is_logged(tmp_path, mutate, message):
    inp, verdicts = relevance_setup(tmp_path)
    mutate(verdicts, inp)
    with pytest.raises(search.SearchError, match=message):
        search.relevance_merge(REFS_TEXT, inp, verdicts, 'converter-a', tmp_path)
    assert relevance_records(tmp_path) == []


def test_a_relevance_verdict_on_a_changed_text_is_refused(tmp_path):
    inp, good = relevance_setup(tmp_path)
    changed = REFS_TEXT.replace('Soft substrates gather', 'Stiff substrates scatter')
    with pytest.raises(search.SearchError, match='not the one the input was built from'):
        search.relevance_merge(changed, inp, good, 'converter-a', tmp_path)
    with pytest.raises(search.SearchError, match='is not in this text'):
        search.relevance_input(REFS_TEXT.replace('[Wang et al., *iScience*, 2018]', '[Wang 2018]'), tmp_path)
    assert relevance_records(tmp_path) == []


# -- accepted cards that may state the same hypothesis ------------------------------------------------

ACCEPTED = sorted((FIX.parent / 'exemplars' / 'cards').glob('*.json'))


def accepted():
    return [json.loads(p.read_text()) for p in ACCEPTED]


def test_a_restated_hypothesis_finds_its_accepted_card_with_the_reason(tmp_path):
    text = ('Giving rapamycin intermittently at a low dose may inhibit mTORC1 but spare mTORC2, '
            'so that hyperglycemia and immunosuppression are avoided while lifespan is still extended.')
    s = search.Searcher(tmp_path)
    r = s.similar_cards(text, accepted())
    top = r['candidates'][0]
    assert top['card'] == 'h_intermittent-rapamycin-mtorc2' and {'mtorc2', 'rapamycin'} <= set(top['shared_terms'])
    assert r['hit_count'] == len(ACCEPTED) and r['works'] == []
    assert 'similar cards of text sha256:' in search.report(tmp_path) and 'h_intermittent-rapamycin-mtorc2 v1' in \
        search.report(tmp_path)


def test_a_text_citing_a_cards_source_is_a_candidate_even_with_no_shared_words(tmp_path):
    # The mutant this guards: matching by words alone. A short note citing the Peto card's article
    # shares no distinctive word with it.
    text = 'Как и здесь: https://doi.org/10.1038/s41586-021-04224-5'
    found = {c['card']: c for c in search.similar_cards(text, accepted())}
    assert found['h_peto-paradox-mammals']['shared_terms'] == []
    assert found['h_peto-paradox-mammals']['shared_works'] == ['10.1038/s41586-021-04224-5']


def test_an_unrelated_text_has_no_candidates_and_nothing_is_refused(tmp_path):
    text = 'Volcanic ash layers in lake sediments record eruptions of the Holocene.'
    r = search.Searcher(tmp_path).similar_cards(text, accepted())
    assert r['outcome'] == 'ok' and r['candidates'] == []
    # The count is the accepted set's own size, not a number typed here: the fixture directory
    # held nine cards until the accepted eight replaced them, and a hard-coded count would
    # fail for the right reason in the wrong place.
    assert f'among {len(accepted())}: none' in search.report(tmp_path)


def test_the_relevance_commands_take_their_files_after_the_text(tmp_path, monkeypatch):
    (tmp_path / 'a.md').write_text(REFS_TEXT)
    net = Net([('10.1016%2Fj.isci.2018.05.016', 'ref-wang-epmc.json'), ('10.1016%2Fj.isci.2099.01.001', 'ref-none-epmc.json'),
               ('AUTH%3A%22Wang%22', 'ref-ambiguous-epmc.json')])
    monkeypatch.setattr(search, 'http_get', net)
    monkeypatch.setattr(search.Searcher.__init__, '__defaults__', ('.', net, lambda _: None, lambda: 0.0))
    w = ['--workdir', str(tmp_path)]
    assert search.main(['check-refs', str(tmp_path / 'a.md')] + w) == 0
    assert search.main(['relevance-input', str(tmp_path / 'a.md'), str(tmp_path / 'in.json')] + w) == 0
    inp = json.loads((tmp_path / 'in.json').read_text())
    (tmp_path / 'v.json').write_text(json.dumps({'checker': {'name': 'c'}, 'verdicts': [
        {'item': 1, 'cited_in_sha256': inp['items'][0]['cited_in_sha256'], 'outcome': 'unrelated', 'locator': 'abstract'}]}))
    assert search.main(['relevance-merge', str(tmp_path / 'a.md'), str(tmp_path / 'in.json'), str(tmp_path / 'v.json'),
                        '--extractor', 'x'] + w) == 0
    assert relevance_records(tmp_path)[0]['relevance'] == 'unrelated'


# -- a numbered reference list (a blog, a preprint) ------------------------------------------------

LIST_TEXT = ('Novelty drives variable behaviour [3]. Habits limit it [62-64], as do rituals [3, 4].\n\n'
             'Nothing cited here.\n\n'
             'References:\n\n'
             '3. Shahan TA, Chase PN (2002) Novelty, stimulus control, and operant variability. Behavior Analyst 25: 175-190.\n\n'
             '4. Roberts S, Gharib A (2006) Variation of bar-press duration: Where do new responses come from? Behavioural Processes\n\n'
             'Proceedings of the Meeting of the Society 72: 215-223.\n\n'
             '62. de Ruyter van Steveninck RR, Lewen GD (1997) Reproducibility and variability in neural spike trains. Science 275: 1805-1808. doi:10.1126/science.275.5307.1805\n\n'
             '63. Kant I (1781) Critique of Pure Reason.\n\n'
             '64. James W (1890) The Principles of Psychology. New York: Holt.\n')


def test_a_numbered_reference_list_is_read_with_the_paragraphs_that_cite_each_entry():
    refs = {r['number']: r for r in search.references_in(LIST_TEXT)}
    assert sorted(refs) == [3, 4, 62, 63, 64]
    assert refs[3]['cited_in'] == [1] and refs[63]['cited_in'] == [1] and refs[4]['cited_in'] == [1]
    assert refs[3]['claimed'] == {'first_author': 'Shahan', 'year': '2002',
                                  'title': 'Novelty, stimulus control, and operant variability'}
    # An entry broken over two paragraphs is one entry; the continuation is not a reference of its own.
    assert refs[4]['claimed']['title'] == 'Variation of bar-press duration: Where do new responses come from?'
    assert refs[62]['claimed']['first_author'] == 'de Ruyter van Steveninck'
    assert refs[62]['ids'] == {'doi': '10.1126/science.275.5307.1805'}
    # The DOI inside the list is not read a second time as a bare reference.
    assert len(search.references_in(LIST_TEXT)) == 5
    assert search.cited_numbers('33, 34-36') == [33, 34, 35, 36]


def test_a_reference_matches_its_record_across_diacritics_online_years_and_subtitles():
    rec = {'title': 'Why does the brain predict sensory consequences of oculomotor commands? Optimal integration.',
           'first_author': 'Jabłoński', 'year': '2006', 'dates': {'online': '2005-09-01'}}
    claimed = {'title': 'Why Does the Brain Predict Sensory Consequences of Oculomotor Commands?',
               'first_author': 'Jablonski', 'year': '2005'}
    assert search.compare(claimed, rec) == ('match', [])
    # The mutants: a title that is not a prefix, an author who is another, a year no date gives.
    assert search.compare(dict(claimed, title='Why does the eye move?'), rec)[0] == 'mismatch'
    assert search.compare(dict(claimed, first_author='Jablonsky'), rec)[0] == 'mismatch'
    assert search.compare(dict(claimed, year='2004'), rec)[0] == 'mismatch'
    assert search.surname('de Ruyter van Steveninck RR') == 'de Ruyter van Steveninck' and search.surname('Kant I') == 'Kant'


def test_a_work_found_by_description_under_another_title_is_not_found(tmp_path):
    text = ('Will is felt [1].\n\nReferences:\n\n'
            '1. Wegner DM (2002) The illusion of conscious will. Boston: MIT press.\n')
    s, _ = searcher(tmp_path, [('AUTH%3A%22Wegner%22', 'desc-epmc-precis.json')])
    r = s.check_refs(text)[0]
    assert r['exists'] == 'not_found' and r['closest']['title'].startswith('Precis') and r['works'] == []
    assert r['found_by'] == 'author and title'


def test_a_work_europe_pmc_lacks_is_found_through_crossref_by_title_and_author(tmp_path):
    text = ('Goals are learned [1].\n\nReferences:\n\n'
            '1. Rescorla RA (1987) A Pavlovian analysis of goal-directed behavior. American Psychologist 42: 119-129.\n')
    s, _ = searcher(tmp_path, [('AUTH%3A%22Rescorla%22', 'desc-epmc-none.json'),
                               ('api.crossref.org/works?query.bibliographic', 'desc-crossref-rescorla.json')])
    r = s.check_refs(text)[0]
    assert (r['exists'], r['matches']) == ('verified', 'match') and r['record']['doi'] == '10.1037/0003-066X.42.2.119'
    assert r['found_by'] == 'author and title (Crossref bibliographic search)'
    # The query sent to Europe PMC leaves the year out and the punctuation of the title.
    assert 'PUB_YEAR' not in r['responses'][0]['url'] and 'goal-directed+behavior%22' in r['responses'][0]['url']


def test_a_numbered_entry_goes_to_the_checker_with_each_paragraph_that_cites_it(tmp_path):
    s = search.Searcher(tmp_path)
    refs = search.references_in(LIST_TEXT)
    for ref in refs:   # as check_refs logs them, the Shahan entry verified, the others not found
        ok = ref['number'] == 3
        s.log({'call_id': f"c{ref['number']}", 'tool': 'check_ref', 'started_at': 't', 'outcome': 'ok',
               'ask': {'id': ref['text'][:200], 'paragraph': ref['paragraph']}, 'reference': ref,
               'exists': 'verified' if ok else 'not_found', 'matches': 'match' if ok else 'not_checked',
               'record': {'source_id': 'MED:1', 'pmid': '1', 'title': 'Novelty', 'year': '2002'} if ok else None})
    inp = search.relevance_input(LIST_TEXT, tmp_path)
    assert [(i['paragraph'], i['number']) for i in inp['items']] == [(1, 3)]
    assert inp['items'][0]['cited_in'].startswith('Novelty drives variable behaviour [3]')
    good = {'checker': {'name': 'c'}, 'verdicts': [{'item': 1, 'cited_in_sha256': inp['items'][0]['cited_in_sha256'],
                                                     'outcome': 'supports_claim', 'locator': 'abstract'}]}
    assert search.relevance_merge(LIST_TEXT, inp, good, 'x', tmp_path)[0]['ask']['paragraph'] == 1


def test_a_long_text_sharing_common_words_with_every_card_has_no_candidate(tmp_path):
    # The mutant this guards: a score that grows with the length of the text, so that a long essay
    # is "similar" to every card. Here the text takes the same number of words from each card.
    words = []
    for c in accepted():
        words += sorted(search.terms_of(search.card_text(c)))[:12]
    assert search.similar_cards(' '.join(words) + '.', accepted()) == []


def test_the_reference_list_of_a_text_does_not_make_it_similar(tmp_path):
    # The works a text lists say what it read, not what it states: an unrelated essay that lists
    # rapamycin papers is not a candidate for the rapamycin card.
    text = ('Volcanic ash layers in lake sediments record eruptions of the Holocene [1, 2].\n\nReferences:\n\n'
            '1. Lamming DW (2012) Rapamycin-induced insulin resistance is mediated by mTORC2 loss and uncoupled '
            'from longevity. Science 335: 1638-1643.\n\n'
            '2. Arriola Apelo SI (2016) Alternative rapamycin treatment regimens mitigate the impact of rapamycin '
            'on glucose homeostasis and the immune system. Aging Cell 15: 28-38.\n')
    assert search.similar_cards(text, accepted()) == []


# -- support per claim; a second reading in the full text ---------------------------------------------

def log_relevance(s, check, para, outcome, basis='abstract_first', work=None):
    s.log({'call_id': f'{check}-{para}-{basis}', 'tool': 'relevance', 'outcome': 'ok', 'started_at': 't',
           'ask': {'id': check, 'paragraph': para, 'check': check}, 'relevance': outcome, 'locator': 'abstract',
           'work': work or {'pmid': check}, 'checker': {'name': 'c'}, 'extractor': 'x', 'basis': basis})


def test_support_is_the_share_of_readable_cited_works_that_state_the_claim_not_their_number(tmp_path):
    s = search.Searcher(tmp_path)
    for c, o in (('a', 'related_not_claim'), ('b', 'related_not_claim'), ('c', 'related_not_claim'),
                 ('d', 'not_retrievable')):
        log_relevance(s, c, 5, o)          # four works cited, none stating the claim
    for c in ('e', 'f'):
        log_relevance(s, c, 9, 'supports_claim')
    text = search.report(tmp_path)
    # The mutants: counting the works cited (4 "supported" by number), or counting an unread work as read.
    assert 'p5: 0/3 supports_claim; 1 not retrievable; NO SUPPORT' in text
    assert 'p9: 2/2 supports_claim' in text
    assert '1 of 2 claims have a supporting work; supports_claim in 2 of 5 readable pairs' in text


def test_a_full_text_reading_replaces_the_abstract_reading_of_the_same_pair(tmp_path):
    s = search.Searcher(tmp_path)
    log_relevance(s, 'a', 5, 'related_not_claim')
    log_relevance(s, 'a', 5, 'supports_claim', basis='full_text')
    text = search.report(tmp_path)
    assert 'p5: 1/1 supports_claim' in text and '1 pairs read again in the full text, 1 of them now supports_claim' in text


def test_a_recheck_sends_only_the_pairs_of_that_verdict_with_open_full_text_and_not_the_verdict(tmp_path):
    inp, good = relevance_setup(tmp_path)
    search.relevance_merge(REFS_TEXT, inp, good, 'converter-a', tmp_path)       # related_not_claim
    # No open full text found yet: nothing to send, the verdict stands.
    again = search.relevance_input(REFS_TEXT, tmp_path, recheck='related_not_claim')
    assert again['items'] == [] and again['not_sent'][-1]['why'].startswith('no open full text')
    s = search.Searcher(tmp_path)
    s.log({'call_id': 't1', 'tool': 'text', 'outcome': 'ok', 'started_at': 't', 'ask': {'id': '10.1016/j.isci.2018.05.016'},
           'hit_count': 1, 'found': 0, 'responses': [],
           'places': [{'kind': 'jats', 'url': 'https://example.org/x.xml', 'licence': 'cc by', 'from': 'europepmc'}]})
    again = search.relevance_input(REFS_TEXT, tmp_path, recheck='related_not_claim')
    assert [i['full_text'][0]['url'] for i in again['items']] == ['https://example.org/x.xml']
    assert again['basis'] == 'full_text' and 'related_not_claim' not in json.dumps(again['items'])
    assert search.relevance_input(REFS_TEXT, tmp_path, recheck='supports_claim')['items'] == []
    v = {'checker': {'name': 'c2'}, 'verdicts': [{'item': 1, 'cited_in_sha256': again['items'][0]['cited_in_sha256'],
                                                  'outcome': 'supports_claim', 'locator': 'Results'}]}
    assert search.relevance_merge(REFS_TEXT, again, v, 'converter-a', tmp_path)[0]['basis'] == 'full_text'
    assert 'p2: 1/1 supports_claim' in search.report(tmp_path)
    with pytest.raises(search.SearchError, match='recheck: one of'):
        search.relevance_input(REFS_TEXT, tmp_path, recheck='weak')


def test_a_full_text_that_could_not_be_read_leaves_the_abstract_reading_standing(tmp_path):
    s = search.Searcher(tmp_path)
    log_relevance(s, 'a', 5, 'related_not_claim')
    log_relevance(s, 'a', 5, 'not_retrievable', basis='full_text')
    # The mutant: the blocked full text erases a reading, and the claim looks unread.
    assert 'p5: 0/1 supports_claim; NO SUPPORT' in search.report(tmp_path)


def test_a_work_whose_licence_forbids_quotation_has_its_own_reason(tmp_path):
    """A work can bear on the atom exactly and still not be citable: a line quotes its passage.

    Without this reason such a work is logged under a false one or left out of the log, and the works
    that bear on a claim most directly are the ones a reader most needs to know were read.
    """
    s, _ = searcher(tmp_path, PILOT)
    r = s.not_cited('PMC8755536', 'licence_refuses_quotation', 'XML .//p[15]', atom='a_coadapt')
    assert r['outcome'] == 'ok' and r['ask']['reason'] == 'licence_refuses_quotation'
    assert 'licence' in search.NOT_CITED['licence_refuses_quotation']


def test_a_work_that_cannot_be_read_has_every_place_tried_and_logged(tmp_path):
    """A refused download is a claim about particular requests, and it belongs where a checker looks.

    Until this command, a conversion that reported "the full text answered HTTP 500" left that only in
    its prose: the search log showed the work as found, every call `ok` and every response 200, so a
    reader checking the log would conclude nothing had refused. The kit does the trying now, and
    `fetch` records the url, the time, the status and the sha256 of each answer it rejects.
    """
    s, _ = searcher(tmp_path, [('PMCID%3APMC11726020', 'text-pmc-epmc.json')],
                    fail={'fullTextXML': [500] * 9, 'BioC': [500] * 9})
    r = s.not_read('PMC11726020')
    assert r['outcome'] == 'ok' and r['readable'] == 0
    jats = [p for p in r['places'] if p['kind'] == 'jats']
    assert jats and 'HTTP 500' in jats[0]['refused']
    assert any(x['status'] == 500 and x['sha256'] for x in r['responses']), r['responses']
    text = search.report(tmp_path)
    assert 'found, NOT READ' in text and 'HTTP 500' in text


def test_a_place_that_answers_makes_the_record_say_the_work_is_readable(tmp_path):
    """The point of the kit doing the trying: a work logged as unreadable that answers is not one."""
    s, _ = searcher(tmp_path, [('PMCID%3APMC11726020', 'text-pmc-epmc.json'),
                               ('fullTextXML', 'text-pmc-epmc.json')])
    r = s.not_read('PMC11726020')
    assert r['readable'] >= 1
    assert any(p.get('read') for p in r['places'])
    assert 'WARNING' in search.report(tmp_path)


def test_a_probed_place_that_answers_leaves_no_body_on_disk(tmp_path):
    """The defect the reviewer found: `not-read` said it kept no bytes while every 200 was written out.

    `fetch` keeps each answer in `search-responses/` by hash so that a call can be repeated from the
    bytes it hashed, which is right for metadata and wrong for a probe of a full text: the probe asks
    whether a place answers at all, and retaining the payload would keep a copy of a work this kit may
    have no licence to reproduce. The probe records hash and status with `kept: false`; the metadata
    lookups around it keep their answers as before.
    """
    # the probe is served different bytes from the metadata lookup, so a body on disk can be told
    # apart by the hash the probe recorded
    s, _ = searcher(tmp_path, [('PMCID%3APMC11726020', 'text-pmc-epmc.json'),
                               ('fullTextXML', 'target.json')])
    r = s.not_read('PMC11726020')
    assert r['readable'] >= 1
    probed = [x for x in r['responses'] if 'fullTextXML' in x['url']]
    assert probed and all(x.get('kept') is False and x['sha256'] for x in probed), probed
    bodies = {p.name for p in (tmp_path / search.RESPONSES).glob('*.body')}
    assert bodies and not any(x['sha256'].split(':')[1] + '.body' in bodies for x in probed), bodies
    # the metadata answer around it is still kept, so the call repeats from its own bytes
    meta = [x for x in r['responses'] if 'PMCID%3A' in x['url']]
    assert meta and all('kept' not in x for x in meta)


# -- a query the service never understood -----------------------------------------------------------

def test_a_query_in_the_other_services_syntax_is_refused_before_it_is_sent(tmp_path):
    """The defect this closes: `"Trojan horse"[tiab]` sent to Europe PMC, and `ABSTRACT:"x"` sent to
    PubMed, each answered 200 with no results and were logged `found 0, outcome ok`. A conversion then
    reads that zero as "nothing is published on it". Both directions are refused on the fields."""
    s, _ = searcher(tmp_path, LITERATURE)
    to_epmc = s.literature('"Trojan horse"[tiab] AND amoeba', sources=('europepmc',))
    to_pubmed = s.literature('ABSTRACT:"accidental pathogen" AND ABSTRACT:"fungal"', sources=('pubmed',))
    for records in (to_epmc, to_pubmed):
        assert records, 'the refusal is logged as a call, not swallowed'
        for r in records:
            assert r['outcome'] == 'malformed_query'
            assert r['found'] == 0 and r['hit_count'] is None and r['works'] == []
            assert r['responses'] == [], 'nothing was sent'
    assert 'tiab' in to_epmc[0]['error'] and 'ABSTRACT' in to_pubmed[0]['error']
    # No request was made for either query: the only URLs are from the fixtures' own lookups, if any.
    assert not [u for u in s.get.urls if 'Trojan' in u or 'accidental' in u]


def test_a_field_tag_the_service_does_implement_is_not_refused(tmp_path):
    """The check is on the syntax, not on the presence of brackets or colons: PubMed's own tags are
    fine for PubMed, Europe PMC's for Europe PMC, and free text is fine for both."""
    assert search.query_fields('amoeba[tiab] AND ABSTRACT:"x"') == {'pubmed': {'tiab'},
                                                                    'europepmc': {'ABSTRACT'}}
    search.refuse_foreign_syntax('amoeba[tiab] AND virulence', 'pubmed')
    search.refuse_foreign_syntax('ABSTRACT:"amoeba" AND PUB_TYPE:review', 'europepmc')
    search.refuse_foreign_syntax('amoeba predation fungal virulence', 'pubmed')
    search.refuse_foreign_syntax('amoeba predation fungal virulence', 'europepmc')
    # An unknown word in brackets or before a colon is not a field tag of either syntax.
    search.refuse_foreign_syntax('amoeba [sic] AND NOTE:"x"', 'pubmed')
    with pytest.raises(search.MalformedQuery):
        search.refuse_foreign_syntax('amoeba[tiab]', 'europepmc')
    with pytest.raises(search.MalformedQuery):
        search.refuse_foreign_syntax('ABSTRACT:"amoeba"', 'pubmed')


def test_the_kits_own_no_review_wrapper_is_never_refused(tmp_path):
    """Each variant wraps the query in that service's own syntax - `NOT review[pt]` for PubMed, `NOT
    PUB_TYPE:review` for Europe PMC - so the check must read the query as given, not the sent form."""
    for source in ('europepmc', 'pubmed'):
        sent = search.VARIANTS['no_reviews'][source].format('amoeba predation')
        search.refuse_foreign_syntax('amoeba predation', source)
        assert search.query_fields(sent)[source] or source == 'europepmc'


# -- the screen: no work leaves the search unlooked-at -----------------------------------------------

def log_lines(tmp_path, *records):
    (tmp_path / search.LOG).write_text('\n'.join(json.dumps(r) for r in records) + '\n')


def work(pmcid, title=None, doi=None):
    return {'pmcid': pmcid, 'title': title, 'doi': doi}


def card_citing(*pmcids):
    return {'author': {'source': 'https://www.ebi.ac.uk/europepmc/webservices/rest/PMC1/fullTextXML'},
            'added': {'sources': {f's{i}': {'source': f'https://www.ebi.ac.uk/europepmc/webservices/rest/{p}/fullTextXML'}
                                  for i, p in enumerate(pmcids)}}}


def returned(tool, call_id, *works):
    return {'call_id': call_id, 'tool': tool, 'ask': {'id': 'PMC1'}, 'started_at': '2026-10-24T00:00:00Z',
            'outcome': 'ok', 'found': len(works), 'hit_count': len(works), 'works': list(works),
            'responses': []}


def test_the_screen_names_a_work_a_used_call_returned_and_no_record_looked_at(tmp_path):
    """The measured failure: the counter-work was returned by calls the card does use - four times on
    one conversion, eighteen on another - so every per-call audit showed those calls as accounted for,
    and the work itself was never recorded as looked at. The screen counts per work."""
    log_lines(tmp_path,
              returned('similar', 'c1', work('PMC100', 'A work the card cites'),
                       work('PMC64930', 'Does amoeboid reasoning explain the evolution of virulence factors?')),
              returned('cited_by', 'c2', work('PMC64930', 'Does amoeboid reasoning explain it?')))
    result = search.screen(card_citing('PMC100'), tmp_path)
    assert [r['ids'] for r in result['unscreened']] == [['pmc64930']]
    assert result['unscreened'][0]['returned_by'] == 2
    assert result['unscreened'][0]['answer_call'], 'a similar call returned it, so no floor applies'
    assert result['unscreened'][0]['tools'] == ['cited_by', 'similar']
    assert 'reasoning' in result['unscreened'][0]['title']
    assert 'accounted for' in search.screen_text(result) and 'PMC100' not in search.screen_text(result)


def test_a_work_is_accounted_for_by_a_citation_a_reading_or_a_refusal(tmp_path):
    """Four records answer "did anyone look at this": the card cites it; a not_cited record says it was
    read and why it is not cited; a not_read record says the kit could not read it; a relevance verdict
    names it. Any of them takes the work off the screen - and nothing else does."""
    found = returned('similar', 'c1', work('PMC2'), work('PMC3'), work('PMC4'), work('PMC5'), work('PMC6'))
    log_lines(tmp_path, found)
    assert len(search.screen(card_citing(), tmp_path)['unscreened']) == 5, 'nothing accounts for them yet'
    log_lines(tmp_path, found,
              {'call_id': 'c2', 'tool': 'not_cited', 'ask': {'id': 'PMC2', 'reason': 'off_topic',
                                                             'locator': 'abstract'},
               'started_at': '2026-10-24T00:00:01Z', 'outcome': 'ok', 'works': [work('PMC2')]},
              {'call_id': 'c3', 'tool': 'not_read', 'ask': {'id': 'PMC3'},
               'started_at': '2026-10-24T00:00:02Z', 'outcome': 'ok', 'works': [],
               'work': work('PMC3')},
              {'call_id': 'c4', 'tool': 'relevance', 'ask': {'id': 'PMC4'}, 'relevance': 'unrelated',
               'started_at': '2026-10-24T00:00:03Z', 'outcome': 'ok', 'works': [], 'work': work('PMC4')})
    left = search.screen(card_citing('PMC6'), tmp_path)
    assert [r['ids'] for r in left['unscreened']] == [['pmc5']], 'only the work no record mentions'
    assert not search.screen(card_citing('PMC6', 'PMC5'), tmp_path)['unscreened']
    assert 'is accounted for' in search.screen_text(search.screen(card_citing('PMC6', 'PMC5'), tmp_path))


def test_a_work_only_broad_queries_returned_is_reported_from_the_exposure_floor_up(tmp_path):
    """A literature query is a net: forty works come back and most are not about the claim. Demanding
    a record for each would make the screen unreadable, and an unreadable demand is ignored, which is
    worse than none. So a literature-only work is reported once enough distinct calls returned it -
    the two counter-works that were missed came back four and eighteen times - while a work any
    similar, cited-by or responses call returned is reported however few calls that was."""
    once = returned('literature', 'c1', work('PMC10', 'Returned by one query only'))
    twice = returned('literature', 'c2', work('PMC20', 'Returned by two')), \
        returned('literature', 'c3', work('PMC20', 'Returned by two'))
    thrice = [returned('literature', f'c{i}', work('PMC30', 'Returned by three')) for i in (4, 5, 6)]
    log_lines(tmp_path, once, *twice, *thrice)
    at_three = search.screen(card_citing(), tmp_path)
    assert [r['ids'] for r in at_three['unscreened']] == [['pmc30']]
    assert at_three['below_exposure'] == 2 and at_three['unscreened_all'] == 3
    assert 'Below the exposure floor: 2 works' in search.screen_text(at_three)
    # The floor is a floor, not a filter on what matters: at 1 every work is named.
    assert len(search.screen(card_citing(), tmp_path, exposure=1)['unscreened']) == 3
    # The same work returned once by a similar call is reported whatever the floor.
    log_lines(tmp_path, once, returned('similar', 'c9', work('PMC10', 'Returned by one query only')))
    assert [r['ids'] for r in search.screen(card_citing(), tmp_path)['unscreened']] == [['pmc10']]


def test_exposure_counts_the_work_not_the_identifiers_one_answer_happened_to_carry(tmp_path):
    """KIT092-R1. A service returns a work by whatever identifiers it holds: PMCID in one answer,
    PMCID and DOI in another, the DOI alone in a third. Keyed by the identifiers of a single answer,
    one work becomes several rows with a fraction of the calls each - review found three calls split
    1 + 2, both parts under the floor of 3, and the command exiting 0 on a work it should have named.
    The alias group is the key, so the count counts the work."""
    log_lines(tmp_path,
              returned('literature', 'c1', {'pmcid': 'PMC900', 'title': 'One work, three answers'}),
              returned('literature', 'c2', {'pmcid': 'PMC900', 'doi': '10.1/x', 'title': 'One work'}),
              returned('literature', 'c3', {'doi': '10.1/x', 'title': 'One work'}))
    result = search.screen(card_citing(), tmp_path)
    assert len(result['unscreened']) == 1, result['unscreened']
    row = result['unscreened'][0]
    assert row['returned_by'] == 3, 'three calls returned this one work'
    assert set(row['ids']) == {'pmc900', '10.1/x'}
    assert result['below_exposure'] == 0
    # And the command says so in its exit code, which is what a check is read by.
    (tmp_path / 'card.json').write_text(json.dumps(card_citing()))
    assert search.main(['screen', str(tmp_path / 'card.json'), '--workdir', str(tmp_path)]) == 1


def test_a_not_read_record_answers_only_when_it_attests_the_work_could_not_be_read(tmp_path):
    """KIT092-R2. Any `not_read` record used to close a work. But a record whose lookup failed attests
    nothing, and one that found a readable place says the opposite of what would take the work off the
    screen: a work the kit can read must be read, or accounted for some other way. A probe that
    succeeded was closing the work it had just proved readable."""
    found = returned('similar', 'c1', work('PMC11', 'a'), work('PMC12', 'b'), work('PMC13', 'c'))

    def not_read(call_id, ident, outcome='ok', readable=0):
        return {'call_id': call_id, 'tool': 'not_read', 'ask': {'id': ident}, 'outcome': outcome,
                'readable': readable, 'places_found': 1, 'started_at': '2026-10-24T00:00:01Z',
                'works': [], 'responses': []}

    log_lines(tmp_path, found,
              not_read('c2', 'PMC11'),                      # attests: no place could be read
              not_read('c3', 'PMC12', readable=1),          # found a readable place: not an answer
              not_read('c4', 'PMC13', outcome='failed'))    # the lookup itself failed: not an answer
    left = {r['ids'][0] for r in search.screen(card_citing(), tmp_path)['unscreened']}
    assert left == {'pmc12', 'pmc13'}, left

    # A not_cited attestation stands even when the metadata lookup failed: the reason and the locator
    # are what it rests on, not the lookup.
    log_lines(tmp_path, found,
              {'call_id': 'c5', 'tool': 'not_cited', 'ask': {'id': 'PMC12', 'reason': 'off_topic',
                                                             'locator': 'abstract'},
               'outcome': 'failed', 'error': 'lookup failed', 'started_at': '2026-10-24T00:00:02Z',
               'works': [], 'responses': []},
              not_read('c6', 'PMC11'), not_read('c7', 'PMC13'))
    assert not search.screen(card_citing(), tmp_path)['unscreened']


# -- a licence measurement keeps a notice, not a work -----------------------------------------------

JATS_TEMPLATE = (b'<?xml version="1.0"?><article xmlns:xlink="http://www.w3.org/1999/xlink">'
                 b'<front><article-meta>'
                 b'<permissions><copyright-statement>(c) 2021 A</copyright-statement>'
                 b'<license xlink:href="%s"><license-p>%s</license-p></license></permissions>'
                 b'</article-meta></front><body><sec><p>The body of the work, which no licence '
                 b'record may keep.</p></sec></body></article>')

ABSTRACT = 'An abstract that no licence record may keep either.'


def licence_routes(statement, href=b'https://creativecommons.org/licenses/by/4.0/'):
    """A metadata answer carrying an abstract, and a JATS answer carrying a body."""
    record = {'hitCount': 1, 'resultList': {'result': [{
        'id': '34242260', 'source': 'MED', 'pmcid': 'PMC8270121', 'pmid': '34242260',
        'doi': '10.1/x', 'title': 'A work', 'journalTitle': 'J Test', 'pubYear': '2021',
        'abstractText': ABSTRACT}]}}
    jats = JATS_TEMPLATE % (href, statement.encode())
    return [('fullTextXML', jats), ('search?query=', json.dumps(record).encode())]


class Bytes:
    """A transport answering from in-memory bodies by route."""

    def __init__(self, routes):
        self.routes, self.urls = routes, []

    def __call__(self, url, body=None):
        self.urls.append(url)
        for key, data in self.routes:
            if key in url:
                return 200, data, {}
        return 404, b'{}', {}


def measure(tmp_path, statement, href=b'https://creativecommons.org/licenses/by/4.0/'):
    s = search.Searcher(tmp_path, get=Bytes(licence_routes(statement, href)), sleep=lambda *_: None,
                        clock=lambda: 0.0)
    return s.licence('PMC8270121')


@pytest.mark.parametrize('statement, href, quotable', [
    ('Distributed under the Creative Commons Attribution 4.0 International License.',
     b'https://creativecommons.org/licenses/by/4.0/', True),
    ('Distributed under the Creative Commons Attribution-NonCommercial 4.0 International License.',
     b'https://creativecommons.org/licenses/by-nc/4.0/', False),
])
def test_a_licence_record_keeps_no_abstract_and_no_body_either_way(tmp_path, statement, href, quotable):
    """KIT092-L1. The first version of this command wrote the whole Europe PMC core record into the
    log, abstract included, and let `fetch` keep the full JATS on disk - for a refused work as much as
    for a quotable one. For a refused work that is the very thing the refusal forbids, and for either
    it breaks the boundary the kit keeps everywhere else: a record carries identifiers and hashes, not
    text the card has no licence to carry."""
    r = measure(tmp_path, statement, href)
    assert r['outcome'] == 'ok' and r['quotable'] is quotable
    blob = json.dumps(r)
    assert ABSTRACT not in blob, 'the abstract is not metadata of the licence'
    assert 'The body of the work' not in blob
    assert set(r['work']) <= set(search.WORK_METADATA)
    assert r['work']['pmcid'] == 'PMC8270121' and r['work']['doi'] == '10.1/x'
    # The logged record, not only the returned one.
    logged = json.loads((tmp_path / search.LOG).read_text().splitlines()[-1])
    assert ABSTRACT not in json.dumps(logged) and 'The body of the work' not in json.dumps(logged)
    # Nothing of the full text on disk: the JATS answer is hashed and not kept.
    bodies = list((tmp_path / search.RESPONSES).glob('*.body'))
    for path in bodies:
        assert b'The body of the work' not in path.read_bytes(), f'{path.name} holds the full text'
    kept = [x for x in logged['responses'] if 'fullTextXML' in x['url']]
    assert kept and kept[0].get('kept') is False, 'the JATS answer is recorded as not kept'
    assert logged['jats_sha256'] and logged['permissions_sha256']
    assert 'Creative Commons' in logged['permissions_text'], 'the notice itself is kept'


# -- removing what a licence forbids keeping, as a command and not as a side effect ------------------

def licence_record(call_id, ident, jats_hash, quotable, responses=()):
    return {'call_id': call_id, 'tool': 'licence', 'ask': {'id': ident}, 'outcome': 'ok',
            'quotable': quotable, 'jats_sha256': f'sha256:{jats_hash}',
            'licence_from': 'article permissions (measured)',
            'refusal': None if quotable else 'the licence has a restriction marker',
            'work': {'pmcid': ident}, 'started_at': '2026-10-24T00:00:00Z', 'responses': list(responses),
            'hit_count': 1, 'found': 0, 'works': []}


def put_body(tmp_path, data=b'the full text'):
    """A body under the name its own bytes hash to, which is the only name purge will act on."""
    digest = hashlib.sha256(data).hexdigest()
    store = tmp_path / search.RESPONSES
    store.mkdir(parents=True, exist_ok=True)
    path = store / f'{digest}.body'
    path.write_bytes(data)
    return path, digest


def test_purge_names_and_removes_only_what_a_measurement_refuses(tmp_path):
    """The rule being enforced is the measurement, so a work measured quotable and a work never
    measured are both left alone: no measurement, no removal. A body a refusal covers is named with
    its hash and its size whether or not it is removed, because a removed file has to be fetchable
    again and checkable against what was removed."""
    refused, d_refused = put_body(tmp_path, b'the full text of a work that may not be reproduced')
    allowed, d_allowed = put_body(tmp_path, b'a quotable work')
    unmeasured, _ = put_body(tmp_path, b'a work nobody measured')
    log_lines(tmp_path,
              licence_record('c1', 'PMC1', d_refused, False),
              licence_record('c2', 'PMC2', d_allowed, True))

    listed = search.purge(tmp_path)
    assert [e['sha256'] for e in listed['forbidden']] == [f'sha256:{d_refused}']
    assert listed['removed'] == [], 'a listing removes nothing'
    assert listed['forbidden'][0]['bytes'] == refused.stat().st_size
    assert listed['forbidden'][0]['work'] == 'PMC1' and listed['forbidden'][0]['measured_by'] == 'c1'
    assert refused.exists() and allowed.exists() and unmeasured.exists()
    assert '--remove' in search.purge_text(listed)

    done = search.purge(tmp_path, remove=True)
    assert [e['sha256'] for e in done['removed']] == [f'sha256:{d_refused}']
    assert not refused.exists(), 'the forbidden body is gone'
    assert allowed.exists(), 'a work measured quotable is never touched'
    assert unmeasured.exists(), 'a work never measured is never touched'
    # The record survives the file, with the hash that identifies what was removed.
    logged = [json.loads(l) for l in (tmp_path / search.LOG).read_text().splitlines()]
    purges = [r for r in logged if r['tool'] == 'purge']
    assert len(purges) == 1, 'the listing wrote nothing; only the removal is logged'
    assert purges[-1]['removed'][0]['bytes'] > 0 and purges[-1]['ask'] == {'remove': True}


def test_an_asked_for_purge_is_logged_even_when_it_removes_nothing(tmp_path):
    """A listing writes nothing, by the reviewer's decision, so a purge record always means a removal
    was asked for. Asked for and finding nothing is still a fact worth recording: it says the question
    was put to this store at that time."""
    _, digest = put_body(tmp_path, b'a quotable work')
    log_lines(tmp_path, licence_record('c1', 'PMC2', digest, True))
    listed = search.purge(tmp_path)
    assert listed['forbidden'] == [] and 'Nothing to remove' in search.purge_text(listed)
    assert [json.loads(l)['tool'] for l in (tmp_path / search.LOG).read_text().splitlines()
            ].count('purge') == 0
    search.purge(tmp_path, remove=True)
    assert [json.loads(l)['tool'] for l in (tmp_path / search.LOG).read_text().splitlines()
            ].count('purge') == 1


def test_purge_covers_a_forbidden_body_whatever_fetched_it(tmp_path):
    """A full text of a refused work is a copy the kit may not keep however it got there - measured by
    `licence`, probed by `not_read`, read by `text`. The hashes of that work's own responses are
    covered too, not only the one the measurement fetched."""
    by_licence, d_lic = put_body(tmp_path, b'the jats the measurement fetched')
    by_text, d_text = put_body(tmp_path, b'the jats an ordinary read fetched')
    log_lines(tmp_path,
              licence_record('c1', 'PMC3', d_lic, False),
              {'call_id': 'c2', 'tool': 'text', 'ask': {'id': 'PMC3'}, 'outcome': 'ok',
               'started_at': '2026-10-24T00:00:01Z', 'works': [],
               'responses': [{'url': 'https://example.org/PMC3/fullTextXML', 'status': 200,
                              'sha256': f'sha256:{d_text}'}]})
    done = search.purge(tmp_path, remove=True)
    assert {e['sha256'] for e in done['removed']} == {f'sha256:{d_lic}', f'sha256:{d_text}'}
    assert not by_licence.exists() and not by_text.exists()
    assert any(e.get('fetched_by') == 'c2' for e in done['removed']), 'the record says what fetched it'


def test_purge_leaves_the_metadata_answers_that_make_a_call_repeatable(tmp_path):
    """Only a full text is removed. A metadata answer is what lets a call be repeated from the hashes
    it recorded, every search keeps one for every work it returns, and the services distribute them as
    metadata. The first form of this rule covered every response of a record about a refused work: on
    the two conversions that named 29 bodies, all of them `search?query=PMCID:…` answers and not one a
    full text."""
    meta, d_meta = put_body(tmp_path, b'{"resultList": {"result": [{"pmcid": "PMC4"}]}}')
    full, d_full = put_body(tmp_path, b'<article>the full text</article>')
    log_lines(tmp_path,
              licence_record('c1', 'PMC4', hashlib.sha256(b'the measured jats').hexdigest(), False,
                             responses=[{'url': 'https://www.ebi.ac.uk/europepmc/webservices/rest/'
                                                'search?query=PMCID%3APMC4&format=json', 'status': 200,
                                         'sha256': f'sha256:{d_meta}'}]),
              {'call_id': 'c2', 'tool': 'not_read', 'ask': {'id': 'PMC4'}, 'outcome': 'ok',
               'readable': 1, 'started_at': '2026-10-24T00:00:01Z', 'works': [],
               'responses': [{'url': 'https://www.ebi.ac.uk/europepmc/webservices/rest/PMC4/fullTextXML',
                              'status': 200, 'sha256': f'sha256:{d_full}'}]})
    done = search.purge(tmp_path, remove=True)
    assert {e['sha256'] for e in done['removed']} == {f'sha256:{d_full}'}
    assert not full.exists(), 'the full text of a refused work goes'
    assert meta.exists(), 'the metadata answer stays, or no call about the work can be repeated'


# -- purge may not reach outside its own store ------------------------------------------------------

def test_purge_refuses_a_digest_that_is_not_a_digest(tmp_path):
    """KIT095-R1. The digests come out of the log, and a log is a file: a record naming
    `../../outside` as its hash made the command delete a file outside the store. A digest is exactly
    64 hex characters, and anything else is refused before a path is built from it."""
    # The path the escape lands on: `<store>/../outside.body`, which is a file beside the store.
    outside = tmp_path / 'outside.body'
    outside.write_bytes(b'a file no purge may touch')
    store = tmp_path / search.RESPONSES
    store.mkdir(parents=True, exist_ok=True)
    log_lines(tmp_path, licence_record('c1', 'PMC1', '../outside', False))
    record = search.purge(tmp_path, remove=True)
    assert outside.exists(), 'a file outside the store was removed'
    assert record['removed'] == []
    assert any('digest' in str(r).lower() for r in record.get('refused', [])), record


def test_purge_refuses_a_symlinked_store_and_never_follows_a_symlinked_body(tmp_path):
    """KIT095-R1. A symlink in place of the store, or of a body inside it, turns a valid-looking
    removal into the deletion of whatever the link points at."""
    outside = tmp_path / 'target'
    outside.write_bytes(b'the real file')
    digest = hashlib.sha256(b'the real file').hexdigest()

    linked_store = tmp_path / 'linked'
    linked_store.mkdir()
    real = tmp_path / 'real-store'
    (real / search.RESPONSES).mkdir(parents=True)
    (linked_store / search.RESPONSES).symlink_to(real / search.RESPONSES, target_is_directory=True)
    log_lines(linked_store, licence_record('c1', 'PMC1', digest, False))
    record = search.purge(linked_store, remove=True)
    assert record['removed'] == [] and outside.exists()
    assert any('symlink' in str(r).lower() for r in record.get('refused', [])), record

    # and a symlinked body inside a real store
    store = tmp_path / search.RESPONSES
    store.mkdir(parents=True, exist_ok=True)
    (store / f'{digest}.body').symlink_to(outside)
    log_lines(tmp_path, licence_record('c2', 'PMC1', digest, False))
    record = search.purge(tmp_path, remove=True)
    assert outside.exists(), 'the link target was removed'
    assert record['removed'] == []
    assert any('symlink' in str(r).lower() for r in record.get('refused', [])), record


def test_purge_hashes_the_bytes_before_it_removes_them(tmp_path):
    """KIT095-R2. The file name is a claim about the bytes, not the bytes. A file with a valid name
    and different content was removed, and the record said it had removed those bytes - a record that
    lies about what it deleted is worse than no record. The bytes are hashed first; on a mismatch
    nothing is removed and the mismatch is recorded."""
    digest = hashlib.sha256(b'the measured bytes').hexdigest()
    store = tmp_path / search.RESPONSES
    store.mkdir(parents=True, exist_ok=True)
    body = store / f'{digest}.body'
    body.write_bytes(b'different bytes under a valid name')
    log_lines(tmp_path, licence_record('c1', 'PMC1', digest, False))
    record = search.purge(tmp_path, remove=True)
    assert body.exists(), 'a file whose bytes do not match its name was removed'
    assert record['removed'] == []
    mismatch = [r for r in record.get('refused', []) if 'hash' in str(r).lower()]
    assert mismatch and mismatch[0]['sha256'].endswith(digest), record
    # with the right bytes it goes
    body.write_bytes(b'the measured bytes')
    record = search.purge(tmp_path, remove=True)
    assert not body.exists() and len(record['removed']) == 1


def test_purge_writes_nothing_to_the_log_until_it_is_asked_to_remove(tmp_path):
    """KIT095-R3, the reviewer's decision: a listing is a read. Without --remove the command reports
    and logs nothing, so a log entry always means something was removed."""
    digest = hashlib.sha256(b'x').hexdigest()
    store = tmp_path / search.RESPONSES
    store.mkdir(parents=True, exist_ok=True)
    (store / f'{digest}.body').write_bytes(b'x')
    log_lines(tmp_path, licence_record('c1', 'PMC1', digest, False))
    before = (tmp_path / search.LOG).read_text()
    listed = search.purge(tmp_path)
    assert listed['forbidden'] and listed['removed'] == []
    assert (tmp_path / search.LOG).read_text() == before, 'a listing wrote to the log'
    search.purge(tmp_path, remove=True)
    after = [json.loads(l) for l in (tmp_path / search.LOG).read_text().splitlines()]
    assert [r['tool'] for r in after].count('purge') == 1


# -- purge: the name, the inode, and a measurement that changed its mind ----------------------------

def test_purge_removes_the_bytes_it_measured_and_leaves_a_later_file_alone(tmp_path, monkeypatch):
    """KIT095-R2-RACE, under the owner's concurrency contract. Checking a name and then acting on it
    loses every time, because the name can be made to point elsewhere in between. So the body is
    moved to a private name inside the store before it is read, and the open, the hash and the unlink
    all speak about that name, which nothing else knows.

    Here the public name is replaced while the hashing runs - the same window that used to make the
    command delete the replacement. Now the measured bytes are what goes, and whatever took their old
    name is left exactly where it is."""
    measured = b'the measured bytes'
    body, digest = put_body(tmp_path, measured)
    log_lines(tmp_path, licence_record('c1', 'PMC1', digest, False))
    real = search.sha256

    def swap(data):
        if data == measured and not body.exists():
            body.write_bytes(b'a different file under the old name')
        return real(data)

    monkeypatch.setattr(search, 'sha256', swap)
    record = search.purge(tmp_path, remove=True)
    assert [e['sha256'] for e in record['removed']] == [f'sha256:{digest}'], record
    assert body.exists() and body.read_bytes() == b'a different file under the old name', \
        'the file that took the old name was touched'
    assert not list((tmp_path / search.RESPONSES).glob('.purging-*')), 'a private name was left behind'


def test_purge_refuses_when_the_body_changes_under_it_while_it_reads(tmp_path, monkeypatch):
    """The second half of the contract: a body rewritten in place keeps its inode, so the inode says
    nothing by itself. What says it is that the size and the times have not moved while the file was
    being read - checked on the same descriptor, after the read. Simulated here by writing into the
    isolated file during the hashing call, which is an overwrite of the very inode just hashed."""
    measured = b'the measured bytes'
    body, digest = put_body(tmp_path, measured)
    log_lines(tmp_path, licence_record('c1', 'PMC1', digest, False))
    store = tmp_path / search.RESPONSES
    real = search.sha256

    def overwrite(data):
        if data == measured:
            for private in store.glob('.purging-*'):
                private.write_bytes(b'rewritten in place, same inode, different bytes')
        return real(data)

    monkeypatch.setattr(search, 'sha256', overwrite)
    record = search.purge(tmp_path, remove=True)
    assert record['removed'] == [], 'bytes that had already changed were removed'
    assert any('changed while it was being read' in d['why'] for d in record['refused']), record
    # and the body is back under its own name, not stranded under a private one
    assert body.exists() and body.read_bytes() == b'rewritten in place, same inode, different bytes'
    assert not list(store.glob('.purging-*')), 'the body was left under a private name'


def test_purge_does_not_hang_on_a_file_swapped_for_a_fifo(tmp_path, monkeypatch):
    """KIT095-R4. A FIFO in place of a regular file blocks an ordinary open for ever. lstat says it is
    a fifo and the command refuses - but between that lstat and the open it can be swapped, so the
    open itself must not block and what it opened must be checked again."""
    body, digest = put_body(tmp_path, b'a regular file')
    log_lines(tmp_path, licence_record('c1', 'PMC1', digest, False))
    body.unlink()
    os.mkfifo(body)
    # lstat lies, as a swap between lstat and open would: the open must still not hang.
    real_lstat = os.lstat

    def regular(path, *a, **kw):
        st = real_lstat(tmp_path / search.RESPONSES / f'{digest}.body', *a, **kw) \
            if str(path).endswith('.body') else real_lstat(path, *a, **kw)
        return os.stat_result((stat.S_IFREG | 0o644,) + tuple(st)[1:])

    monkeypatch.setattr(os, 'lstat', regular)
    record = search.purge(tmp_path, remove=True)
    assert record['removed'] == []
    assert any('regular file' in d['why'] for d in record['refused']), record
    assert body.is_fifo(), 'the fifo was removed'


@pytest.mark.parametrize('order', ['refused_then_quotable', 'quotable_then_refused'])
def test_a_work_measured_quotable_at_any_time_is_never_purged(tmp_path, order):
    """KIT095-R5, and the reason it matters now: the owner's licence rule of 2026-10-24 turns works
    that were refused into works that may be quoted, so a store holds measurements that disagree -
    the same bytes refused in the morning and quotable in the afternoon. Deleting on the strength of
    the older one destroys a work the card may now quote. Any measurement of quotable is protection;
    measurements that disagree are held, with the disagreement recorded, and nothing is removed."""
    body, digest = put_body(tmp_path, b'a work whose licence was read twice')
    records = [licence_record('c1', 'PMC1', digest, False), licence_record('c2', 'PMC1', digest, True)]
    log_lines(tmp_path, *(records if order == 'refused_then_quotable' else list(reversed(records))))
    record = search.purge(tmp_path, remove=True)
    assert body.exists(), f'{order}: a work with a quotable measurement was removed'
    assert record['removed'] == []
    held = [d for d in record['refused'] if 'quotable' in d['why']]
    assert held, record
    assert 'c2' in json.dumps(held) or 'disagree' in json.dumps(held), held


@pytest.mark.parametrize('order', ['negative_first', 'positive_first'])
def test_protection_binds_to_the_work_not_to_the_label_the_ask_carried(tmp_path, order):
    """KIT095-R6. One work has many labels: a measurement asked by PMID and one asked by PMCID are
    the same work, and binding the protection to the raw label let the body be removed anyway - two
    records differing only in the label were enough. The grouping is now the one the screen uses,
    built from the identifiers the records themselves carry together."""
    body, digest = put_body(tmp_path, b'a work asked for by two different labels')
    # Each measurement knows only the label it was asked by. What ties them together is a third
    # record that returned the work with its identifiers side by side, which is where the alias
    # groups come from - and it is the link the protection used to miss.
    # The two measurements fetched different bytes - a record is re-tagged, a publisher restates a
    # licence - so the body on disk is the one the refusal measured and the protection cannot come
    # from a shared hash. It has to come from the work, which is the point.
    refused_by_pmid = dict(licence_record('c1', '12345678', digest, False),
                           work={'pmid': '12345678'})
    quotable_by_pmcid = dict(licence_record('c2', 'PMC123',
                                            hashlib.sha256(b'the same work, fetched again').hexdigest(),
                                            True),
                             work={'pmcid': 'PMC123'})
    found_together = returned('literature', 'c0',
                              {'pmcid': 'PMC123', 'pmid': '12345678', 'doi': '10.1/x',
                               'title': 'one work, three identifiers'})
    pair = [refused_by_pmid, quotable_by_pmcid]
    log_lines(tmp_path, found_together, *(pair if order == 'negative_first' else list(reversed(pair))))
    record = search.purge(tmp_path, remove=True)
    assert body.exists(), f'{order}: the body of a work measured quotable under another label was removed'
    assert record['removed'] == []
    assert any('quotable' in d['why'] for d in record['refused']), record


def test_every_writer_of_a_work_directory_takes_the_same_lock(tmp_path):
    """The owner's contract: a removal and a write of this kit's own cannot interleave, because both
    take one lock on the work directory. It is re-entrant within a process, so a command that holds it
    and then logs does not wait for itself - which is what purge does at the end of every run."""
    import fcntl
    s = search.Searcher(tmp_path, get=Bytes([]), sleep=lambda *_: None, clock=lambda: 0.0)
    s.log({'call_id': 'c0', 'tool': 'purge', 'started_at': '2026-10-24T05:00:00Z', 'outcome': 'ok',
           'ask': {}, 'forbidden': [], 'removed': [], 'refused': [], 'responses': [], 'works': []})
    assert (tmp_path / search.LOCK).exists(), 'the lock file is made where the writers can find it'
    with search.store_lock(tmp_path):
        with search.store_lock(tmp_path):  # re-entrant, or purge would deadlock on its own log
            s.log({'call_id': 'nested', 'tool': 'test', 'works': []})
    assert any(r['call_id'] == 'nested' for r in search.read_log(tmp_path))
    # and the lock is really exclusive between holders: taken from a second descriptor it would block,
    # so it is tried without waiting here.
    fd = os.open(tmp_path / search.LOCK, os.O_RDWR)
    try:
        with search.store_lock(tmp_path):
            with pytest.raises(BlockingIOError):
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)  # all nested scopes really released it
        fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def test_the_log_is_read_with_the_lock_already_held(tmp_path):
    """KIT095-R7, the half a single process can show: the log was read before the lock was taken, so
    a cooperative writer of this kit - inside the model - had time to record a `quotable` measurement
    in between, and the removal then acted on a snapshot that was already wrong. The order is now
    lock, read, decide, quarantine, unlink, record, without letting go."""
    body, digest = put_body(tmp_path, b'a body')
    log_lines(tmp_path, licence_record('c1', 'PMC1', digest, False))
    real_read, seen = search.read_log, {}

    def note(workdir):
        import fcntl
        with open(Path(workdir) / search.LOCK, 'rb') as probe:
            try:
                fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
                seen['locked'] = False
                fcntl.flock(probe, fcntl.LOCK_UN)
            except BlockingIOError:
                seen['locked'] = True
        return real_read(workdir)

    search.read_log = note
    try:
        search.purge(tmp_path, remove=True)
    finally:
        search.read_log = real_read
    assert seen['locked'], 'the log was read before the lock was held'


def test_a_writer_of_this_kit_cannot_land_a_record_inside_a_removal(tmp_path):
    """And the half that needs a second process, since the lock is re-entrant within one: a real
    `Searcher.log` attempted while the removal holds the lock waits for it, so it cannot interleave.
    The removal's own record is therefore in the log before the writer's."""
    body, digest = put_body(tmp_path, b'a body')
    log_lines(tmp_path, licence_record('c1', 'PMC1', digest, False))
    writer = (
        'import sys, json; sys.path.insert(0, %r); import search;\n'
        's = search.Searcher(%r);\n'
        's.log({"call_id": "from-another-process", "tool": "licence", "ask": {"id": "PMC1"},\n'
        '       "outcome": "ok", "quotable": True, "jats_sha256": "sha256:%s",\n'
        '       "started_at": "2026-10-24T06:00:00Z", "responses": [], "works": []})\n'
        % (str(SCRIPTS), str(tmp_path), digest))
    real_read, started = search.read_log, {}

    def read_and_let_the_writer_try(workdir):
        out = real_read(workdir)
        if 'proc' not in started:
            started['proc'] = subprocess.Popen([sys.executable, '-c', writer])
            time.sleep(0.5)  # long enough for it to reach the lock and block on it
        return out

    search.read_log = read_and_let_the_writer_try
    try:
        search.purge(tmp_path, remove=True)
    finally:
        search.read_log = real_read
        started['proc'].wait(timeout=30)
    order = [json.loads(l).get('tool') if json.loads(l).get('call_id') != 'from-another-process'
             else 'writer' for l in (tmp_path / search.LOG).read_text().splitlines()]
    assert 'purge' in order and 'writer' in order
    assert order.index('purge') < order.index('writer'), \
        f'the writer landed inside the removal: {order}'


def test_a_listing_leaves_the_tree_byte_for_byte_as_it_found_it(tmp_path):
    """KIT095-R3 regression. A listing is advisory: it takes no lock, writes no record, and must
    create nothing - the lock file included, which the first version of the locking made on every
    run."""
    body, digest = put_body(tmp_path, b'a refused body')
    log_lines(tmp_path, licence_record('c1', 'PMC1', digest, False))

    def tree():
        return sorted((str(p.relative_to(tmp_path)), p.stat().st_size, p.stat().st_mtime_ns)
                      for p in tmp_path.rglob('*') if p.is_file())

    before = tree()
    listed = search.purge(tmp_path)
    assert listed['forbidden'] and listed['removed'] == []
    assert not (tmp_path / search.LOCK).exists(), 'a listing created the lock file'
    assert tree() == before, 'a listing changed the tree'


# -- a licence measured by whichever route answers, and the record says which -----------------------

# The two route strings, written out here instead of imported from `search`, so that this file runs
# unchanged against an older head when a mutant's discrimination is checked (`against_revision.py`).
# `test_the_route_names_are_the_kit_s_own` binds them to the kit's constants, so they cannot drift.
JATS = 'article permissions (measured)'
BIOC = 'PMC BioC front passage, license infon (measured)'


BIOC_LICENCE = ('This work is licensed under a Creative Commons Attribution 4.0 International '
                'License, which allows reusers to distribute, remix, adapt and build upon the '
                'material in any medium or format.')


def bioc_routes(licence_text, jats_status=500):
    """Metadata, a JATS that refuses, and a BioC JSON whose front passage carries a licence infon."""
    record = {'hitCount': 1, 'resultList': {'result': [{
        'id': '37708888', 'source': 'MED', 'pmcid': 'PMC10592076', 'pmid': '37708888',
        'doi': '10.1/x', 'title': 'A work whose JATS refuses', 'abstractText': ABSTRACT}]}}
    bioc = [{'documents': [{'passages': [
        {'infons': {'license': licence_text, 'article-id_pmc': '10592076'}, 'text': 'front matter'},
        {'infons': {'section_type': 'INTRO'}, 'text': 'The body of the work, which no record may keep.'},
    ]}]}]
    return [('fullTextXML', None, jats_status), ('BioC_json', json.dumps(bioc).encode(), 200),
            ('search?query=', json.dumps(record).encode(), 200)]


class Routed:
    """A transport that can refuse one route and answer another."""

    def __init__(self, routes):
        self.routes, self.urls = routes, []

    def __call__(self, url, body=None):
        self.urls.append(url)
        for key, data, status in self.routes:
            if key in url:
                return status, data if data is not None else b'upstream error', {}
        return 404, b'{}', {}


def test_a_licence_is_measured_by_the_route_that_answers_and_the_record_says_which(tmp_path):
    """An acceptance found a refusal that rested on no measurement: the work's JATS answered HTTP 500,
    so `licence` failed and the only basis on record was `europepmc license field` - a service's
    metadata, which is the thing the standard's licence rule exists to not rely on. The measurement
    was available all along: the same work's PMC BioC front passage carries a `license` infon, and the
    exclusion's own locator pointed at it.

    So the command tries the BioC infon when the JATS refuses, and the record names the route it
    measured by - `measured_from` - because a measurement whose route is unstated is not much better
    than a field."""
    s = search.Searcher(tmp_path, get=Routed(bioc_routes(BIOC_LICENCE)), sleep=lambda *_: None,
                        clock=lambda: 0.0)
    r = s.licence('PMC10592076')
    assert r['outcome'] == 'ok' and r['quotable'] is True
    assert r['licence'] == 'CC-BY-4.0'
    assert r['measured_from'] == 'PMC BioC front passage, license infon (measured)'
    assert r['licence_from'] == r['measured_from'], 'the basis and the route are the same statement'
    assert r['bioc_sha256'] and r['jats_status'] == 500, 'the record says what the JATS answered'
    assert r['jats_refused_code'] == 'SearchError', 'and what kind of failure it was'
    assert 'Creative Commons' in r['permissions_text']
    # The BioC JSON is the whole article: not one byte of it is kept, as for the JATS route.
    for path in (tmp_path / search.RESPONSES).glob('*.body'):
        assert b'The body of the work' not in path.read_bytes(), f'{path.name} holds the full text'
    assert ABSTRACT not in json.dumps(r), 'no abstract reaches a licence record by either route'


def test_a_bioc_infon_that_names_no_licence_is_refused_and_its_statement_is_kept(tmp_path):
    """The real case, and the reason the refusal is honest rather than lucky. PMC10592076's infon
    reads "This work is licensed under a , which allows reusers to distribute, remix, adapt..." - the
    licence **name** is missing from the sentence. So the measurement refuses it, and for a sharper
    reason than the service field suggested: not "CC BY without a version" but a record that names no
    licence at all.

    The refusal itself is a code and the kit's own sentence - no words of the statement travel in it -
    while the statement is kept in `permissions_text`, the one field that carries it, so that a reader
    can see the missing name for themselves."""
    nameless = ('This work is licensed under a , which allows reusers to distribute, remix, adapt, '
                'and build upon the material in any medium or format, so long as attribution is '
                'given to the creator. The license allows for commercial use.')
    s = search.Searcher(tmp_path, get=Routed(bioc_routes(nameless)), sleep=lambda *_: None,
                        clock=lambda: 0.0)
    r = s.licence('PMC10592076')
    assert r['outcome'] == 'ok' and r['quotable'] is False
    assert r['licence'] is None
    assert r['licence_refusal_code'] == 'no_licence_named', r.get('refusal')
    assert r['refusal'] == search.REFUSAL_PHRASES['no_licence_named'], (
        "the record carries the kit's own sentence for the code, not the statement's words")
    assert r['measured_from'] == 'PMC BioC front passage, license infon (measured)'
    assert 'licensed under a ,' in r['permissions_text'], (
        'the statement is kept, so a reader can see for themselves that the name is missing from it')


# -- two routes, one article: the kit refuses rather than choose -------------------------------------

def cached_jats(workdir, statement, href='https://creativecommons.org/licenses/by/4.0/',
                pmcid='PMC10592076'):
    """A full text cached beside the work, as an ordinary read of it writes: the article's own
    permissions element, with the body a licence record may not keep."""
    xml = (f'<?xml version="1.0"?><article xmlns:xlink="http://www.w3.org/1999/xlink"><front>'
           f'<article-meta><permissions><copyright-statement>(c) 2023 A</copyright-statement>'
           f'<license xlink:href="{href}"><license-p>{statement}</license-p></license>'
           f'</permissions></article-meta></front><body><sec><p>The body of the work, which no '
           f'record may keep.</p></sec></body></article>').encode()
    (workdir / f'{pmcid}.xml').write_bytes(xml)
    (workdir / f'{pmcid}.xml.retrieved').write_text('2026-10-24T08:00:00Z')
    return xml


def test_two_routes_that_disagree_refuse_the_work_and_choose_neither(tmp_path):
    """The owner's condition on accepting the BioC infon as the article's own record: when the kit
    holds answers from both routes for one article and they disagree, it refuses with
    `licence_sources_disagree` and does not choose.

    The mutant is the dangerous shape, not an abstract one. The infon says commercial use is allowed
    and names CC BY 4.0; the same article's permissions element, cached beside the work by an ordinary
    read, carries a NonCommercial grant. Either route alone gives a confident answer, and the two
    answers are opposite: one would let a card quote the work, the other forbids converting it at all.
    A kit that picked the route it measured today would license the quotation on the record it happened
    to reach, which is the choice this refusal exists to refuse."""
    cached_jats(tmp_path, 'This article is licensed under a Creative Commons '
                          'Attribution-NonCommercial 4.0 International License.',
                href='https://creativecommons.org/licenses/by-nc/4.0/')
    s = search.Searcher(tmp_path, get=Routed(bioc_routes(BIOC_LICENCE)), sleep=lambda *_: None,
                        clock=lambda: 0.0)
    r = s.licence('PMC10592076')
    assert r['outcome'] == 'ok', r.get('error')
    assert r['quotable'] is False and r['licence'] is None, 'neither route is chosen'
    assert r['refusal_code'] == 'licence_sources_disagree'
    assert 'restriction_marker' in r['refusal'] and 'CC-BY-4.0' in r['refusal'], (
        'the reason names what each route says - a licence id, or the code of a refusal, and never '
        'a refusal\'s words, which would carry the statement back into the record')
    routes = {a['route'] for a in r['licence_answers']}
    assert routes == {JATS, BIOC}, routes
    assert r['measured_from'] == BIOC, (
        'the route measured now is still recorded; the refusal is about holding two answers')
    # Without the cached permissions element, the same BioC answer passes - so the refusal is the
    # disagreement talking and not a route this test happens to break.
    (tmp_path / 'PMC10592076.xml').unlink()
    alone = search.Searcher(tmp_path, get=Routed(bioc_routes(BIOC_LICENCE)), sleep=lambda *_: None,
                            clock=lambda: 0.0).licence('PMC10592076')
    assert alone['quotable'] is True and alone['licence'] == 'CC-BY-4.0'


def test_two_routes_that_agree_pass_and_the_record_shows_both(tmp_path):
    """The mutant that must pass. Both routes answer, both answer CC BY 4.0 - the prose differs,
    because the infon is the publisher's sentence and the permissions block is JATS, and that is
    exactly why the comparison is by the licence and not by the words. So the work is quotable, no
    refusal appears, and the record carries both answers with the route each came by, so that a reader
    can see the agreement rather than infer it from the absence of a refusal."""
    cached_jats(tmp_path, '© The Author(s) 2023. This article is licensed under a Creative Commons '
                          'Attribution 4.0 International License.')
    s = search.Searcher(tmp_path, get=Routed(bioc_routes(BIOC_LICENCE)), sleep=lambda *_: None,
                        clock=lambda: 0.0)
    r = s.licence('PMC10592076')
    assert r['outcome'] == 'ok', r.get('error')
    assert r['quotable'] is True and r['licence'] == 'CC-BY-4.0'
    assert 'refusal' not in r and 'refusal_code' not in r
    assert {a['route'] for a in r['licence_answers']} == {JATS, BIOC}
    assert [a['licence'] for a in r['licence_answers']] == ['CC-BY-4.0', 'CC-BY-4.0']
    texts = {a.get('held_as') for a in r['licence_answers']}
    assert texts == {'measured now', 'PMC10592076.xml in the work directory'}, texts
    for path in (tmp_path / search.RESPONSES).glob('*.body'):
        assert b'The body of the work' not in path.read_bytes(), f'{path.name} holds the full text'


def test_one_route_measured_twice_is_a_re_measurement_and_not_a_disagreement(tmp_path):
    """The narrow side of the rule, which the two mutants above cannot show. The comparison is between
    routes: two answers by the same route are one route measured twice, and the later record
    supersedes the earlier one. Were it otherwise, a work whose publisher corrected its licence
    statement - or a kit whose own rules changed, which happened at 1.1.4 - would become permanently
    unquotable because the log remembers what the same route used to say."""
    nameless = ('This work is licensed under a , which allows reusers to distribute, remix, adapt, '
                'and build upon the material in any medium or format.')
    first = search.Searcher(tmp_path, get=Routed(bioc_routes(nameless)), sleep=lambda *_: None,
                            clock=lambda: 0.0).licence('PMC10592076')
    assert first['quotable'] is False and first['measured_from'] == BIOC
    again = search.Searcher(tmp_path, get=Routed(bioc_routes(BIOC_LICENCE)), sleep=lambda *_: None,
                            clock=lambda: 0.0).licence('PMC10592076')
    assert again['quotable'] is True and again['licence'] == 'CC-BY-4.0', (
        'the same route measured again answers for itself')
    assert again.get('refusal_code') is None
    assert search.routes_disagree([{'route': BIOC, 'held_as': 'measured now',
                                    'licence': None, 'refusal': 'x'},
                                   {'route': BIOC, 'held_as': 'earlier',
                                    'licence': 'CC-BY-4.0', 'refusal': None}]) == []


def test_a_cached_document_that_states_no_licence_is_an_answer_and_disagrees(tmp_path):
    """What an answer is, after three reviews of the same confusion: a **verdict** - a licence or a
    coded refusal of the work's own record - and not the shape of the text a route read.

    This case changed with that definition, and the change is the conservative one. A cached full text
    with no permissions element of the article's own used to be counted as silence, so the other
    route's CC BY 4.0 made the work quotable. But that document is the work's own record, and it
    states no licence: against a service's sentence granting CC BY 4.0, the kit holds two records that
    disagree, and it refuses rather than choosing the one that permits quotation.

    The second route is not harmed by this, which is what the sequence tests below check: the case it
    exists for is a JATS that did not answer at all, where there is no verdict to contradict."""
    (tmp_path / 'PMC10592076.xml').write_bytes(
        b'<article><front><article-meta/></front><body><sec><p>Body.</p></sec></body></article>')
    (tmp_path / 'PMC10592076.xml.retrieved').write_text('2026-10-24T08:00:00Z')
    s = search.Searcher(tmp_path, get=Routed(bioc_routes(BIOC_LICENCE)), sleep=lambda *_: None,
                        clock=lambda: 0.0)
    r = s.licence('PMC10592076')
    assert r['quotable'] is False and r['licence'] is None
    assert r['refusal_code'] == 'licence_sources_disagree'
    held = [a for a in r['licence_answers'] if 'in the work directory' in a['held_as']]
    assert held and held[0]['refusal_code'] == 'no_article_permissions'


# -- a BioC answer is bound to the work asked for, or it is unavailable -----------------------------

CC_BY_JATS = ('<?xml version="1.0"?><article xmlns:xlink="http://www.w3.org/1999/xlink"><front>'
              '<article-meta><permissions><license xlink:href="https://creativecommons.org/licenses/'
              'by/4.0/"><license-p>Creative Commons Attribution 4.0 International License</license-p>'
              '</license></permissions></article-meta></front><body><sec><p>The body of the work, '
              'which no record may keep.</p></sec></body></article>').encode()
NC_JATS = CC_BY_JATS.replace(b'licenses/by/4.0', b'licenses/by-nc/4.0').replace(
    b'Attribution 4.0 International', b'Attribution-NonCommercial 4.0 International')


def bioc_payload(licence_text=None, document=None, passages=None):
    """A BioC answer, with the document's identity and passages open to the caller: the shape is what
    these tests vary, so it is built here rather than taken from `bioc_routes`."""
    if passages is None:
        passages = [{'infons': {'license': licence_text, 'article-id_pmc': '10592076'},
                     'text': 'front matter'},
                    {'infons': {'section_type': 'INTRO'}, 'text': 'The body of the work.'}]
    doc = {'id': '10592076', 'infons': {}, 'passages': passages}
    doc.update(document or {})
    return [{'source': 'PMC', 'documents': [doc]}]


def payload_routes(payload, jats=None, jats_status=500):
    record = {'hitCount': 1, 'resultList': {'result': [{
        'id': '37708888', 'source': 'MED', 'pmcid': 'PMC10592076', 'pmid': '37708888',
        'doi': '10.1/x', 'title': 'A work whose JATS refuses', 'abstractText': ABSTRACT}]}}
    return [('fullTextXML', jats, 200 if jats else jats_status),
            ('BioC_json', json.dumps(payload).encode(), 200),
            ('search?query=', json.dumps(record).encode(), 200)]


def measured(tmp_path, routes, ident='PMC10592076', command='licence', **kwargs):
    searcher = search.Searcher(tmp_path, get=Routed(routes), sleep=lambda *_: None, clock=lambda: 0.0)
    if command == 'locate':
        return searcher.locate(ident, kwargs['find'])
    return searcher.licence(ident)


def test_a_bioc_answer_about_another_article_is_not_this_article_s_licence(tmp_path):
    """The review's first finding, and the worst of the three. Asked for PMC10592076, the service
    answered with a document carrying PMC99999999, and the kit recorded CC BY 4.0 **for
    PMC10592076**: the only thing binding the licence to the work was the URL the kit had typed. A
    licence recorded for the wrong work is worse than no licence, because a card may quote on it.
    So the identity the payload states is checked against the work asked for, and a mismatch is
    `unavailable` - the route answered and gave nothing usable - with no licence claimed."""
    payload = bioc_payload(BIOC_LICENCE, document={'id': 'PMC99999999',
                                                   'infons': {'article-id_pmc': '99999999'}},
                           passages=[{'infons': {'license': BIOC_LICENCE}, 'text': 'front'}])
    r = measured(tmp_path, payload_routes(payload))
    assert r['outcome'] == 'unavailable'
    assert 'licence' not in r and 'quotable' not in r, 'nothing is claimed about the work asked for'
    assert 'PMC99999999' in r['error'] and 'PMC10592076' in r['error']
    assert (tmp_path / search.LOG).exists(), 'and the call is in the log'
    kept = [resp for resp in read_calls(tmp_path)[-1]['responses'] if 'BioC' in resp['url']]
    assert kept and kept[0]['sha256'] and kept[0]['kept'] is False, (
        'the answer stays in evidence by hash, with no body kept')


def test_a_bioc_answer_that_states_no_identity_is_not_assumed_from_the_url(tmp_path):
    """The same finding's other half: a payload that names no article at all. Reading a licence out
    of it would rest on the assumption that the service answered about what it was asked, which is
    the assumption the first case disproves. It fails closed."""
    payload = bioc_payload(document={'id': '', 'infons': {}},
                           passages=[{'infons': {'license': BIOC_LICENCE}, 'text': 'front'}])
    r = measured(tmp_path, payload_routes(payload))
    assert r['outcome'] == 'unavailable' and 'states no article identity' in r['error']
    assert 'the URL is not evidence' in r['error']


def test_a_stated_revision_is_reported_and_never_claimed_to_match(tmp_path):
    """A revision cannot be bound, because the service's URL names none: `BioC_json/PMC…/unicode`
    asks for whatever is current. So the kit says exactly that - the revision the answer states, and
    `revision_requested: null` beside it - rather than passing silence off as agreement."""
    payload = bioc_payload(BIOC_LICENCE, document={'id': 'PMC10592076.99',
                                                   'infons': {'article-id_pmc': '10592076',
                                                              'article-version': '99'}})
    r = measured(tmp_path, payload_routes(payload))
    assert r['outcome'] == 'ok' and r['licence'] == 'CC-BY-4.0'
    assert r['bioc_document_id'] == 'PMC10592076'
    assert r['revision_requested'] is None
    assert r['bioc_revision_stated'] == {'document id': '99',
                                         'document infons article-version': '99'}, (
        'each statement of the revision is recorded with the field that stated it')
    assert r['bioc_revisions_agree'] is True


def test_two_documents_claiming_the_article_are_ambiguous_rather_than_the_first_one(tmp_path):
    """`documents[0]` was taken on faith. Two documents claiming the same article is the case where
    taking the first would be a choice between records, which is the thing this release refuses."""
    payload = bioc_payload(BIOC_LICENCE)
    payload[0]['documents'].append({'id': '10592076', 'infons': {},
                                    'passages': [{'infons': {'license': 'CC0 1.0'}, 'text': 'f'}]})
    r = measured(tmp_path, payload_routes(payload))
    assert r['outcome'] == 'unavailable' and 'ambiguous' in r['error']


@pytest.mark.parametrize('payload,shape', [([], 'an empty answer'), ([{'documents': []}], 'no document'),
                                           ([{'documents': None}], 'documents: null'),
                                           ([{'documents': [{'id': '10592076', 'passages': []}]}],
                                            'a document with no passage')])
def test_a_malformed_bioc_answer_is_a_recorded_failure_and_not_an_escaping_exception(tmp_path, payload, shape):
    """The review's second finding. `documents[0]['passages']` raised IndexError on an empty answer
    and TypeError on `documents: null`, and both escaped `Searcher.call` - so the command died with
    no record at all, which is the one outcome a log must never have: a reader cannot tell a call
    that was never made from one whose answer was unusable. Each shape is now a typed refusal with
    its record, and the answer stays in evidence by hash."""
    r = measured(tmp_path, payload_routes(payload))
    assert r['outcome'] == 'unavailable', shape
    assert (tmp_path / search.LOG).exists(), f'{shape}: the failure is in the log'
    assert 'licence' not in r and 'quotable' not in r
    for path in (tmp_path / search.RESPONSES).glob('*.body'):
        assert b'The body of the work' not in path.read_bytes()


def test_an_unreadable_cache_is_not_a_refusal_to_disagree_with(tmp_path):
    """The review's third finding, first half. A cached file that does not parse states nothing, but
    it entered the comparison with `route: null` and `licence: null` and so contradicted a perfectly
    good measurement: the work came out refused for `licence_sources_disagree` although one route had
    answered and the other had not spoken. The comment in the code said this was kept out of the
    comparison; the code did not do it. Now it is named in the record and compared with nothing."""
    (tmp_path / 'PMC10592076.xml').write_bytes(b'<article><front>  unclosed')
    r = measured(tmp_path, payload_routes(bioc_payload(BIOC_LICENCE)))
    assert r['outcome'] == 'ok' and r['quotable'] is True and r['licence'] == 'CC-BY-4.0'
    assert r.get('refusal_code') is None, 'silence is not a disagreement'
    assert 'licence_answers' not in r, 'and it is not an answer either'
    aside = r['licence_held_aside']
    assert aside and 'PMC10592076.xml' in aside[0]['held_as'] and aside[0]['not_an_answer']


def test_an_earlier_disagreement_does_not_make_the_refusal_permanent(tmp_path):
    """The review's third finding, second half, and the one that needed sequence to see. A call that
    refuses with `licence_sources_disagree` writes `licence: null` with the route it measured by -
    the **call's** verdict, not that route's answer. Read back as a route answer, it refused the work
    for ever: the BioC route had said CC BY 4.0, the aggregate said nothing, and the next
    measurement disagreed with its own earlier self while both routes actually said CC BY 4.0.

    The sequence: BioC says CC BY 4.0 while the cached permissions element says NonCommercial, so
    the call refuses, rightly. The cache goes (the file was wrong, or it was a figure's licence). The
    JATS now answers CC BY 4.0, the earlier BioC answer is recovered from the aggregate's own
    `licence_answers`, the two routes agree, and the work is quotable."""
    (tmp_path / 'PMC10592076.xml').write_bytes(NC_JATS)
    first = measured(tmp_path, payload_routes(bioc_payload(BIOC_LICENCE)))
    assert first['refusal_code'] == 'licence_sources_disagree', 'the refusal itself is right'
    (tmp_path / 'PMC10592076.xml').unlink()
    second = measured(tmp_path, payload_routes(bioc_payload(BIOC_LICENCE), jats=CC_BY_JATS))
    assert second['outcome'] == 'ok' and second['licence'] == 'CC-BY-4.0'
    assert second['quotable'] is True and second.get('refusal_code') is None
    recovered = [a for a in second['licence_answers'] if a['route'] == BIOC]
    assert recovered and recovered[0]['licence'] == 'CC-BY-4.0', (
        'the route answer is recovered from the aggregate, not the aggregate read as an answer')
    assert 'the answer of the route it measured' in recovered[0]['held_as']


def read_calls(workdir):
    return search.read_log(workdir)


def test_the_route_names_are_the_kit_s_own():
    """The one place this file and the kit are tied together. The route names above are literals so
    that a mutant can be run against an older head without editing it; this test is what keeps them
    from drifting away from the strings the kit actually writes into a record."""
    assert (JATS, BIOC) == (search.JATS_ROUTE, search.BIOC_ROUTE)


def test_two_statements_of_the_revision_are_kept_apart_rather_than_reduced_to_one():
    """The review's advisory. A document id ending `.1` beside an `article-version` of 99 are two
    different claims about which revision answered, and the first form of this reported a single
    unqualified `revision: 1` - agreement that is not there. Each statement is kept with the field
    that made it, and the record says plainly that they do not agree."""
    doc = {'id': '10592076.1', 'infons': {'article-version': '99'}}
    front = {'infons': {'license': BIOC_LICENCE}}
    identity = search.bioc_identity(doc, front, 'PMC10592076', evidence={})
    assert identity['bioc_revision_stated'] == {'document id': '1',
                                               'document infons article-version': '99'}
    assert identity['bioc_revisions_agree'] is False
    assert identity['revision_requested'] is None
    assert 'bioc_revision' not in identity, 'there is no single revision to report'


@pytest.mark.parametrize('payload,shape', [
    ([{'documents': [{'id': '', 'infons': {'article-id_pmc': '99999999',
                                           'article-id_pmcid': '10592076'},
                      'passages': [{'infons': {'license': BIOC_LICENCE}}]}]}],
     'the document infons contradict each other'),
    ([{'documents': [{'id': '', 'infons': {},
                      'passages': [{'infons': {'license': BIOC_LICENCE,
                                               'article-id_pmc': '99999999',
                                               'article-id_pmcid': '10592076'}}]}]}],
     'the front passage infons contradict each other'),
    ([{'documents': [{'id': '10592076', 'infons': {'article-id_pmc': '99999999'},
                      'passages': [{'infons': {'license': BIOC_LICENCE}}]}]}],
     'the document id and its infon contradict each other'),
])
def test_identifiers_that_contradict_each_other_are_a_payload_in_dispute(tmp_path, payload, shape):
    """The review's R1b. The first form kept one identifier per level, so a document saying
    `article-id_pmc: 99999999` and `article-id_pmcid: 10592076` was accepted for the second: the
    fields contradicted each other and the later one silently won, which is how a licence came to be
    recorded for the requested work out of a payload that half-named another. Two identifiers that
    disagree are not a work named twice; they are a payload whose own identity is in dispute, and
    nothing is read out of it. Every field at every level is now read on its own."""
    r = measured(tmp_path, payload_routes(payload))
    assert r['outcome'] == 'unavailable', shape
    assert 'licence' not in r and 'quotable' not in r
    assert '99999999' in r['error'], shape
    assert (tmp_path / search.LOG).exists()


@pytest.mark.parametrize('payload,shape', [
    ([{'documents': [{'id': '10592076', 'infons': ['article-id_pmc'],
                      'passages': [{'infons': {'license': BIOC_LICENCE}}]}]}],
     'the document infons are a list'),
    ([{'documents': [{'id': '10592076', 'infons': {},
                      'passages': [{'infons': ['license'], 'text': 'front'}]}]}],
     'the front passage infons are a list'),
    ([{'documents': [{'id': '10592076', 'infons': {}, 'passages': 7}]}],
     'the passages are a number'),
    ([{'documents': [{'id': '10592076', 'infons': {}, 'passages': 'front'}]}],
     'the passages are a string'),
])
def test_an_answer_whose_nested_shape_is_wrong_is_recorded_not_raised(tmp_path, payload, shape):
    """The review's R2b, which is R2 one level deeper. `infons` that is not an object raised
    AttributeError on `.get`, and `passages: 7` raised TypeError, both escaping the call with no
    record - so the kit again had an outcome that leaves nothing in the log. Each nested step is
    typed before it is used, and the answer is an `unavailable` call with its record."""
    r = measured(tmp_path, payload_routes(payload))
    assert r['outcome'] == 'unavailable', shape
    assert 'licence' not in r and 'quotable' not in r
    assert (tmp_path / search.LOG).exists(), f'{shape}: the failure is in the log'


# -- a diagnostic may not be a copy of the answer ---------------------------------------------------

CANARY = 'CANARY-BODY-THAT-NO-RECORD-MAY-KEEP'


@pytest.mark.parametrize('payload,shape', [
    ({'body': CANARY}, 'an answer with no document at all'),
    ([{'documents': [{'id': '10592076', 'infons': [CANARY],
                      'passages': [{'infons': {'license': BIOC_LICENCE}}]}]}],
     'infons that are a list'),
    ([{'documents': [{'id': '10592076', 'infons': {},
                      'passages': [{'infons': {'license': [CANARY]}, 'text': CANARY}]}]}],
     'a licence infon that is a list'),
    ([{'documents': [{'id': '10592076', 'infons': {}, 'passages': {'text': CANARY}}]}],
     'passages that are an object'),
    ([{'documents': [{'id': '10592076', 'infons': {}, 'passages': []},
                     {'id': '10592076', 'infons': {}, 'passages': [{'text': CANARY}]}]}],
     'two documents claiming the article'),
])
def test_an_unusable_answer_is_described_and_never_quoted(tmp_path, payload, shape):
    """The licence finding of the third review, and the sharpest of the series. The refusals above
    carried `json.dumps(payload)[:120]` and `json.dumps(infons)[:80]` into the error and from there
    into the log - so this command, which fetches every route with `keep_body=False` precisely so
    that no part of a work it may not reproduce is written down, wrote parts of it down in its
    diagnostics. A diagnostic that quotes the answer is a copy of the answer.

    So an unusable answer is described by where it came from, what it answered, the hash of its bytes
    and the type and path of the shape that was wrong - and by nothing out of those bytes. The canary
    sits in each payload where a body would be; it must appear in no record, no log and no file."""
    r = measured(tmp_path, payload_routes(payload))
    assert r['outcome'] == 'unavailable', shape
    log = (tmp_path / search.LOG).read_text()
    assert CANARY not in json.dumps(r), f'{shape}: the record quotes the answer'
    assert CANARY not in log, f'{shape}: the log quotes the answer'
    for path in (tmp_path / search.RESPONSES).glob('*'):
        assert CANARY not in path.read_bytes().decode('utf-8', 'replace'), f'{shape}: {path.name}'
    # and what a reader does get: the route, its status, the hash of what arrived, and the shape.
    assert 'HTTP 200' in r['error'] and 'sha256:' in r['error'] and 'body not kept' in r['error']


@pytest.mark.parametrize('licence_infon,kind', [(['CC BY 4.0'], 'a list'),
                                                ({'text': 'CC BY 4.0'}, 'an object'),
                                                (4.0, 'a number')])
def test_a_licence_infon_that_is_not_a_statement_is_recorded_not_raised(tmp_path, licence_infon, kind):
    """The third review's R2c: the shape checks reached the infons but not the one field read out of
    them. A `license` infon that is a list or an object raised TypeError from `norm` and escaped the
    call with no record - the same defect as the shapes around it, one field deeper."""
    payload = [{'documents': [{'id': '10592076', 'infons': {},
                               'passages': [{'infons': {'license': licence_infon}}]}]}]
    r = measured(tmp_path, payload_routes(payload))
    assert r['outcome'] == 'unavailable', kind
    assert 'not a string' in r['error'] and 'licence infon' in r['error']
    assert (tmp_path / search.LOG).exists()
    assert 'licence' not in r and 'quotable' not in r


# -- one pass over every field the kit reflects out of an answer ------------------------------------

def canary_in(tmp_path, record, files=True):
    """Everywhere a record could keep what it must not: the record itself, the log, and the files.

    With `files=False` the kept answers are not searched, which is right for a case whose canary sits
    in a **metadata** answer: those are kept by hash on purpose, so that a call can be repeated from
    the bytes it was made of, and the services distribute them as metadata. The rule being tested is
    about what the kit *reflects* - what it copies into a record and into the log - and about the
    full-text routes, which are fetched with `keep_body=False` and leave no file at all.
    """
    where = []
    if CANARY in json.dumps(record):
        where.append('the record')
    log = tmp_path / search.LOG
    if log.exists() and CANARY in log.read_text():
        where.append('the log')
    for path in (tmp_path / search.RESPONSES).glob('*') if files else ():
        if CANARY in path.read_bytes().decode('utf-8', 'replace'):
            where.append(path.name)
    return where


IDENTITY_FIELDS = [
    ('the document id', {'id': {'body': CANARY}, 'infons': {'article-id_pmc': '10592076'}}),
    ('the document id as a list', {'id': [CANARY], 'infons': {'article-id_pmc': '10592076'}}),
    ('article-id_pmc as an object', {'id': '', 'infons': {'article-id_pmc': {'body': CANARY}}}),
    ('article-id_pmcid as a list', {'id': '', 'infons': {'article-id_pmcid': [CANARY]}}),
    ('article-id_pmc as a string of the wrong shape',
     {'id': '', 'infons': {'article-id_pmc': CANARY}}),
    ('article-version as an object',
     {'id': '10592076', 'infons': {'article-version': {'body': CANARY}}}),
    ('article-id_pmc-version as a list',
     {'id': '10592076', 'infons': {'article-id_pmc-version': [CANARY]}}),
    ('article-version as a string of the wrong shape',
     {'id': '10592076', 'infons': {'article-version': CANARY}}),
]


@pytest.mark.parametrize('what,document', IDENTITY_FIELDS, ids=[c[0][:44] for c in IDENTITY_FIELDS])
def test_an_identifier_or_revision_is_validated_before_it_is_reflected(tmp_path, what, document):
    """The review's R4b, and the end of a series it had been finding one field at a time: the
    boundary that lets a refusal name the article it was about holds only for values that are
    identifiers. `article-id_pmc: {"body": …}` was stringified and then put in the message, and
    `article-version: {"body": …}` was written straight into `bioc_revision_stated` with
    `outcome: ok` - so the structure, with whatever it carried, reached the error and the log.

    A string of the wrong shape is in here too, because that is what a body fragment looks like: the
    check is not "is it a `str`" but "is it an identifier", and a value that fails is named by its
    type and its path only.
    """
    payload = [{'documents': [dict(document, passages=[{'infons': {'license': BIOC_LICENCE}}])]}]
    r = measured(tmp_path, payload_routes(payload))
    assert r['outcome'] == 'unavailable', what
    assert canary_in(tmp_path, r) == [], f'{what}: reflected into {canary_in(tmp_path, r)}'
    assert 'does not have the shape of' in r['error'] and 'documents[]' in r['error'], what


def test_an_infons_that_is_null_is_a_shape_and_not_an_absence(tmp_path):
    """The review's R2d. An absent `infons` is an answer that states nothing there, which is
    ordinary and handled; an explicit `null` is a shape the kit does not read, and `.get` on it
    raised AttributeError out of the command with no record at all."""
    payload = [{'documents': [{'id': '10592076', 'infons': {},
                               'passages': [{'infons': None, 'text': 'front'}]}]}]
    r = measured(tmp_path, payload_routes(payload))
    assert r['outcome'] == 'unavailable'
    assert 'null rather than absent' in r['error']
    assert (tmp_path / search.LOG).exists()


def test_a_metadata_value_the_kit_did_not_expect_is_dropped_and_named(tmp_path):
    """Found by sweeping the rest of the reflected fields rather than waiting for the next review.
    `WORK_METADATA` said which keys may be reflected and nothing said what their values may be, so a
    record answering `{"title": {"body": …}}` had that structure copied into the card's work record
    and into the log. It is dropped and named by its path and type, and the measurement goes on,
    because the licence is read from the work's own bytes and a strange `journal` must not stop it."""
    record = {'hitCount': 1, 'resultList': {'result': [{
        'id': '1', 'source': 'MED', 'pmcid': 'PMC10592076', 'doi': '10.1/x',
        'title': {'body': CANARY}, 'journal': ['x' * 400], 'year': 2019}]}}
    routes = [('fullTextXML', None, 500),
              ('BioC_json', json.dumps(bioc_payload(BIOC_LICENCE)).encode(), 200),
              ('search?query=', json.dumps(record).encode(), 200)]
    r = measured(tmp_path, routes)
    assert r['outcome'] == 'ok' and r['licence'] == 'CC-BY-4.0', 'the measurement still happens'
    # files=False: the canary is in the metadata answer, which this kit keeps by hash on purpose so
    # that the call can be repeated. What must not happen is the kit *reflecting* it into the record
    # or the log, and that is what the whitelist now prevents.
    assert canary_in(tmp_path, r, files=False) == []
    assert r['work']['metadata_dropped'] == {'title': 'dict', 'journal': 'list'}
    assert r['work']['pmcid'] == 'PMC10592076' and r['work']['year'] == 2019


def test_a_licence_notice_longer_than_a_notice_is_kept_by_hash(tmp_path):
    """The same rule applied to the one field a record reflects whole by design. A licence statement
    is prose and the measurement is of that prose, so it is carried as it stands - but an answer that
    puts a megabyte where a licence sentence belongs is not a notice. The statement is hashed whole,
    whatever its length, and the text is kept only when it is the length of a notice."""
    long_notice = 'This work is licensed under a Creative Commons Attribution 4.0 International ' \
                  'License. ' + CANARY * 200
    payload = bioc_payload(long_notice)
    r = measured(tmp_path, payload_routes(payload))
    assert r['outcome'] == 'ok' and r['licence'] == 'CC-BY-4.0', 'it is still measured'
    assert r['permissions_text'] is None
    assert 'longer than' in r['permissions_text_withheld']
    assert r['permissions_sha256'] == search.sha256(search.ohfkit.norm(long_notice).encode()) \
        if hasattr(search, 'ohfkit') else r['permissions_sha256'].startswith('sha256:')
    assert canary_in(tmp_path, r) == []


def test_a_parse_failure_is_named_by_its_kind_and_place_not_by_the_parser_s_words(tmp_path):
    """The last reflected field: the exception that says why a route did not answer. A transport
    refusal is the kit's own sentence - a URL and a status - and is kept whole. A parse failure's
    wording comes from the parser and is about the bytes, so the record keeps the kind of failure and
    where in the document it happened, and takes nothing from the answer."""
    jats = f'<article><front>{CANARY}<unclosed></front>'.encode()
    routes = [('fullTextXML', jats, 200),
              ('BioC_json', json.dumps(bioc_payload(BIOC_LICENCE)).encode(), 200),
              ('search?query=', json.dumps({'hitCount': 1, 'resultList': {'result': [
                  {'id': '1', 'source': 'MED', 'pmcid': 'PMC10592076', 'doi': '10.1/x',
                   'title': 'A work'}]}}).encode(), 200)]
    r = measured(tmp_path, routes)
    assert r['outcome'] == 'ok' and r['measured_from'] == BIOC
    assert r['jats_refused'].startswith('xml not well formed at line ')
    assert canary_in(tmp_path, r) == []


# -- every sink, walked with a canary ---------------------------------------------------------------

def licence_routes_for(payload=None, jats=None, jats_status=500, pmcid='PMC10592076', title='A work'):
    record = {'hitCount': 1, 'resultList': {'result': [
        {'id': '1', 'source': 'MED', 'pmcid': pmcid, 'doi': '10.1/x', 'title': title}]}}
    routes = [('fullTextXML', jats, 200 if jats else jats_status),
              ('search?query=', json.dumps(record).encode(), 200)]
    if payload is not None:
        routes.insert(1, ('BioC_json', json.dumps(payload).encode(), 200))
    return routes


def one_document(**document):
    doc = {'id': '10592076', 'infons': {},
           'passages': [{'infons': {'license': BIOC_LICENCE}, 'text': 'front matter'}]}
    doc.update(document)
    return [{'source': 'PMC', 'documents': [doc]}]


LONG_CANARY_NOTICE = ('This work is licensed under some terms. ' + CANARY + ' ') * 80
NOTICE_WITH_CANARY = f'This work is licensed under a {CANARY} License.'


def sink_document_id(tmp_path):
    return licence_routes_for(one_document(id={'body': CANARY}, infons={'article-id_pmc': '10592076'}))


def sink_article_identifiers(tmp_path):
    return licence_routes_for(one_document(id='', infons={'article-id_pmc': CANARY}))


def sink_revision_fields(tmp_path):
    return licence_routes_for(one_document(infons={'article-version': {'body': CANARY}}))


def sink_bioc_permissions_text(tmp_path):
    return licence_routes_for(one_document(
        passages=[{'infons': {'license': LONG_CANARY_NOTICE}, 'text': 'front'}]))


def sink_jats_permissions_text(tmp_path):
    jats = CC_BY_JATS.replace(b'Creative Commons Attribution 4.0 International License',
                              LONG_CANARY_NOTICE.encode())
    return licence_routes_for(one_document(), jats=jats)


def sink_measured_refusal(tmp_path):
    # A refusal whose reason quotes the statement, with the statement too long to be carried: the
    # quote must not become the copy the withholding prevented.
    return licence_routes_for(one_document(
        passages=[{'infons': {'license': LONG_CANARY_NOTICE}, 'text': 'front'}]))


def sink_jats_refused(tmp_path):
    return licence_routes_for(one_document(), jats=f'<article>{CANARY}<unclosed></article>'.encode())


def sink_response_url_status_hash(tmp_path):
    return licence_routes_for(one_document(), pmcid=f'PMC{CANARY}')


def sink_work_metadata(tmp_path):
    return licence_routes_for(one_document(), title={'body': CANARY})


def sink_held_aside(tmp_path):
    (tmp_path / 'PMC10592076.xml').write_bytes(f'<{CANARY}><front/></{CANARY}>'.encode())
    return licence_routes_for(one_document())


def sink_historical_answer(tmp_path):
    # A first measurement whose notice is withheld, then a second by the other route: the first is an
    # answer and the comparison must see it. The canary rides in the withheld notice.
    searcher = search.Searcher(tmp_path, get=Routed(licence_routes_for(
        one_document(passages=[{'infons': {'license': LONG_CANARY_NOTICE}, 'text': 'f'}]))),
        sleep=lambda *_: None, clock=lambda: 0.0)
    searcher.licence('PMC10592076')
    return licence_routes_for(one_document(), jats=CC_BY_JATS)


SINKS = [
    ('document id', sink_document_id),
    ('document/front article-id_pmc and article-id_pmcid', sink_article_identifiers),
    ('document/front revision fields', sink_revision_fields),
    ('BioC permissions_text', sink_bioc_permissions_text),
    ('JATS permissions_text', sink_jats_permissions_text),
    ('licence/refusal and licence_answers refusal', sink_measured_refusal),
    ('jats_refused', sink_jats_refused),
    ('response URL/status/hash', sink_response_url_status_hash),
    ('work WORK_METADATA', sink_work_metadata),
    ('licence_held_aside.not_an_answer', sink_held_aside),
    ('licence_held historical answer inclusion', sink_historical_answer),
]


@pytest.mark.parametrize('sink,build', SINKS, ids=[name for name, _ in SINKS])
def test_no_sink_reflects_what_the_answer_carried(tmp_path, sink, build):
    """Every place this command writes something that came from an answer, walked with a canary.

    The list is the review's own inventory of eleven sinks, in its order, and the reason it is one
    test rather than eleven rounds: four reviews fixed the same defect in four places, and each time
    the next sink was found by someone else. Now the rule has one implementation (`reflect`) and this
    test is what says so - a new sink that does not go through the gate fails here.

    What may still appear: the kit's own sentences, the URL it built, the status, the hash, and a
    licence notice short enough to be a notice. What may not: anything else out of the answer. The
    canary stands for a body in each case; a kept **metadata** answer is excluded by `files=False`,
    because the kit keeps those by hash on purpose so a call can be repeated.
    """
    routes = build(tmp_path)
    r = measured(tmp_path, routes)
    assert r['outcome'] in ('ok', 'unavailable'), r.get('error')
    assert canary_in(tmp_path, r, files=False) == [], f'{sink}: reflected into {canary_in(tmp_path, r, files=False)}'
    for path in (tmp_path / search.RESPONSES).glob('*.body'):
        kept = path.read_bytes().decode('utf-8', 'replace')
        assert 'resultList' in kept or CANARY not in kept, f'{sink}: a full text was kept in {path.name}'


def test_a_withheld_statement_is_still_an_answer(tmp_path):
    """The review's R3b, and the one finding of the series that was a mistake of meaning rather than
    of hygiene - my own bound undoing my own rule.

    Keeping a long notice by hash only made `permissions_text: null`, and `licence_held` read the
    absent text as a route that had said nothing. So a measured refusal - an NonCommercial licence,
    with its hash, its time and its route - dropped out of the comparison, and the other route's
    CC BY 4.0 came out quotable with no disagreement at all: the kit would have let a card quote a
    work whose own permissions element refuses it. Whether a statement was measured is now read from
    the hash, not from the text, and silence is the hash of an empty statement.
    """
    long_nc = ('This article is licensed under a Creative Commons Attribution-NonCommercial 4.0 '
               'International License. ' + 'padding to make it longer than a notice. ' * 60)
    first = measured(tmp_path, licence_routes_for(
        one_document(), jats=NC_JATS.replace(b'Attribution-NonCommercial 4.0 International',
                                             long_nc.encode())))
    assert first['quotable'] is False and first['permissions_text'] is None, 'the text is withheld'
    assert first['permissions_sha256'] != search.sha256(b''), 'but a statement was measured'
    second = measured(tmp_path, licence_routes_for(one_document()))
    assert second['refusal_code'] == 'licence_sources_disagree', (
        'the withheld refusal is an answer, and it disagrees with CC BY 4.0 from the other route')
    assert second['quotable'] is False and second['licence'] is None


# -- the four paths that free-text filtering could not hold -----------------------------------------

APOSTROPHE_NOTICE = ("This article's licence is described at the publisher's site. " + CANARY + ' ') * 40


def test_a_statement_with_an_apostrophe_cannot_push_itself_into_a_refusal(tmp_path):
    """The first of the review's four paths, and the one that ended free-text filtering. A refusal's
    words were filtered by removing spans the author had quoted - which works while the author quotes
    with apostrophes. `repr` switches to double quotes when the string itself contains an apostrophe,
    so a statement that says "the article's licence" came back through the filter untouched.

    There is no refusal text from the answer any more. A record carries the code, the kit's own
    sentence for that code, and facts of the kit's own vocabulary."""
    payload = one_document(passages=[{'infons': {'license': APOSTROPHE_NOTICE}, 'text': 'front'}])
    r = measured(tmp_path, licence_routes_for(payload))
    assert r['outcome'] == 'ok' and r['quotable'] is False
    assert r['licence_refusal_code'] == 'no_licence_named'
    assert r['refusal'] == search.REFUSAL_PHRASES['no_licence_named']
    assert canary_in(tmp_path, r) == [], 'the apostrophe route is closed with the rest'


def test_a_cached_verdict_is_read_through_the_gate(tmp_path):
    """The second path: a verdict measured by an earlier call was reflected into
    `licence_answers[].refusal` as text. Whatever that older record quoted - written by this kit
    before the codes, or by an older one - came back into a new record and a new log line. A held
    answer carries its code and its licence, which is all a comparison needs."""
    searcher = search.Searcher(tmp_path, get=Routed(licence_routes_for(one_document(
        passages=[{'infons': {'license': APOSTROPHE_NOTICE}, 'text': 'f'}]))),
        sleep=lambda *_: None, clock=lambda: 0.0)
    first = searcher.licence('PMC10592076')
    assert first['quotable'] is False
    # An older record, as one would be on disk: a refusal in words, with the statement in it.
    hand_written = dict(first, call_id='00000000dead', refusal=f"ambiguous licence: {CANARY}",
                        licence_refusal_code=None)
    searcher.log(hand_written)
    second = measured(tmp_path, licence_routes_for(one_document(), jats=CC_BY_JATS))
    assert second['outcome'] == 'ok'
    # The old line stays in the log, where it was written; what must not happen is its words coming
    # back into the new record, and into the new line this call writes.
    assert CANARY not in json.dumps(second), 'the new record quotes the old record'
    assert CANARY not in search.read_log(tmp_path)[-1].get('refusal', ''), 'and neither does the log line'
    held = [a for a in (second['licence_answers'] or []) if 'earlier measurement' in a['held_as']]
    assert held and all('refusal' not in a for a in held), 'a held answer carries a code, not words'
    assert held[0]['refusal_code'] in (None, 'no_licence_named')


def test_a_response_that_lies_about_its_encoding_keeps_its_bytes_out_of_the_record(tmp_path):
    """The third path. `foreign` trusted a `SearchError` because the kit writes those itself - but one
    of them wrapped a decompressor's complaint, and gzip names the first bytes of what it was given:
    a body fragment inside the kit's own exception. No exception's words are reflected now, whoever
    wrote it."""
    class Lying:
        def __call__(self, url, body=None):
            if 'fullTextXML' in url:
                return 200, CANARY.encode() * 50, {'Content-Encoding': 'gzip'}
            if 'BioC_json' in url:
                return 200, json.dumps(one_document()).encode(), {}
            return 200, json.dumps({'hitCount': 1, 'resultList': {'result': [
                {'id': '1', 'source': 'MED', 'pmcid': 'PMC10592076', 'doi': '10.1/x',
                 'title': 'A work'}]}}).encode(), {}

    r = search.Searcher(tmp_path, get=Lying(), sleep=lambda *_: None,
                        clock=lambda: 0.0).licence('PMC10592076')
    assert r['outcome'] == 'ok' and r['measured_from'] == BIOC, 'the other route answered'
    assert canary_in(tmp_path, r) == [], f'reflected into {canary_in(tmp_path, r)}'
    assert r['jats_refused'] == search.reflect('foreign', search.SearchError('x')), (
        "the record carries the kit's own phrase for a route that did not answer, not the "
        "exception's words - which is what carried the bytes")
    assert r['jats_refused_code'] == 'SearchError'


def test_a_jats_that_answers_without_a_licence_is_a_coded_refusal_not_an_escaping_error(tmp_path):
    """Two findings meet in this one case.

    The first: on the direct JATS route a `LicenceError` left `run` entirely, and `call` recorded
    `str(e)` - so the document's root element, quoted in that message, landed in the log one frame
    further out than any of the gates.

    The second, which came next and is about meaning: catching that error must not turn "the JATS
    answered and states no licence" into a reason to ask another service. The owner's rule is that
    the BioC infon is read when the JATS **refuses** - a transport failure, or an answer the kit
    cannot read at all - and a document that parsed is an answer, whatever it says. So this refuses
    with the route's own code, and the BioC route is not asked, although it would have said CC BY 4.0.
    """
    jats = f'<{CANARY}><front><article-meta/></front></{CANARY}>'.encode()
    asked = []

    class Watched(Routed):
        def __call__(self, url, body=None):
            asked.append(url)
            return super().__call__(url, body)

    r = search.Searcher(tmp_path, get=Watched(licence_routes_for(one_document(), jats=jats)),
                        sleep=lambda *_: None, clock=lambda: 0.0).licence('PMC10592076')
    assert r['outcome'] == 'ok' and r['measured_from'] == JATS
    assert r['quotable'] is False and r['licence'] is None
    assert r['licence_refusal_code'] == 'root_not_article'
    assert not any('BioC' in url for url in asked), 'a route that answered is not second-guessed'
    assert canary_in(tmp_path, r) == [], 'the root element never reaches a record'



def test_a_shape_is_matched_whole(tmp_path):
    """The review's advisory, which is a mutant of its own: `match` with `$` lets a trailing newline
    through, because `$` matches before a final LF. An identifier is a line or it is not one."""
    payload = one_document(id='', infons={'article-id_pmc': '10592076\n'})
    r = measured(tmp_path, licence_routes_for(payload))
    assert r['outcome'] == 'unavailable' and 'does not have the shape' in r['error']


# -- a route that answered is not second-guessed, and a fact belongs to its reason ------------------

ARTICLE_NO_PERMISSIONS = (b'<article><front><article-meta><title-group><article-title>A work'
                          b'</article-title></title-group></article-meta></front><body><sec><p>Body.'
                          b'</p></sec></body></article>')


def test_a_jats_that_states_no_licence_is_a_refusal_and_the_other_route_is_not_asked(tmp_path):
    """The review's R5, and a regression I introduced myself while closing an unrelated leak.

    The owner's rule for the second route is narrow: the BioC infon is read when the JATS **refuses**.
    Catching `LicenceError` to stop it escaping into `call` widened that to "or answers without a
    licence", and the consequence is as bad as it gets here - a valid article whose own permissions
    element is absent came out `quotable: true` on another service's sentence. On the head before the
    catch this was a `failed` call; it is now a refusal with the JATS route's own code.

    The assertion that matters is the one about the transport: the BioC route is never asked, so the
    kit cannot have taken its answer.
    """
    asked = []

    class Watched(Routed):
        def __call__(self, url, body=None):
            asked.append(url)
            return super().__call__(url, body)

    r = search.Searcher(tmp_path, get=Watched(licence_routes_for(one_document(),
                                                                 jats=ARTICLE_NO_PERMISSIONS)),
                        sleep=lambda *_: None, clock=lambda: 0.0).licence('PMC10592076')
    assert r['outcome'] == 'ok'
    assert r['quotable'] is False and r['licence'] is None
    assert r['measured_from'] == JATS and r['licence_refusal_code'] == 'no_article_permissions'
    assert not any('BioC' in url for url in asked), 'the other route was asked after an answer'


def test_the_other_route_is_still_read_when_the_jats_does_not_answer(tmp_path):
    """The other side of the same rule, so that closing R5 cannot close the fallback itself: a
    transport refusal and an unreadable answer are what the second route exists for."""
    for jats, status, what in ((None, 500, 'a transport refusal'),
                               (b'<article><front', 200, 'an answer that does not parse')):
        work = tmp_path / what.replace(' ', '-')
        work.mkdir()
        r = measured(work, licence_routes_for(one_document(), jats=jats, jats_status=status))
        assert r['outcome'] == 'ok' and r['measured_from'] == BIOC, what
        assert r['licence'] == 'CC-BY-4.0', what


FACT_MUTANTS = [
    ('marker', 'restriction_marker', 'nc', True),
    ('marker', 'restriction_marker', 'canary', False),
    ('marker', 'restriction_marker', 'CANARY-BODY', False),
    ('count', 'several_versions', 3, True),
    ('count', 'several_versions', 1, False),
    ('count', 'several_versions', '2', False),
    ('count', 'several_versions', True, False),
    ('licence', 'version_not_allowed', 'CC-BY-5.0', False),
    ('licence', 'version_not_allowed', 'CC-BY-4.0', True),
    ('licence', 'version_not_allowed', f'CC-BY-{CANARY}', False),
    ('release', 'no_version_before_1_1_4', '1.1.3', True),
    ('release', 'no_version_before_1_1_4', CANARY, False),
    ('release', 'no_version_before_1_1_4', '1.1', False),
    ('marker', 'no_statement', 'nc', False),
    ('count', 'no_licence_named', 3, False),
]


@pytest.mark.parametrize('key,code,value,kept', FACT_MUTANTS,
                         ids=[f'{k}={v!r} on {c}{"" if keep else " dropped"}'[:60]
                              for k, c, v, keep in FACT_MUTANTS])
def test_a_fact_is_part_of_its_reason_or_it_is_nothing(key, code, value, kept):
    """The review's F1, one mutant per key. The facts beside a refusal's code were checked against
    shapes wide enough to admit a body fragment - `marker` against `[a-z]{2,20}`, `licence` against
    `[A-Za-z0-9.-]{1,60}` - and a key could ride on a code that never produces it.

    So each code declares which keys it may have, and each key has a vocabulary or a range rather
    than a shape: a marker is one of the kit's own marker names, a licence one of the ids the kit
    itself can emit, a release a three-part version, a count a small whole number of the right size.
    The last two cases are the other half: a perfectly shaped value on a code that does not declare
    it is dropped, because a fact belongs to a reason or to nothing.
    """
    import ohfkit
    record = search.refusal_record(ohfkit.LicenceError('message', code=code, **{key: value}))
    assert record['code'] == code
    assert (key in record) is kept, record
    if kept:
        assert record[key] == value


# -- one definition of an answer, walked as sequences -----------------------------------------------

def test_a_coded_refusal_is_remembered_when_the_route_later_fails(tmp_path):
    """The review's R3c, and the third time the same confusion came back wearing different clothes.

    The sequence: the JATS answers 200 with an article that has no permissions element, which is a
    coded refusal and an answer, so the other route is not asked. Then the JATS answers 500 and the
    BioC route says CC BY 4.0 - and the earlier verdict was being forgotten, because `licence_held`
    still decided what counted as an answer by looking at the statement's hash while the routing had
    moved on to verdicts. Two copies of one definition, drifting apart for the third time.

    There is one definition now (`answered`), in one place, and both the routing and `licence_held`
    call it. The verdict stands, the routes disagree, and the work is not quotable."""
    first = measured(tmp_path, licence_routes_for(one_document(), jats=ARTICLE_NO_PERMISSIONS))
    assert first['licence_refusal_code'] == 'no_article_permissions' and first['quotable'] is False
    second = measured(tmp_path, licence_routes_for(one_document()))
    assert second['refusal_code'] == 'licence_sources_disagree', 'the earlier verdict was forgotten'
    assert second['quotable'] is False and second['licence'] is None
    earlier = [a for a in second['licence_answers'] if 'earlier measurement' in a['held_as']]
    assert earlier and earlier[0]['refusal_code'] == 'no_article_permissions'
    assert earlier[0]['at'] and earlier[0]['statement_sha256'], 'with its time and its hash'


def test_a_transport_failure_is_not_remembered_as_an_answer(tmp_path):
    """The other half of the same definition, which keeps closing R3c from closing the fallback: a
    route that could not be reached said nothing, and nothing is not a verdict. Two failed calls in a
    row leave no answer behind, so the first real measurement stands on its own."""
    for _ in range(2):
        failed = measured(tmp_path, [('fullTextXML', None, 500),
                                     ('BioC_json', None, 503),
                                     ('search?query=', json.dumps({'hitCount': 1, 'resultList': {
                                         'result': [{'id': '1', 'source': 'MED',
                                                     'pmcid': 'PMC10592076', 'doi': '10.1/x',
                                                     'title': 'A work'}]}}).encode(), 200)])
        assert failed['outcome'] == 'failed', failed.get('outcome')
    now = measured(tmp_path, licence_routes_for(one_document()))
    assert now['quotable'] is True and now['licence'] == 'CC-BY-4.0'
    assert now.get('refusal_code') is None and 'licence_answers' not in now


def test_an_unreadable_answer_is_not_remembered_as_an_answer(tmp_path):
    """And the third sequence: a JATS whose bytes do not parse is unreadable, not a refusal of the
    work. It falls through to the other route, as it must, and leaves no verdict to contradict the
    next measurement."""
    first = measured(tmp_path, licence_routes_for(one_document(), jats=b'<article><front'))
    assert first['measured_from'] == BIOC and first['licence'] == 'CC-BY-4.0'
    second = measured(tmp_path, licence_routes_for(one_document(), jats=CC_BY_JATS))
    assert second['measured_from'] == JATS and second['quotable'] is True
    assert second.get('refusal_code') is None, 'two CC BY 4.0 answers do not disagree'
    assert {a['route'] for a in second['licence_answers']} == {JATS, BIOC}


# -- no code means no code --------------------------------------------------------------------------

def test_a_grant_keeps_no_refusal_code_through_three_calls(tmp_path):
    """The review's R3d, and the narrowest defect of the series with the furthest reach.

    `reflect('code', None)` returned `unclassified`, so a licence recovered from an earlier call came
    back as CC-BY-4.0 **with a refusal code beside it** - and the next call wrote that invented
    refusal into a new log line, where a third call would read it as a real one. A reflection that
    fills in a value is not a reflection.

    Three calls, because that is how far it travelled: measure, carry the answer through an aggregate,
    and read it back again."""
    first = measured(tmp_path, licence_routes_for(one_document(), jats=CC_BY_JATS))
    assert first['licence'] == 'CC-BY-4.0' and 'licence_refusal_code' not in first
    # A disagreement between two **routes**, so the grant has to pass through an aggregate on its way
    # to the third call: the BioC infon grants CC BY 4.0 while the cached permissions element carries
    # NonCommercial.
    (tmp_path / 'PMC10592076.xml').write_bytes(NC_JATS)
    second = measured(tmp_path, licence_routes_for(one_document()))
    assert second['refusal_code'] == 'licence_sources_disagree'
    carried = [a for a in second['licence_answers'] if a['licence'] == 'CC-BY-4.0']
    assert carried and all(a['refusal_code'] is None for a in carried), carried
    (tmp_path / 'PMC10592076.xml').unlink()
    third = measured(tmp_path, licence_routes_for(one_document(), jats=CC_BY_JATS))
    grants = [a for a in (third['licence_answers'] or []) if a['licence'] == 'CC-BY-4.0']
    assert grants and all(a['refusal_code'] is None for a in grants), grants
    assert 'unclassified' not in json.dumps(third), 'an invented code reached the third call'
    assert 'unclassified' not in (tmp_path / search.LOG).read_text()


def test_a_real_refusal_with_no_code_stays_a_refusal(tmp_path):
    """The other case, which must not be swept up with it: an error the kit cannot name is still an
    error. `refusal_record` maps it to `unclassified` - there *was* a refusal, and the kit has no name
    for its reason - while a grant has no code at all. The two are opposite and must not be written
    the same way."""
    import ohfkit
    nameless = search.refusal_record(ohfkit.LicenceError('something the kit has no code for'))
    assert nameless['code'] == 'unclassified'
    assert nameless['phrase'] == search.REFUSAL_PHRASES['unclassified']
    # And through the log: an answer carrying it stays a refusal, with no licence.
    assert search.answered(None, 'unclassified') is True
    assert search.answered(None, None) is False, 'nothing is not an answer'
    assert search.reflect('code', None) is None
    assert search.reflect('code', 'no_licence_named') == 'no_licence_named'
    assert search.reflect('code', 'something else entirely') == 'unclassified'


# -- an address without a body ----------------------------------------------------------------------

NC_BODY = ('<article><front><article-meta><permissions><license><license-p>This work is licensed '
           'under CC BY-NC 4.0</license-p></license></permissions></article-meta></front><body><sec>'
           '<p>First paragraph of the body, which no record may keep.</p>'
           '<p>Amoebae counter-select virulence attributes here. A second sentence follows. '
           'A third mentions counter-select again.</p></sec></body></article>').encode()


def locate_routes(body=NC_BODY, pmcid='PMC9927882'):
    record = {'hitCount': 1, 'resultList': {'result': [
        {'id': '1', 'source': 'MED', 'pmcid': pmcid, 'doi': '10.1/x', 'title': 'A work',
         'abstractText': ABSTRACT}]}}
    return [('fullTextXML', body, 200), ('search?query=', json.dumps(record).encode(), 200)]


def test_an_address_is_produced_without_keeping_or_quoting_the_work(tmp_path):
    """A quote_withheld line needs the native locator even when quotation is refused.

    Addresses match the native reader. Injected JATS passages are absent from the
    record, log and controlled response files; metadata and caller words remain.
    """
    r = measured(tmp_path, locate_routes(), command='locate', find='counter-select')
    assert r['outcome'] == 'ok' and r['addresses'] == 1
    at = r['at'][0]
    assert at['locator'] == 'XML .//p[2] (1-based document order)'
    assert at['paragraph'] == 2 and at['sentences'] == [1, 3]
    assert at['sentences_in_paragraph'] == 3 and at['paragraph_characters'] > 0
    assert r['document_sha256'].startswith('sha256:') and r['kept'] is False
    # Check these injected JATS passages in the explicit record/log/cache sinks.
    for place in (json.dumps(r), (tmp_path / search.LOG).read_text()):
        assert 'counter-select virulence attributes' not in place
        assert 'First paragraph of the body' not in place
    for path in (tmp_path / search.RESPONSES).glob('*'):
        assert b'counter-select virulence' not in path.read_bytes()


def test_an_address_is_the_same_address_the_card_s_locator_means(tmp_path):
    """The address is worth nothing unless it is the one a reader of the card will use. The split is
    `ohfkit`'s own - `.//p` in document order - so this test reads the same bytes both ways and
    requires the two to agree, rather than trusting that two copies of a rule stay equal."""
    import ohfkit
    r = measured(tmp_path, locate_routes(), command='locate', find='counter-select')
    paragraph = r['at'][0]['paragraph']
    doc_paragraphs = [ohfkit.norm(''.join(el.itertext()))
                      for el in search.ET.fromstring(NC_BODY).iter('p')]
    assert 'counter-select' in doc_paragraphs[paragraph - 1].casefold()
    assert r['locator_form'] == ohfkit.LOCATOR
    assert r['paragraphs'] == len(doc_paragraphs)


def test_words_that_are_not_there_give_no_address(tmp_path):
    """A locate that finds nothing says so, and its exit code says so too: no address may be read out
    of an absence. The log keeps the call, because a question asked is a record."""
    r = measured(tmp_path, locate_routes(), command='locate', find='phlogiston')
    assert r['outcome'] == 'ok' and r['addresses'] == 0 and r['at'] == []
    assert r['paragraphs'] == 2, 'the document was read; it simply does not say that'
    assert (tmp_path / search.LOG).exists(), 'a question asked is a record'


def test_a_full_text_that_does_not_parse_has_no_addresses(tmp_path):
    """And the shape of a failure: an answer that does not parse is `unavailable` with its record, as
    everywhere else in this file, and the parse error is named by its kind and place."""
    r = measured(tmp_path, locate_routes(body=b'<article><front'), command='locate', find='anything')
    assert r['outcome'] == 'unavailable' and 'does not parse' in r['error']
    assert 'xml not well formed at line' in r['error']


def body_markers_in_sinks(paths, body, needle_length=48, max_bytes=2_000_000):
    """Inspect only explicitly supplied fixture sinks; never walk host /tmp.

    No names or mtimes are excluded. Files over max_bytes and unreadable paths are reported as
    unchecked, not clean. Matches use only the first/last needle_length bytes (default 48): arbitrary
    excerpts, transformed/compressed data, transient/deleted files and uninstrumented writes are
    outside this test's evidence. This is not a universal no-text or filesystem-retention proof.
    """
    markers = (bytes(body)[:needle_length], bytes(body)[-needle_length:])
    result = {'matched': [], 'checked': [], 'unchecked': []}
    for path in sorted(set(map(Path, paths))):
        try:
            with path.open('rb') as f:
                data = f.read(max_bytes + 1)
        except OSError as e:
            result['unchecked'].append({'path': str(path), 'reason': type(e).__name__})
            continue
        if len(data) > max_bytes:
            result['unchecked'].append({'path': str(path), 'reason': 'size_limit'})
            continue
        result['checked'].append(str(path))
        if any(marker in data for marker in markers):
            result['matched'].append(str(path))
    return result


@pytest.fixture
def written_paths(monkeypatch):
    """Record path-based Python open calls for this fixture, including overwrites outside workdir.

    This covers builtins.open, io.open (Path.open) and os.open; not direct native writes, inherited
    descriptors, mmap, transient content or subprocesses. The offline test runner denies processes.
    """
    import builtins
    import io
    paths = set()

    def remember(path):
        if not isinstance(path, int):
            paths.add(Path(os.fsdecode(path)).absolute())

    def wrap_open(original):
        def opened(path, mode='r', *args, **kwargs):
            if any(c in mode for c in 'wax+'):
                remember(path)
            return original(path, mode, *args, **kwargs)
        return opened

    original_os_open = os.open

    def os_open(path, flags, *args, **kwargs):
        if flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
            assert kwargs.get('dir_fd') is None, 'dir_fd writes need explicit sink binding'
            remember(path)
        return original_os_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(builtins, 'open', wrap_open(builtins.open))
    monkeypatch.setattr(io, 'open', wrap_open(io.open))
    monkeypatch.setattr(os, 'open', os_open)
    return paths


def test_locate_jats_markers_absent_from_instrumented_sinks(tmp_path, written_paths):
    """The controlled call retains no complete JATS markers in its recorded Python write sinks.
    Metadata abstractText and caller find are intentionally retained; this is not a no-text claim.
    """
    r = measured(tmp_path, locate_routes(), command='locate', find='counter-select')
    assert r['outcome'] == 'ok' and r['addresses'] == 1
    sinks = written_paths | {p for p in tmp_path.rglob('*') if p.is_file()}
    audit = body_markers_in_sinks(sinks, NC_BODY)
    assert audit['checked'] and not audit['unchecked']
    assert not audit['matched'], 'JATS body markers survived in an inspected fixture sink'
    # The response record says so too, and no file was written for that hash.
    fetched = [x for x in r['responses'] if 'fullTextXML' in x['url']]
    assert fetched and fetched[0]['kept'] is False
    digest = fetched[0]['sha256'].split(':')[1]
    assert not list((tmp_path / search.RESPONSES).glob(f'{digest}*'))
    # And what does remain: the hash, which is a name for bytes and not the bytes.
    assert r['document_sha256'] == search.sha256(NC_BODY)
    assert r['ask']['find'] == 'counter-select'
    assert read_calls(tmp_path)[-1]['ask']['find'] == 'counter-select'
    assert any(ABSTRACT.encode() in p.read_bytes()
               for p in (tmp_path / search.RESPONSES).glob('*'))


@pytest.mark.parametrize('dirname', ['old', '.git', '.cache', 'venv', 'node_modules', '__pycache__'])
def test_locate_sink_check_detects_overwrite_below_old_ancestor(tmp_path, dirname):
    work = tmp_path / 'work'
    work.mkdir()
    old = tmp_path / dirname
    nested = old / 'existing'
    nested.mkdir(parents=True)
    leak = nested / 'existing.xml'
    leak.write_bytes(b'prior bytes')
    os.utime(old, (1, 1))
    old_mtime = old.stat().st_mtime_ns
    leak.write_bytes(NC_BODY)
    assert old.stat().st_mtime_ns == old_mtime
    # Explicit sinks include an existing file outside workdir, without mtime or name pruning.
    assert body_markers_in_sinks([leak], NC_BODY)['matched'] == [str(leak)]


def test_locate_write_instrumentation_tracks_existing_external_fixture(tmp_path, written_paths):
    work = tmp_path / 'work'
    work.mkdir()
    nested = tmp_path / 'outside-workdir' / 'old'
    nested.mkdir(parents=True)
    leak = nested / 'existing.xml'
    leak.write_bytes(b'prior bytes')
    written_paths.clear()
    os.utime(nested.parent, (1, 1))
    leak.write_bytes(NC_BODY)
    measured(work, locate_routes(), command='locate', find='counter-select')
    assert leak in written_paths
    assert body_markers_in_sinks(written_paths, NC_BODY)['matched'] == [str(leak)]


def test_locate_sink_audit_reports_size_missing_and_marker_limits(tmp_path):
    big = tmp_path / 'large.xml'
    big.write_bytes(NC_BODY + b'x' * 2_000_001)
    missing = tmp_path / 'missing.xml'
    excerpt = tmp_path / 'excerpt.txt'
    excerpt.write_bytes(b'Amoebae counter-select virulence attributes here.')
    audit = body_markers_in_sinks([big, missing, excerpt], NC_BODY)
    assert audit['matched'] == []  # Arbitrary body excerpts are outside first/last48-byte matching.
    assert audit['checked'] == [str(excerpt)]
    assert {x['reason'] for x in audit['unchecked']} == {'size_limit', 'FileNotFoundError'}


@pytest.mark.parametrize('text,needle,expected', [
    ('Dr. Ada measured growth. Next result followed.', 'growth', [1]),
    ('Value rose.” Next result followed.', 'Next', [2]),
    ('A result (Fig. 2) rose. Next result followed.', 'Next', [2]),
])
def test_locate_sentence_addresses_match_native_reader(tmp_path, text, needle, expected):
    import ohfkit
    raw = ('<article><body><p>' + text + '</p></body></article>').encode()
    r = measured(tmp_path, locate_routes(raw), command='locate', find=needle)
    native = ohfkit.sentences_of(ohfkit.norm(text))
    assert r['at'][0]['sentences'] == expected
    assert r['at'][0]['sentences'] == [n for n, s in enumerate(native, 1)
                                      if needle.casefold() in s.casefold()]
    assert r['at'][0]['sentences_in_paragraph'] == len(native)


@pytest.mark.parametrize('limit,expected', [(None, 5), ('1', 1), ('3', 3), ('9', 7)])
def test_locate_cli_limit_reaches_native_call(tmp_path, monkeypatch, capsys, limit, expected):
    raw = b'<article><body>' + b'<p>needle.</p>' * 7 + b'</body></article>'
    s = search.Searcher(tmp_path, get=Routed(locate_routes(raw)), sleep=lambda *_: None,
                        clock=lambda: 0.0)
    monkeypatch.setattr(search, 'Searcher', lambda *_: s)
    args = ['locate', 'PMC9927882', '--find', 'needle', '--workdir', str(tmp_path)]
    if limit is not None:
        args += ['--limit', limit]
    assert search.main(args) == 0
    r = json.loads(capsys.readouterr().out)
    assert r['addresses'] == expected
    assert r['ask']['limit'] == (5 if limit is None else int(limit))


@pytest.mark.parametrize('limit', ['0', '-1', '1.5', 'no'])
def test_locate_cli_rejects_invalid_limit_before_search(tmp_path, monkeypatch, limit):
    def no_search(*args, **kwargs):
        pytest.fail('invalid CLI limit reached Searcher')
    monkeypatch.setattr(search, 'Searcher', no_search)
    with pytest.raises(SystemExit) as exc:
        search.main(['locate', 'PMC9927882', '--find', 'needle', '--limit', limit,
                     '--workdir', str(tmp_path)])
    assert exc.value.code == 2
    assert not (tmp_path / search.LOG).exists()


@pytest.mark.parametrize('limit', [0, -1, True, 1.5, '1'])
def test_locate_api_rejects_invalid_limit_without_metadata_lookup(tmp_path, monkeypatch, limit):
    s = search.Searcher(tmp_path)
    def no_lookup(*args, **kwargs):
        pytest.fail('invalid API limit reached metadata lookup')
    monkeypatch.setattr(s, 'epmc_record', no_lookup)
    r = s.locate('PMC9927882', 'needle', limit=limit)
    assert r['outcome'] == 'failed' and 'positive integer' in r['error']
    assert r['responses'] == []


def test_locate_cli_no_address_and_missing_pmcid_keep_failure_semantics(tmp_path, monkeypatch, capsys):
    cls = search.Searcher
    s = cls(tmp_path, get=Routed(locate_routes()), sleep=lambda *_: None, clock=lambda: 0.0)
    monkeypatch.setattr(search, 'Searcher', lambda *_: s)
    assert search.main(['locate', 'PMC9927882', '--find', 'phlogiston',
                        '--workdir', str(tmp_path)]) == 1
    r = json.loads(capsys.readouterr().out)
    assert r['outcome'] == 'ok' and r['addresses'] == 0
    assert r['document_sha256'] == search.sha256(NC_BODY)
    missing = cls(tmp_path / 'missing', get=Routed(locate_routes(pmcid=None)),
                  sleep=lambda *_: None, clock=lambda: 0.0)
    r = missing.locate('PMC9927882', 'needle')
    assert r['outcome'] == 'failed' and 'no PMCID' in r['error']
    assert not any('fullTextXML' in response['url'] for response in r['responses'])


@pytest.mark.parametrize('limit,expected', [(None, 100), ('7', 7)])
def test_locate_cli_change_preserves_literature_limits(tmp_path, monkeypatch, capsys, limit, expected):
    seen = []
    class Literature:
        def literature(self, query, count, *args):
            seen.append(count)
            return []
    monkeypatch.setattr(search, 'Searcher', lambda *_: Literature())
    args = ['literature', 'synthetic', '--workdir', str(tmp_path)]
    if limit is not None:
        args += ['--limit', limit]
    assert search.main(args) == 0
    assert seen == [expected]


@pytest.mark.parametrize('entrypoint',['api','cli'])
def test_locate_unknown_xml_codec_is_logged_unavailable(tmp_path,monkeypatch,capsys,entrypoint):
    raw=b'<?xml version="1.0" encoding="not-a-codec"?><article><body><p>needle.</p></body></article>'
    s=search.Searcher(tmp_path,get=Routed(locate_routes(raw)),sleep=lambda *_:None,clock=lambda:0.0)
    if entrypoint=='api':record=s.locate('PMC9927882','needle')
    else:
        monkeypatch.setattr(search,'Searcher',lambda *_:s)
        assert search.main(['locate','PMC9927882','--find','needle','--workdir',str(tmp_path)])==1
        record=json.loads(capsys.readouterr().out)
    assert record['outcome']=='unavailable' and 'LookupError' in record['error']
    assert 'not-a-codec' not in record['error']
    assert read_calls(tmp_path)[-1]['call_id']==record['call_id']
    fetched=next(row for row in record['responses'] if 'fullTextXML' in row['url'])
    assert fetched['kept'] is False and fetched['sha256']==search.sha256(raw)
    assert not list((tmp_path/search.RESPONSES).glob(search.sha256(raw).split(':')[1]+'*'))


@pytest.mark.parametrize('encoding',['utf-8','utf-16','iso-8859-1'])
def test_locate_supported_xml_encoding_retains_native_address(tmp_path,encoding):
    raw=('<?xml version="1.0" encoding="'+encoding+'"?><article><body><p>needle.</p></body></article>').encode(encoding)
    s=search.Searcher(tmp_path,get=Routed(locate_routes(raw)),sleep=lambda *_:None,clock=lambda:0.0)
    record=s.locate('PMC9927882','needle')
    assert record['outcome']=='ok' and record['at'][0]['paragraph']==1
    assert record['at'][0]['sentences']==[1] and record['document_sha256']==search.sha256(raw)
    assert read_calls(tmp_path)[-1]['call_id']==record['call_id']


def test_locate_does_not_swallow_unrelated_programming_lookup_error(tmp_path,monkeypatch):
    s=search.Searcher(tmp_path)
    def broken(*args,**kwargs):raise LookupError('invented programming failure outside XML parse')
    monkeypatch.setattr(s,'epmc_record',broken)
    with pytest.raises(LookupError,match='outside XML parse'):s.locate('PMC9927882','needle')
# -- a search is not closed while something that answers the article has no verdict -----------------

def answering_log(tmp_path, works, extra_calls=()):
    """A search log with one `responses` call returning `works`, plus whatever records a case adds."""
    s = search.Searcher(tmp_path)
    s.log({'call_id': 'c0', 'tool': 'responses', 'ask': {'id': 'PMC6463022'}, 'outcome': 'ok',
           'started_at': '2026-10-24T09:00:00Z', 'works': works})
    for call in extra_calls:
        s.log(call)
    return s


COMMENT = {'source_id': 'MED:1111', 'pmid': '1111', 'doi': '10.1111/evl3.1111', 'pmcid': 'PMC1111',
           'title': 'Mother and offspring in conflict: why not?',
           'pubTypeList': {'pubType': ['comment', 'Journal Article']}}
ERRATUM = {'source_id': 'MED:2222', 'pmid': '2222', 'pmcid': 'PMC2222', 'title': 'Correction to…',
           'pubTypeList': {'pubType': ['published erratum']}}
ORDINARY = {'source_id': 'MED:3333', 'pmid': '3333', 'pmcid': 'PMC3333', 'title': 'A study',
            'pubTypeList': {'pubType': ['research-article', 'Journal Article']}}


def bare_card():
    return {'author': {'source': {'url': 'https://doi.org/10.3390/jof5010010',
                                  'doi': '10.3390/jof5010010'}},
            'added': {'sources': {}}}


def test_a_published_comment_with_no_verdict_keeps_the_search_open(tmp_path):
    """Item 3 of the extractor review, as a gate. The failure it comes from is concrete: an official
    published Comment on the converted article sat in the **first** search output and was picked up
    only by the fourth wave of critics. A search log is not a review of what the search found.

    So a work whose publication type says it answers the article needs one of three verdicts, and
    `closeout` refuses to close the search while one has none. There is no exposure floor here, which
    is the point: the Comment that was missed came back from one call, and a floor would have hidden
    it exactly as the screen's floor did."""
    answering_log(tmp_path, [COMMENT, ERRATUM, ORDINARY])
    out = search.closeout(bare_card(), tmp_path)
    assert out['closed'] is False
    open_ids = {i for r in out['without_verdict'] for i in r['ids']}
    assert {'pmc1111', 'pmc2222'} <= open_ids and 'pmc3333' not in open_ids, out['without_verdict']
    assert all('research' not in ' '.join(r['classes']) for r in out['answering_works']), (
        'an ordinary study is not an answering work and this gate says nothing about it')
    assert 'NOT closed' in search.closeout_text(out)


@pytest.mark.parametrize('verdict,call', [
    ('set_aside', {'call_id': 'c1', 'tool': 'not_cited', 'outcome': 'ok',
                   'started_at': '2026-10-24T09:01:00Z', 'work': COMMENT,
                   'ask': {'id': 'PMC1111', 'reason': 'other_endpoint', 'locator': 'Results'}}),
    ('unavailable', {'call_id': 'c2', 'tool': 'not_read', 'outcome': 'ok', 'readable': False,
                     'started_at': '2026-10-24T09:01:00Z', 'work': COMMENT,
                     'ask': {'id': 'PMC1111'}}),
    ('unavailable', {'call_id': 'c3', 'tool': 'licence', 'outcome': 'ok', 'quotable': False,
                     'licence_refusal_code': 'restriction_marker',
                     'started_at': '2026-10-24T09:01:00Z', 'work': COMMENT,
                     'ask': {'id': 'PMC1111'}}),
])
def test_each_of_the_three_verdicts_closes_a_work(tmp_path, verdict, call):
    """The three the review named, and nothing else counts: carried by the card, read and set aside
    with a reason, unavailable with the measurement that says so. A licence refusal is a verdict
    because a work a card may name and not quote still has its reason on the record."""
    answering_log(tmp_path, [COMMENT], [call])
    out = search.closeout(bare_card(), tmp_path)
    row = next(r for r in out['answering_works'] if 'pmc1111' in r['ids'])
    assert row['verdict'] == verdict, out
    assert out['closed'] is True


def test_a_comment_the_card_carries_is_closed_by_the_card(tmp_path):
    """The first verdict: the card cites it. Nothing else is needed, and the gate must not ask for a
    record beside a line that already exists - a demand that duplicates what the card says is the
    kind a conversion satisfies formally."""
    answering_log(tmp_path, [COMMENT])
    card = bare_card()
    card['added']['sources'] = {'cmt': {'source': 'https://doi.org/10.1111/evl3.1111'}}
    out = search.closeout(card, tmp_path)
    assert out['closed'] is True
    row = next(r for r in out['answering_works'] if '10.1111/evl3.1111' in r['ids'])
    assert row['verdict'] == 'carried'


def test_a_work_is_classified_in_the_shape_the_log_actually_uses(tmp_path):
    """A Europe PMC answer carries `pubTypeList`; the record this kit logs carries `type`, the same
    list joined with semicolons. The first form of the gate read only `pubTypeList`, so on both
    finished conversions it found no answering work at all and reported the search closed - a check
    that passes for the wrong reason, which is the very failure item 3 exists to stop. Both shapes
    are read now, and this case is in the logged shape."""
    logged = {'source_id': 'MED:4444', 'pmid': '4444', 'pmcid': 'PMC4444',
              'title': 'A comment as the log stores it',
              'type': "Comment; Journal Article; Research Support, Non-U.S. Gov't"}
    answering_log(tmp_path, [logged])
    out = search.closeout(bare_card(), tmp_path)
    assert out['closed'] is False
    assert out['without_verdict'][0]['classes'] == ['comment']


def test_the_gate_says_what_it_cannot_see(tmp_path):
    """A direct test of a prediction is not a publication type. No metadata names it, so this check
    cannot see it, and the result says so rather than letting a reader take the gate for more than it
    is. A check that hides its own blind spot is how a requirement becomes a formality."""
    answering_log(tmp_path, [ORDINARY])
    out = search.closeout(bare_card(), tmp_path)
    assert out['closed'] is True and out['answering_works'] == []
    assert out['declared_only'] and 'declared by the conversion' in out['declared_only'][0]
    assert 'not seen by this check' in search.closeout_text(out)


# -- a retraction is a publication type, not a structural field -------------------------------------

RETRACTED_LOGGED = {'source_id': 'MED:5555', 'pmid': '5555', 'doi': '10.1111/evo.14193',
                    'title': 'Inference of symbiotic adaptations in nature',
                    'type': 'Journal Article; Retracted Publication', 'retracted': None}


def test_a_retraction_is_caught_by_the_type_when_the_field_says_nothing(tmp_path):
    """Measured on the amoebae conversion, and the reason this is a kit finding rather than a card
    finding: Europe PMC's structural `retracted` field was **null** for a work whose `type` said
    "Retracted Publication", and that work came back from seven literature calls with nothing in the
    log about it. A screen resting on the field would pass it; an exact-string table would miss the
    lowercased form the kit's own log carries.

    So the screen keys on the publication type, normalised, in either shape, and the field is a
    signal beside it rather than the key."""
    assert search.retraction_classes(RETRACTED_LOGGED) == ['retracted']
    assert search.retraction_classes({'pubTypeList': {'pubType': ['Retraction of Publication']}}) \
        == ['retracted']
    assert search.retraction_classes({'type': 'research-article'}) == []
    answering_log(tmp_path, [RETRACTED_LOGGED])
    out = search.closeout(bare_card(), tmp_path)
    assert out['closed'] is False
    row = out['without_verdict'][0]
    assert row['notice'] == ['retracted'] and 'retracted publication' in row['classes']


def test_a_retracted_work_the_card_does_not_use_is_closed_by_its_reason(tmp_path):
    """What the verdict is for such a work, by the owner's decision: it was returned by the search,
    read far enough to see the retraction, and not used - so it carries the reason `retracted`, and no
    retraction notice is requested, because the card does not rest on it. Silence is what the gate
    refuses, not the absence of a notice."""
    assert 'retracted' in search.NOT_CITED
    answering_log(tmp_path, [RETRACTED_LOGGED], [
        {'call_id': 'c9', 'tool': 'not_cited', 'outcome': 'ok', 'work': RETRACTED_LOGGED,
         'started_at': '2026-10-24T09:02:00Z', 'ask': {'id': '10.1111/evo.14193',
                                                       'reason': 'retracted', 'locator': 'Notice'}}])
    out = search.closeout(bare_card(), tmp_path)
    assert out['closed'] is True
    row = next(r for r in out['answering_works'] if '10.1111/evo.14193' in r['ids'])
    assert row['verdict'] == 'set_aside' and 'retracted' in (row['record'] or '')


# -- a correction is not a retraction ---------------------------------------------------------------

# In the service's shape, because `not_cited` looks the work up again and reads `pubTypeList`; the
# logged shape (`type`) is covered by RETRACTED_LOGGED above.
ERRATUM_WORK = {'id': '6666', 'source': 'MED', 'pmid': '6666', 'doi': '10.1111/evl3.6666',
                'title': 'A study, corrected',
                'pubTypeList': {'pubType': ['Journal Article', 'Published Erratum']}}
WITHDRAWN_WORK = {'id': '7777', 'source': 'MED', 'pmid': '7777', 'doi': '10.1111/evl3.7777',
                  'title': 'A study, withdrawn',
                  'pubTypeList': {'pubType': ['Journal Article', 'Withdrawn Publication']}}


@pytest.mark.parametrize('work,classes,is_withdrawn', [
    (RETRACTED_LOGGED, ['retracted'], True),
    (WITHDRAWN_WORK, ['retracted'], True),
    (ERRATUM_WORK, ['corrected'], False),
    ({'type': 'Journal Article; Corrected and Republished Article'}, ['corrected'], False),
    ({'pubTypeList': {'pubType': ['Expression of Concern']}}, ['concern'], False),
    ({'type': 'research-article'}, [], False),
])
def test_three_classes_are_three_things(work, classes, is_withdrawn):
    """The lead's correction to my own form, and it is an error of meaning rather than of hygiene. A
    **retraction** withdraws the result: the work is not read as a result at all. A **correction**
    changes it: the work is still a result and is read together with its correction. An **expression
    of concern** is neither - a doubt reported and not resolved.

    I had listed all of them in one table, which would have let a corrected work be set aside with
    the reason `retracted` - "not read as a result" - and that is false about a work a card may
    perfectly well use."""
    assert search.retraction_classes(work) == classes
    assert search.withdrawn(work) is is_withdrawn


def test_the_reason_retracted_is_refused_for_a_corrected_work(tmp_path):
    """Where the distinction has to bite: the reason itself. `retracted` is checked against the
    work's own publication types rather than taken on the caller's word, because a reason that says
    "not read as a result" about a corrected work records something untrue - and the record is what a
    reader of the card will believe."""
    routes = [('search?query=', json.dumps({'hitCount': 1, 'resultList': {
        'result': [ERRATUM_WORK]}}).encode(), 200)]
    s = search.Searcher(tmp_path, get=Routed(routes), sleep=lambda *_: None, clock=lambda: 0.0)
    out = s.not_cited('10.1111/evl3.6666', 'retracted', 'the correction notice')
    assert out['outcome'] == 'failed'
    assert 'corrected' in out['error'] and 'read with its correction' in out['error']


def test_the_reason_retracted_stands_for_a_withdrawn_work(tmp_path):
    """And the other side, so that the guard cannot be satisfied by refusing everything: a work the
    publisher withdrew takes the reason, and the record carries the notice class beside it."""
    routes = [('search?query=', json.dumps({'hitCount': 1, 'resultList': {
        'result': [WITHDRAWN_WORK]}}).encode(), 200)]
    s = search.Searcher(tmp_path, get=Routed(routes), sleep=lambda *_: None, clock=lambda: 0.0)
    out = s.not_cited('10.1111/evl3.7777', 'retracted', 'the retraction notice')
    assert out['outcome'] == 'ok' and out['notice'] == ['retracted']


# -- a partial retraction is its own class ----------------------------------------------------------

PARTIAL_WORK = {'source_id': 'MED:8888', 'pmid': '8888', 'doi': '10.1111/evl3.8888',
                'title': 'A study, partly retracted',
                'type': 'Journal Article; Partial Retraction'}


def test_a_partial_retraction_is_neither_a_correction_nor_a_retraction():
    """The owner's correction to my three classes, and the reason it matters more than it looks: a
    partial retraction withdraws **part** of the results, and which part is in the notice and nowhere
    else. Read as a correction - "the work is still a result, read it with the correction" - a line
    can come to rest exactly on the withdrawn part."""
    assert search.retraction_classes(PARTIAL_WORK) == ['partial']
    assert search.withdrawn(PARTIAL_WORK) is False, 'the work is not withdrawn whole'
    assert search.status_of('Partial Retraction') == 'partial'
    assert search.status_of('Partial retraction in') == 'partial'


def test_a_partial_retraction_does_not_pass_as_an_ordinary_work(tmp_path):
    """So a verdict that uses the work - carried, or set aside after reading - is not enough on its
    own: the gate holds it open until the notice has been read, and says why."""
    answering_log(tmp_path, [PARTIAL_WORK], [
        {'call_id': 'p1', 'tool': 'not_cited', 'outcome': 'ok', 'work': PARTIAL_WORK,
         'started_at': '2026-10-24T09:03:00Z',
         'ask': {'id': '10.1111/evl3.8888', 'reason': 'off_topic', 'locator': 'Results'}}])
    out = search.closeout(bare_card(), tmp_path)
    assert out['closed'] is False, out['answering_works']
    row = out['without_verdict'][0]
    assert row['notice'] == ['partial'] and row['notice_read'] is False
    assert 'in the notice and nowhere else' in row['needs']
    assert 'in the notice and nowhere else' in search.closeout_text(out)


def test_a_partial_retraction_whose_notice_was_read_is_closed(tmp_path):
    """And with a bound attestation that the specific notice was read, the ordinary verdict stands. What
    no check can do is say whether the line rests on the withdrawn part; that is a reading, and the
    gate demands the evidence of reading rather than pretending to judge it."""
    answering_log(tmp_path, [PARTIAL_WORK], [
        {'call_id': 'p2', 'tool': 'status', 'outcome': 'ok', 'work': PARTIAL_WORK,
         'started_at': '2026-10-24T09:04:00Z', 'ask': {'id': '10.1111/evl3.8888'},
         'notices': [{'status': 'partial', 'kind': 'Partial retraction in',
                      'from': 'europepmc', 'notice': 'MED:9999'}]},
        {'call_id': 'p3', 'tool': 'not_cited', 'outcome': 'ok', 'work': PARTIAL_WORK,
         'started_at': '2026-10-24T09:05:00Z',
         'ask': {'id': '10.1111/evl3.8888', 'reason': 'off_topic', 'locator': 'Results'}}])
    search.Searcher(tmp_path).notice_read(PARTIAL_WORK['doi'], 'MED:9999', 'p2', 'paragraph 2',
                                         'sha256:' + '1' * 64, 'test-reader')
    out = search.closeout(bare_card(), tmp_path)
    assert out['closed'] is True
    row = next(r for r in out['answering_works'] if '10.1111/evl3.8888' in r['ids'])
    assert row['verdict'] == 'set_aside' and row['notice_read'] is True


def test_a_partial_retraction_recorded_as_unavailable_needs_nothing_further(tmp_path):
    """The one case that needs no notice: a work recorded as unavailable was not rested on by anyone,
    so there is nothing for the notice to protect."""
    answering_log(tmp_path, [PARTIAL_WORK], [
        {'call_id': 'p4', 'tool': 'not_read', 'outcome': 'ok', 'readable': False,
         'started_at': '2026-10-24T09:06:00Z', 'work': PARTIAL_WORK,
         'ask': {'id': '10.1111/evl3.8888'}}])
    out = search.closeout(bare_card(), tmp_path)
    assert out['closed'] is True
    row = next(r for r in out['answering_works'] if '10.1111/evl3.8888' in r['ids'])
    assert row['verdict'] == 'unavailable'
