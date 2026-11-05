#!/usr/bin/env python3
"""The entities a card or a submitted text names, linked to databases, with how each link was made.

A mention is read by the converter, not guessed by the kit: its words as they stand in the source, its
kind, and where it stands. The kit checks that the words stand there, looks each mention up with the
clients of scripts/biodb.py (every call in the search log), and gives each a status by rule:

  exact      a database has exactly one entry whose name, symbol or equivalent term is the mention's
             query, in its letter case if one is, else in any case (entries the case set aside stay in
             `candidates`, `set_aside_by: "letter case"`); `links` holds it, one per database that has one. A gene's
             alias is not an equivalent: aliases are not unique, and a family's name (PI3K, Akt) is
             listed as an alias of one of its genes.
  ambiguous  a database has several such entries, or only entries that carry the query as an alias or
             not at all; `candidates` holds them (`exact_name`: true, "alias" or false), and nothing is
             chosen.
  not_found  no database the kind is looked up in returned anything.

The kit also lists the symbol-like words of the source (letters with a digit, or two capitals: mTORC1,
4E-BP1, PI3K) that no mention covers, so that what the converter left out is seen, not decided.

Usage:
  entities.py tokens SOURCE                      (symbol-like words of the source, with where they stand)
  entities.py link SOURCE MENTIONS [--out FILE]  (link the mentions; FILE defaults to entities.json)
with --workdir DIR (default: the current directory) for the search log and the responses, and --as-of
YYYY-MM-DD to mark, for each link and candidate, whether its entry was public on that day.

SOURCE is a card (a .json file) or a submitted text (any other file), whose paragraphs are split at blank
lines as the kit reads a submitted text, spaces collapsed, and named p1, p2, ... (its paragraph 1, 2...). MENTIONS is a JSON list of {"text", "kind", "where", "query"?, "taxon"?}:
`where` is a JSON pointer into the card or a paragraph name, or a list of them; `query` is given only when
the words to look up differ from the text (a translation, a full name), and the record says the converter
gave it; `taxon` (a name or an NCBI Taxonomy id) is the organism a gene or protein is meant in, as the
source says, never assumed.
"""
import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import biodb  # noqa: E402
import search  # noqa: E402

SCHEMA = 'ohf-extractor:entities@1'
# Which databases each kind of mention is looked up in, in order. HGNC names human genes only: a gene or
# protein whose mention has a taxon other than human is looked up first in NCBI Gene for that taxon.
HUMAN = '9606'
RESOLVERS = {'gene': ('hgnc', 'mesh'), 'protein': ('hgnc', 'mesh'), 'complex': ('go', 'mesh'),
             'component': ('go', 'mesh'), 'process': ('go', 'mesh'), 'organism': ('taxonomy',),
             'compound': ('mesh', 'pubchem'), 'other': ('mesh',)}
LOOKUP = {'hgnc': biodb.hgnc_gene, 'go': biodb.go_terms, 'mesh': biodb.mesh_terms, 'taxonomy': biodb.taxonomy,
          'ncbi_gene': biodb.ncbi_gene_search, 'pubchem': biodb.pubchem}
# Card fields that hold identifiers, hashes or references, not prose: not searched for symbol-like words.
NOT_PROSE = {'id', 'src', 'url', 'uri', 'doi', 'pmid', 'pmcid', 'sha256', 'locator', 'pointer', 'citation',
             'source_text_sha256', 'converter_hash', 'schema', 'run_id', 'proposition_id'}
SYMBOL = re.compile(r'(?<![\w-])(?=[\w-]*[^\W\d_])(?=[\w-]*(?:\d|[A-Z][\w-]*[A-Z]))[^\W_][\w-]*[^\W_]|'
                    r'(?<![\w-])[A-Za-z]\d+(?![\w-])')
NOT_SYMBOL = re.compile(r'^(?:PMC\d*|PMID\d*|DOI|URL|HTTPS?|XML|HTML|PDF|JSON|API|sha256|\d+[a-z]{0,2}|[IVX]+|.*_.*)$')
LINK = re.compile(r'\]\([^)]*\)|https?://\S+|10\.\d{4,9}/\S+')


class MentionError(ValueError):
    pass


def units(path):
    """The source as {where: text}: a card's string fields by JSON pointer, or a text's paragraphs."""
    raw = Path(path).read_bytes()
    if Path(path).suffix == '.json':
        out = {}

        def walk(x, at):
            if isinstance(x, dict):
                for k, v in x.items():
                    walk(v, f"{at}/{k.replace('~', '~0').replace('/', '~1')}")
            elif isinstance(x, list):
                for i, v in enumerate(x):
                    walk(v, f'{at}/{i}')
            elif isinstance(x, str):
                out[at] = x
        card = json.loads(raw)
        walk(card, '')
        return 'card', raw, out, card
    # Split and spaced as ohfkit.SubmittedText reads it (a test holds the two together), so that p3 here
    # is its paragraph 3; ohfkit itself needs a checkout of the standard, which a lookup does not.
    text = raw.decode('utf-8').replace('\r\n', '\n')
    paragraphs = [norm(p) for p in re.split(r'\n[ \t]*\n', text) if norm(p)]
    return 'text', raw, {f'p{i}': p for i, p in enumerate(paragraphs, 1)}, None


def norm(text):
    return re.sub(r'\s+', ' ', text).strip()


def prose(at, text):
    return ' ' in text.strip() and at.rsplit('/', 1)[-1] not in NOT_PROSE


def tokens(found):
    """Symbol-like words of the source's prose: {word: [where, ...]}, in order of first appearance."""
    out = {}
    for at, text in found.items():
        if not prose(at, text):
            continue
        for m in SYMBOL.finditer(LINK.sub(' ', text)):
            if not NOT_SYMBOL.match(m.group()):
                out.setdefault(m.group(), [])
                if at not in out[m.group()]:
                    out[m.group()].append(at)
    return out


def checked(mentions, found):
    """The mentions whose words stand where they say, merged by (text, kind, query); and those rejected."""
    merged, rejected = {}, []
    for m in mentions:
        text, kind = m.get('text'), m.get('kind')
        wheres = m.get('where') if isinstance(m.get('where'), list) else [m.get('where')]
        if not text or kind not in RESOLVERS:
            rejected.append({'mention': m, 'reason': f'needs text and a kind of {sorted(RESOLVERS)}'})
            continue
        bad = [w for w in wheres if w not in found or text not in found[w]]
        if bad:
            rejected.append({'mention': m, 'reason': f'the text does not stand at {bad}'})
            continue
        query, taxon = m.get('query') or text, m.get('taxon')
        key = (text, kind, query, taxon)
        e = merged.setdefault(key, {'text': text, 'kind': kind, 'query': query,
                                    'query_from': 'converter' if m.get('query') else 'text', 'where': []})
        if taxon:
            e['taxon'] = str(taxon)
        for w in wheres:
            at = {'at': w, 'offset': found[w].index(text)}
            if at not in e['where']:
                e['where'].append(at)
    return list(merged.values()), rejected


def names(db, w):
    """The names of an entry that make a query an exact match: its own, and its equivalents."""
    if db == 'hgnc':
        return [w['symbol']] + w['prev_symbols']
    if db == 'ncbi_gene':
        return [w['symbol']]
    if db == 'go':
        return [] if w.get('obsolete') else [w['name']] + [n for n, t in w['synonym_types'].items() if t == 'exact']
    if db == 'mesh':
        return [w['heading']] + w['synonyms']
    if db == 'pubchem':
        # PubChem finds a compound by a name it or its salt carries exactly: the name asked is one of them.
        return [x for x in [w['name'], w['found_by']] + (w['synonyms'] or []) if x]
    return [w['scientific_name']] + w['synonyms']


def aliases(db, w):
    """A gene's aliases: they name it, but not it alone."""
    return w['alias_symbols'] if db == 'hgnc' else w['aliases'] if db == 'ncbi_gene' else []


def named(db, w, query):
    """true, 'alias' or false: how an entry carries the query."""
    q = fold(query)
    return True if q in map(fold, names(db, w)) else 'alias' if q in map(fold, aliases(db, w)) else False


def matching(db, works, query):
    """The entries carrying the query as their own name: in its letter case if any does (in plants RPS4 and
    rps4 are different genes), else in any case (Leucine for leucine)."""
    exact = [w for w in works if named(db, w, query) is True]
    same_case = [w for w in exact if query in names(db, w)]
    return same_case or exact


def curie(w):
    sid = w['source_id']
    for old, new in (('NCBITAXON:', 'NCBITaxon:'), ('NCBIGENE:', 'NCBIGene:'), ('PUBCHEM.COMPOUND:', 'pubchem.compound:')):
        if sid.startswith(old):
            return new + sid[len(old):]
    return sid


def entry(db, w, call):
    out = {'curie': curie(w), 'label': w.get('symbol') or w.get('name') or w.get('heading') or w.get('scientific_name'),
           'database': db, 'url': w['url'], 'call_id': call['call_id']}
    if w.get('release'):
        out['release'] = w['release']
    if (w.get('dates') or {}).get('since'):
        out['since'] = w['dates']['since']
    if db == 'hgnc':
        out.update(scope='human gene', ncbi_gene=w['ncbi_gene'], uniprot=w['uniprot'])
    if db == 'ncbi_gene':
        out.update(scope='gene of the taxon', taxon=w['taxon'], organism=w['organism'])
    if db == 'pubchem':
        out.update(scope='parent compound', inchikey=w['inchikey'], collapsed_from=w['collapsed_from'])
    return out


def fold(x):
    return ' '.join(x.split()).casefold()


def taxon_id(s, e, lookup):
    """The NCBI Taxonomy id of a mention's taxon: given as an id, or a name with exactly one exact entry."""
    if e['taxon'].isdigit():
        return e['taxon']
    call = lookup['taxonomy'](s, e['taxon'])
    e['established_by'].append({'call_id': call['call_id'], 'tool': call['tool'], 'outcome': call['outcome'],
                                'for': 'taxon'})
    exact = [w for w in call['works'] if named('taxonomy', w, e['taxon']) is True]
    return exact[0]['taxon'] if len(exact) == 1 else None


def link(s, e, lookup=None):
    """Look one mention up in each database of its kind and give it a status by rule. A gene of another
    species is looked up in NCBI Gene for its taxon; the human gene of the same name, only when that finds
    nothing, and then as a candidate (scope ortholog): a shared name does not establish orthology."""
    lookup = lookup or LOOKUP
    e.update(status='not_found', links=[], candidates=[], established_by=[])
    dbs, taxon = list(RESOLVERS[e['kind']]), None
    if e['kind'] in ('gene', 'protein') and e.get('taxon'):
        taxon = taxon_id(s, e, lookup)
        if taxon is None:
            e.update(status='ambiguous', note=f"the taxon {e['taxon']!r} has no single NCBI Taxonomy entry")
            return e
        if taxon != HUMAN:
            dbs = ['ncbi_gene'] + dbs
    seen, several = False, False
    for db in dbs:
        if db == 'hgnc' and 'ncbi_gene' in dbs and (e['links'] or seen):
            continue
        call = lookup[db](s, e['query'], taxon) if db == 'ncbi_gene' else lookup[db](s, e['query'])
        e['established_by'].append({'call_id': call['call_id'], 'tool': call['tool'], 'outcome': call['outcome']})
        works = call['works']
        exact = matching(db, works, e['query'])
        if db == 'hgnc' and 'ncbi_gene' in dbs:
            # Nothing in the mention's own taxon: the human gene of that name, as a candidate only.
            e['candidates'] += [entry(db, w, call) | {'exact_name': named(db, w, e['query']), 'scope': 'ortholog',
                                                      'mention_taxon': taxon} for w in works]
            seen = seen or bool(works)
            continue
        seen = seen or bool(works)
        if len(exact) == 1:
            e['links'].append(entry(db, exact[0], call))
            # Entries that carry the name in another letter case, set aside by it: shown, not dropped.
            e['candidates'] += [entry(db, w, call) | {'exact_name': True, 'set_aside_by': 'letter case'}
                                for w in works if w is not exact[0] and named(db, w, e['query']) is True]
        else:
            several = several or len(exact) > 1
            e['candidates'] += [entry(db, w, call) | {'exact_name': named(db, w, e['query'])} for w in works]
    if e['links'] and not several:
        e['status'] = 'exact'
    elif seen:
        e['status'] = 'ambiguous'
    if e['kind'] in ('gene', 'protein') and not taxon and any(x['database'] == 'hgnc' for x in e['links']):
        e['note'] = 'no taxon given: HGNC names human genes, and the link is to the human gene of that name'
    return e


def card_ids(card, entities):
    """Identifiers the card already holds (`id` fields with a CURIE, taxon names, in its two zones),
    against the links: `linked_by` names the mention linked to it, `candidate_of` one that has it only
    as a candidate (the card's id is then a broader, narrower or other entry than the mention's)."""
    held, linked = [], {x['curie']: e['text'] for e in entities for x in e['links']}
    candidate = {x['curie']: e['text'] for e in entities for x in e['candidates']}
    labels = {fold(x['label']): x['curie'] for e in entities for x in e['links'] if x['database'] == 'taxonomy'}

    def walk(x, at):
        if isinstance(x, dict):
            if isinstance(x.get('id'), str) and re.match(r'^[A-Za-z][\w.]*:\S+$', x['id']) and at.startswith(
                    ('/author', '/added')):
                held.append({'at': at + '/id', 'id': x['id'], 'linked_by': linked.get(x['id']),
                             'candidate_of': candidate.get(x['id'])})
            if isinstance(x.get('taxon'), dict) and isinstance(x['taxon'].get('value'), str):
                t = x['taxon']['value']
                held.append({'at': at + '/taxon/value', 'id': t, 'linked_by': labels.get(fold(t)), 'candidate_of': None})
            for k, v in x.items():
                walk(v, f'{at}/{k}')
        elif isinstance(x, list):
            for i, v in enumerate(x):
                walk(v, f'{at}/{i}')
    walk(card, '')
    return held


def at_cutoff(entities, cutoff):
    """Whether each linked or candidate entry was public on the cutoff (`at_cutoff`: "public", or
    search.as_of's reason). A link identifies what the source names, and is kept: an entity is not newer
    than the entry made for it later. Counts of the links not shown public by then."""
    counts = dict.fromkeys(search.AS_OF_REASONS, 0)
    for e in entities:
        for x in e['links'] + e['candidates']:
            r = search.as_of(True, x.get('since'), cutoff)
            x['at_cutoff'] = 'public' if r['basis'] else r['reason']
        for x in e['links']:
            if x['at_cutoff'] != 'public':
                counts[x['at_cutoff']] += 1
    return {'date': cutoff, 'links_not_public': counts}


def run(source, mentions_path, s, lookup=None, cutoff=None):
    if cutoff:
        search.cutoff_day(cutoff)
    kind, raw, found, card = units(source)
    mraw = Path(mentions_path).read_bytes()
    entities, rejected = checked(json.loads(mraw), found)
    for i, e in enumerate(entities, 1):
        e['id'] = f'e{i}'
        link(s, e, lookup)
    covered = [e['text'] for e in entities]
    unlisted = [{'word': w, 'where': at} for w, at in tokens(found).items()
                if not any(w in c or c in w for c in covered)]
    out = {'schema': SCHEMA, 'kit': f'ohf-extractor/{search.VERSION}',
           'made_at': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
           'source': {'kind': kind, 'file': Path(source).name, 'sha256': 'sha256:' + hashlib.sha256(raw).hexdigest()},
           'mentions_sha256': 'sha256:' + hashlib.sha256(mraw).hexdigest(),
           'search_log': search.LOG,
           'counts': {k: sum(e['status'] == k for e in entities) for k in ('exact', 'ambiguous', 'not_found')},
           'entities': entities, 'rejected': rejected, 'unlisted': unlisted}
    if card is not None:
        out['source']['card'] = f"{card.get('id')}@{card.get('version')}"
        out['card_ids'] = card_ids(card, entities)
    if cutoff:
        out['cutoff'] = at_cutoff(entities, cutoff)
    return out


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    p.add_argument('command', choices=('tokens', 'link'))
    p.add_argument('source')
    p.add_argument('mentions', nargs='?')
    p.add_argument('--out', default='entities.json')
    p.add_argument('--workdir', default='.')
    p.add_argument('--as-of', metavar='YYYY-MM-DD', help='mark which linked entries were public on this day')
    a = p.parse_args(argv)
    if a.command == 'tokens':
        print(json.dumps(tokens(units(a.source)[2]), ensure_ascii=False, indent=1))
        return 0
    if not a.mentions:
        p.error('link needs MENTIONS')
    out = run(a.source, a.mentions, search.Searcher(a.workdir), cutoff=a.as_of)
    Path(a.out).write_text(json.dumps(out, ensure_ascii=False, indent=1) + '\n')
    print(json.dumps(out['counts'] | {'rejected': len(out['rejected']), 'unlisted': len(out['unlisted'])}))
    return 0 if not out['rejected'] else 1


if __name__ == '__main__':
    sys.exit(main())
