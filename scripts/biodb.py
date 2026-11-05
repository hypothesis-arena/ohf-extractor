#!/usr/bin/env python3
"""Read-only clients of biological databases for a conversion: genes, their ageing evidence, and links.

A card rests on more than its article: the genes, targets and interventions it names are described in
databases. This module looks them up through key-free open APIs and records each call in the search
log of scripts/search.py, with the same transport, waits and hashes (search.Searcher, imported, not
copied), so a database lookup is a search with its URLs and responses behind it.

A record holds identifiers, links and counts, and the licence of the data with where it comes from, or
none. It holds a database's descriptive text or values only where they are licensed: access through an
API is not a licence to republish its content.

Usage:
  biodb.py gene NAME [NAME ...]            (HGNC, then NCBI Gene and UniProt for the gene it names)
  biodb.py hgnc NAME [NAME ...]            (HGNC: the approved symbol for a symbol, alias or former symbol)
  biodb.py ncbi-gene ID [ID ...]           (NCBI Gene: names and location of a gene id)
  biodb.py uniprot ACCESSION [...]         (UniProtKB: function, subunit, regulation, with evidence)
  biodb.py genage SYMBOL [SYMBOL ...]      (HAGR GenAge: the gene in human and model-organism ageing genes)
  biodb.py drugage COMPOUND [...]          (HAGR DrugAge: lifespan studies of a compound, with regimens)
  biodb.py hagr-fetch DATASET              (download a HAGR build: genage_human, genage_models, drugage)
  biodb.py reactome ACCESSION [...]        (Reactome: the human pathways a UniProt protein takes part in)
  biodb.py reactome-pathway ID [ID ...]    (Reactome: a pathway's summary and the studies behind it)
  biodb.py target ENSEMBL|SYMBOL [...]     (Open Targets: the target's diseases and its drugs in the clinic)
  biodb.py drug NAME|CHEMBL [...]          (Open Targets: a drug's ChEMBL id and links, link only)
  biodb.py mesh TERM [TERM ...]            (MeSH: the heading for a term, its entry terms and tree numbers)
  biodb.py taxonomy NAME|ID [...]          (NCBI Taxonomy: an organism's names, lineage, closeness to humans)
  biodb.py taxon NAME|NCBITaxon:ID [...]   (the same)
  biodb.py go TERM|GO:ID [...]             (Gene Ontology: a term's name, definition and synonyms)
  biodb.py chembl NAME|CHEMBL [...]        (ChEMBL: a compound's id, links and counts, link only)
  biodb.py geo QUERY|GSE [...]             (GEO: expression series, their metadata and links, not the data)
  biodb.py pubchem NAME [NAME ...]         (PubChem: the parent compound a name stands for, its InChIKey and names)
  biodb.py opengenes SYMBOL [SYMBOL ...]   (Open Genes: the gene, its ageing evidence and the studies behind it)
  biodb.py hallmarks GENE|CHEBI|CID [...]  (hints of hallmarks of ageing from Open Genes and GO, not assigned;
                                           a compound's only --via GENE, its target)
  biodb.py proximity CARD --standard DIR   (OHF 1.1 human_proximity of each evidence line, derived by the standard's
                                           check_refs from system.taxon_id and endpoint kind, or a gap saying why;
                                           --taxa taxa.json adds rows, --out FILE places them; no network)
  biodb.py taxon-ids CARD [--reading FILE] (OHF 1.1 system.taxon_id: the one NCBI taxon, of any rank, a line's
                                           system.taxon (or the reading) names exactly, with the call as source,
                                           or a gap; --taxa FILE writes their rows, --out FILE --standard DIR
                                           places them)
with --workdir DIR (default: the current directory) for the log and the responses, and --as-of YYYY-MM-DD
for a conversion with a cutoff: each value as known on that day, or null with the reason.

In one process, pass the same Searcher to every client and to search.py's calls: the waits between
requests to a host are kept per Searcher.
"""
import argparse
import csv
import html
import io
import json
import sys
import re
import subprocess
import urllib.parse
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import search  # noqa: E402

OPENGENES = 'https://open-genes.com/api/'
HGNC = 'https://rest.genenames.org/fetch/'
HGNC_PAGE = 'https://www.genenames.org/data/gene-symbol-report/#!/hgnc_id/'
NCBI_GENE_PAGE = 'https://www.ncbi.nlm.nih.gov/gene/'
UNIPROT = 'https://rest.uniprot.org/uniprotkb/'
UNIPROT_PAGE = 'https://www.uniprot.org/uniprotkb/'
HAGR = 'https://genomics.senescence.info/'
REACTOME = 'https://reactome.org/ContentService/'
REACTOME_PAGE = 'https://reactome.org/content/detail/'
OPENTARGETS = 'https://api.platform.opentargets.org/api/v4/graphql'
OPENTARGETS_PAGE = 'https://platform.opentargets.org/'
CHEMBL_PAGE = 'https://www.ebi.ac.uk/chembl/explore/compound/'
CHEMBL = 'https://www.ebi.ac.uk/chembl/api/data/'
GEO_PAGE = 'https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc='
PUBCHEM = 'https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/'
PUBCHEM_PAGE = 'https://pubchem.ncbi.nlm.nih.gov/compound/'
MESH_PAGE = 'https://meshb.nlm.nih.gov/record/ui?ui='
TAXONOMY_PAGE = 'https://www.ncbi.nlm.nih.gov/Taxonomy/Browser/wwwtax.cgi?id='
QUICKGO = 'https://www.ebi.ac.uk/QuickGO/services/ontology/go/'
GO_PAGE = 'https://www.ebi.ac.uk/QuickGO/term/'
OPENGENES_PAGE = 'https://open-genes.com/gene/'
# Seconds between two requests to one host. HGNC allows 10 a second; Open Genes and UniProt state no
# rate, and the kit keeps one a second. NCBI is spaced by search.py, which shares the host.
for _host, _interval in {'open-genes.com': 1.0, 'rest.genenames.org': 0.2, 'rest.uniprot.org': 1.0,
                         'genomics.senescence.info': 1.0, 'reactome.org': 1.0,
                         'api.platform.opentargets.org': 1.0, 'pubchem.ncbi.nlm.nih.gov': 0.25}.items():
    search.MIN_INTERVAL.setdefault(_host, _interval)

# Open Genes data are under CC BY 4.0 by permission of the rights holder (Open Longevity), a note the kit
# carries: the site and the API do not state a licence. Without the note, a record is link only: the
# gene's identifiers, page and counts, no value or text of the database.
OPENGENES_PERMISSION = 'references/permissions/open-genes.md'
OPENGENES_LICENCE = 'CC-BY-4.0'
OPENGENES_ATTRIBUTION = 'Open Genes (open-genes.com), Open Longevity'
OPENGENES_LINK_ONLY = ('source_id', 'opengenes_id', 'symbol', 'ncbi_gene', 'uniprot', 'ensembl', 'url',
                       'evidence_counts', 'licence', 'licence_from')
# Text Open Genes repeats from other sources is theirs, under their terms: not recorded.
OPENGENES_WITHHELD = {'proteinDescriptionUniProt': 'UniProt text', 'descriptionNCBI': 'NCBI Gene text',
                      'humanProteinAtlas': 'Human Protein Atlas data'}
# Keys of an evidence row that are the database's own row numbers or a cross-reference, not evidence.
OPENGENES_NOT_EVIDENCE = ('id', 'gene', 'uuid', 'doi', 'pmid')
# Licences as each source states them, and where.
HGNC_LICENCE, HGNC_LICENCE_FROM = 'CC0-1.0', 'https://www.genenames.org/about/license/'
# UniProt's licence page answers a program at rest.uniprot.org and a reader at www.uniprot.org.
UNIPROT_LICENCE = 'CC-BY-4.0'
UNIPROT_LICENCE_FROM = 'https://rest.uniprot.org/help/license (https://www.uniprot.org/help/license)'
HAGR_LICENCE, HAGR_LICENCE_FROM = 'CC-BY-3.0', 'https://genomics.senescence.info/legal.html'
REACTOME_LICENCE, REACTOME_LICENCE_FROM = 'CC0-1.0', 'https://reactome.org/license'
# Open Targets marks its data CC0, and asks to be cited. Its drugs, mechanisms and clinical stages come
# from ChEMBL, whose releases are CC BY-SA 3.0: ShareAlike does not fit a CC BY card, and an aggregator's
# mark does not lift the first source's terms. Those are recorded link only: identifiers, links, counts.
OPENTARGETS_LICENCE, OPENTARGETS_LICENCE_FROM = 'CC0-1.0', 'https://platform-docs.opentargets.org/licence'
OPENTARGETS_ATTRIBUTION = 'Open Targets Platform (platform.opentargets.org), CC0'
OPENTARGETS_CITATION = ('Buniello A, et al. Open Targets Platform: facilitating therapeutic hypotheses building in '
                        'drug discovery. Nucleic Acids Research (2025)')
CHEMBL_LINK_ONLY = 'from ChEMBL (CC BY-SA 3.0): identifiers, links and counts only'
MESH_TERMS = 'NLM freely provides MeSH data; acknowledge NLM as the source'
MESH_TERMS_FROM = 'https://www.nlm.nih.gov/databases/download/terms_and_conditions_mesh.html'
GO_LICENCE, GO_LICENCE_FROM = 'CC-BY-4.0', 'https://geneontology.org/docs/go-citation-policy/'
# How many entries a term search reads in full: MeSH headings and concepts, taxa, GO terms. A GO text
# search looks at more, so that the term named exactly is among them, not cut by QuickGO's order.
TERMS_READ = 5
GO_SEARCHED = 25
# NCBI Taxonomy name classes that are not other names of the organism.
TAXONOMY_NOT_NAMES = ('Includes', 'misspelling', 'authority', 'type material')
CHEMBL_LICENCE = 'CC-BY-SA-3.0'
CHEMBL_LICENCE_FROM = 'https://chembl.gitbook.io/chembl-interface-documentation/about'
# How many compounds a ChEMBL name search reads (each with three counts), and how many series a GEO
# search reads.
CHEMBL_READ = 3
GEO_READ = 20
# How many associated diseases a target lookup keeps, by score; the record says how many there are.
OPENTARGETS_DISEASES = 25
# NCBI names no licence: it places no restriction on its molecular databases, and says material others
# submitted may be protected. The gene summary is not recorded: it may draw on such material.
NCBI_TERMS = 'no restriction placed by NCBI; submitted material may carry its own rights'
NCBI_TERMS_FROM = 'https://www.ncbi.nlm.nih.gov/home/about/policies/'
# How HGNC resolves a name: an approved symbol first, then a former symbol, then an alias.
HGNC_FIELDS = ('symbol', 'prev_symbol', 'alias_symbol')
# UniProtKB comments recorded as text, and how many entries a gene lookup reads.
UNIPROT_COMMENTS = ('FUNCTION', 'SUBUNIT', 'ACTIVITY REGULATION')
UNIPROT_ENTRIES = 3
# HAGR builds, as HAGR offers them for download: the archive, the table in it, and the table's header.
# HAGR asks that many queries go to the downloads, not the site: a build is fetched once and searched here.
HAGR_DATASETS = {
    'genage_human': ('genes/human_genes.zip', 'genage_human.csv',
                     ['GenAge ID', 'symbol', 'name', 'entrez gene id', 'uniprot', 'why']),
    'genage_models': ('genes/models_genes.zip', 'genage_models.csv',
                      ['GenAge ID', 'symbol', 'name', 'organism', 'entrez gene id', 'avg lifespan change (max obsv)',
                       'lifespan effect', 'longevity influence']),
    'drugage': ('drugs/dataset.zip', 'drugage.csv',
                ['compound_name', 'species', 'strain', 'dosage', 'age_at_initiation', 'treatment_duration',
                 'avg_lifespan_change_percent', 'avg_lifespan_significance', 'max_lifespan_change_percent',
                 'max_lifespan_significance', 'gender', 'weight_change_percent', 'weight_change_significance',
                 'ITP', 'pubmed_id']),
}
# The citations HAGR asks for (legal.html): HAGR for GenAge, the DrugAge paper for DrugAge.
HAGR_CITATION = ('de Magalhaes JP, et al. Human Ageing Genomic Resources: updates on key databases in ageing '
                 'research. Nucleic Acids Research 52(D1):D900-D908 (2024)')
DRUGAGE_CITATION = ('Barardo D, et al. The DrugAge database of ageing-related drugs. Aging Cell 16(3):594-597 '
                    '(2017)')
# Open Genes evidence sections, by the name the API gives them.
OPENGENES_SECTIONS = ('increaseLifespan', 'ageRelatedChangesOfGene', 'interventionToGeneImprovesVitalProcesses',
                      'proteinRegulatesOtherGenes', 'geneAssociatedWithProgeriaSyndromes',
                      'geneAssociatedWithLongevityEffects', 'additionalEvidences')


def not_found(error, responses):
    """True when a lookup failed only because the service answered 404: the entry does not exist."""
    return isinstance(error, search.SearchError) and responses and responses[-1]['status'] == 404


# -- Dates: since when a value stands --------------------------------------------------------------
# A database answers as it is now. For a conversion with a cutoff (--as-of), each record says when it
# was made public (`since`), the day of the release read (`release_date`), and, for each of its values,
# the date since which the value has stood unchanged, where the source states one: None where it does
# not. Identifiers, links, licences and the version read are not dated. Deciding against a cutoff is
# search.as_of's, one rule for every source: a field's date is its `dated`, the release date its `release`.
NOT_DATED = {'source_id', 'url', 'chembl_url', 'files', 'pubmed_query', 'licence', 'licence_from', 'attribution',
             'citation', 'data_from', 'data_licence', 'data_licence_from', 'drugs_data_from', 'drugs_licence',
             'drugs_licence_from', 'evidence_licence', 'evidence_licence_from', 'release', 'release_date',
             'released', 'build', 'dataset', 'archive_sha256', 'rows', 'line', 'version', 'entry_version',
             'last_annotation', 'via', 'dates', 'accession', 'ui', 'kind', 'stable_id', 'opengenes_id', 'pmid',
             'doi', 'taxon', 'organism', 'year_introduced', 'cid', 'inchikey', 'found_by', 'collapsed_from',
             'matched_by'}
MONTHS = ('January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October',
          'November', 'December')


def day(v):
    """A source's date as search.as_of takes it, YYYY-MM-DD, or YYYY for a year alone; or None.
    2026-09-27, 2026/07/21, 2016-04-01T00:00:00Z and June 17, 2023 are days; anything else is not a date."""
    v = str(v or '').strip()
    if m := re.match(r'(\d{4})[-/](\d{2})[-/](\d{2})(?!\d)', v):
        return '-'.join(m.groups())
    if re.fullmatch(r'\d{4}', v):
        return v
    if (m := re.fullmatch(r'([A-Z][a-z]+) (\d{1,2}), (\d{4})', v)) and m[1] in MONTHS:
        return f'{m[3]}-{MONTHS.index(m[1]) + 1:02d}-{int(m[2]):02d}'
    return None


def dated(w, since=None, release=None, every=None, **fields):
    """Mark a record's dates: `every` is the day each value has stood since, unless fields names one."""
    w['dates'] = {'since': day(since), 'release_date': day(release),
                  'fields': {k: day(fields.get(k, every)) for k in w if k not in NOT_DATED}}
    return w


# Values of a call outside its records that change with time: the counts Open Genes gives by section.
UNDATED_EXTRA = ('evidence_counts', 'rows_without_study_id')


def by_study(w):
    """A record that is one study's result as a database curated it: a DrugAge cohort. It stands from
    its study, or not at all."""
    return w['source_id'].startswith('DRUGAGE:')


def cited_dates(s, works, responses):
    """Date the studies a database cites (records with `via`) by the work itself: its Europe PMC record,
    found by PMID or DOI, and the earliest of its dates (search.earliest). A study Europe PMC does not
    find stays undated. A DrugAge cohort takes its study's date, for itself and each of its values: they
    are what that study reported."""
    cited = [w for w in works if 'via' in w]
    pmids = [w['pmid'] for w in cited if w.get('pmid')]
    pmids += [w['pubmed_id'] for w in works if by_study(w) and w.get('pubmed_id')]
    found = s.epmc_lookup([('MED', p) for p in pmids], responses)
    dois = list(dict.fromkeys(w['doi'] for w in cited if w.get('doi') and not w.get('pmid')))
    by_doi = {}
    for i in range(0, len(dois), search.BATCH):
        part = dois[i:i + search.BATCH]
        q = ' OR '.join(f'DOI:"{d}"' for d in part)
        by_doi |= {(r.get('doi') or '').lower(): r for r in s.epmc_search(q, len(part), responses)[1]}
    for w in cited:
        r = found.get(('MED', w.get('pmid'))) or by_doi.get((w.get('doi') or '').lower())
        if r:
            w['dates']['work'] = search.work_dates(r)
            w['dates']['since_by'], w['dates']['since'] = search.earliest(w['dates']['work'])
    for w in works:
        r = by_study(w) and found.get(('MED', w.get('pubmed_id')))
        if r:
            _, since = search.earliest(search.work_dates(r))
            w['dates'].update(since=since, since_by=f"study MED:{w['pubmed_id']}",
                              fields=dict.fromkeys(w['dates']['fields'], since))


def at_cutoff(s, cutoff):
    """Make every call of s answer as of the cutoff (YYYY-MM-DD, inclusive): an entry made public after
    it is left out, and so is a study a database cites unless its work is dated by then; each value is
    search.as_of's, null unless known to hold by then. The record names the cutoff, and keeps each
    decision whole, the value as stated with it (`as_of`)."""
    search.cutoff_day(cutoff)
    plain = s.call

    def call(tool, ask, run):
        def run_at(responses):
            hits, works, extra = run(responses)
            cited_dates(s, works, responses)
            kept, decided = [], {'cutoff': cutoff, 'left_out': [], 'fields': {}}
            for w in works:
                d = w.get('dates')
                dated_only = 'via' in w or by_study(w)  # a study, or a study's result: undated is left out
                entry = d and (d['since'] or dated_only) and search.as_of(w['source_id'], d['since'], cutoff)
                if entry and entry['reason']:
                    decided['left_out'].append({k: entry[k] for k in ('stated', 'dated', 'reason')})
                    continue
                for k, dated_k in (d['fields'] if d else {}).items():
                    r = search.as_of(w[k], dated_k, cutoff, d['release_date'])
                    w[k] = r['value']
                    decided['fields'].setdefault(w['source_id'], {})[k] = r
                kept.append(w)
            for k in UNDATED_EXTRA:
                if k in extra:
                    decided['fields'].setdefault('', {})[k] = r = search.as_of(extra[k], None, cutoff)
                    extra[k] = r['value']
            return hits, kept, extra | {'as_of': decided}
        return plain(tool, ask | {'as_of': cutoff}, run_at)
    s.call = call
    return s


# -- Open Genes ------------------------------------------------------------------------------------

def opengenes_gene(s, symbol):
    """Look up a gene in Open Genes by symbol: one logged record, the gene and the studies it cites."""
    url = OPENGENES + 'gene/' + urllib.parse.quote(symbol) + '?lang=en'

    def run(responses):
        try:
            d = s.json(url, responses)
        except search.SearchError as e:
            if not_found(e, responses):
                return 0, [], {'service': 'Open Genes API gene', 'note': f'no Open Genes entry for {symbol}'}
            raise
        licence_from = opengenes_permission()
        gene = work_opengenes_gene(d, licence_from)
        studies, unidentified = opengenes_studies(d, gene['source_id'], licence_from)
        withheld = dict(OPENGENES_WITHHELD) if licence_from else {
            'values and text': f'no licence for Open Genes data: {OPENGENES_PERMISSION} is not in the kit'}
        return 1, [gene] + studies, {'service': 'Open Genes API gene', 'evidence_counts': gene['evidence_counts'],
                                     'rows_without_study_id': unidentified, 'withheld': withheld}
    return s.call('opengenes_gene', {'id': symbol, 'source': 'opengenes'}, run)


def opengenes_permission(root=search.SKILL):
    """Where the Open Genes data licence is stated: the permission note in the kit, with its hash; or None
    when the kit carries no note."""
    path = root / OPENGENES_PERMISSION
    if not path.is_file():
        return None
    return f'{OPENGENES_PERMISSION} ({search.sha256(path.read_bytes())})'


def work_opengenes_gene(d, licence_from):
    """The gene as a found record: identifiers, its page, how many studies each section holds and, when
    the data are licensed, Open Genes' own classification of it (confidence level, ageing mechanisms,
    why it is in the database)."""
    researches = d.get('researches') or {}
    w = {'source_id': f"OPENGENES:{d['symbol']}", 'opengenes_id': d.get('id'), 'symbol': d['symbol'],
         'name': d.get('name'), 'aliases': d.get('aliases') or [],
         'ncbi_gene': d.get('ncbiId'), 'uniprot': d.get('uniprot'), 'ensembl': d.get('ensembl'),
         'url': OPENGENES_PAGE + urllib.parse.quote(d['symbol']),
         'confidence_level': (d.get('confidenceLevel') or {}).get('name'),
         'selection_criteria': names(d.get('commentCause')), 'aging_mechanisms': names(d.get('agingMechanisms')),
         'aging_mechanism_ids': ids(d.get('agingMechanisms')),
         'functional_clusters': names(d.get('functionalClusters')),
         'protein_classes': names(d.get('proteinClasses')), 'diseases': names(d.get('diseases')),
         'evidence_counts': {k: len(researches.get(k) or []) for k in OPENGENES_SECTIONS},
         'licence': OPENGENES_LICENCE, 'licence_from': licence_from, 'attribution': OPENGENES_ATTRIBUTION}
    if not licence_from:
        w = {k: w[k] for k in OPENGENES_LINK_ONLY} | {'licence': None}
    return dated(w)


def opengenes_studies(d, via, licence_from):
    """The studies an Open Genes entry cites, by DOI or PMID, once each, with the evidence rows that cite
    them; and how many rows cite neither, so that a row without a study is counted, not lost.
    The rows are Open Genes data, kept only when licensed; the study keeps its own licence, not known here."""
    out, unidentified = {}, 0
    for section in OPENGENES_SECTIONS:
        for r in (d.get('researches') or {}).get(section) or []:
            doi, pmid = (r.get('doi') or '').strip() or None, str(r.get('pmid') or '').strip() or None
            if not doi and not pmid:
                unidentified += 1
                continue
            key = f'DOI:{doi.lower()}' if doi else f'MED:{pmid}'
            w = out.setdefault(key, {'source_id': key, 'doi': doi, 'pmid': pmid, 'relation': [], 'via': via,
                                     'licence': None, 'licence_from': None})
            w['pmid'] = w['pmid'] or pmid
            if section not in w['relation']:
                w['relation'].append(section)
            if licence_from:
                w.setdefault('evidence', []).append({'section': section} | plain(
                    {k: v for k, v in r.items() if k not in OPENGENES_NOT_EVIDENCE}))
                w.update(evidence_licence=OPENGENES_LICENCE, evidence_licence_from=licence_from)
    return [dated(w) for w in out.values()], unidentified


def names(items):
    return [i['name'] for i in items or [] if isinstance(i, dict) and i.get('name')]


def ids(items):
    """The ids of the terms names() reads, in the same order."""
    return [i.get('id') for i in items or [] if isinstance(i, dict) and i.get('name')]


def plain(v):
    """A value without row numbers or empty fields; a term reduced to its name, a gene to its symbol."""
    if isinstance(v, dict):
        v = {k: plain(x) for k, x in v.items() if k not in OPENGENES_NOT_EVIDENCE}
        v = {k: x for k, x in v.items() if x not in (None, '', [], {})}
        if 'symbol' in v:
            return v['symbol']
        return v['name'] if set(v) == {'name'} else v
    if isinstance(v, list):
        return [x for x in map(plain, v) if x not in (None, '', [], {})]
    return v


# -- HGNC, NCBI Gene, UniProt -------------------------------------------------------------------

def hgnc_gene(s, name):
    """Resolve a gene name to its approved HGNC symbol: one logged record. A name that is an alias of
    several genes returns them all, and the record says so; it is not decided here."""
    def run(responses):
        for field in HGNC_FIELDS:
            url = HGNC + field + '/' + urllib.parse.quote(name)
            docs = hgnc_docs(s.fetch(url, responses))
            if docs:
                return len(docs), [work_hgnc(d) for d in docs], {
                    'service': 'HGNC REST fetch', 'resolved_by': field, 'ambiguous': len(docs) > 1}
        return 0, [], {'service': 'HGNC REST fetch', 'resolved_by': None, 'note': f'no HGNC gene named {name}'}
    return s.call('hgnc_gene', {'id': name, 'source': 'hgnc'}, run)


def hgnc_docs(data):
    """The genes of an HGNC answer. HGNC answers in XML (Solr) unless asked otherwise by a header, which
    the shared transport does not send: a field is an element named by its name attribute, a list an arr."""
    docs = []
    for doc in ET.fromstring(data).iter('doc'):
        docs.append({f.get('name'): [x.text for x in f] if f.tag == 'arr' else f.text for f in doc})
    return docs


def work_hgnc(d):
    """An HGNC gene: the approved symbol and name, the names it had and has, and its cross-references."""
    synonyms = [d['symbol']] + d.get('alias_symbol', []) + d.get('prev_symbol', [])
    w = {'source_id': d['hgnc_id'], 'symbol': d['symbol'], 'name': d.get('name'), 'status': d.get('status'),
            'alias_symbols': d.get('alias_symbol', []), 'prev_symbols': d.get('prev_symbol', []),
            'alias_names': d.get('alias_name', []), 'prev_names': d.get('prev_name', []),
            'synonyms': list(dict.fromkeys(synonyms)), 'locus_group': d.get('locus_group'),
            'gene_groups': d.get('gene_group', []),
            'location': d.get('location'), 'ncbi_gene': d.get('entrez_id'), 'uniprot': d.get('uniprot_ids', []),
            'ensembl': d.get('ensembl_gene_id'), 'url': HGNC_PAGE + d['hgnc_id'],
            'licence': HGNC_LICENCE, 'licence_from': HGNC_LICENCE_FROM}
    # HGNC dates the entry's last change, and the symbol's and the name's own.
    first = d.get('date_approved_reserved')
    return dated(w, since=first, every=d.get('date_modified'), symbol=d.get('date_symbol_changed') or first,
                 name=d.get('date_name_changed') or first)


def ncbi_gene(s, gene_id):
    """Names and location of an NCBI Gene id: one logged record."""
    def run(responses):
        result = s.json(s.eutils('esummary', {'db': 'gene', 'id': gene_id}), responses).get('result', {})
        g = result.get(str(gene_id))
        if not g or g.get('error'):
            return 0, [], {'service': 'NCBI E-utilities esummary (gene)', 'note': f'no NCBI gene {gene_id}'}
        return 1, [work_ncbi_gene(g)], {'service': 'NCBI E-utilities esummary (gene)', 'withheld': {
            'summary': 'not licensed by NCBI for material others submitted'}}
    return s.call('ncbi_gene', {'id': str(gene_id), 'source': 'ncbi gene'}, run)


def ncbi_gene_search(s, symbol, taxon):
    """The NCBI Gene entries of one organism (an NCBI Taxonomy id, with the taxa below it: rice genes are
    filed under its subspecies) whose symbol or alias is symbol: for a gene of any species, where HGNC
    names human genes only. One logged record."""
    def run(responses):
        found = s.json(s.eutils('esearch', {'db': 'gene', 'term': f'{symbol}[sym] AND txid{taxon}[Organism:exp]',
                                            'retmax': TERMS_READ}), responses)['esearchresult']
        ids = found.get('idlist', [])
        if not ids:
            return 0, [], {'service': 'NCBI E-utilities esearch+esummary (gene)'}
        result = s.json(s.eutils('esummary', {'db': 'gene', 'id': ','.join(ids)}), responses)['result']
        return int(found.get('count', 0)), [work_ncbi_gene(result[u]) for u in result.get('uids', [])], {
            'service': 'NCBI E-utilities esearch+esummary (gene)',
            'withheld': {'summary': 'not licensed by NCBI for material others submitted'}}
    return s.call('ncbi_gene_search', {'id': symbol, 'taxon': str(taxon), 'source': 'ncbi gene'}, run)


def work_ncbi_gene(g):
    split = lambda v, sep: [x.strip() for x in (v or '').split(sep) if x.strip()]  # noqa: E731
    return dated({'source_id': f"NCBIGENE:{g['uid']}", 'symbol': g.get('name'), 'name': g.get('description'),
            'aliases': split(g.get('otheraliases'), ','), 'designations': split(g.get('otherdesignations'), '|'),
            'taxon': (g.get('organism') or {}).get('taxid'), 'organism': (g.get('organism') or {}).get('scientificname'),
            'chromosome': g.get('chromosome'), 'map_location': g.get('maplocation'),
            'replaced_by': g.get('currentid') or None, 'url': NCBI_GENE_PAGE + str(g['uid']),
            'licence': NCBI_TERMS, 'licence_from': NCBI_TERMS_FROM})


def uniprot_entry(s, accession):
    """A UniProtKB entry: its names, version, and the function, subunit and regulation it states, with
    the studies behind each statement. One logged record."""
    def run(responses):
        try:
            e = s.json(UNIPROT + urllib.parse.quote(accession) + '.json', responses)
        except search.SearchError as err:
            if not_found(err, responses):
                return 0, [], {'service': 'UniProt REST entry', 'note': f'no UniProtKB entry {accession}'}
            raise
        entry = work_uniprot(e)
        return 1, [entry] + uniprot_studies(e, entry['source_id']), {'service': 'UniProt REST entry'}
    return s.call('uniprot_entry', {'id': accession, 'source': 'uniprot'}, run)


def uniprot_gene(s, symbol, taxon=9606):
    """The reviewed UniProtKB entries of a gene in one species (human by default), each read in full.
    The search is one logged record; each entry read is another."""
    query = f'gene_exact:{symbol} AND organism_id:{taxon} AND reviewed:true'

    def run(responses):
        url = UNIPROT + 'search?' + urllib.parse.urlencode({'query': query, 'fields': 'accession,id,gene_primary',
                                                            'format': 'json', 'size': UNIPROT_ENTRIES})
        rows = s.json(url, responses).get('results', [])
        return len(rows), [dated({'source_id': f"UNIPROT:{r['primaryAccession']}", 'accession': r['primaryAccession'],
                                  'entry_name': r.get('uniProtkbId'), 'url': UNIPROT_PAGE + r['primaryAccession'],
                                  'licence': UNIPROT_LICENCE, 'licence_from': UNIPROT_LICENCE_FROM}) for r in rows], {
            'service': 'UniProt REST search', 'query': query}
    found = s.call('uniprot_search', {'query': query, 'id': symbol, 'source': 'uniprot'}, run)
    return [found] + [uniprot_entry(s, w['accession']) for w in found['works']]


def work_uniprot(e):
    acc, audit = e['primaryAccession'], e.get('entryAudit') or {}
    desc = (e.get('proteinDescription') or {}).get('recommendedName') or {}
    comments = {}
    for c in e.get('comments') or []:
        if c.get('commentType') in UNIPROT_COMMENTS:
            comments.setdefault(c['commentType'].lower().replace(' ', '_'), []).extend(
                {'text': x['value'], 'pmids': evidence_pmids(x)} for x in c.get('texts') or [])
    w = {'source_id': f'UNIPROT:{acc}', 'accession': acc, 'entry_name': e.get('uniProtkbId'),
            'reviewed': 'Swiss-Prot' in (e.get('entryType') or ''),
            'protein': (desc.get('fullName') or {}).get('value'),
            'genes': [g['geneName']['value'] for g in e.get('genes') or [] if g.get('geneName')],
            'taxon': (e.get('organism') or {}).get('taxonId'),
            'entry_version': audit.get('entryVersion'), 'last_annotation': audit.get('lastAnnotationUpdateDate'),
            'keywords': [k['name'] for k in e.get('keywords') or []], **comments,
            'url': UNIPROT_PAGE + acc, 'licence': UNIPROT_LICENCE, 'licence_from': UNIPROT_LICENCE_FROM,
            'attribution': f"UniProt Consortium, UniProtKB {acc} (entry version {audit.get('entryVersion')}), CC BY 4.0"}
    # The last annotation update dates every value but the sequence, which is not recorded.
    return dated(w, since=audit.get('firstPublicDate'), every=audit.get('lastAnnotationUpdateDate'))


def evidence_pmids(text):
    return list(dict.fromkeys(ev['id'] for ev in text.get('evidences') or [] if ev.get('source') == 'PubMed'))


def uniprot_studies(e, via):
    """The studies the recorded statements cite, by PMID, once each, with the statements citing them."""
    out = {}
    for c in e.get('comments') or []:
        if c.get('commentType') not in UNIPROT_COMMENTS:
            continue
        for x in c.get('texts') or []:
            for pmid in evidence_pmids(x):
                w = out.setdefault(pmid, {'source_id': f'MED:{pmid}', 'pmid': pmid, 'relation': [], 'via': via,
                                          'licence': None, 'licence_from': None})
                if c['commentType'] not in w['relation']:
                    w['relation'].append(c['commentType'])
    return [dated(w) for w in out.values()]


# -- HAGR: GenAge, DrugAge -------------------------------------------------------------------------

def hagr_fetch(s, dataset):
    """Download a HAGR build as HAGR offers it: one logged record with the build, its release date, the
    archive's SHA-256 and the table's row count. The archive is kept with the responses."""
    path, member, header = HAGR_DATASETS[dataset]

    def run(responses):
        data = s.fetch(HAGR + path, responses)
        build, released, rows = hagr_read(data, member, header)
        return len(rows), [dated({'source_id': f'HAGR:{dataset}:build-{build}', 'dataset': dataset, 'build': build,
                                  'released': released, 'archive_sha256': search.sha256(data), 'url': HAGR + path,
                                  'rows': len(rows), **hagr_rights(dataset)}, release=released)], {
            'service': 'HAGR offered download'}
    return s.call('hagr_fetch', {'id': dataset, 'source': 'hagr'}, run)


def hagr_rights(dataset):
    return {'licence': HAGR_LICENCE, 'licence_from': HAGR_LICENCE_FROM,
            'attribution': f"Human Ageing Genomic Resources (HAGR), {'DrugAge' if dataset == 'drugage' else 'GenAge'}",
            'citation': DRUGAGE_CITATION if dataset == 'drugage' else HAGR_CITATION}


def hagr_read(data, member, header):
    """Build number, release date and rows of a HAGR archive. The build and date come from the archive's
    own release notes; a table without the known header, or a row of another width, is refused."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
        notes = archive.read('release.html').decode('utf-8', 'replace')
        table = archive.read(member).decode('utf-8')
    except (zipfile.BadZipFile, KeyError) as e:
        raise search.SearchError(f'not a HAGR build archive: {e}')
    notes = re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', notes)))
    build, released = re.search(r'Build (\d+)', notes), re.search(r'Release date: ([A-Z][a-z]+ \d{1,2}, \d{4})', notes)
    reader = csv.reader(io.StringIO(table))
    if next(reader, None) != header:
        raise search.SearchError(f'{member}: not the known header')
    rows = []
    for line in reader:
        if len(line) != len(header):
            raise search.SearchError(f'{member}: a row of {len(line)} fields, not {len(header)}')
        rows.append(dict(zip(header, line)))
    return build and build.group(1), released and released.group(1), rows


def hagr_build(s, dataset):
    """The build of dataset fetched last in this work directory, fetching it if there is none: (record of
    the fetch, rows). A kept archive whose hash no longer matches its record is refused."""
    path, member, header = HAGR_DATASETS[dataset]
    fetched = [r for r in search.read_log(s.workdir)
               if r['tool'] == 'hagr_fetch' and r['ask']['id'] == dataset and r['outcome'] == 'ok']
    record = fetched[-1] if fetched else hagr_fetch(s, dataset)
    if record['outcome'] != 'ok':
        raise search.SearchError(f"{dataset}: no build ({record['error']})")
    sha = record['works'][0]['archive_sha256']
    data = (s.workdir / search.RESPONSES / (sha.split(':')[1] + '.body')).read_bytes()
    if search.sha256(data) != sha:
        raise search.SearchError(f'{dataset}: the kept archive does not match {sha}')
    return record['works'][0], hagr_read(data, member, header)[2]


def genage(s, symbol):
    """A gene in GenAge, human genes and model-organism genes: one logged record, searched in the
    fetched builds. A symbol matches regardless of case, so MTOR finds the mouse Mtor too; an ortholog
    with another name (the worm let-363) is not found by it."""
    def run(responses):
        works, builds = [], []
        for dataset in ('genage_human', 'genage_models'):
            build, rows = hagr_build(s, dataset)
            builds.append(build['source_id'] + ' ' + build['archive_sha256'])
            works += [work_genage(dataset, r, build) for r in rows if r['symbol'].lower() == symbol.lower()]
        return len(works), works, {'service': 'HAGR GenAge, fetched builds searched locally', 'builds': builds}
    return s.call('genage', {'id': symbol, 'source': 'hagr'}, run)


def work_genage(dataset, r, build):
    w = {'source_id': f"GENAGE:{r['GenAge ID']}", 'dataset': dataset, 'symbol': r['symbol'], 'name': r['name'],
         'organism': r.get('organism', 'Homo sapiens'), 'ncbi_gene': r['entrez gene id'] or None}
    if dataset == 'genage_human':
        w |= {'uniprot': r['uniprot'] or None, 'why': [x for x in r['why'].split(',') if x]}
    else:
        w |= {'lifespan_effect': r['lifespan effect'] or None, 'longevity_influence': r['longevity influence'] or None,
              'max_lifespan_change_percent': r['avg lifespan change (max obsv)'] or None}
    return dated(w | {'build': build['source_id'], **hagr_rights(dataset)}, release=build['released'])


def drugage_compounds(s, build, rows):
    """Each compound name of a DrugAge build mapped to PubChem parent CIDs, once per build: the record
    of the mapping made last in this work directory, or a new one (about a thousand PubChem lookups).
    {name: set of CIDs}; a name PubChem does not find (a combination, a class) maps to none."""
    made = [r for r in search.read_log(s.workdir) if r['tool'] == 'pubchem_drugage'
            and r['ask']['id'] == build['source_id'] and r['outcome'] == 'ok']

    def run(responses):
        works = []
        for name in dict.fromkeys(r['compound_name'] for r in rows):
            cids, how = pubchem_parent(s, name, responses)
            works.append({'source_id': f'DRUGAGE-NAME:{name}', 'name': name, 'cids': cids, 'by': how})
        return len(works), works, {'service': 'PubChem PUG REST', 'build': build['source_id'],
                                   'unmatched': sum(not w['cids'] for w in works)}
    record = made[-1] if made else s.call('pubchem_drugage', {'id': build['source_id'], 'source': 'pubchem'}, run)
    if record['outcome'] != 'ok':
        raise search.SearchError(f"DrugAge names to PubChem: {record['error']}")
    return {w['name']: set(w['cids']) for w in record['works']}


def drugage(s, compound):
    """A compound's lifespan studies in DrugAge: one logged record, searched in the fetched build. A row
    is the compound's when its name is the one asked, or names the same PubChem parent compound
    (`matched_by`): DrugAge files a compound under one name (rapamycin, not sirolimus) and sometimes as a
    salt. Each row is one cohort: species, strain, sex, dose, age at start, duration, lifespan change and
    significance, and the study by PMID, which is also listed once as a lead."""
    def run(responses):
        build, rows = hagr_build(s, 'drugage')
        found = pubchem(s, compound)
        cids = {w['cid'] for w in found['works']}
        by_cid = drugage_compounds(s, build, rows) if cids else {}
        works, studies = [], {}
        for n, r in enumerate(rows, 2):
            if r['compound_name'].lower() == compound.lower():
                matched_by = 'name'
            elif by_cid.get(r['compound_name'], set()) & cids:
                matched_by = 'PubChem parent CID'
            else:
                continue
            works.append(dated({'source_id': f"DRUGAGE:{build['build']}:{n}", 'line': n,
                                **{k: v for k, v in r.items() if v not in ('', 'NA')}, 'matched_by': matched_by,
                                'build': build['source_id'], **hagr_rights('drugage')}, release=build['released']))
            if r['pubmed_id']:
                w = studies.setdefault(r['pubmed_id'], {'source_id': f"MED:{r['pubmed_id']}", 'pmid': r['pubmed_id'],
                                                         'relation': ['DrugAge cohorts'], 'cohorts': 0,
                                                         'via': f'DRUGAGE:{compound}', 'licence': None,
                                                         'licence_from': None})
                w['cohorts'] += 1
        return len(works), works + [dated(w, release=build['released']) for w in studies.values()], {
            'service': 'HAGR DrugAge, fetched build searched locally',
            'builds': [build['source_id'] + ' ' + build['archive_sha256']],
            'pubchem': {'call_id': found['call_id'], 'cids': sorted(cids)},
            'names_matched': sorted({w['compound_name'] for w in works})}
    return s.call('drugage', {'id': compound, 'source': 'hagr'}, run)


# -- Reactome --------------------------------------------------------------------------------------

def reactome_pathways(s, accession, species=9606):
    """The pathways of a species (human by default) in which a UniProt protein takes part, as Reactome
    maps them, with the Reactome release: one logged record."""
    def run(responses):
        release = s.fetch(REACTOME + 'data/database/version', responses).decode().strip()
        try:
            rows = s.json(REACTOME + f'data/mapping/UniProt/{urllib.parse.quote(accession)}/pathways?species={species}',
                          responses)
        except search.SearchError as e:
            if not_found(e, responses):
                return 0, [], {'service': 'Reactome ContentService mapping', 'release': release,
                               'note': f'no Reactome pathway for UniProt {accession}'}
            raise
        return len(rows), [work_reactome(r, release) for r in rows], {
            'service': 'Reactome ContentService mapping', 'release': release}
    return s.call('reactome_pathways', {'id': accession, 'source': 'reactome'}, run)


def reactome_pathway(s, stable_id):
    """A Reactome pathway or reaction: its name, version, summary and the studies it cites, by PMID."""
    def run(responses):
        try:
            d = s.json(REACTOME + 'data/query/' + urllib.parse.quote(stable_id), responses)
        except search.SearchError as e:
            if not_found(e, responses):
                return 0, [], {'service': 'Reactome ContentService query', 'note': f'no Reactome entry {stable_id}'}
            raise
        w = dated(work_reactome(d, None) | {'summary': [x['text'] for x in d.get('summation') or [] if x.get('text')],
                                            'in_disease': d.get('isInDisease'), 'released': d.get('releaseDate')},
                  since=d.get('releaseDate'))
        studies = [dated({'source_id': f"MED:{r['pubMedIdentifier']}", 'pmid': str(r['pubMedIdentifier']),
                          'title': r.get('displayName'), 'relation': ['Reactome literature reference'],
                          'via': w['source_id'], 'licence': None, 'licence_from': None})
                   for r in d.get('literatureReference') or [] if r.get('pubMedIdentifier')]
        return 1, [w] + studies, {'service': 'Reactome ContentService query'}
    return s.call('reactome_pathway', {'id': stable_id, 'source': 'reactome'}, run)


def work_reactome(r, release):
    """A pathway, dated from its first release: Reactome dates no change to it, nor a protein's place in it."""
    return dated({'source_id': f"REACTOME:{r['stId']}", 'stable_id': r['stId'], 'version': r.get('stIdVersion'),
            'name': r.get('displayName'), 'species': r.get('speciesName'), 'release': release,
            'url': REACTOME_PAGE + r['stId'], 'licence': REACTOME_LICENCE, 'licence_from': REACTOME_LICENCE_FROM},
                 since=r.get('releaseDate'))


# -- Open Targets ----------------------------------------------------------------------------------

OT_SEARCH = 'query($q:String!,$e:[String!]!){search(queryString:$q,entityNames:$e,page:{index:0,size:5}){hits{id name entity}}}'
OT_TARGET = ('query($id:String!,$n:Int!){target(ensemblId:$id){id approvedSymbol approvedName biotype '
             'associatedDiseases(page:{index:0,size:$n}){count rows{score disease{id name}}} '
             'drugAndClinicalCandidates{count rows{drug{id}}}}}')
OT_DRUG = 'query($id:String!){drug(chemblId:$id){id name mechanismsOfAction{rows{actionType}} indications{count}}}'


def opentargets(s, query, variables, responses):
    """The data of an Open Targets GraphQL query (a POST); an answer with errors is a failed call."""
    d = s.json(OPENTARGETS, responses, body={'query': query, 'variables': variables})
    if d.get('errors'):
        raise search.SearchError('Open Targets: ' + '; '.join(e.get('message', '')[:200] for e in d['errors']))
    return d['data']


def opentargets_id(s, name, entity, pattern, responses, first=False):
    """An identifier as given, or the one Open Targets' search finds for a name: its first hit of the
    entity whose name is the name, regardless of case; with first, else its first hit of the entity.
    None if there is none."""
    if re.fullmatch(pattern, name):
        return name
    hits = [h for h in opentargets(s, OT_SEARCH, {'q': name, 'e': [entity]}, responses)['search']['hits']
            if h['entity'] == entity]
    exact = [h for h in hits if h['name'].lower() == name.lower()]
    return (exact or (hits[:1] if first else [{'id': None}]))[0]['id']


def opentargets_target(s, name):
    """A target by Ensembl gene id or symbol: its diseases by association score (the first 25, and how
    many there are), Open Targets' own data; and the drugs and clinical candidates acting on it, which
    come from ChEMBL, by identifier and link only."""
    def run(responses):
        ensembl = opentargets_id(s, name, 'target', r'ENSG\d+', responses)
        t = ensembl and opentargets(s, OT_TARGET, {'id': ensembl, 'n': OPENTARGETS_DISEASES}, responses)['target']
        if not t:
            return 0, [], {'service': 'Open Targets GraphQL', 'note': f'no Open Targets target {name}'}
        assoc, drugs = t['associatedDiseases'], t['drugAndClinicalCandidates']
        w = {'source_id': f"ENSEMBL:{t['id']}", 'symbol': t['approvedSymbol'], 'name': t['approvedName'],
             'biotype': t['biotype'], 'diseases_count': assoc['count'],
             'diseases': [{'id': r['disease']['id'], 'name': r['disease']['name'], 'score': round(r['score'], 4)}
                          for r in assoc['rows']],
             'drugs_count': drugs['count'],
             'drugs': [{'id': r['drug']['id'], 'url': CHEMBL_PAGE + r['drug']['id']} for r in drugs['rows'] or []],
             'drugs_data_from': 'ChEMBL', 'drugs_licence': CHEMBL_LICENCE, 'drugs_licence_from': CHEMBL_LICENCE_FROM,
             'url': OPENTARGETS_PAGE + 'target/' + t['id'], 'licence': OPENTARGETS_LICENCE,
             'licence_from': OPENTARGETS_LICENCE_FROM, 'attribution': OPENTARGETS_ATTRIBUTION,
             'citation': OPENTARGETS_CITATION}
        return 1, [dated(w)], {'service': 'Open Targets GraphQL', 'withheld': {
            'drug names, stages and diseases': CHEMBL_LINK_ONLY}}
    return s.call('opentargets_target', {'id': name, 'source': 'opentargets'}, run)


def opentargets_drug(s, name):
    """A drug by ChEMBL id or name, as Open Targets' search finds it (rapamycin finds sirolimus): its
    identifier, preferred name, links, and how many mechanisms and indications Open Targets holds. The
    drug data come from ChEMBL and are recorded link only."""
    def run(responses):
        # The search names a drug by its preferred name: without an exact match, its first drug hit.
        chembl = opentargets_id(s, name, 'drug', r'CHEMBL\d+', responses, first=True)
        d = chembl and opentargets(s, OT_DRUG, {'id': chembl}, responses)['drug']
        if not d:
            return 0, [], {'service': 'Open Targets GraphQL', 'note': f'no Open Targets drug {name}'}
        w = {'source_id': d['id'], 'name': d['name'],
             'mechanisms_count': len((d.get('mechanismsOfAction') or {}).get('rows') or []),
             'indications_count': d['indications']['count'],
             'url': OPENTARGETS_PAGE + 'drug/' + d['id'], 'chembl_url': CHEMBL_PAGE + d['id'],
             'licence': None, 'licence_from': None, 'data_from': 'ChEMBL', 'data_licence': CHEMBL_LICENCE,
             'data_licence_from': CHEMBL_LICENCE_FROM}
        return 1, [dated(w)], {'service': 'Open Targets GraphQL',
                        'matched': d['name'] if d['name'].lower() != name.lower() else None,
                        'withheld': {'mechanisms, targets, stages, indications, synonyms': CHEMBL_LINK_ONLY}}
    return s.call('opentargets_drug', {'id': name, 'source': 'opentargets'}, run)


# -- Terms: MeSH, NCBI Taxonomy, Gene Ontology -------------------------------------------------------
# Each record holds the entry's preferred name and its other names in `synonyms`, so that a literature
# search can be widened with them; the search itself stays search.py's.

def mesh_terms(s, term):
    """The MeSH headings and supplementary concepts a term finds: each with its preferred heading, entry
    terms, tree numbers and the heading a concept is indexed under, and the NCBI MeSH build read. The
    heading the term maps to ([MH]) is read first, then the text search; a record whose terms include the
    term itself comes first. One logged record."""
    def run(responses):
        heading = s.json(s.eutils('esearch', {'db': 'mesh', 'term': f'"{term}"[MH]', 'retmax': 1}),
                         responses)['esearchresult'].get('idlist', [])
        found = s.json(s.eutils('esearch', {'db': 'mesh', 'term': term, 'retmax': 20}), responses)['esearchresult']
        ids = list(dict.fromkeys(heading + found.get('idlist', [])))
        if not ids:
            return 0, [], {'service': 'NCBI E-utilities esearch+esummary (mesh)'}
        result = s.json(s.eutils('esummary', {'db': 'mesh', 'id': ','.join(ids)}), responses)['result']
        works = [work_mesh(result[u]) for u in result.get('uids', [])]
        info = s.json(s.eutils('einfo', {'db': 'mesh'}), responses)['einforesult']['dbinfo'][0]
        for w, u in zip(works, result.get('uids', [])):
            w['release'], w['release_date'] = info.get('dbbuild'), info.get('lastupdate')
            # MeSH's year introduced is absent for some headings and not always the first (Osteoarthritis
            # reads 2013): recorded, not taken as a date. Its entry and revision dates read 1/01/01.
            w['year_introduced'] = result[u].get('ds_yearintroduced') or None
            dated(w, release=info.get('lastupdate'))
        works.sort(key=lambda w: term.lower() not in (x.lower() for x in [w['heading']] + w['synonyms']))
        return int(found.get('count', 0)), works[:TERMS_READ], {'service': 'NCBI E-utilities esearch+esummary (mesh)'}
    return s.call('mesh_terms', {'id': term, 'source': 'mesh'}, run)


def work_mesh(r):
    terms, ui = r.get('ds_meshterms') or [], r.get('ds_meshui')
    w = {'source_id': f'MESH:{ui}', 'ui': ui, 'kind': 'heading' if ui.startswith('D') else 'concept',
         'heading': terms[0] if terms else None, 'synonyms': terms[1:],
         'tree_numbers': [x['treenum'] for x in r.get('ds_idxlinks') or [] if x.get('treenum')],
         'indexed_under': [x if isinstance(x, str) else x.get('heading') for x in r.get('ds_headingmappedtolist') or []] or None,
         'scope_note': (r.get('ds_scopenote') or '').strip() or None, 'url': MESH_PAGE + ui,
         'licence': MESH_TERMS, 'licence_from': MESH_TERMS_FROM,
         'attribution': 'Medical Subject Headings (MeSH), U.S. National Library of Medicine'}
    if w['kind'] == 'heading' and w['heading']:
        w['pubmed_query'] = f'"{w["heading"]}"[MeSH Terms]'
    return w


TAXON_IDS = r'(?:NCBITaxon:)?\d+(?:,(?:NCBITaxon:)?\d+)*'


def taxonomy(s, name):
    """An organism in NCBI Taxonomy by name, by id (9031 or NCBITaxon:9031) or by ids separated by commas:
    its scientific name, rank, lineage with the id and rank of each node, other names (common names,
    synonyms, former names) and its rung of closeness to humans (`proximity`). One logged record."""
    def run(responses):
        if re.fullmatch(TAXON_IDS, name):
            ids = [x.split(':')[-1] for x in name.split(',')]
            count = len(ids)
        else:
            found = s.json(s.eutils('esearch', {'db': 'taxonomy', 'term': name, 'retmax': TERMS_READ}),
                           responses)['esearchresult']
            ids, count = found.get('idlist', []), int(found.get('count', 0))
        if not ids:
            return 0, [], {'service': 'NCBI E-utilities efetch (taxonomy)'}
        url = search.EUTILS + 'efetch.fcgi?' + urllib.parse.urlencode({'db': 'taxonomy', 'id': ','.join(ids),
                                                                        'tool': 'ohf-extractor'})
        taxa = ET.fromstring(s.fetch(url, responses)).findall('Taxon')
        return count, [work_taxon(x) for x in taxa], {'service': 'NCBI E-utilities efetch (taxonomy)'}
    return s.call('taxonomy', {'id': name, 'source': 'ncbi taxonomy'}, run)


# How close an organism is to humans (OHF human_proximity, the taxon's part), from its NCBI lineage by
# taxon id: the first rule that holds. An organism outside Metazoa is not an invertebrate: no rung.
HUMAN_TAXON = '9606'
PROXIMITY = (('40674', 'Mammalia', 'mammal'), ('7742', 'Vertebrata', 'non_mammal_vertebrate'),
             ('33208', 'Metazoa', 'invertebrate'))


def proximity(tax, lineage):
    """(rung, by) of a taxon from its lineage [{id, name, rank}]: human for Homo sapiens itself, then
    PROXIMITY; (None, 'not an animal') outside Metazoa."""
    if tax == HUMAN_TAXON:
        return 'human', f'NCBITaxon:{HUMAN_TAXON} Homo sapiens'
    ids = {x['id'] for x in lineage} | {f'NCBITaxon:{tax}'}
    for node, name, rung in PROXIMITY:
        if f'NCBITaxon:{node}' in ids:
            return rung, f'NCBITaxon:{node} {name}'
    return None, 'not an animal'


def work_taxon(x):
    names = []
    for n in x.find('OtherNames') if x.find('OtherNames') is not None else []:
        if n.tag == 'Name':
            if n.findtext('ClassCDE') not in TAXONOMY_NOT_NAMES and n.findtext('DispName'):
                names.append(n.findtext('DispName').strip())
        elif n.tag not in TAXONOMY_NOT_NAMES and (n.text or '').strip():
            names.append(n.text.strip())
    tax = x.findtext('TaxId')
    lineage = [{'id': f"NCBITaxon:{n.findtext('TaxId')}", 'name': n.findtext('ScientificName'), 'rank': n.findtext('Rank')}
               for n in (x.find('LineageEx') if x.find('LineageEx') is not None else [])]
    rung, by = proximity(tax, lineage)
    # The taxon's public date, and its last update, which dates every name in it.
    return dated({'source_id': f'NCBITAXON:{tax}', 'taxon': tax, 'scientific_name': x.findtext('ScientificName'),
            'rank': x.findtext('Rank'), 'division': x.findtext('Division'), 'synonyms': list(dict.fromkeys(names)),
            'lineage': x.findtext('Lineage'), 'lineage_ids': lineage, 'proximity': rung, 'proximity_by': by,
            'url': TAXONOMY_PAGE + tax,
            'licence': NCBI_TERMS, 'licence_from': NCBI_TERMS_FROM},
                 since=x.findtext('PubDate'), every=x.findtext('UpdateDate'))


def go_terms(s, term):
    """Gene Ontology terms by id or by text: each with its name, aspect, definition and synonyms (with
    their type: exact, narrow, broad, related), and the GO release read. A text search looks at QuickGO's
    first 25 terms and keeps five, a term named exactly (by name or exact synonym) first."""
    def run(responses):
        if re.fullmatch(r'GO:\d{7}', term):
            ids, count = [term], None
        else:
            found = s.json(QUICKGO + 'search?' + urllib.parse.urlencode({'query': term, 'limit': GO_SEARCHED}),
                           responses)
            ids, count = [r['id'] for r in found.get('results', [])], found.get('numberOfHits', 0)
        if not ids:
            return 0, [], {'service': 'QuickGO ontology'}
        try:
            rows = s.json(QUICKGO + 'terms/' + ','.join(ids), responses).get('results', [])
        except search.SearchError as e:
            if not_found(e, responses):
                return 0, [], {'service': 'QuickGO ontology', 'note': f'no GO term {term}'}
            raise
        # QuickGO answers terms/ in its own order: the search's order is kept.
        works = [work_go(r) for r in sorted(rows, key=lambda r: ids.index(r['id']) if r['id'] in ids else len(ids))]
        named = lambda w: term.lower() in [w['name'].lower()] + [  # noqa: E731
            n.lower() for n, t in w['synonym_types'].items() if t == 'exact']
        works = sorted(works, key=lambda w: not named(w))[:TERMS_READ]
        if works:
            about = s.json(QUICKGO + 'about', responses)['go']
            for w in works:
                w['release'], w['release_date'] = about.get('timestamp'), about.get('timestamp')
                dated(w, release=about.get('timestamp'))
        return len(rows) if count is None else count, works, {'service': 'QuickGO ontology'}
    return s.call('go_terms', {'id': term, 'source': 'gene ontology'}, run)


def work_go(r):
    syn = r.get('synonyms') or []
    return {'source_id': r['id'], 'name': r['name'], 'aspect': r.get('aspect'), 'obsolete': r.get('isObsolete'),
            'definition': (r.get('definition') or {}).get('text'), 'synonyms': [x['name'] for x in syn],
            'synonym_types': {x['name']: x.get('type') for x in syn}, 'url': GO_PAGE + r['id'],
            'licence': GO_LICENCE, 'licence_from': GO_LICENCE_FROM,
            'attribution': 'Gene Ontology Consortium, CC BY 4.0'}


# -- ChEMBL: link only ---------------------------------------------------------------------------------
# ChEMBL is CC BY-SA 3.0, which a CC BY card cannot carry: a record holds the compound's identifier, its
# preferred name, links and counts, and the release read; structures, synonyms, phases, mechanisms,
# indications and activities stay in ChEMBL, behind the link.

def chembl(s, name):
    """A compound in ChEMBL by id or name (a name finds it through its synonyms: rapamycin finds
    sirolimus): its id, preferred name, links, how many mechanisms, indications and activity records
    ChEMBL holds for it, and the ChEMBL release. One logged record."""
    def run(responses):
        fields = 'molecule_chembl_id,pref_name'
        if re.fullmatch(r'CHEMBL\d+', name):
            try:
                found, count = [s.json(f'{CHEMBL}molecule/{name}.json?only={fields}', responses)], 1
            except search.SearchError as e:
                if not_found(e, responses):
                    return 0, [], {'service': 'ChEMBL web services', 'note': f'no ChEMBL compound {name}'}
                raise
        else:
            page = s.json(CHEMBL + 'molecule/search.json?' + urllib.parse.urlencode(
                {'q': name, 'limit': CHEMBL_READ, 'only': fields}), responses)
            found, count = page['molecules'], page['page_meta']['total_count']
        if not found:
            return 0, [], {'service': 'ChEMBL web services'}
        status = s.json(CHEMBL + 'status.json', responses)
        works = [work_chembl(s, m, status, responses) for m in found]
        return count, works, {'service': 'ChEMBL web services',
                              'withheld': {'structures, synonyms, phase, mechanisms, indications, activities':
                                           CHEMBL_LINK_ONLY}}
    return s.call('chembl', {'id': name, 'source': 'chembl'}, run)


def work_chembl(s, m, status, responses):
    cid = m['molecule_chembl_id']
    def total(resource):
        q = urllib.parse.urlencode({'molecule_chembl_id': cid, 'limit': 1, 'only': 'molecule_chembl_id'})
        return s.json(f'{CHEMBL}{resource}.json?{q}', responses)['page_meta']['total_count']
    return dated({'source_id': cid, 'name': m.get('pref_name'), 'url': CHEMBL_PAGE + cid,
            'mechanisms_count': total('mechanism'), 'indications_count': total('drug_indication'),
            'activities_count': total('activity'),
            'release': status.get('chembl_db_version'), 'release_date': status.get('chembl_release_date'),
            'licence': None, 'licence_from': None, 'data_from': 'ChEMBL', 'data_licence': CHEMBL_LICENCE,
            'data_licence_from': CHEMBL_LICENCE_FROM}, release=status.get('chembl_release_date'))


# -- PubChem: a compound by its parent -------------------------------------------------------------
# A name finds a PubChem compound, and its parent stands for it: a salt or a hydrate is the compound
# (metformin hydrochloride is metformin, quercetin dihydrate quercetin). Not where the metal is the active
# part: the parent of zinc acetate is acetic acid, so a name with such a metal keeps its own compound
# (the rule of hyp-arena's compounds.py, MIT). A record holds identifiers, the preferred name and short
# synonyms (names, for matching), under NCBI's terms; no property or deposited text.
ACTIVE_METAL = re.compile(
    r'\b(?:lithium|beryllium|barium|strontium|zinc|cupric|cuprous|copper|ferric|ferrous|iron|nickel\w*|cobalt\w*|'
    r'mangan\w*|cadmium|(?:methyl)?mercur\w*|lead|alumin\w*|silver|gold|chrom\w*|vanad\w*|selen\w*|tin|stannous|'
    r'platinum|palladium|ruthenium|bismuth|molybd\w*|tungst\w*|arsen\w*|antimony|thallium|c(?:a)?esium|rubidium|'
    r'titanium)\b', re.I)
# How many synonyms a record keeps, of at most PUBCHEM_NAME characters (systematic names are left out).
PUBCHEM_SYNONYMS, PUBCHEM_NAME = 50, 60


def pubchem_cids(s, path, responses):
    """The CIDs PubChem answers for path, or [] when it finds none (404) or cannot read the name (400)."""
    try:
        return s.json(PUBCHEM + path, responses).get('IdentifierList', {}).get('CID') or []
    except search.SearchError:
        if responses and responses[-1]['status'] in (400, 404):
            return []
        raise


def pubchem_parent(s, name, responses):
    """(parent CIDs, how) of a name: 'parent'; 'own: active metal' when a metal in the name is the
    active part; 'own: no parent' when PubChem has none (an inorganic salt); ([], None) for no compound."""
    q = urllib.parse.quote(name.strip(), safe='')
    if ACTIVE_METAL.search(name):
        own = pubchem_cids(s, f'name/{q}/cids/JSON', responses)
        return own, 'own: active metal' if own else None
    parent = pubchem_cids(s, f'name/{q}/cids/JSON?cids_type=parent', responses)
    if parent:
        return parent, 'parent'
    own = pubchem_cids(s, f'name/{q}/cids/JSON', responses)
    return own, 'own: no parent' if own else None


def pubchem(s, name):
    """A compound by name in PubChem: the CIDs the name finds, the parent each stands for (see
    ACTIVE_METAL), and for each parent its preferred name, InChIKey, formula and short synonyms. One
    logged record."""
    def run(responses):
        q = urllib.parse.quote(name.strip(), safe='')
        own = pubchem_cids(s, f'name/{q}/cids/JSON', responses)
        if not own:
            return 0, [], {'service': 'PubChem PUG REST', 'note': f'no PubChem compound named {name}'}
        parents, how = pubchem_parent(s, name, responses)
        ids = ','.join(map(str, parents[:TERMS_READ]))
        props = s.json(PUBCHEM + f'cid/{ids}/property/Title,InChIKey,MolecularFormula/JSON',
                       responses)['PropertyTable']['Properties']
        syn = {x['CID']: x.get('Synonym') or [] for x in s.json(PUBCHEM + f'cid/{ids}/synonyms/JSON',
                                                                 responses)['InformationList']['Information']}
        works = [work_pubchem(p, syn.get(p['CID'], []), name, own) for p in props]
        return len(parents), works, {'service': 'PubChem PUG REST', 'name_cids': own, 'parent_by': how}
    return s.call('pubchem', {'id': name, 'source': 'pubchem'}, run)


def work_pubchem(p, synonyms, name, own):
    cid = p['CID']
    short = [x for x in synonyms if len(x) <= PUBCHEM_NAME]
    return dated({'source_id': f'PUBCHEM.COMPOUND:{cid}', 'cid': cid, 'name': p.get('Title'),
                  'inchikey': p.get('InChIKey'), 'formula': p.get('MolecularFormula'),
                  'found_by': name, 'collapsed_from': [c for c in own if c != cid] or None,
                  'synonyms': short[:PUBCHEM_SYNONYMS], 'synonyms_count': len(synonyms),
                  'url': PUBCHEM_PAGE + str(cid), 'licence': NCBI_TERMS, 'licence_from': NCBI_TERMS_FROM})


# -- GEO: series metadata and links ----------------------------------------------------------------------
# A series is a lead to data, not data: the record holds what GEO lists about it and where it is. The
# submitters' summary and sample titles are not recorded, as with NCBI Gene's summary.

def geo(s, query):
    """GEO series (GSE) for a query or an accession, through E-utilities: each with its title,
    organism, type, number of samples, platforms, release date, the PubMed ids that describe it, and links
    to its page and files. The first twenty are read, in GEO's order. One logged record."""
    def run(responses):
        term = f'{query}[ACCN]' if re.fullmatch(r'GSE\d+', query) else f'({query})'
        found = s.json(s.eutils('esearch', {'db': 'gds', 'term': term + ' AND gse[ETYP]', 'retmax': GEO_READ}),
                       responses)['esearchresult']
        ids = found.get('idlist', [])
        if not ids:
            return 0, [], {'service': 'NCBI E-utilities esearch+esummary (gds)'}
        result = s.json(s.eutils('esummary', {'db': 'gds', 'id': ','.join(ids)}), responses)['result']
        return int(found.get('count', 0)), [work_geo(result[u]) for u in result.get('uids', [])], {
            'service': 'NCBI E-utilities esearch+esummary (gds)', 'withheld': {
                'summary, sample titles': 'submitted text, which may carry its own rights'}}
    return s.call('geo', {'id': query, 'source': 'geo'}, run)


def work_geo(r):
    acc = r['accession']
    # GEO's summary dates a series' release, not a later change to it (a PubMed id added, say).
    return dated({'source_id': f'GEO:{acc}', 'accession': acc, 'title': r.get('title'), 'organism': r.get('taxon'),
            'type': r.get('gdstype'), 'samples_count': r.get('n_samples'),
            'platforms': [f'GPL{x}' for x in (r.get('gpl') or '').split(';') if x],
            'released': r.get('pdat'), 'pmids': [str(x) for x in r.get('pubmedids') or []],
            'bioproject': r.get('bioproject') or None, 'url': GEO_PAGE + acc, 'files': r.get('ftplink') or None,
            'licence': NCBI_TERMS, 'licence_from': NCBI_TERMS_FROM}, since=r.get('pdat'))


TAXA_SCHEMA = 'ohf-extractor:taxa@1'


def taxa_rows(records):
    """Rows for taxa.json beside a card, in the shape of ohf:terms@1 taxa ({id, label, proximity}) with
    where each comes from: one per asked taxon that is one NCBI Taxonomy entry (an id, or a name naming
    exactly one taxon); a name naming several is listed in `ambiguous`, not chosen."""
    rows, ambiguous = {}, []
    for r in records:
        works = r['works']
        if len(works) > 1 and not re.fullmatch(TAXON_IDS, r['ask']['id']):
            named = [w for w in works if r['ask']['id'].casefold() in
                     [x.casefold() for x in [w['scientific_name']] + (w['synonyms'] or []) if x]]
            if len(named) != 1:
                ambiguous.append({'asked': r['ask']['id'], 'taxa': [f"NCBITaxon:{w['taxon']}" for w in works]})
                continue
            works = named
        for w in works:
            rows[w['taxon']] = {'id': f"NCBITaxon:{w['taxon']}", 'label': w['scientific_name'],
                                'proximity': w['proximity'], 'by': w['proximity_by'], 'rank': w['rank'],
                                'call_id': r['call_id'], 'taxonomy_updated': w['dates']['fields'].get('lineage')}
    return {'schema': TAXA_SCHEMA, 'taxa': list(rows.values()), 'ambiguous': ambiguous}


# -- Proximity to humans of a card's evidence lines (OHF 1.1 human_proximity) -------------------
# The rung is the standard's to derive, not the kit's: check_refs.derived_proximity of the checkout
# given, with its pinned taxon table and the rows of taxa.json, run in that checkout's tools. A line
# gets a value only where that derivation gives exactly one rung; otherwise a gap that says why, and
# never a default. A value the line already declares is left as it is and compared.

PROXIMITY_STATED = ('in_vitro', 'ex_vivo')
DERIVE = """
import json, sys
sys.path.insert(0, sys.argv[1] + '/tools')
import check_refs
lines, extra = json.load(sys.stdin)
terms = check_refs.load(check_refs.ROOT / 'vocabularies/terms-1.json')
table = {r['id']: r['proximity'] for r in terms['taxa']}
for r in extra:
    table.setdefault(r['id'], r.get('proximity'))
known = {i: p for i, p in table.items() if p is not None}
out = [check_refs.derived_proximity(line, known) for line in lines]
print(json.dumps({'derived': [sorted(d) if d is not None else None for d in out],
                  'pinned': {i: table[i] for i in table if i in {r['id'] for r in terms['taxa']}},
                  'stated_only': sorted(check_refs.STATED_ONLY)}))
"""


def standard_run(standard, script, *args, stdin=None):
    """Run python in the standard checkout's own tools, isolated from the kit's modules."""
    r = subprocess.run([sys.executable, '-I', '-c', script, str(standard), *map(str, args)], input=stdin,
                       capture_output=True, text=True)
    if r.returncode not in (0, 1) or not r.stdout.strip():
        raise RuntimeError(f'the standard at {standard} failed: {r.stderr.strip()[-800:]}')
    return r.stdout


def standard_version(standard):
    """The release a checkout holds; the derivation needs OHF 1.1 or later."""
    version = (Path(standard) / 'VERSION').read_text().strip()
    if not re.fullmatch(r'1\.(?:[1-9]|\d{2,})\.\d+', version):
        raise SystemExit(f'{standard} holds OHF {version}: human_proximity needs a checkout of OHF 1.1 or later')
    return version


def _val(node):
    return node.get('value') if isinstance(node, dict) else node


def proximity_values(card, standard, taxa=None):
    """Per added-zone evidence line: the human_proximity the standard derives from its system.taxon_id and
    endpoint kind, with the src of the taxon id; or a gap with the reason it cannot be derived."""
    if card.get('standard_version') != '1.1':
        raise SystemExit('human_proximity is an OHF 1.1 member; this card is ' + str(card.get('standard_version')))
    lines = card['added']['layers'].get('evidence', {}).get('lines', [])
    extra = (taxa or {}).get('taxa', [])
    got = json.loads(standard_run(standard, DERIVE, stdin=json.dumps([lines, extra])))
    pinned = got['pinned']
    rows = {r['id']: r for r in extra}
    out = []
    for i, (line, derived) in enumerate(zip(lines, got['derived'])):
        system = line.get('system') if isinstance(line.get('system'), dict) else {}
        taxon_id, kind = system.get('taxon_id'), line.get('endpoint_kind')
        term = kind.get('term') if isinstance(kind, dict) else None
        declared = _val(line.get('human_proximity'))
        v = {'pointer': f'/added/layers/evidence/lines/{i}', 'line': line.get('id'), 'taxon_id': _val(taxon_id),
             'endpoint_kind': term, 'declared': declared}
        rungs = sorted(set(derived) - set(got['stated_only'])) if derived is not None else []
        if declared in PROXIMITY_STATED:
            v |= {'value': declared, 'by': 'stated: in vitro and ex vivo are taken as stated'}
        elif len(rungs) == 1:
            ident = _val(taxon_id)
            v |= {'value': rungs[0], 'src': taxon_id['src'],
                  'by': ('pinned table of the standard' if ident in pinned else
                         f"taxa.json row (call {rows.get(ident, {}).get('call_id')}): a warning, not an error, if it differs")
                  + (f', endpoint kind {term}' if rungs[0].startswith('human') else '')}
        else:
            taxon = _val(system.get('taxon'))
            if not system:
                why = 'the line states no system'
            elif taxon_id is None:
                why = (f'the line names no one taxon by id (system.taxon {taxon!r}): without system.taxon_id '
                       'the standard derives no rung')
            elif _val(taxon_id) not in pinned and _val(taxon_id) not in rows:
                why = f'{_val(taxon_id)} is in neither the pinned taxon table nor taxa.json'
            elif rows.get(_val(taxon_id), {}).get('proximity', '') is None and _val(taxon_id) not in pinned:
                why = f"{_val(taxon_id)} has no rung: {rows[_val(taxon_id)].get('by')}"
            else:
                why = (f'a human line with endpoint kind {term or "none"}: the standard determines the human rung only '
                       'from biomarker, physiological or molecular (marker) and lifespan, mortality, function, disease '
                       'or adverse_event (clinical)')
            v |= {'value': None, 'gap': {'path': f'evidence.lines[{i}].human_proximity', 'disposition': 'not_supplied',
                                         'reason': f'Not derived: {why}. No rung is given by default.',
                                         'query_ids': [], 'inspected_artifacts': []}}
        if declared is not None and v.get('value') is not None and declared != v['value']:
            v['disagrees'] = f'the line declares {declared}, the derivation gives {v["value"]}: left as declared'
        out.append(v)
    return out


CONTENT_HASH = """
import json, sys
sys.path.insert(0, sys.argv[1] + '/tools')
import content_hash
print(content_hash.content_hash(json.load(sys.stdin)))
"""
CHECK_REFS = """
import json, sys
sys.path.insert(0, sys.argv[1] + '/tools')
from pathlib import Path
import check_refs
taxa = check_refs.load(Path(sys.argv[3]))['taxa'] if len(sys.argv) > 3 else None
print(json.dumps(check_refs.check(check_refs.load(Path(sys.argv[2])), taxa)))
"""


def place_proximity(card, values):
    """The card with each derived value set where the line has none, and a gap where it is not derived
    and no gap is there yet; a declared value is never changed."""
    card = json.loads(json.dumps(card))
    lines = card['added']['layers']['evidence']['lines']
    gaps = card['added'].setdefault('gaps', [])
    paths = {g['path'] for g in gaps}
    placed = {'values': 0, 'gaps': 0, 'kept': 0}
    for i, v in enumerate(values):
        if v['declared'] is not None:
            placed['kept'] += 1
        elif v.get('value') is not None:
            lines[i]['human_proximity'] = {'value': v['value'], 'src': v['src']}
            placed['values'] += 1
        elif v['gap']['path'] not in paths:
            gaps.append(v['gap'])
            placed['gaps'] += 1
    return card, placed


def card_proximity(card_path, standard, taxa_path=None, out=None):
    """biodb.py proximity: the values and gaps; with out, the card with them placed, rehashed and checked by
    the standard's check_refs (its REF_PROXIMITY_* issues reported)."""
    version = standard_version(standard)
    card = json.loads(Path(card_path).read_text())
    taxa = json.loads(Path(taxa_path).read_text()) if taxa_path else None
    values = proximity_values(card, standard, taxa)
    report = {'standard': version, 'lines': values}
    if out:
        placed, counts = place_proximity(card, values)
        placed['content_hash'] = standard_run(standard, CONTENT_HASH, stdin=json.dumps(placed)).strip()
        Path(out).write_text(json.dumps(placed, ensure_ascii=False, indent=2) + '\n')
        checked = json.loads(standard_run(standard, CHECK_REFS, Path(out).resolve(),
                                          *([Path(taxa_path).resolve()] if taxa_path else [])))
        report |= {'placed': counts, 'out': str(out), 'content_hash': placed['content_hash'],
                   'check_refs': {'valid': checked['valid'],
                                  'proximity': [x for x in checked['errors'] + checked['warnings']
                                                if x['code'].startswith('REF_PROXIMITY')]}}
    return report


# -- The taxon id of a card's evidence lines (OHF 1.1 system.taxon_id) ----------------------------
# The NCBI Taxonomy id of the taxon a line's system names, of any rank (OHF 1.1 field catalogue: "the
# taxon named in taxon"). The word asked is the line's system.taxon, or the converter's reading of it
# (a scientific name or an NCBITaxon id). It is placed only when it is exactly one taxon: its id, or its
# scientific name or one of its NCBI common names, matched whole, with no other taxon so named. Otherwise
# the line gets a gap that names the lookup: an informal group ("amphibians and reptiles"), a name of
# two taxa, a list of species. A word of the line that matches a taxon only by a common name is not
# placed but put to the converter, who confirms it in the reading: NCBI gives "humans" to the genus
# Homo and "flies" to the order Diptera, so the line's word alone would make a human line a mammal one.

def taxon_source(record, row):
    """The added.sources entry of a taxon from its call: the efetch that read it, when, and the call."""
    fetched = [x for x in record['responses'] if 'efetch.fcgi' in x['url']][-1]
    return {'source': fetched['url'], 'locator': f"NCBI Taxonomy: {row['label']} ({row['id']})",
            'accessed_at': fetched['at'], 'tool': f"biodb.py taxon-ids ({record['kit']}), call {record['call_id']}"}


def named_exactly(asked, works, common=True):
    """The taxa that asked names whole: by id, or as scientific name or (with common) an NCBI common
    name or synonym, case aside."""
    if re.fullmatch(TAXON_IDS, asked) and ',' not in asked:
        return [w for w in works if w['taxon'] == asked.split(':')[-1]]
    key = ' '.join(asked.split()).casefold()
    return [w for w in works if key in {x.casefold() for x in [w['scientific_name']] + (w['synonyms'] if common else [])
                                        if x}]


def taxon_ids(s, card, reading=None):
    """Per line with a system and no taxon id (or named in reading {line id: word or NCBITaxon id}): the
    taxon id to place with its source, or the gap that says why not."""
    if card.get('standard_version') != '1.1':
        raise SystemExit('system.taxon_id is an OHF 1.1 member; this card is ' + str(card.get('standard_version')))
    lines = card['added']['layers'].get('evidence', {}).get('lines', [])
    index = {line.get('id'): i for i, line in enumerate(lines)}
    reading = reading or {}
    unknown = sorted(set(reading) - set(index))
    if unknown:
        raise SystemExit(f'the reading names lines the card does not have: {unknown}')
    calls, out = {}, []
    for i, line in enumerate(lines):
        system = line.get('system') if isinstance(line.get('system'), dict) else None
        declared = _val(system.get('taxon_id')) if system else None
        if line.get('id') not in reading and (system is None or declared is not None or not _val(system.get('taxon'))):
            continue
        asked = reading.get(line.get('id')) or _val(system.get('taxon')) if system else reading.get(line.get('id'))
        v = {'pointer': f'/added/layers/evidence/lines/{i}', 'line': line.get('id'), 'asked': asked,
             'taxon': _val(system.get('taxon')) if system else None, 'declared': declared}
        if system is None:
            out.append(v | {'value': None, 'why': 'the line states no system to hold a taxon id'})
            continue
        if asked not in calls:
            calls[asked] = taxonomy(s, asked)
        record = calls[asked]
        v['call_id'] = record['call_id']
        gap = {'path': f'evidence.lines[{i}].system.taxon_id', 'query_ids': [record['call_id']], 'inspected_artifacts': []}
        if record['outcome'] != 'ok':
            out.append(v | {'value': None, 'gap': gap | {'disposition': 'blocked', 'reason': (
                f"The NCBI Taxonomy lookup of {asked!r} failed ({record.get('error')}); no taxon id is given.")}})
            continue
        read = line.get('id') in reading
        named = named_exactly(asked, record['works'], common=read)
        by_common = [] if read or named else named_exactly(asked, record['works'])
        if len(by_common) == 1:
            w = by_common[0]
            out.append(v | {'value': None, 'candidate': f"NCBITaxon:{w['taxon']}", 'why': (
                f"{asked!r} is an NCBI common name of {w['scientific_name']} (NCBITaxon:{w['taxon']}, {w['rank']}), "
                'not its scientific name: confirm it, or name the taxon meant, in the reading')})
            continue
        named = named or by_common
        if len(named) != 1:
            found = ', '.join(f"{w['scientific_name']} (NCBITaxon:{w['taxon']}, {w['rank']})" for w in
                              (named or record['works'])[:5])
            why = (f'{asked!r} names {len(named)} taxa of NCBI Taxonomy: {found}' if named else
                   f'{asked!r} is no name of one NCBI Taxonomy taxon' + (f'; the search found {found}' if found else ''))
            out.append(v | {'value': None, 'gap': gap | {'disposition': 'searched_not_found', 'reason': (
                f'{why}. A group the words do not name as one taxon gets no id.')}})
            continue
        work = named[0]
        row = taxa_rows([record | {'works': [work], 'ask': {'id': f"NCBITaxon:{work['taxon']}"}}])['taxa'][0]
        v |= {'value': row['id'], 'src': f"biodb_{record['call_id']}", 'label': row['label'], 'rank': work['rank'],
              'source': taxon_source(record, row), 'row': row}
        if declared is not None and declared != row['id']:
            v['disagrees'] = f"the line declares {declared}, the lookup gives {row['id']}: left as declared"
        out.append(v)
    return out


def place_taxon_ids(card, values):
    """The card with each looked-up id set where the line has none, its call among added.sources, and
    each gap not already there; a declared id is never changed."""
    card = json.loads(json.dumps(card))
    lines = card['added']['layers']['evidence']['lines']
    sources = card['added'].setdefault('sources', {})
    gaps = card['added'].setdefault('gaps', [])
    paths = {g['path'] for g in gaps}
    placed = {'values': 0, 'gaps': 0, 'kept': 0, 'not_placed': 0}
    for v in values:
        i = int(v['pointer'].rsplit('/', 1)[1])
        if v['declared'] is not None:
            placed['kept'] += 1
        elif v.get('value'):
            lines[i]['system']['taxon_id'] = {'value': v['value'], 'src': v['src']}
            sources.setdefault(v['src'], v['source'])
            gaps[:] = [g for g in gaps if g['path'] != f'evidence.lines[{i}].system.taxon_id']  # a value answers it
            placed['values'] += 1
        elif v.get('gap') and v['gap']['path'] not in paths:
            gaps.append(v['gap'])
            placed['gaps'] += 1
        else:
            placed['not_placed'] += 1
    return card, placed


def card_taxon_ids(s, card_path, reading_path, standard=None, out=None, taxa_out=None):
    """biodb.py taxon-ids: the values; with taxa_out the rows for --taxa; with out the card with them
    placed, rehashed by the standard."""
    card = json.loads(Path(card_path).read_text())
    values = taxon_ids(s, card, json.loads(Path(reading_path).read_text()) if reading_path else None)
    report = {'lines': [{k: x for k, x in v.items() if k not in ('source', 'row')} for v in values]}
    if taxa_out:
        rows = {v['row']['id']: v['row'] for v in values if v.get('row')}
        Path(taxa_out).write_text(json.dumps({'schema': TAXA_SCHEMA, 'taxa': list(rows.values()), 'ambiguous': []},
                                             ensure_ascii=False, indent=1) + '\n')
    if out:
        if not standard:
            raise SystemExit('--out rehashes the card by the standard: give --standard DIR')
        standard_version(standard)
        placed, counts = place_taxon_ids(card, values)
        placed['content_hash'] = standard_run(standard, CONTENT_HASH, stdin=json.dumps(placed)).strip()
        Path(out).write_text(json.dumps(placed, ensure_ascii=False, indent=2) + '\n')
        report |= {'placed': counts, 'out': str(out), 'content_hash': placed['content_hash']}
    return report


# -- Hallmarks of ageing: hints, not hallmarks ---------------------------------------------------
# Which of the twelve hallmarks of ageing (Lopez-Otin 2023) a gene's database terms suggest, through a
# pinned table whose every row names its source: Open Genes' ageing mechanisms by id, and GO processes
# its annotations map to. A hint gives its reason and a link, and assigns nothing: the converter sets a
# card's hallmark from the card's text, with its atoms. A term in no row of the table suggests none.

HALLMARKS_MAP = 'references/hallmarks-map.json'
# The table's hash, here so that the rules hash (which reads scripts, not JSON) changes with the table.
HALLMARKS_MAP_SHA256 = 'sha256:cc07d06f8c004effb30b49a09ac77eb9d72c700c4c83a7086d5fd8c58ae0757a'
HALLMARK_HINTS = 'ohf-extractor:hallmark-hints@1'
QUICKGO_ANNOTATIONS = 'https://www.ebi.ac.uk/QuickGO/services/annotation/search?'
GO_ANNOTATIONS_PAGE = 'https://www.ebi.ac.uk/QuickGO/annotations?'
# QuickGO maps an annotation to a term of the table by these relations: a gene annotated to "negative
# regulation of macroautophagy" counts under macroautophagy.
GO_SLIM_RELATIONS = 'is_a,part_of,occurs_in,regulates'
GO_ANNOTATIONS_READ = 100
COMPOUND_IDS = r'(?i)CHEBI:\d+|(?:PUBCHEM\.COMPOUND:|CID:?)\d+'


def hallmark_map(root=search.SKILL):
    """The pinned table, checked: its hash is the one pinned, and every row names its source and a
    hallmark of the vocabulary."""
    data = (root / HALLMARKS_MAP).read_bytes()
    if root == search.SKILL and search.sha256(data) != HALLMARKS_MAP_SHA256:
        raise ValueError(f'{HALLMARKS_MAP}: not the table pinned ({HALLMARKS_MAP_SHA256})')
    m = json.loads(data)
    known = set(m['vocabulary']['hallmarks'])
    for part in ('opengenes', 'go'):
        for row in m[part]['rows']:
            if not row.get('source') or not row.get('basis') or row.get('hallmark') not in known:
                raise ValueError(f"{HALLMARKS_MAP}: {row.get('from')}: no source, or not a hallmark of the vocabulary")
    return m


def go_annotations(s, accessions, terms):
    """How many GO annotations of the UniProt proteins QuickGO maps to each of the GO terms given, with
    their evidence codes; annotations qualified NOT are counted apart, never as the term. One logged record."""
    def run(responses):
        q = {'geneProductId': ','.join(accessions), 'goId': ','.join(terms), 'goUsage': 'slim',
             'goUsageRelationships': GO_SLIM_RELATIONS, 'limit': GO_ANNOTATIONS_READ}
        found, page, pages = [], 1, 1
        while page <= pages:
            data = s.json(QUICKGO_ANNOTATIONS + urllib.parse.urlencode(q | {'page': page}, safe=':,'), responses)
            found += data.get('results') or []
            pages, page = (data.get('pageInfo') or {}).get('total') or 1, page + 1
        works = {}
        for a in found:
            for go in a.get('slimmedIds') or []:
                w = works.setdefault(go, {
                    'source_id': go, 'annotations': 0, 'not_annotations': 0, 'evidence': {}, 'gene_products': [],
                    'url': GO_ANNOTATIONS_PAGE + urllib.parse.urlencode(
                        {'geneProductId': ','.join(accessions), 'goId': go, 'goUsage': 'descendants',
                         'goUsageRelationships': GO_SLIM_RELATIONS}, safe=':,'),
                    'licence': GO_LICENCE, 'licence_from': GO_LICENCE_FROM,
                    'attribution': 'Gene Ontology Consortium, CC BY 4.0'})
                if (a.get('qualifier') or '').startswith('NOT'):
                    w['not_annotations'] += 1
                    continue
                w['annotations'] += 1
                w['evidence'][a.get('goEvidence')] = w['evidence'].get(a.get('goEvidence'), 0) + 1
                if a.get('geneProductId') not in w['gene_products']:
                    w['gene_products'].append(a.get('geneProductId'))
        works = [works[t] for t in terms if t in works]
        if works:
            release = s.json(QUICKGO + 'about', responses)['go'].get('timestamp')
            for w in works:
                dated(w, release=release)
        return len(found), works, {'service': 'QuickGO annotation', 'go_usage': f'slim: {GO_SLIM_RELATIONS}'}
    return s.call('go_annotations', {'id': ','.join(accessions), 'source': 'gene ontology', 'terms': terms}, run)


def hallmarks(s, name, table=None, via=None):
    """Hallmark hints for a gene by any name: HGNC resolves it, then Open Genes and GO are read for it.
    The logged records and the hints drawn from them. A compound gets none of its own: no open source
    states the hallmarks of a compound. With via, a gene the card names as its target, it gets the
    gene's, each marked via that gene."""
    table = table or hallmark_map()
    if re.fullmatch(COMPOUND_IDS, name):
        if not via:
            return [], hallmark_hints(name, None, [], table, [
                'a compound: neither Open Genes nor GO files a compound under an ageing mechanism or a process'])
        records, h = hallmarks(s, via, table)
        return records, h | {'asked': name, 'via': via,
                             'hints': [x | {'via': via, 'reason': f"via {via}: {x['reason']}"} for x in h['hints']]}
    first = hgnc_gene(s, name)
    if first['outcome'] != 'ok' or len(first['works']) != 1:
        return [first], hallmark_hints(name, None, [first], table, [f'HGNC names no one gene for {name}'])
    g = first['works'][0]
    records = [first, opengenes_gene(s, g['symbol'])]
    if g['uniprot']:
        records.append(go_annotations(s, g['uniprot'], [r['from'] for r in table['go']['rows']]))
    return records, hallmark_hints(name, g['symbol'], records, table)


def hallmark_hints(asked, symbol, records, table, notes=()):
    """Hints from logged records through the table: one per term of a row, with the hallmark, the term,
    why, the source of the row, a link and the call it rests on. A term in no row is listed as not
    mapped, with why if the table says, and suggests nothing."""
    hints, unmapped, notes = [], [], list(notes)
    og = {r['from']: r for r in table['opengenes']['rows']}
    og_left = {r['from']: r['why'] for r in table['opengenes']['not_mapped']}
    go = {r['from']: r for r in table['go']['rows']}

    def hint(row, reason, link, call, **more):
        return {'hallmark': row['hallmark'], 'from': row['from'], 'label': row['label'], 'reason': reason,
                'source': row['source'], 'basis': row['basis'], 'link': link, 'call_id': call['call_id']} | more
    for r in records:
        if r['outcome'] != 'ok':
            notes.append(f"{r['tool']} {r['ask']['id']}: failed: {r.get('error')}")
        elif r['tool'] == 'opengenes_gene':
            gene = next((w for w in r['works'] if w['source_id'].startswith('OPENGENES:')), None)
            if gene is None:
                notes.append(r.get('note') or f'no Open Genes entry for {symbol}')
            elif gene.get('aging_mechanism_ids') is None or gene.get('aging_mechanisms') is None:
                notes.append('Open Genes ageing mechanisms not recorded: no licence, or not known at the cutoff')
            else:
                for i, label in zip(gene['aging_mechanism_ids'], gene['aging_mechanisms']):
                    key = f'opengenes:{i}'
                    if key not in og:
                        unmapped.append({'from': key, 'label': label, 'why': og_left.get(key, 'not in the table'),
                                         'call_id': r['call_id']})
                        continue
                    hints.append(hint(og[key], f"Open Genes files {gene['symbol']} under the ageing mechanism "
                                      f"'{label}'", gene['url'], r, licence=gene['licence'],
                                      attribution=gene['attribution']))
        elif r['tool'] == 'go_annotations':
            for w in r['works']:
                if w['source_id'] in go and w['annotations']:
                    row = go[w['source_id']]
                    hints.append(hint(row, f"{w['annotations']} GO annotations of {symbol} map to "
                                      f"'{row['label']}' ({w['source_id']})", w['url'], r,
                                      evidence=w['evidence'], licence=w['licence'], attribution=w['attribution']))
    return {'schema': HALLMARK_HINTS, 'asked': asked, 'gene': symbol, 'vocabulary': table['vocabulary']['id'],
            'hallmarks': [h for h in table['vocabulary']['hallmarks'] if h in {x['hallmark'] for x in hints}],
            'hints': hints, 'not_mapped': unmapped, 'notes': notes,
            'assigned': 'none: a hint is not a hallmark of a card; the converter sets one from the text, with atoms'}


def gene(s, name):
    """A gene by any name: HGNC resolves it; NCBI Gene and UniProt are read by the identifiers HGNC gives.
    An ambiguous or unknown name stops at HGNC."""
    first = hgnc_gene(s, name)
    if first['outcome'] != 'ok' or len(first['works']) != 1:
        return [first]
    g = first['works'][0]
    out = [first]
    if g['ncbi_gene']:
        out.append(ncbi_gene(s, g['ncbi_gene']))
    for acc in g['uniprot']:
        out.append(uniprot_entry(s, acc))
    return out


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    p.add_argument('command', choices=('gene', 'hgnc', 'ncbi-gene', 'uniprot', 'genage', 'drugage', 'hagr-fetch',
                                       'reactome', 'reactome-pathway', 'target', 'drug', 'mesh', 'taxonomy', 'go',
                                       'opengenes', 'chembl', 'geo', 'pubchem', 'taxon', 'hallmarks', 'proximity', 'taxon-ids'))
    p.add_argument('args', nargs='+')
    p.add_argument('--workdir', default='.')
    p.add_argument('--taxa', metavar='FILE', help='with taxon: also write the rows of the taxa asked to FILE (taxa.json); '
                                               'with proximity: read them, as further rows of the taxon table')
    p.add_argument('--standard', metavar='DIR', help='with proximity: a checkout of OHF 1.1 or later (its VERSION file)')
    p.add_argument('--out', metavar='FILE', help='with proximity or taxon-ids: write the card with the values placed')
    p.add_argument('--reading', metavar='FILE', help='with taxon-ids: {line id: name or NCBITaxon id} in place of '
                                                 "the line's system.taxon")
    p.add_argument('--hints', metavar='FILE', help='with hallmarks: also write the hints to FILE')
    p.add_argument('--via', metavar='GENE', help='with hallmarks of a compound: the hints of this gene, its target')
    p.add_argument('--as-of', metavar='YYYY-MM-DD', help='answer as of this day, inclusive (added.cutoff_date)')
    a = p.parse_args(argv)
    if a.command == 'proximity':
        if not a.standard or len(a.args) != 1:
            p.error('proximity takes one CARD and --standard DIR')
        report = card_proximity(a.args[0], a.standard, a.taxa, a.out)
        print(json.dumps(report, ensure_ascii=False, indent=1))
        return 0 if report.get('check_refs', {'valid': True})['valid'] else 1
    s = search.Searcher(a.workdir)
    if a.as_of:
        at_cutoff(s, a.as_of)
    if a.command == 'taxon-ids':
        if len(a.args) != 1:
            p.error('taxon-ids takes one CARD')
        report = card_taxon_ids(s, a.args[0], a.reading, a.standard, a.out, a.taxa)
        print(json.dumps(report, ensure_ascii=False, indent=1))
        return 0
    one = {'hgnc': hgnc_gene, 'ncbi-gene': ncbi_gene, 'uniprot': uniprot_entry, 'genage': genage, 'drugage': drugage,
           'hagr-fetch': hagr_fetch, 'reactome': reactome_pathways, 'reactome-pathway': reactome_pathway,
           'target': opentargets_target, 'drug': opentargets_drug, 'mesh': mesh_terms, 'taxonomy': taxonomy, 'taxon': taxonomy,
           'go': go_terms, 'opengenes': opengenes_gene, 'chembl': chembl, 'geo': geo,
           'pubchem': pubchem}
    if a.command == 'hallmarks':
        found = [hallmarks(s, x, via=a.via) for x in a.args]
        out, hints = [r for records, _ in found for r in records], [h for _, h in found]
        if a.hints:
            Path(a.hints).write_text(json.dumps(hints, ensure_ascii=False, indent=1) + '\n')
        print(json.dumps(hints, ensure_ascii=False, indent=1))
        return 0 if all(r['outcome'] == 'ok' for r in out) else 1
    out = [r for x in a.args for r in (gene(s, x) if a.command == 'gene' else [one[a.command](s, x)])]
    if a.taxa and a.command in ('taxon', 'taxonomy'):
        Path(a.taxa).write_text(json.dumps(taxa_rows([r for r in out if r['outcome'] == 'ok']),
                                           ensure_ascii=False, indent=1) + '\n')
    for r in out:
        print(json.dumps({k: v for k, v in r.items() if k != 'works'} | {'works': r['works'][:1],
                          'more_works': len(r['works'][1:])}, ensure_ascii=False, indent=1))
    return 0 if all(r['outcome'] == 'ok' for r in out) else 1


if __name__ == '__main__':
    sys.exit(main())
