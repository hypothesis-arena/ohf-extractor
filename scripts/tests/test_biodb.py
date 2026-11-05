# Export fixture provenance: inputs named in SYNTHETIC-FIXTURES.json are
# constructed test data; their identifiers and dates are regression tokens.
# Recorded-response descriptions below identify the replaced source snapshots,
# not live-service provenance for those synthetic replacement inputs.
"""Database clients: recorded responses, no network.

The Open Genes fixture is the real answer for MTOR (2026-10-21) without orthologs, GO terms, location
and expression, and with the text Open Genes repeats from UniProt, NCBI and the Human Protein Atlas
replaced by a marker: that text is not Open Genes' to license, and the client does not record it."""

from _export_fixture_paths import fixture_path
import io
import json
import urllib.parse
import zipfile
from pathlib import Path

import pytest

import biodb
import search

FIX = Path(__file__).resolve().parent / 'fixtures' / 'biodb'


class Net:
    """A transport that answers from fixtures by route and records each URL it was asked."""

    def __init__(self, routes):
        self.routes, self.urls = routes, []

    def __call__(self, url):
        self.urls.append(url)
        for key, (status, name) in self.routes.items():
            if key in url:
                return status, (fixture_path(FIX, name)).read_bytes(), {}
        return 500, b'{}', {}


OPENGENES = {'gene/MTOR': (200, 'opengenes-MTOR.json'), 'gene/NOTAGENE1': (404, 'opengenes-404.json')}


PERMISSION = 'references/permissions/open-genes.md (sha256:00)'


@pytest.fixture
def licensed(monkeypatch):
    monkeypatch.setattr(biodb, 'opengenes_permission', lambda: PERMISSION)


@pytest.fixture
def unlicensed(monkeypatch):
    monkeypatch.setattr(biodb, 'opengenes_permission', lambda: None)


def searcher(tmp_path, routes):
    sleeps = []
    return search.Searcher(tmp_path, get=Net(routes), sleep=sleeps.append, clock=lambda: 0.0), sleeps


def test_opengenes_gene_links_the_gene_and_counts_its_evidence(tmp_path, licensed):
    s, _ = searcher(tmp_path, OPENGENES)
    r = biodb.opengenes_gene(s, 'MTOR')
    assert r['outcome'] == 'ok' and r['hit_count'] == 1
    gene = r['works'][0]
    assert gene['source_id'] == 'OPENGENES:MTOR' and gene['url'] == 'https://open-genes.com/gene/MTOR'
    assert (gene['ncbi_gene'], gene['uniprot'], gene['ensembl']) == (2475, 'MTOR_HUMAN', 'ENSG00000198793')
    assert gene['evidence_counts']['increaseLifespan'] == 18
    assert gene['evidence_counts']['interventionToGeneImprovesVitalProcesses'] == 12
    assert gene['confidence_level'] == 'high' and 'TOR pathway dysregulation' in gene['aging_mechanisms']
    assert 'FRAP1' in gene['aliases']
    # The data are CC BY 4.0 by the rights holder's permission, a note the kit carries.
    assert (gene['licence'], gene['licence_from']) == ('CC-BY-4.0', PERMISSION)
    assert gene['attribution'] == 'Open Genes (open-genes.com), Open Longevity'
    # Text Open Genes repeats from other sources is not recorded.
    assert set(r['withheld']) == {'proteinDescriptionUniProt', 'descriptionNCBI', 'humanProteinAtlas'}
    assert 'THIRD-PARTY' not in json.dumps(r['works'])


def test_opengenes_cited_studies_are_listed_once_with_their_sections(tmp_path, licensed):
    s, _ = searcher(tmp_path, OPENGENES)
    studies = biodb.opengenes_gene(s, 'MTOR')['works'][1:]
    ids = [w['source_id'] for w in studies]
    assert len(ids) == len(set(ids)) and search.read_log(tmp_path)[-1]['found'] == len(studies) + 1
    celrep = next(w for w in studies if w['source_id'] == 'DOI:10.1016/j.celrep.2013.07.030')
    assert 'increaseLifespan' in celrep['relation'] and celrep['via'] == 'OPENGENES:MTOR'
    # The evidence rows are Open Genes data, under its licence; the study's own licence is not known here.
    row = celrep['evidence'][0]
    assert row['section'] == 'increaseLifespan' and row['modelOrganism'] == 'mouse'
    assert row['interventionResultForLifespan'] == 'increases lifespan' and 'autophagy' in row['interventionImproves']
    assert 'id' not in row and 'doi' not in row
    assert celrep['evidence_licence'] == 'CC-BY-4.0' and celrep['licence'] is None


def test_opengenes_rows_without_a_study_are_counted_not_lost():
    d = {'researches': {'increaseLifespan': [{'doi': '10.1/a', 'pmid': ''}, {'doi': '', 'pmid': None}],
                        'ageRelatedChangesOfGene': [{'doi': '10.1/A', 'pmid': '7'}]}}
    studies, unidentified = biodb.opengenes_studies(d, 'OPENGENES:X', PERMISSION)
    assert unidentified == 1
    assert [(w['source_id'], w['pmid'], w['relation'], len(w['evidence'])) for w in studies] == [
        ('DOI:10.1/a', '7', ['increaseLifespan', 'ageRelatedChangesOfGene'], 2)]


def test_opengenes_without_the_permission_note_is_link_only(tmp_path, unlicensed):
    s, _ = searcher(tmp_path, OPENGENES)
    r = biodb.opengenes_gene(s, 'MTOR')
    gene, studies = r['works'][0], r['works'][1:]
    assert set(gene) == set(biodb.OPENGENES_LINK_ONLY) | {'dates'} and gene['licence'] is None
    assert gene['evidence_counts']['increaseLifespan'] == 18 and studies
    assert not any('evidence' in w for w in studies) and 'values and text' in r['withheld']
    assert 'high' not in json.dumps(r['works'])


def test_opengenes_permission_names_the_note_in_the_kit_with_its_hash(tmp_path):
    assert biodb.opengenes_permission(tmp_path) is None
    note = tmp_path / biodb.OPENGENES_PERMISSION
    note.parent.mkdir(parents=True)
    note.write_bytes(b'permission')
    assert biodb.opengenes_permission(tmp_path) == f'{biodb.OPENGENES_PERMISSION} ({search.sha256(b"permission")})'


def test_plain_drops_row_numbers_and_empties_and_names_terms():
    row = {'id': 3, 'sex': 'male', 'comment': '', 'pValue': None, 'interventionImproves': [{'id': '39', 'name': 'bone'}],
           'regulatedGene': {'id': 65, 'symbol': 'HIF1A', 'ncbiId': 3091},
           'interventions': {'experiment': [{'id': 1, 'gene': 220, 'interventionMethod': 'knockout'}],
                             'controlAndExperiment': []}}
    assert biodb.plain(row) == {'sex': 'male', 'interventionImproves': ['bone'], 'regulatedGene': 'HIF1A',
                                'interventions': {'experiment': [{'interventionMethod': 'knockout'}]}}


def test_opengenes_missing_gene_is_a_search_that_found_nothing(tmp_path):
    s, _ = searcher(tmp_path, OPENGENES)
    r = biodb.opengenes_gene(s, 'NOTAGENE1')
    assert r['outcome'] == 'ok' and r['hit_count'] == 0 and r['works'] == []
    assert r['responses'][0]['status'] == 404


def test_opengenes_unavailable_is_a_failed_search_not_an_empty_one(tmp_path):
    s, _ = searcher(tmp_path, {})
    r = biodb.opengenes_gene(s, 'MTOR')
    assert r['outcome'] == 'failed' and r['hit_count'] is None


def test_calls_share_the_search_log_and_the_waits_per_host(tmp_path):
    s, sleeps = searcher(tmp_path, OPENGENES)
    biodb.opengenes_gene(s, 'MTOR')
    biodb.opengenes_gene(s, 'NOTAGENE1')
    assert [r['tool'] for r in search.read_log(tmp_path)] == ['opengenes_gene', 'opengenes_gene']
    assert search.MIN_INTERVAL['open-genes.com'] == 1.0 and sleeps == [1.0]
    assert 'opengenes_gene' in search.report(tmp_path)


# -- HGNC, NCBI Gene, UniProt ----------------------------------------------------------------------
# Real answers for RPTOR (2026-10-21). The UniProt entry (UniProt Consortium, UniProtKB Q8N122, CC BY 4.0)
# is without features, sequence, references and cross-references; the NCBI Gene summary is replaced by
# a marker, as the client does not record it.

GENE = {'fetch/symbol/RAPTOR': (200, 'hgnc-symbol-RAPTOR.xml'), 'fetch/prev_symbol/RAPTOR': (200, 'hgnc-prev-RAPTOR.xml'),
        'fetch/alias_symbol/RAPTOR': (200, 'hgnc-alias-RAPTOR.xml'), 'db=gene&id=57521': (200, 'ncbi-gene-57521.json'),
        'uniprotkb/search': (200, 'uniprot-search-RPTOR.json'), 'uniprotkb/Q8N122.json': (200, 'uniprot-Q8N122.json'),
        'uniprotkb/Q00000.json': (404, 'opengenes-404.json')}


def test_hgnc_resolves_an_alias_to_the_approved_symbol_after_trying_symbol_and_former_symbol(tmp_path):
    s, _ = searcher(tmp_path, GENE)
    r = biodb.hgnc_gene(s, 'RAPTOR')
    assert r['outcome'] == 'ok' and r['resolved_by'] == 'alias_symbol' and not r['ambiguous']
    assert [x['url'].rsplit('/', 2)[1] for x in r['responses']] == ['symbol', 'prev_symbol', 'alias_symbol']
    g = r['works'][0]
    assert (g['source_id'], g['symbol'], g['ncbi_gene'], g['uniprot']) == ('HGNC:30287', 'RPTOR', '57521', ['Q8N122'])
    # HGNC matches a name regardless of case: the alias it holds is "raptor".
    assert 'raptor' in g['synonyms'] and 'MTOR complex 1' in g['gene_groups']
    assert (g['licence'], g['licence_from']) == ('CC0-1.0', 'https://www.genenames.org/about/license/')


def test_hgnc_an_alias_of_several_genes_returns_them_all_and_says_so(tmp_path):
    two = (b'<response><result numFound="2"><doc><str name="hgnc_id">HGNC:1</str><str name="symbol">A1</str>'
           b'<arr name="alias_symbol"><str>X</str></arr></doc><doc><str name="hgnc_id">HGNC:2</str>'
           b'<str name="symbol">B2</str></doc></result></response>')
    empty = (fixture_path(FIX, 'hgnc-symbol-RAPTOR.xml')).read_bytes()
    s = search.Searcher(tmp_path, get=lambda url: (200, two if 'alias_symbol' in url else empty, {}),
                        sleep=lambda x: None, clock=lambda: 0.0)
    r = biodb.hgnc_gene(s, 'X')
    assert r['ambiguous'] and [g['symbol'] for g in r['works']] == ['A1', 'B2']
    assert biodb.gene(s, 'X') and len(biodb.gene(s, 'X')) == 1  # an ambiguous name stops at HGNC


def test_ncbi_gene_records_names_and_location_not_the_summary(tmp_path):
    s, _ = searcher(tmp_path, GENE)
    r = biodb.ncbi_gene(s, '57521')
    g = r['works'][0]
    assert (g['source_id'], g['symbol'], g['taxon'], g['map_location']) == ('NCBIGENE:57521', 'RPTOR', 9606, '17q25.3')
    assert 'KOG1' in g['aliases'] and 'summary' in r['withheld'] and 'SUMMARY' not in json.dumps(r['works'])
    assert g['licence_from'] == 'https://www.ncbi.nlm.nih.gov/home/about/policies/'
    assert 'eutils.ncbi.nlm.nih.gov' in r['responses'][0]['url'] and 'tool=ohf-extractor' in r['responses'][0]['url']


def test_uniprot_entry_records_function_and_subunit_with_their_studies_and_attribution(tmp_path):
    s, _ = searcher(tmp_path, GENE)
    r = biodb.uniprot_entry(s, 'Q8N122')
    e, studies = r['works'][0], r['works'][1:]
    assert (e['source_id'], e['entry_name'], e['reviewed'], e['genes']) == ('UNIPROT:Q8N122', 'RPTOR_HUMAN', True, ['RPTOR'])
    assert e['function'][0]['text'] and e['function'][0]['pmids']
    assert any('mTORC1' in x['text'] for x in e['subunit'])
    assert e['licence'] == 'CC-BY-4.0' and f"version {e['entry_version']}" in e['attribution']
    cited = {p for k in ('function', 'subunit') for x in e[k] for p in x['pmids']}
    assert {w['pmid'] for w in studies} == cited and all(w['via'] == 'UNIPROT:Q8N122' for w in studies)


def test_uniprot_missing_entry_is_a_search_that_found_nothing(tmp_path):
    s, _ = searcher(tmp_path, GENE)
    r = biodb.uniprot_entry(s, 'Q00000')
    assert r['outcome'] == 'ok' and r['hit_count'] == 0


def test_uniprot_gene_searches_reviewed_human_entries_and_reads_each(tmp_path):
    s, _ = searcher(tmp_path, GENE)
    found, entry = biodb.uniprot_gene(s, 'RPTOR')
    assert found['tool'] == 'uniprot_search' and 'reviewed:true' in found['query'] and found['hit_count'] == 1
    assert entry['tool'] == 'uniprot_entry' and entry['works'][0]['accession'] == 'Q8N122'


def test_gene_resolves_a_name_and_reads_ncbi_gene_and_uniprot_by_hgnc_identifiers(tmp_path):
    s, sleeps = searcher(tmp_path, GENE)
    out = biodb.gene(s, 'RAPTOR')
    assert [r['tool'] for r in out] == ['hgnc_gene', 'ncbi_gene', 'uniprot_entry']
    assert all(r['outcome'] == 'ok' for r in out)
    # HGNC is asked three times in a row: spaced by its own interval, not by the default second.
    assert sleeps[:2] == [0.2, 0.2]


# -- HAGR: GenAge, DrugAge -------------------------------------------------------------------------
# Builds made from the real ones (GenAge Build 21, DrugAge Build 5; HAGR, CC BY 3.0): their release
# notes as they are, and their tables cut to the rows of a few genes and compounds.

def hagr_zip(name, table=None):
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w') as z:
        z.writestr('release.html', (fixture_path(FIX, f'hagr-{name}-release.html')).read_bytes())
        z.writestr(biodb.HAGR_DATASETS[name][1], table if table is not None else (fixture_path(FIX, f'hagr-{name}.csv')).read_bytes())
    return out.getvalue()


class Hagr:
    """HAGR's download site, answering each offered archive and counting the requests."""

    def __init__(self, **archives):
        self.archives = {biodb.HAGR_DATASETS[k][0]: v for k, v in archives.items()}
        self.urls = []

    def __call__(self, url):
        self.urls.append(url)
        for path, data in self.archives.items():
            if url.endswith(path):
                return 200, data, {}
        return 404, b'', {}


def hagr(tmp_path, **archives):
    net = Hagr(**({k: hagr_zip(k) for k in biodb.HAGR_DATASETS} | archives))
    return search.Searcher(tmp_path, get=net, sleep=lambda x: None, clock=lambda: 0.0), net


def test_hagr_fetch_records_the_build_its_date_hash_and_licence(tmp_path):
    s, _ = hagr(tmp_path)
    r = biodb.hagr_fetch(s, 'drugage')
    b = r['works'][0]
    assert (b['source_id'], b['build'], b['released'], b['rows']) == ('HAGR:drugage:build-5', '5', 'November 29, 2024', 40)
    assert b['archive_sha256'] == r['responses'][0]['sha256'] == search.sha256(hagr_zip('drugage'))
    assert (b['licence'], b['licence_from']) == ('CC-BY-3.0', 'https://genomics.senescence.info/legal.html')
    assert 'DrugAge database' in b['citation']


def test_genage_finds_the_human_gene_and_the_model_orthologs_of_its_name_in_the_fetched_builds(tmp_path):
    s, net = hagr(tmp_path)
    r = biodb.genage(s, 'RICTOR')
    by_id = {w['source_id']: w for w in r['works']}
    assert by_id['GENAGE:303']['why'] == ['functional', 'putative'] and by_id['GENAGE:303']['organism'] == 'Homo sapiens'
    mouse = by_id['GENAGE:1852']
    assert (mouse['organism'], mouse['lifespan_effect'], mouse['longevity_influence']) == (
        'Mus musculus', 'Decrease', 'Pro-Longevity')
    assert mouse['build'] == 'HAGR:genage_models:build-21' and 'GenAge' in mouse['attribution']
    # A build is fetched once per work directory, then searched locally.
    biodb.genage(s, 'MTOR')
    assert len(net.urls) == 2 and [x['tool'] for x in search.read_log(tmp_path)].count('hagr_fetch') == 2


def test_drugage_lists_cohorts_with_their_regimens_and_each_study_once(tmp_path):
    s, _ = hagr(tmp_path)
    r = biodb.drugage(s, 'rapamycin')
    cohorts = [w for w in r['works'] if w['source_id'].startswith('DRUGAGE:')]
    studies = [w for w in r['works'] if w['source_id'].startswith('MED:')]
    assert r['hit_count'] == len(cohorts) == 37
    every5 = next(w for w in cohorts if 'every 5 days' in w['dosage'])
    assert (every5['species'], every5['age_at_initiation'], every5['pubmed_id']) == ('Mus musculus', '20 months', '27091134')
    assert (every5['avg_lifespan_change_percent'], every5['weight_change_percent']) == ('7', '-7')
    fly = next(w for w in cohorts if w['species'] == 'Drosophila melanogaster')
    assert 'max_lifespan_change_percent' not in fly and 'max_lifespan_significance' not in fly  # empty and "NA"
    assert sum(w['cohorts'] for w in studies) == 37 and len({w['pmid'] for w in studies}) == len(studies)
    assert biodb.drugage(s, 'Sirolimus')['hit_count'] == 0  # DrugAge names it rapamycin


def test_hagr_archive_with_another_header_is_refused(tmp_path):
    s, _ = hagr(tmp_path, drugage=hagr_zip('drugage', b'name,species\nRapamycin,mouse\n'))
    r = biodb.drugage(s, 'Rapamycin')
    assert r['outcome'] == 'failed' and 'header' in r['error']


def test_hagr_kept_archive_that_changed_is_refused(tmp_path):
    s, _ = hagr(tmp_path)
    fetched = biodb.hagr_fetch(s, 'drugage')
    sha = fetched['works'][0]['archive_sha256'].split(':')[1]
    (tmp_path / search.RESPONSES / f'{sha}.body').write_bytes(hagr_zip('drugage', b''))
    r = biodb.drugage(s, 'Rapamycin')
    assert r['outcome'] == 'failed' and 'does not match' in r['error']


def test_hagr_unavailable_is_a_failed_search(tmp_path):
    s = search.Searcher(tmp_path, get=Hagr(), sleep=lambda x: None, clock=lambda: 0.0)
    r = biodb.genage(s, 'MTOR')
    assert r['outcome'] == 'failed' and r['hit_count'] is None


# -- Reactome, Open Targets ------------------------------------------------------------------------
# Real answers (2026-10-21): Reactome release 97 (CC0) for MTOR (P42345) and "MTOR signalling"; Open
# Targets for MTOR and sirolimus, to the link-only queries the client sends for data from ChEMBL.

class Post:
    """A transport answering a GET by its URL and a POST by a part of its body."""

    def __init__(self, routes):
        self.routes, self.bodies = routes, []

    def __call__(self, url, body=None):
        text = url + (body.decode() if body else '')
        self.bodies.append(body)
        for key, (status, name) in self.routes.items():
            if key in text:
                return status, (fixture_path(FIX, name)).read_bytes(), {}
        return 500, b'{}', {}


PATHWAYS = {'database/version': (200, 'reactome-version.txt'), 'UniProt/P42345': (200, 'reactome-P42345.json'),
            'UniProt/Q00000': (404, 'reactome-404.json'), 'query/R-HSA-165159': (200, 'reactome-R-HSA-165159.json'),
            '"q":"rapamycin"': (200, 'opentargets-search-rapamycin.json'), '"q":"MTOR"': (200, 'opentargets-search-MTOR.json'),
            '"q":"NOTAGENE1"': (200, 'opentargets-search-none.json'),
            '"id":"CHEMBL413"': (200, 'opentargets-drug-CHEMBL413.json'),
            '"id":"ENSG00000198793"': (200, 'opentargets-target-MTOR.json')}


def post(tmp_path, routes=PATHWAYS):
    net = Post(routes)
    return search.Searcher(tmp_path, get=net, sleep=lambda x: None, clock=lambda: 0.0), net


def test_reactome_pathways_of_a_protein_with_the_release(tmp_path):
    s, _ = post(tmp_path)
    r = biodb.reactome_pathways(s, 'P42345')
    assert r['outcome'] == 'ok' and r['release'] == '97' and r['hit_count'] == len(r['works']) == 15
    mtor = next(w for w in r['works'] if w['stable_id'] == 'R-HSA-165159')
    assert (mtor['name'], mtor['url']) == ('MTOR signalling', 'https://reactome.org/content/detail/R-HSA-165159')
    assert (mtor['licence'], mtor['licence_from']) == ('CC0-1.0', 'https://reactome.org/license')
    assert biodb.reactome_pathways(s, 'Q00000')['hit_count'] == 0


def test_reactome_pathway_summary_and_its_studies(tmp_path):
    s, _ = post(tmp_path)
    r = biodb.reactome_pathway(s, 'R-HSA-165159')
    w, studies = r['works'][0], r['works'][1:]
    assert w['version'] == 'R-HSA-165159.10' and w['summary'][0].startswith('Mammalian target of rapamycin')
    assert '21157483' in {x['pmid'] for x in studies} and all(x['via'] == 'REACTOME:R-HSA-165159' for x in studies)


def test_opentargets_drug_by_name_finds_the_preferred_name_with_one_search_and_links_only(tmp_path):
    s, net = post(tmp_path)
    r = biodb.opentargets_drug(s, 'rapamycin')
    d = r['works'][0]
    assert (d['source_id'], d['name'], r['matched']) == ('CHEMBL413', 'SIROLIMUS', 'SIROLIMUS')
    assert d['chembl_url'] == 'https://www.ebi.ac.uk/chembl/explore/compound/CHEMBL413'
    assert d['mechanisms_count'] == 1 and d['indications_count'] > 100
    # The drug data come from ChEMBL (CC BY-SA): link only, no licence claimed, the fields withheld named.
    assert d['licence'] is None and d['data_from'] == 'ChEMBL' and 'mechanisms' not in d and 'indications' not in d
    assert (d['data_licence'], d['data_licence_from']) == (
        'CC-BY-SA-3.0', 'https://chembl.gitbook.io/chembl-interface-documentation/about')
    assert any('ChEMBL' in why for why in r['withheld'].values())
    # Two POSTs, a search and the drug; each body is kept and hashed so the request repeats.
    assert len(net.bodies) == 2 and all(x.get('request_sha256') for x in r['responses'])
    biodb.opentargets_drug(s, 'CHEMBL413')
    assert len(net.bodies) == 3  # an identifier is not searched


def test_opentargets_target_diseases_attributed_and_drugs_by_identifier_only(tmp_path):
    s, _ = post(tmp_path)
    r = biodb.opentargets_target(s, 'MTOR')
    t = r['works'][0]
    assert t['source_id'] == 'ENSEMBL:ENSG00000198793' and t['diseases_count'] > len(t['diseases']) == 25
    assert t['licence'] == 'CC0-1.0' and 'Buniello' in t['citation'] and t['attribution'].startswith('Open Targets')
    assert t['drugs_count'] == len(t['drugs']) and set(t['drugs'][0]) == {'id', 'url'}
    assert (t['drugs_data_from'], t['drugs_licence']) == ('ChEMBL', 'CC-BY-SA-3.0')  # not the record's CC0
    # Open Targets files sirolimus under FKBP1A, its binding partner: MTOR's drugs do not include it.
    assert 'CHEMBL413' not in {d['id'] for d in t['drugs']}
    assert biodb.opentargets_target(s, 'NOTAGENE1')['hit_count'] == 0


def test_opentargets_answer_with_errors_is_a_failed_call(tmp_path):
    errors = b'{"errors":[{"message":"Cannot query field"}]}'
    s = search.Searcher(tmp_path, get=lambda url, body=None: (200, errors, {}),
                        sleep=lambda x: None, clock=lambda: 0.0)
    r = biodb.opentargets_drug(s, 'CHEMBL413')
    assert r['outcome'] == 'failed' and 'Cannot query field' in r['error']


# -- Terms: MeSH, NCBI Taxonomy, Gene Ontology ---------------------------------------------------
# Real answers (2026-10-21): MeSH through NCBI E-utilities (NLM), NCBI Taxonomy, QuickGO (CC BY 4.0).

TERMS = {'term=%22rapamycin%22%5BMH%5D': (200, 'mesh-esearch-mh-rapamycin.json'),
         'term=%22NOTATERMXYZ%22%5BMH%5D': (200, 'mesh-esearch-mh-none.json'),
         'db=mesh&term=rapamycin': (200, 'mesh-esearch-rapamycin.json'), 'esummary.fcgi?db=mesh': (200, 'mesh-esummary-rapamycin.json'),
         'db=mesh&term=NOTATERMXYZ': (200, 'mesh-esearch-none.json'),
         'db=taxonomy&term=mouse': (200, 'taxonomy-esearch-mouse.json'), 'efetch.fcgi?db=taxonomy': (200, 'taxonomy-efetch-mouse.xml'),
         'go/search?query=TOR': (200, 'go-search-TOR.json'), 'go/terms/GO%3A9999999': (200, 'go-terms-none.json'),
         'go/terms/GO:9999999': (200, 'go-terms-none.json'), 'go/terms/': (200, 'go-terms-TOR.json'),
         'einfo.fcgi?db=mesh': (200, 'mesh-einfo.json'), 'go/about': (200, 'go-about.json')}


def test_mesh_finds_the_heading_its_entry_terms_and_a_pubmed_query(tmp_path):
    s, _ = searcher(tmp_path, TERMS)
    r = biodb.mesh_terms(s, 'rapamycin')
    first = r['works'][0]
    # The heading whose terms include the term asked comes first, though the service orders otherwise.
    assert (first['source_id'], first['kind'], first['heading']) == ('MESH:D020123', 'heading', 'Sirolimus')
    assert 'Rapamycin' in first['synonyms'] and first['pubmed_query'] == '"Sirolimus"[MeSH Terms]'
    assert first['tree_numbers'] and first['url'].endswith('ui=D020123')
    assert first['licence_from'].startswith('https://www.nlm.nih.gov/') and 'National Library of Medicine' in first['attribution']
    assert r['hit_count'] == 29 and len(r['works']) == biodb.TERMS_READ
    # MeSH asks that the version used be named: the NCBI build and its date, as the service states them.
    assert (first['release'], first['release_date']) == ('Build261021-0310.1', '2026/10/21 03:20')
    assert biodb.mesh_terms(s, 'NOTATERMXYZ')['hit_count'] == 0


def test_taxonomy_gives_the_scientific_name_and_other_names_not_strains_or_misspellings(tmp_path):
    s, _ = searcher(tmp_path, TERMS)
    r = biodb.taxonomy(s, 'mouse')
    mus = next(w for w in r['works'] if w['taxon'] == '10090')
    assert (mus['scientific_name'], mus['rank']) == ('Mus musculus', 'species')
    assert {'house mouse', 'mouse'} <= set(mus['synonyms'])
    assert not any('C57BL' in x or 'nude' in x for x in mus['synonyms'])  # misspellings and "Includes" left out
    assert mus['licence_from'] == 'https://www.ncbi.nlm.nih.gov/home/about/policies/'


def test_go_text_search_reads_terms_with_synonyms_and_their_types(tmp_path):
    s, _ = searcher(tmp_path, TERMS)
    r = biodb.go_terms(s, 'TOR signaling')
    tor = next(w for w in r['works'] if w['source_id'] == 'GO:0031929')
    assert tor['name'] == 'TOR signaling' and 'target of rapamycin signaling pathway' in tor['synonyms']
    assert tor['synonym_types']['TOR signaling cascade'] == 'related'
    assert (tor['licence'], tor['licence_from']) == ('CC-BY-4.0', 'https://geneontology.org/docs/go-citation-policy/')
    assert r['hit_count'] > len(r['works'])
    assert all(w['release'] == '2026-09-27' for w in r['works'])  # GO asks that the release be mentioned


def test_go_unknown_id_finds_nothing(tmp_path):
    s, _ = searcher(tmp_path, TERMS)
    r = biodb.go_terms(s, 'GO:9999999')
    assert r['outcome'] == 'ok' and r['hit_count'] == 0 and r['works'] == []
    assert not any('about' in c['url'] for c in r['responses'])  # no release read for no record


def test_every_term_record_carries_synonyms_for_widening_a_search(tmp_path):
    s, _ = searcher(tmp_path, TERMS)
    for r in (biodb.mesh_terms(s, 'rapamycin'), biodb.taxonomy(s, 'mouse'), biodb.go_terms(s, 'TOR signaling')):
        assert all(isinstance(w['synonyms'], list) for w in r['works'])


# -- ChEMBL: link only; GEO: series metadata ----------------------------------------------------------
# Real answers (2026-10-21): ChEMBL web services (ChEMBL_37), GEO through NCBI E-utilities.

CHEMBL = {'molecule/search.json?q=rapamycin': (200, 'chembl-search-rapamycin.json'),
          'molecule/search.json?q=notadrugxyz': (200, 'chembl-search-notadrugxyz.json'),
          'molecule/CHEMBL413.json': (200, 'chembl-molecule-CHEMBL413.json'),
          'molecule/CHEMBL0000.json': (404, 'chembl-404.json'), 'status.json': (200, 'chembl-status.json')}
CHEMBL.update({f'{r}.json?molecule_chembl_id={c}&': (200, f'chembl-{r}-{c}.json')
               for r in ('mechanism', 'drug_indication', 'activity') for c in ('CHEMBL413', 'CHEMBL263752', 'CHEMBL436696')})
GEO = {'term=GSE272972': (200, 'geo-esearch-GSE272972.json'), 'esummary.fcgi?db=gds&id=200272972&': (200, 'geo-esummary-GSE272972.json'),
       'term=%28rapamycin+AND+mTORC2%29': (200, 'geo-esearch-mtorc2.json'), 'esummary.fcgi?db=gds': (200, 'geo-esummary-mtorc2.json'),
       'term=%28notadatasetxyz%29': (200, 'geo-esearch-none.json')}


def test_chembl_name_finds_the_compound_through_its_synonyms_link_only(tmp_path):
    s, _ = searcher(tmp_path, CHEMBL)
    r = biodb.chembl(s, 'rapamycin')
    first = r['works'][0]
    assert (first['source_id'], first['name']) == ('CHEMBL413', 'SIROLIMUS')
    assert (first['mechanisms_count'], first['indications_count'], first['activities_count']) == (1, 158, 3048)
    assert (first['release'], first['release_date']) == ('ChEMBL_37', '2026-05-01')
    # CC BY-SA: no licence of the record, ChEMBL's named beside it; nothing but ids, links and counts.
    assert first['licence'] is None and first['data_licence'] == 'CC-BY-SA-3.0'
    assert set(first) <= {'source_id', 'name', 'url', 'mechanisms_count', 'indications_count', 'activities_count',
                          'release', 'release_date', 'licence', 'licence_from', 'data_from', 'data_licence',
                          'data_licence_from', 'dates'}
    assert r['withheld'] and r['hit_count'] == 39 and len(r['works']) == biodb.CHEMBL_READ


def test_chembl_by_id_and_unknown_ones(tmp_path):
    s, _ = searcher(tmp_path, CHEMBL)
    assert biodb.chembl(s, 'CHEMBL413')['works'][0]['activities_count'] == 3048
    for name in ('CHEMBL0000', 'notadrugxyz'):
        r = biodb.chembl(s, name)
        assert r['outcome'] == 'ok' and r['hit_count'] == 0 and r['works'] == []


def test_geo_gives_series_metadata_and_links_not_the_submitters_text(tmp_path):
    s, _ = searcher(tmp_path, GEO)
    r = biodb.geo(s, 'rapamycin AND mTORC2')
    assert r['hit_count'] == 26 and len(r['works']) == biodb.GEO_READ
    first = r['works'][0]
    assert (first['source_id'], first['organism'], first['samples_count']) == ('GEO:GSE272972', 'Homo sapiens', 18)
    assert first['platforms'] == ['GPL18573'] and first['pmids'] == ['42685210']
    assert first['url'].endswith('acc=GSE272972') and first['files'].startswith('ftp://ftp.ncbi.nlm.nih.gov/geo/')
    assert 'summary' not in first and 'summary' in next(iter(r['withheld']))
    assert first['licence_from'] == 'https://www.ncbi.nlm.nih.gov/home/about/policies/'


def test_geo_accession_and_nothing_found(tmp_path):
    s, _ = searcher(tmp_path, GEO)
    assert [w['accession'] for w in biodb.geo(s, 'GSE272972')['works']] == ['GSE272972']
    r = biodb.geo(s, 'notadatasetxyz')
    assert r['outcome'] == 'ok' and r['hit_count'] == 0


# -- Dates: since when a value stands, for a cutoff ---------------------------------------------------

def test_day_reads_each_sources_dates_and_keeps_a_year_a_year():
    assert [biodb.day(v) for v in ('2026-09-27', '2026/07/21', '2016-04-01T00:00:00Z', 'June 17, 2023',
                                   '2026/10/21 03:20', '1999', '1/01/01 00:00', 'Smarch 1, 2020', None)] == [
        '2026-09-27', '2026-07-21', '2016-04-01', '2023-06-17', '2026-10-21', '1999', None, None, None]


def test_records_date_their_values_where_the_source_does_and_leave_the_rest_undated(tmp_path):
    s, _ = searcher(tmp_path, GENE)
    hgnc = biodb.hgnc_gene(s, 'RAPTOR')['works'][0]['dates']
    # HGNC: the symbol since approval (never changed), the name since its change, the rest since the last change.
    assert (hgnc['since'], hgnc['fields']['symbol'], hgnc['fields']['name']) == ('2009-05-29', '2009-05-29', '2016-04-01')
    assert hgnc['fields']['alias_symbols'] == '2023-01-20' and 'source_id' not in hgnc['fields']
    uniprot = biodb.uniprot_entry(s, 'Q8N122')['works'][0]['dates']
    assert uniprot['since'] == '2004-04-26' and set(uniprot['fields'].values()) == {'2026-09-02'}
    ncbi = biodb.ncbi_gene(s, '57521')['works'][0]['dates']
    assert set(ncbi['fields'].values()) == {None} and ncbi['release_date'] is None
    s, _ = searcher(tmp_path, TERMS)
    mesh = biodb.mesh_terms(s, 'rapamycin')['works'][0]['dates']
    assert (mesh['since'], mesh['release_date'], mesh['fields']['synonyms']) == (None, '2026-10-21', None)
    assert biodb.mesh_terms(s, 'rapamycin')['works'][0]['year_introduced'] == '1999'  # recorded, not a date
    s, _ = searcher(tmp_path, CHEMBL)
    chembl = biodb.chembl(s, 'rapamycin')['works'][0]['dates']
    assert chembl['release_date'] == '2026-05-01' and chembl['fields']['indications_count'] is None
    s, _ = searcher(tmp_path, GEO)
    assert biodb.geo(s, 'GSE272972')['works'][0]['dates']['since'] == '2026-07-21'


def test_at_a_cutoff_a_value_is_kept_only_when_known_by_then_and_the_log_keeps_it_as_stated(tmp_path):
    s, _ = searcher(tmp_path, GENE)
    r = biodb.hgnc_gene(biodb.at_cutoff(s, '2015-01-01'), 'RAPTOR')
    w = r['works'][0]
    # Approved 2009 under RPTOR, renamed 2016, last changed 2023: on 1.1.2015 only the symbol is known.
    assert (w['source_id'], w['symbol'], w['name'], w['alias_symbols']) == ('HGNC:30287', 'RPTOR', None, None)
    name = r['as_of']['fields']['HGNC:30287']['name']
    assert (name['reason'], name['dated'], name['stated']) == ('after_cutoff', '2016-04-01', 'regulatory associated protein of MTOR complex 1')
    assert r['ask']['as_of'] == r['as_of']['cutoff'] == '2015-01-01'
    logged = search.read_log(tmp_path)[-1]
    assert logged['call_id'] == r['call_id'] and logged['as_of']['fields']['HGNC:30287']['symbol']['basis'] == 'dated'


def test_at_a_cutoff_an_entry_made_public_after_it_is_left_out_and_an_undated_value_is_unknown(tmp_path):
    s, _ = searcher(tmp_path, GEO)
    before = biodb.geo(biodb.at_cutoff(s, '2026-07-20'), 'GSE272972')
    assert before['works'] == [] and before['as_of']['left_out'] == [
        {'stated': 'GEO:GSE272972', 'dated': '2026-07-21', 'reason': 'after_cutoff'}]
    s, _ = searcher(tmp_path, GEO)
    on = biodb.geo(biodb.at_cutoff(s, '2026-07-21'), 'GSE272972')['works'][0]  # the cutoff is inclusive
    assert on['accession'] == 'GSE272972' and on['pmids'] is None and on['samples_count'] is None
    with pytest.raises(search.SearchError):
        biodb.at_cutoff(s, '2026-07')


def test_at_a_cutoff_a_cited_study_stays_only_when_its_work_is_dated_by_then(tmp_path, licensed):
    # Real Europe PMC answers (2026-10-21) for the studies Open Genes cites for MTOR, by PMID and by DOI.
    routes = dict(OPENGENES, **{'EXT_ID%3A15186745': (200, 'epmc-pmid-opengenes-MTOR.json'),
                                'DOI%3A': (200, 'epmc-doi-opengenes-MTOR.json')})
    s, _ = searcher(tmp_path, routes)
    r = biodb.opengenes_gene(biodb.at_cutoff(s, '2014-06-01'), 'MTOR')
    kept = {w['source_id']: w['dates'] for w in r['works'] if 'via' in w}
    assert len(kept) == 7 and all(d['since'] <= '2014-06-01' for d in kept.values())
    # Online before print: Nature 2004 is dated by its print issue, the earliest date Europe PMC gives.
    assert (kept['DOI:10.1038/nature02661']['since'], kept['DOI:10.1038/nature02661']['since_by']) == ('2004-06-01', 'print')
    assert all(w.get('evidence') is None for w in r['works'] if 'via' in w)  # Open Genes dates no row
    left = {x['stated']: (x['dated'], x['reason']) for x in r['as_of']['left_out']}
    assert left['DOI:10.1126/scitranslmed.3009892'] == ('2014-12-01', 'after_cutoff') and len(left) == 6


def test_at_a_cutoff_a_cited_study_europe_pmc_does_not_find_is_left_out_undated(tmp_path):
    routes = dict(PATHWAYS, **{'europepmc': (200, 'epmc-pmid-opengenes-MTOR.json')})  # none of Reactome's
    s, _ = post(tmp_path, routes)
    r = biodb.reactome_pathway(biodb.at_cutoff(s, '2026-10-21'), 'R-HSA-165159')
    assert [w['source_id'] for w in r['works']] == ['REACTOME:R-HSA-165159']
    assert r['as_of']['left_out'] and {x['reason'] for x in r['as_of']['left_out']} == {'undated'}
    s, _ = post(tmp_path, dict(PATHWAYS, **{'europepmc': (200, 'epmc-pmid-R-HSA-165159.json')}))
    r = biodb.reactome_pathway(biodb.at_cutoff(s, '2026-10-21'), 'R-HSA-165159')
    assert '21157483' in {w.get('pmid') for w in r['works']} and r['as_of']['left_out'] == []


def test_at_a_cutoff_a_drugage_cohort_stands_from_its_study_with_what_it_reported(tmp_path):
    hagr_net = Hagr(**{k: hagr_zip(k) for k in biodb.HAGR_DATASETS})
    epmc = (fixture_path(FIX, 'epmc-pmid-drugage-rapamycin.json')).read_bytes()  # Europe PMC, 2026-10-22

    def net(url):
        return (200, epmc, {}) if 'europepmc' in url else hagr_net(url)
    s = search.Searcher(tmp_path, get=net, sleep=lambda x: None, clock=lambda: 0.0)
    r = biodb.drugage(biodb.at_cutoff(s, '2014-06-01'), 'rapamycin')
    cohorts = [w for w in r['works'] if w['source_id'].startswith('DRUGAGE:')]
    assert len(cohorts) == 18 and all(w['dates']['since'] <= '2014-06-01' for w in cohorts)
    harrison = next(w for w in cohorts if w['pubmed_id'] == '19587680')  # Harrison 2009, the ITP study
    assert (harrison['dates']['since'], harrison['dates']['since_by']) == ('2009-07-01', 'study MED:19587680')
    assert harrison['species'] == 'Mus musculus' and harrison['avg_lifespan_change_percent'] is not None
    left = [x for x in r['as_of']['left_out'] if x['stated'].startswith('DRUGAGE:')]
    assert len(left) == 19 and {x['reason'] for x in left} == {'after_cutoff'}  # 27091134 (2016) among them


# -- PubChem: a compound by its parent; DrugAge matched by it ----------------------------------------
# Real answers (2026-10-22) of PubChem PUG REST, by path; and real DrugAge build 5 rows: rapamycin,
# promethazine, promethazine hydrochloride and zinc acetate.
PUBCHEM_ANSWERS = json.loads((fixture_path(FIX, 'pubchem-recorded.json')).read_text())


def pubchem_net(tmp_path, table='hagr-drugage-salts.csv'):
    hagr_net = Hagr(drugage=hagr_zip('drugage', (fixture_path(FIX, table)).read_bytes()))

    def net(url):
        if url.startswith(biodb.PUBCHEM):
            status, body = PUBCHEM_ANSWERS.get(url[len(biodb.PUBCHEM):], (404, '{"Fault": {}}'))
            return status, body.encode(), {}
        return hagr_net(url)
    return search.Searcher(tmp_path, get=net, sleep=lambda x: None, clock=lambda: 0.0)


def test_pubchem_a_name_stands_for_its_parent_compound_with_identifiers_and_names(tmp_path):
    s = pubchem_net(tmp_path)
    w = biodb.pubchem(s, 'sirolimus')['works'][0]
    assert (w['source_id'], w['name'], w['inchikey']) == ('PUBCHEM.COMPOUND:5284616', 'Sirolimus', 'QFJCIRLUMZQUOT-HPLJOQBZSA-N')
    assert 'rapamycin' in w['synonyms'] and all(len(x) <= biodb.PUBCHEM_NAME for x in w['synonyms'])
    assert w['licence'] == biodb.NCBI_TERMS and w['url'].endswith('/compound/5284616')
    acid = biodb.pubchem(s, 'acetic acid')
    assert [x['cid'] for x in acid['works']] == [176] and acid['parent_by'] == 'parent'
    none = biodb.pubchem(s, 'notacompoundxyz')
    assert none['outcome'] == 'ok' and none['works'] == []


def salt_is_found(s):
    """DrugAge files promethazine twice: as itself (2 cohorts) and as its hydrochloride (3)."""
    r = biodb.drugage(s, 'promethazine')
    by = [w['matched_by'] for w in r['works'] if w['source_id'].startswith('DRUGAGE:')]
    assert sorted(by) == ['PubChem parent CID'] * 3 + ['name'] * 2
    assert r['names_matched'] == ['Promethazine', 'Promethazine hydrochloride'] and r['pubchem']['cids'] == [4927]


def test_drugage_finds_a_compound_filed_under_a_synonym_or_as_a_salt_by_its_parent(tmp_path):
    s = pubchem_net(tmp_path)
    salt_is_found(s)
    sirolimus = biodb.drugage(s, 'sirolimus')  # DrugAge files it as rapamycin
    assert sirolimus['hit_count'] == 3 and sirolimus['names_matched'] == ['Rapamycin']
    # Zinc acetate keeps its own compound: acetic acid, its parent by PubChem, is not zinc acetate.
    assert biodb.drugage(s, 'acetic acid')['hit_count'] == 0
    assert sum(x['tool'] == 'pubchem_drugage' for x in search.read_log(tmp_path)) == 1  # mapped once a build


def test_the_salt_check_fails_on_a_mutant_that_does_not_collapse_salts(tmp_path, monkeypatch):
    # The mutant: a name stands for its own compound, not its parent. Promethazine hydrochloride is
    # then another compound, its three cohorts are lost, and the check above must fail.
    def own(s, name, responses):
        cids = biodb.pubchem_cids(s, f"name/{urllib.parse.quote(name.strip(), safe='')}/cids/JSON", responses)
        return cids, cids and 'own'
    monkeypatch.setattr(biodb, 'pubchem_parent', own)
    with pytest.raises(AssertionError):
        salt_is_found(pubchem_net(tmp_path))


def test_at_a_cutoff_a_pubchem_compound_keeps_its_identifiers_and_its_names_are_unknown(tmp_path):
    # PubChem dates neither a compound's names nor its record here: the CID and InChIKey identify it.
    w = biodb.pubchem(biodb.at_cutoff(pubchem_net(tmp_path), '2010-01-01'), 'sirolimus')['works'][0]
    assert (w['cid'], w['inchikey'], w['name'], w['synonyms']) == (5284616, 'QFJCIRLUMZQUOT-HPLJOQBZSA-N', None, None)


# -- Closeness to humans, from the NCBI lineage ---------------------------------------------------------
# The taxa table of ohf:terms@1 (OHF 1.1), as pinned there; NCBI Taxonomy's answer for its sixteen taxa,
# the rock pigeon (not in it) and baker's yeast (not an animal), 2026-10-22.
TERMS_1_TAXA = {'9606': 'human', '10090': 'mammal', '10116': 'mammal', '10141': 'mammal', '9544': 'mammal',
                '9541': 'mammal', '9483': 'mammal', '9615': 'mammal', '10181': 'mammal',
                '7955': 'non_mammal_vertebrate', '105023': 'non_mammal_vertebrate', '8355': 'non_mammal_vertebrate',
                '9031': 'non_mammal_vertebrate', '6239': 'invertebrate', '7227': 'invertebrate', '7159': 'invertebrate'}
TAXA = {'efetch.fcgi?db=taxonomy&id=9606%2C10090': (200, 'taxonomy-efetch-terms-1.xml')}
TAXA_ASKED = ','.join(f'NCBITaxon:{x}' for x in [*TERMS_1_TAXA, '8932', '4932'])


def taxa_rungs(tmp_path):
    s, _ = searcher(tmp_path, TAXA)
    return {w['taxon']: (w['proximity'], w['proximity_by']) for w in biodb.taxonomy(s, TAXA_ASKED)['works']}


def test_the_rung_from_the_lineage_is_the_pinned_one_for_every_taxon_of_the_table(tmp_path):
    rungs = taxa_rungs(tmp_path)
    assert {t: rungs[t][0] for t in TERMS_1_TAXA} == TERMS_1_TAXA
    assert rungs['10090'][1] == 'NCBITaxon:40674 Mammalia' and rungs['9606'][1] == 'NCBITaxon:9606 Homo sapiens'


def out_of_table_rungs(tmp_path):
    rungs = taxa_rungs(tmp_path)
    assert rungs['8932'] == ('non_mammal_vertebrate', 'NCBITaxon:7742 Vertebrata')  # Columba livia
    assert rungs['4932'] == (None, 'not an animal')  # yeast is not an invertebrate


def test_a_taxon_outside_the_table_has_its_rung_from_its_lineage(tmp_path):
    out_of_table_rungs(tmp_path)
    s, _ = searcher(tmp_path, TAXA)
    w = biodb.taxonomy(s, TAXA_ASKED)['works'][-2]
    assert w['lineage_ids'][-1]['rank'] == 'genus' and {'id': 'NCBITaxon:7742', 'name': 'Vertebrata',
                                                         'rank': 'clade'} in w['lineage_ids']


def test_the_out_of_table_check_fails_on_a_mutant_that_drops_a_rung(tmp_path, monkeypatch):
    # The mutant forgets Vertebrata: a pigeon becomes an invertebrate, and the check must fail.
    monkeypatch.setattr(biodb, 'PROXIMITY', tuple(x for x in biodb.PROXIMITY if x[1] != 'Vertebrata'))
    with pytest.raises(AssertionError):
        out_of_table_rungs(tmp_path)


def test_taxa_rows_are_terms_1_rows_with_their_origin_and_a_common_name_of_two_taxa_is_not_chosen(tmp_path):
    s, _ = searcher(tmp_path, dict(TAXA, **TERMS))
    out = biodb.taxa_rows([biodb.taxonomy(s, 'NCBITaxon:9606,NCBITaxon:10090'), biodb.taxonomy(s, 'mouse')])
    assert out['schema'] == 'ohf-extractor:taxa@1'
    pigeon = next(r for r in out['taxa'] if r['id'] == 'NCBITaxon:8932')
    assert {k: pigeon[k] for k in ('id', 'label', 'proximity')} == {
        'id': 'NCBITaxon:8932', 'label': 'Columba livia', 'proximity': 'non_mammal_vertebrate'}
    assert pigeon['by'] == 'NCBITaxon:7742 Vertebrata' and pigeon['call_id']
    # "mouse" is a name of Mus musculus and of Mus: neither is chosen.
    assert out['ambiguous'] == [{'asked': 'mouse', 'taxa': ['NCBITaxon:10090', 'NCBITaxon:10088']}]


# -- OHF 1.1 system.taxon_id of a card's lines ------------------------------------------------------
# Real answers (2026-10-23): NCBI Taxonomy for Mus musculus by id and by name, the genus Drosophila
# (7215), the class Mammalia by name and as "mammals" (a common name), "humans" (the common name NCBI
# gives the genus Homo, 9605), "amphibians and squamate reptiles" (three taxa found, none so named),
# and "mouse" as above (Mus musculus and the genus Mus).
LINE_TAXA = {'id=10090%2C': (200, 'taxonomy-efetch-mouse.xml'), 'id=10090&': (200, 'taxonomy-efetch-10090.xml'),
             'id=7215&': (200, 'taxonomy-efetch-7215.xml'), 'id=40674&': (200, 'taxonomy-efetch-40674.xml'),
             'id=9605&': (200, 'taxonomy-efetch-9605.xml'), 'id=1294634': (200, 'taxonomy-efetch-amphibians-squamates.xml'),
             'term=Mus+musculus': (200, 'taxonomy-esearch-mus-musculus.json'),
             'term=Mammalia': (200, 'taxonomy-esearch-mammalia.json'), 'term=mammals': (200, 'taxonomy-esearch-mammals.json'),
             'term=humans': (200, 'taxonomy-esearch-humans.json'),
             'term=amphibians': (200, 'taxonomy-esearch-amphibians-squamates.json'),
             'term=mouse': (200, 'taxonomy-esearch-mouse.json')}


def card_of(*systems, version='1.1'):
    lines = [{'id': f'e{n}', **({'system': s} if s is not None else {})} for n, s in enumerate(systems)]
    return {'standard_version': version, 'added': {'layers': {'evidence': {'lines': lines}}, 'sources': {}}}


def taxon(words, ident=None):
    return {'taxon': {'value': words, 'src': 'p1'}} | ({'taxon_id': {'value': ident, 'src': 'biodb_old'}} if ident else {})


def test_a_line_gets_the_taxon_id_of_one_species_with_its_call_as_source(tmp_path):
    s, _ = searcher(tmp_path, LINE_TAXA)
    card = card_of(taxon('mice'), taxon('aged mice'), taxon('mice', 'NCBITaxon:10088'))
    got = biodb.taxon_ids(s, card, {'e0': 'NCBITaxon:10090', 'e1': 'Mus musculus', 'e2': 'Mus musculus'})
    assert [v['value'] for v in got] == ['NCBITaxon:10090'] * 3
    assert got[0]['src'] == f"biodb_{got[0]['call_id']}" and got[0]['rank'] == 'species'
    source = got[0]['source']
    assert source['source'].endswith('efetch.fcgi?db=taxonomy&id=10090&tool=ohf-extractor')
    assert source['locator'] == 'NCBI Taxonomy: Mus musculus (NCBITaxon:10090)' and got[0]['call_id'] in source['tool']
    # By name it is one call more, and its own source.
    assert got[1]['call_id'] != got[0]['call_id'] and got[2]['call_id'] == got[1]['call_id']
    assert 'left as declared' in got[2]['disagrees']
    placed, counts = biodb.place_taxon_ids(card, got)
    lines = placed['added']['layers']['evidence']['lines']
    assert lines[0]['system']['taxon_id'] == {'value': 'NCBITaxon:10090', 'src': got[0]['src']}
    assert lines[2]['system']['taxon_id']['value'] == 'NCBITaxon:10088'
    assert placed['added']['sources'][got[0]['src']] == source and 'biodb_old' not in placed['added']['sources']
    assert counts == {'values': 2, 'gaps': 0, 'kept': 1, 'not_placed': 0} and card['added']['sources'] == {}


def test_a_clade_of_any_rank_is_placed_when_one_taxon_is_named(tmp_path):
    s, _ = searcher(tmp_path, LINE_TAXA)
    # The line's own word, Mammalia, is a scientific name; flies are read as the genus Drosophila.
    got = biodb.taxon_ids(s, card_of(taxon('Mammalia'), taxon('flies')), {'e1': 'NCBITaxon:7215'})
    assert [(v['value'], v['rank']) for v in got] == [('NCBITaxon:40674', 'class'), ('NCBITaxon:7215', 'genus')]
    assert got[0]['row']['proximity'] == 'mammal' and got[1]['row']['proximity'] == 'invertebrate'


def test_a_word_matched_only_by_a_common_name_waits_for_the_reading(tmp_path):
    s, _ = searcher(tmp_path, LINE_TAXA)
    # NCBI gives "humans" to the genus Homo: placed from the word, a human line would derive as a mammal.
    got = biodb.taxon_ids(s, card_of(taxon('humans'), taxon('mammals')))
    assert [v['value'] for v in got] == [None, None] and not any('gap' in v for v in got)
    assert got[0]['candidate'] == 'NCBITaxon:9605' and 'Homo (NCBITaxon:9605, genus)' in got[0]['why']
    assert got[1]['candidate'] == 'NCBITaxon:40674'
    # In the reading a common name is the converter's word for the taxon meant.
    assert biodb.taxon_ids(s, card_of(taxon('mammals')), {'e0': 'mammals'})[0]['value'] == 'NCBITaxon:40674'


def test_a_group_a_name_of_two_taxa_and_a_failed_lookup_get_a_gap_naming_the_call(tmp_path):
    s, _ = searcher(tmp_path, LINE_TAXA)
    card = card_of(taxon('amphibians and squamate reptiles'), taxon('mouse'), taxon('tardigrades'), None)
    got = biodb.taxon_ids(s, card, {'e3': 'Mus musculus'})
    assert [v['value'] for v in got] == [None] * 4
    group, mouse, failed = got[0]['gap'], got[1]['gap'], got[2]['gap']
    assert group['disposition'] == 'searched_not_found' and group['query_ids'] == [got[0]['call_id']]
    assert group['path'] == 'evidence.lines[0].system.taxon_id' and 'is no name of one NCBI Taxonomy taxon' in group['reason']
    assert "'mouse' names 2 taxa" in mouse['reason'] and 'Mus (NCBITaxon:10088, genus)' in mouse['reason']
    assert failed['disposition'] == 'blocked' and 'failed (' in failed['reason']
    assert got[3]['why'] == 'the line states no system to hold a taxon id'
    placed, counts = biodb.place_taxon_ids(card, got)
    assert counts == {'values': 0, 'gaps': 3, 'kept': 0, 'not_placed': 1}
    # A value placed later answers the gap: it goes.
    reread = biodb.taxon_ids(s, placed, {'e1': 'Mus musculus'})
    again, _ = biodb.place_taxon_ids(placed, reread)
    assert [g['path'] for g in again['added']['gaps']] == ['evidence.lines[0].system.taxon_id',
                                                           'evidence.lines[2].system.taxon_id']


def test_the_common_name_guard_fails_on_a_mutant_that_takes_any_name(tmp_path, monkeypatch):
    real = biodb.named_exactly
    monkeypatch.setattr(biodb, 'named_exactly', lambda asked, works, common=True: real(asked, works, True))
    s, _ = searcher(tmp_path, LINE_TAXA)
    assert biodb.taxon_ids(s, card_of(taxon('humans')))[0]['value'] == 'NCBITaxon:9605'
    with pytest.raises(AssertionError):
        test_a_word_matched_only_by_a_common_name_waits_for_the_reading(tmp_path / 'm')


def test_taxon_ids_refuses_a_1_0_card_and_a_line_the_card_lacks(tmp_path):
    s, _ = searcher(tmp_path, LINE_TAXA)
    with pytest.raises(SystemExit, match='1.1 member'):
        biodb.taxon_ids(s, card_of(taxon('mice'), version='1.0'), {'e0': 'Mus musculus'})
    with pytest.raises(SystemExit, match=r"\['e9'\]"):
        biodb.taxon_ids(s, card_of(taxon('mice')), {'e9': 'Mus musculus'})


# -- Hallmarks of ageing: hints through the pinned table ---------------------------------------------
# Real answers (2026-10-22): HGNC, Open Genes and QuickGO annotations for MTOR and ELN, and Open Genes'
# list of its ageing mechanisms. ELN is filed under one mechanism only, 94 (changes in the extracellular
# matrix structure), which the table leaves out, and has no GO annotation to a term of the table.
HALLMARKS = {'fetch/symbol/MTOR': (200, 'hgnc-symbol-MTOR.xml'), 'fetch/symbol/ELN': (200, 'hgnc-symbol-ELN.xml'),
             'gene/MTOR': (200, 'opengenes-MTOR.json'), 'gene/ELN': (200, 'opengenes-ELN.json'),
             'geneProductId=P42345&': (200, 'go-annotations-P42345.json'),
             'geneProductId=P15502&': (200, 'go-annotations-P15502.json'), 'go/about': (200, 'go-about.json')}
TWELVE = ['genomic_instability', 'telomere_attrition', 'epigenetic_alterations', 'loss_of_proteostasis',
          'disabled_macroautophagy', 'deregulated_nutrient_sensing', 'mitochondrial_dysfunction', 'cellular_senescence',
          'stem_cell_exhaustion', 'altered_intercellular_communication', 'chronic_inflammation', 'dysbiosis']


def test_the_hallmark_table_rows_each_name_a_source_and_a_hallmark_of_the_twelve():
    table = biodb.hallmark_map()
    # The standard's vocabulary (ohf:hallmarks@1), its bytes as published: the same twelve, pinned by hash.
    vocabulary = (fixture_path(FIX, 'ohf-hallmarks-1.json')).read_bytes()
    assert table['vocabulary']['sha256'] == search.sha256(vocabulary) and table['vocabulary']['id'] == 'ohf:hallmarks@1'
    assert table['vocabulary']['hallmarks'] == [x['id'] for x in json.loads(vocabulary)['terms']] == TWELVE
    rows = table['opengenes']['rows'] + table['go']['rows']
    assert all(r['source'] and r['basis'] and r['hallmark'] in TWELVE for r in rows)
    assert len({r['from'] for r in rows}) == len(rows)
    # Every ageing mechanism Open Genes lists is either a row or left out with why: none is forgotten.
    listed = {f"opengenes:{m['id']}": m['name'] for m in json.loads((fixture_path(FIX, 'opengenes-aging-mechanisms.json')).read_text())}
    left = {r['from']: r['label'] for r in table['opengenes']['not_mapped']}
    assert {r['from']: r['label'] for r in table['opengenes']['rows']} | left == listed
    assert set(left) == {'opengenes:91', 'opengenes:94'}


def test_the_kit_reads_only_the_table_pinned(tmp_path, monkeypatch):
    monkeypatch.setattr(biodb, 'HALLMARKS_MAP_SHA256', 'sha256:00')
    with pytest.raises(ValueError, match='not the table pinned'):
        biodb.hallmark_map()


def test_a_row_without_its_source_stops_the_table(tmp_path):
    table = json.loads((search.SKILL / biodb.HALLMARKS_MAP).read_text())
    table['opengenes']['rows'][0]['source'] = ''
    (tmp_path / 'references').mkdir()
    (tmp_path / biodb.HALLMARKS_MAP).write_text(json.dumps(table))
    with pytest.raises(ValueError, match='opengenes:75'):
        biodb.hallmark_map(tmp_path)


def test_hallmark_hints_for_a_gene_give_the_reason_the_source_and_a_link_and_assign_nothing(tmp_path, licensed):
    s, _ = searcher(tmp_path, HALLMARKS)
    records, h = biodb.hallmarks(s, 'MTOR')
    assert [r['tool'] for r in records] == ['hgnc_gene', 'opengenes_gene', 'go_annotations']
    assert h['hallmarks'] == ['genomic_instability', 'loss_of_proteostasis', 'disabled_macroautophagy',
                              'deregulated_nutrient_sensing', 'altered_intercellular_communication',
                              'chronic_inflammation']
    tor = next(x for x in h['hints'] if x['from'] == 'opengenes:84')
    assert tor['hallmark'] == 'deregulated_nutrient_sensing' and "'TOR pathway dysregulation'" in tor['reason']
    assert tor['link'] == 'https://open-genes.com/gene/MTOR' and tor['source'].startswith('López-Otín C')
    assert (tor['licence'], tor['attribution']) == ('CC-BY-4.0', 'Open Genes (open-genes.com), Open Longevity')
    assert tor['call_id'] == records[1]['call_id']
    # "negative regulation of macroautophagy" and the like count under macroautophagy: QuickGO maps them.
    auto = next(x for x in h['hints'] if x['from'] == 'GO:0016236')
    assert auto['hallmark'] == 'disabled_macroautophagy' and auto['evidence'] == {'IDA': 2, 'TAS': 1, 'IBA': 1}
    assert auto['link'].startswith('https://www.ebi.ac.uk/QuickGO/annotations?geneProductId=P42345&goId=GO:0016236')
    assert auto['call_id'] == records[2]['call_id'] and auto['licence'] == 'CC-BY-4.0'
    assert h['not_mapped'] == [] and h['assigned'].startswith('none')
    assert records[2]['works'][0]['dates']['release_date'] == '2026-09-27'


def an_unmapped_mechanism_gives_no_hallmark(tmp_path):
    s, _ = searcher(tmp_path, HALLMARKS)
    records, h = biodb.hallmarks(s, 'ELN')
    assert h['gene'] == 'ELN' and h['hints'] == [] and h['hallmarks'] == []
    assert [x['from'] for x in h['not_mapped']] == ['opengenes:94']
    assert 'no one hallmark' in h['not_mapped'][0]['why'] and h['not_mapped'][0]['call_id'] == records[1]['call_id']


def test_a_gene_with_a_mechanism_outside_the_table_gets_no_hallmark(tmp_path, licensed):
    an_unmapped_mechanism_gives_no_hallmark(tmp_path)


def test_the_check_fails_when_an_unmapped_mechanism_is_guessed(tmp_path, licensed, monkeypatch):
    """The mutant: a mechanism outside the table is given the hallmark its words come nearest to."""
    hints = biodb.hallmark_hints

    def guessing(asked, symbol, records, table, notes=()):
        table = json.loads(json.dumps(table))
        for r in table['opengenes']['not_mapped']:
            table['opengenes']['rows'].append({'from': r['from'], 'label': r['label'], 'source': 'guess',
                                               'basis': 'guess', 'hallmark': 'altered_intercellular_communication'})
        return hints(asked, symbol, records, table, notes)
    monkeypatch.setattr(biodb, 'hallmark_hints', guessing)
    with pytest.raises(AssertionError):
        an_unmapped_mechanism_gives_no_hallmark(tmp_path)


def test_hallmark_hints_without_the_open_genes_licence_or_for_a_compound_say_why_there_are_none(tmp_path, unlicensed):
    s, _ = searcher(tmp_path, HALLMARKS)
    _, h = biodb.hallmarks(s, 'MTOR')
    assert {x['from'][:3] for x in h['hints']} == {'GO:'} and 'no licence' in h['notes'][0]
    records, h = biodb.hallmarks(s, 'CHEBI:9168')
    assert records == [] and h['hints'] == [] and 'a compound' in h['notes'][0]


def test_a_compound_gets_the_hints_of_the_target_it_is_given_marked_via_it(tmp_path, licensed):
    s, _ = searcher(tmp_path, HALLMARKS)
    _, gene = biodb.hallmarks(s, 'MTOR')
    records, h = biodb.hallmarks(s, 'CHEBI:9168', via='MTOR')
    assert (h['asked'], h['via'], h['gene']) == ('CHEBI:9168', 'MTOR', 'MTOR') and h['hallmarks'] == gene['hallmarks']
    assert all(x['via'] == 'MTOR' and x['reason'].startswith('via MTOR: ') for x in h['hints'])
    assert [r['tool'] for r in records] == ['hgnc_gene', 'opengenes_gene', 'go_annotations']


def test_at_a_cutoff_open_genes_mechanisms_are_unknown_and_give_no_hint(tmp_path, licensed):
    routes = dict(HALLMARKS, **{'EXT_ID%3A15186745': (200, 'epmc-pmid-opengenes-MTOR.json'),
                                'DOI%3A': (200, 'epmc-doi-opengenes-MTOR.json')})
    s, _ = searcher(tmp_path, routes)
    records, h = biodb.hallmarks(biodb.at_cutoff(s, '2026-10-21'), 'MTOR')
    assert all(r['outcome'] == 'ok' for r in records)
    assert not any(x['from'].startswith('opengenes:') for x in h['hints'])
    assert any('not known at the cutoff' in n for n in h['notes'])
