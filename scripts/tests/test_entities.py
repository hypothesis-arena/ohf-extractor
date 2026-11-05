# Export fixture provenance: inputs named in SYNTHETIC-FIXTURES.json are
# constructed test data; their identifiers and dates are regression tokens.
# Recorded-response descriptions below identify the replaced source snapshots,
# not live-service provenance for those synthetic replacement inputs.
"""Entities of a card or a submitted text: the status rule on stand-in lookups, then one run on recorded
responses, no network."""
import json

import entities
import search
from test_biodb import TERMS, Net


# Real PubChem answers (2026-10-22) for rapamycin: the parent's route first, the name's own after it.
PUBCHEM = {'name/rapamycin/cids/JSON?cids_type=parent': (200, 'pubchem-name-rapamycin-parent.json'),
           'name/rapamycin/cids/JSON': (200, 'pubchem-name-rapamycin.json'),
           'cid/5284616/property/': (200, 'pubchem-5284616-property.json'),
           'cid/5284616/synonyms/': (200, 'pubchem-5284616-synonyms.json')}


def call(works, tool='lookup'):
    return {'call_id': f'c{len(works)}', 'tool': tool, 'outcome': 'ok', 'works': works}


def hgnc(symbol, aliases=(), prev=()):
    return {'source_id': f'HGNC:{len(symbol)}', 'symbol': symbol, 'alias_symbols': list(aliases),
            'prev_symbols': list(prev), 'url': 'u', 'ncbi_gene': '1', 'uniprot': []}


def gene(symbol, aliases=(), taxon='10090'):
    return {'source_id': 'NCBIGENE:78757', 'symbol': symbol, 'aliases': list(aliases), 'url': 'u',
            'taxon': int(taxon), 'organism': 'Mus musculus'}


def taxon(name, tax, others=()):
    return {'source_id': f'NCBITAXON:{tax}', 'taxon': tax, 'scientific_name': name, 'synonyms': list(others), 'url': 'u'}


def mention(text, kind, **kw):
    return dict({'text': text, 'kind': kind, 'query': kw.pop('query', text), 'query_from': 'text', 'where': []}, **kw)


def lookups(**answers):
    """Stand-in lookups: each database answers its list of works; the calls are counted."""
    asked = []

    def one(db):
        def f(s, q, *taxon):
            asked.append((db, q) + taxon)
            return call(answers.get(db, []), db)
        return f
    return {db: one(db) for db in entities.LOOKUP}, asked


def test_one_entry_carrying_the_query_as_its_symbol_is_exact():
    look, _ = lookups(hgnc=[hgnc('VAMP7')])
    e = entities.link(None, mention('VAMP7', 'protein'), look)
    assert e['status'] == 'exact' and [x['curie'] for x in e['links']] == ['HGNC:5']
    assert e['links'][0]['scope'] == 'human gene' and 'no taxon given' in e['note']


def test_an_alias_is_not_an_identity_and_two_symbols_are_not_one():
    # HGNC lists PI3K as an alias of PIK3CA alone; the text means the family. Not chosen.
    look, _ = lookups(hgnc=[hgnc('PIK3CA', aliases=['PI3K'])])
    e = entities.link(None, mention('PI3K', 'protein'), look)
    assert e['status'] == 'ambiguous' and e['links'] == [] and e['candidates'][0]['exact_name'] == 'alias'
    look, _ = lookups(hgnc=[hgnc('CDKN2A', prev=['P16']), hgnc('H3P10', prev=['P16'])])
    assert entities.link(None, mention('p16', 'gene'), look)['status'] == 'ambiguous'


def test_nothing_returned_is_not_found_and_only_other_names_is_ambiguous():
    look, _ = lookups()
    assert entities.link(None, mention('lung fibroblasts', 'other'), look)['status'] == 'not_found'
    look, _ = lookups(mesh=[{'source_id': 'MESH:D1', 'heading': 'Biglycan', 'synonyms': [], 'url': 'u'}])
    assert entities.link(None, mention('leucine', 'compound'), look)['status'] == 'ambiguous'


def test_a_process_linked_in_two_databases_is_one_exact_entity_with_two_links():
    look, _ = lookups(go=[{'source_id': 'GO:0006914', 'name': 'autophagy', 'synonym_types': {}, 'url': 'u'}],
                      mesh=[{'source_id': 'MESH:D001343', 'heading': 'Autophagy', 'synonyms': [], 'url': 'u'}])
    e = entities.link(None, mention('аутофагии', 'process', query='autophagy', query_from='converter'), look)
    assert e['status'] == 'exact' and [x['curie'] for x in e['links']] == ['GO:0006914', 'MESH:D001343']


def test_a_narrow_go_synonym_is_a_candidate_not_a_link():
    torc1 = {'source_id': 'GO:0031931', 'name': 'TORC1 complex', 'url': 'u',
             'synonym_types': {'mTORC1': 'narrow', 'TORC1': 'exact'}}
    look, _ = lookups(go=[torc1])
    e = entities.link(None, mention('mTORC1', 'complex'), look)
    assert e['links'] == [] and e['candidates'][0]['curie'] == 'GO:0031931'


def compound(cid, name, found_by, synonyms=()):
    return {'source_id': f'PUBCHEM.COMPOUND:{cid}', 'cid': cid, 'name': name, 'found_by': found_by,
            'synonyms': list(synonyms), 'inchikey': 'K', 'collapsed_from': None, 'url': 'u'}


def test_a_compound_is_one_link_in_mesh_and_one_in_pubchem_and_two_parents_are_not_one():
    look, _ = lookups(mesh=[{'source_id': 'MESH:D020123', 'heading': 'Sirolimus', 'synonyms': ['Rapamycin'], 'url': 'u'}],
                      pubchem=[compound(5284616, 'Sirolimus', 'rapamycin', ['rapamycin'])])
    e = entities.link(None, mention('rapamycin', 'compound'), look)
    assert e['status'] == 'exact' and [x['curie'] for x in e['links']] == ['MESH:D020123', 'pubchem.compound:5284616']
    assert e['links'][1]['scope'] == 'parent compound'
    # A name PubChem gives two parent compounds for names neither alone.
    look, _ = lookups(pubchem=[compound(1, 'A', 'x'), compound(2, 'B', 'x')])
    e = entities.link(None, mention('x', 'compound'), look)
    assert e['status'] == 'ambiguous' and e['links'] == [] and len(e['candidates']) == 2


def test_a_mouse_gene_is_linked_in_its_taxon_and_human_is_not_asked():
    look, asked = lookups(ncbi_gene=[gene('Rictor', ['AVO3'])], hgnc=[hgnc('RICTOR')],
                          taxonomy=[taxon('Mus musculus', '10090', ['house mouse'])])
    e = entities.link(None, mention('Rictor', 'gene', taxon='Mus musculus'), look)
    assert e['status'] == 'exact' and e['links'][0]['curie'] == 'NCBIGene:78757'
    assert e['links'][0]['scope'] == 'gene of the taxon' and ('ncbi_gene', 'Rictor', '10090') in asked
    assert not any(db == 'hgnc' for db, *_ in asked)
    assert e['established_by'][0]['for'] == 'taxon'


def test_without_the_gene_in_its_taxon_the_human_gene_of_that_name_is_a_candidate_only():
    look, asked = lookups(hgnc=[hgnc('RRS1')])
    e = entities.link(None, mention('RRS1', 'gene', taxon='3702'), look)
    assert e['status'] == 'ambiguous' and e['links'] == []
    assert e['candidates'][0]['scope'] == 'ortholog' and e['candidates'][0]['mention_taxon'] == '3702'
    assert not any(db == 'taxonomy' for db, *_ in asked)  # an id is not looked up


def test_letter_case_tells_plant_genes_apart_when_it_can():
    # Arabidopsis: RPS4 the immune receptor, rps4 chloroplast ribosomal proteins.
    look, _ = lookups(ncbi_gene=[gene('RPS4', taxon='3702'), gene('rps4', taxon='3702'), gene('rps4', taxon='3702')])
    e = entities.link(None, mention('RPS4', 'gene', taxon='3702'), look)
    assert e['status'] == 'exact' and e['links'][0]['label'] == 'RPS4'
    assert [(c['label'], c['set_aside_by']) for c in e['candidates']] == [('rps4', 'letter case')] * 2
    e = entities.link(None, mention('Rps4', 'gene', taxon='3702'), look)
    assert e['status'] == 'ambiguous'  # no entry in its case: three in any case


def test_a_taxon_name_without_one_entry_leaves_the_gene_ambiguous():
    look, asked = lookups(taxonomy=[taxon('Mus musculus', '10090', ['mouse']), taxon('Mus', '10088', ['mouse'])])
    e = entities.link(None, mention('Rictor', 'gene', taxon='mouse'), look)
    assert e['status'] == 'ambiguous' and 'mouse' in e['note']
    assert [db for db, *_ in asked] == ['taxonomy']


def test_a_mention_must_stand_where_it_says_and_mentions_merge_by_text_kind_and_query():
    found = {'p1': 'mTORC1 and lysosomes', 'p2': 'again mTORC1'}
    kept, rejected = entities.checked([{'text': 'mTORC1', 'kind': 'complex', 'where': 'p1'},
                                       {'text': 'mTORC1', 'kind': 'complex', 'where': ['p2']},
                                       {'text': 'mTORC2', 'kind': 'complex', 'where': 'p1'},
                                       {'text': 'mTORC1', 'kind': 'enzyme', 'where': 'p1'}], found)
    assert len(kept) == 1 and [w['at'] for w in kept[0]['where']] == ['p1', 'p2']
    assert kept[0]['where'][1]['offset'] == 6
    assert [r['mention']['text'] for r in rejected] == ['mTORC2', 'mTORC1']


def test_symbol_like_words_of_prose_and_not_links_or_identifiers():
    found = {'p1': 'S6K and 4E-BP1 via PI3K–Akt; p16/p21 [paper](https://doi.org/10.1/x PMC5496614) mTORC1',
             '/added/id': 'h_x', '/added/layers/core/atoms/0/id': 'a_X1'}
    words = entities.tokens(found)
    assert {'S6K', '4E-BP1', 'PI3K', 'p16', 'p21', 'mTORC1'} <= set(words)
    assert not {'PMC5496614', 'a_X1', 'x'} & set(words)


def test_a_text_is_linked_end_to_end_on_recorded_responses(tmp_path):
    src = tmp_path / 'answer.md'
    src.write_text('Mice lacking Rictor.\n\nRapamycin acts on mTORC1. Rictor again, and VAMP7.\n')
    mentions = tmp_path / 'mentions.json'
    mentions.write_text(json.dumps([{'text': 'Rictor', 'kind': 'gene', 'where': ['p1', 'p2'], 'taxon': '10090'},
                                    {'text': 'Rapamycin', 'kind': 'compound', 'where': 'p2', 'query': 'rapamycin'},
                                    {'text': 'mTORC1', 'kind': 'complex', 'where': 'p1'}]))
    routes = dict(TERMS, **PUBCHEM, **{'Rictor%5Bsym%5D': (200, 'ncbi-gene-search-Rictor-10090.json'),
                                       'db=gene&id=78757': (200, 'ncbi-gene-78757.json')})
    s = search.Searcher(tmp_path, get=Net(routes), sleep=lambda x: None, clock=lambda: 0.0)
    out = entities.run(src, mentions, s)
    assert out['schema'] == 'ohf-extractor:entities@1' and out['source']['kind'] == 'text'
    assert out['source']['sha256'] == search.sha256(src.read_bytes())
    rictor, rapa = out['entities']
    assert (rictor['status'], rictor['links'][0]['curie']) == ('exact', 'NCBIGene:78757')
    assert [w['at'] for w in rictor['where']] == ['p1', 'p2']
    assert (rapa['status'], rapa['links'][0]['curie'], rapa['query_from']) == ('exact', 'MESH:D020123', 'converter')
    assert rapa['links'][1]['curie'] == 'pubchem.compound:5284616' and rapa['links'][1]['label'] == 'Sirolimus'
    assert out['rejected'][0]['mention']['text'] == 'mTORC1'  # it stands in p2, not p1
    assert [u['word'] for u in out['unlisted']] == ['mTORC1', 'VAMP7']
    logged = {r['call_id'] for r in search.read_log(tmp_path)}
    assert {c['call_id'] for e in out['entities'] for c in e['established_by']} <= logged
    assert out['counts'] == {'exact': 2, 'ambiguous': 0, 'not_found': 0}


def test_paragraphs_are_the_ones_the_kit_reads_in_a_submitted_text(tmp_path):
    import ohfkit
    from test_submitted import MANIFEST
    text = 'First  line\nwraps here.\n\n\n\n  Second, after  three blank lines. \r\n \r\nThird.\n'
    (tmp_path / 'answer.md').write_bytes(text.encode())
    manifest = {k: v for k, v in MANIFEST.items() if k != 'prompt_file'}
    (tmp_path / 'answer.md.manifest.json').write_text(json.dumps(manifest))
    doc = ohfkit.SubmittedText(None, 'answer.md', tmp_path)
    found = entities.units(tmp_path / 'answer.md')[2]
    assert list(found.values()) == doc.paragraphs and list(found) == ['p1', 'p2', 'p3']


def test_ids_a_card_already_holds_are_set_against_the_links():
    card = {'vocabularies': {'heuristics': {'id': 'ohf:heuristics@1'}},
            'added': {'layers': {'mechanism': {'molecular_targets': {'value': [{'id': 'GO:0031931'}]}},
                                 'predictions': [{'system': {'taxon': {'value': 'Mus musculus'}}}]}}}
    found = [{'text': 'mTORC1', 'links': [{'curie': 'MESH:D000076222', 'database': 'mesh', 'label': 'x'}],
              'candidates': [{'curie': 'GO:0031931'}]},
             {'text': 'Mus musculus', 'links': [{'curie': 'NCBITaxon:10090', 'database': 'taxonomy',
                                                 'label': 'Mus musculus'}], 'candidates': []}]
    held = entities.card_ids(card, found)
    assert [(h['id'], h['linked_by'], h['candidate_of']) for h in held] == [
        ('GO:0031931', None, 'mTORC1'), ('Mus musculus', 'NCBITaxon:10090', None)]


def test_at_a_cutoff_a_link_stays_and_says_whether_its_entry_was_public_then(tmp_path):
    src = tmp_path / 'answer.md'
    src.write_text('Mice lacking Rictor, given rapamycin.\n')
    mentions = tmp_path / 'mentions.json'
    mentions.write_text(json.dumps([{'text': 'Rictor', 'kind': 'gene', 'where': 'p1', 'taxon': '10090'},
                                    {'text': 'rapamycin', 'kind': 'compound', 'where': 'p1'},
                                    {'text': 'Mice', 'kind': 'organism', 'where': 'p1', 'query': 'mouse'}]))
    routes = dict(TERMS, **PUBCHEM, **{'Rictor%5Bsym%5D': (200, 'ncbi-gene-search-Rictor-10090.json'),
                                       'db=gene&id=78757': (200, 'ncbi-gene-78757.json')})
    s = search.Searcher(tmp_path, get=Net(routes), sleep=lambda x: None, clock=lambda: 0.0)
    out = entities.run(src, mentions, s, cutoff='1999-06-01')
    rictor, rapa, mice = out['entities']
    assert (rictor['status'], rictor['links'][0]['at_cutoff']) == ('exact', 'undated')  # NCBI Gene dates nothing
    # MeSH's year introduced is not taken as a date: the link stays, undated.
    assert (rapa['status'], rapa['links'][0].get('since'), rapa['links'][0]['at_cutoff']) == ('exact', None, 'undated')
    # NCBI Taxonomy made Mus musculus public in 1992.
    mus = next(x for x in mice['links'] + mice['candidates'] if x['curie'] == 'NCBITaxon:10090')
    assert (mus['since'], mus['at_cutoff']) == ('1992-09-16', 'public')
    # Undated: Rictor in NCBI Gene, rapamycin in MeSH and in PubChem.
    assert out['cutoff']['date'] == '1999-06-01' and out['cutoff']['links_not_public']['undated'] == 3
    assert 'cutoff' not in entities.run(src, mentions, s)
