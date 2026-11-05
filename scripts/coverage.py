#!/usr/bin/env python3
"""Reconcile an inventory of an article with the card: coverage.py INVENTORY CARD [--reasons FILE]
[--confirm FILE] [--held FILE]

An inventory is what a reader found in the article, item by item, each with its paragraph
(references/inventory.md). This script asks of each item: does the card hold it? It matches by
paragraph and by type — the paragraph the item is in, against the paragraph each card value is
sourced to, and the item's type against the places in the card where a thing of that type belongs.

**A match of paragraph and type alone is not coverage.** It says the card looked at that part of
the article; it does not say the card carried this item. Two claims can stand in one paragraph and
the card carry one of them, and both would match the same value by address. So such a match is
reported as *awaiting an answer*, and the converter may answer it either way: with a sentence naming
the value and what in it carries the item (--confirm FILE, JSON: {"i7": "why this value carries it"}),
or with a reason that the card read that paragraph and still does not hold this item (--reasons, the
same file as for an unmatched item). Both at once is reported as a P1: they contradict each other.
A match on the item's own quoted words is stronger evidence and needs no confirmation, and it is
still not a finding of fidelity: a value can quote the passage and lose the hedge the item records,
which the entailment pass and the critics' second lens are there to catch.

Matching is by paragraph, so an item of the abstract finds nothing when the card sources the same
statement to the body paragraph that gives it in full. The answer to that is a pointer, not a
sentence: --held FILE, JSON {"i7": "/added/layers/core/explains"}, and the script checks that the
pointer is a sourced value of this card, in a place where an item of that type belongs, and in
another paragraph than the item's own. That is a checked answer rather than a judged one; it still
says nothing about whether the value keeps the item's hedge.

Every item with no match is a P1, which is not by itself a defect of the card: it is a question the
report must answer, either by the card holding the item or by a line saying why it does not
(--reasons FILE, JSON: {"i7": "why the card does not hold it", ...}). A reason is **judged**, never
deterministic: it is a sentence a reader can disagree with, and this script neither grades it nor
treats its presence as proof.

So nothing here is ever reported as full or complete coverage. The counts are of kinds of evidence,
and the exit code is 1 while any item is unanswered — unmatched with no reason, or matched by
address alone with no confirmation. Read the table; do not read only the exit code.
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ohfkit  # noqa: E402

# Where a thing of each inventory type belongs in a card. A pointer matches when any pattern is in
# it. An item's type is matched against its own places only: a prediction in the evidence lines is
# not the same statement as a prediction in the predictions layer.
#
# `/core/assumptions` is a place for a `condition` and for a `limitation`: the standard's
# assumptions list holds a condition the hypothesis depends on, and an assumption the authors state
# about their own analysis ("a missing cause of death is missing at random") is also a limit they
# state on their own work. It was missing here until 0.8.6, so an inventory item that the card held
# as an assumption was reported as not in the card at all — found on the first card to carry
# assumptions and be reconciled with a second reader's inventory.
PLACES = {
    'claim': ('/core/statement', '/core/atoms/', '/core/explains', '/core/reinterprets',
              '/mechanism/', '/core/kind'),
    'scope': ('/core/scope', '/predictions/', '/profile/', '/evidence/lines/'),
    'condition': ('/core/scope', '/core/atoms/', '/core/assumptions/', '/predictions/',
                  '/core/testability', '/evidence/lines/'),
    'hedge': ('/core/atoms/', '/core/uncertainties', '/predictions/', '/evidence/lines/',
              '/core/statement'),
    'prediction': ('/predictions/', '/core/testability', '/core/opens'),
    'evidence_for': ('/evidence/lines/',),
    'evidence_against': ('/evidence/lines/', '/core/uncertainties'),
    # A reinterpretation's `current_interpretation` is the reading a finding is given today, which
    # the hypothesis disputes — a rival explanation, which is what an `alternative` item is. The
    # standard's own example reads "Sheltering cannot cause Y-linked gene loss, so Muller's
    # hypothesis is rejected" (spec/fields.md, core.reinterprets[]). Added in 0.8.7.
    'alternative': ('/core/alternative_explanations', '/core/reinterprets', '/predictions/'),
    'limitation': ('/core/uncertainties', '/core/assumptions/', '/core/testability',
                   '/evidence/lines/', '/gaps/'),
    'open_question': ('/core/opens', '/core/uncertainties', '/gaps/'),
}
# Directions of an evidence line, by the type of item the line can answer.
FOR = ('supports', 'confirms')
AGAINST = ('disputes', 'refutes', 'weakens')


def norm(text):
    return re.sub(r'\s+', ' ', str(text)).strip().lower()


def paragraph_of(card, src):
    """The paragraph or page number the source record `src` names, or None."""
    rec = card.get('added', {}).get('sources', {}).get(src)
    return ohfkit.para_number(rec.get('locator', '')) if isinstance(rec, dict) else None


def document_of(card, src):
    """What document the source record `src` reads, as the string the card names it by, or None.

    A paragraph number means nothing without it. A card that cites four articles has a paragraph 7
    in each of them, and the inventory being reconciled is of one article only.
    """
    rec = card.get('added', {}).get('sources', {}).get(src)
    if not isinstance(rec, dict):
        return None
    for key in ('source', 'artifact', 'uri', 'url'):
        if isinstance(rec.get(key), str) and rec[key].strip():
            return rec[key]
    return None


def in_article(value, article):
    """Whether this value reads the article the inventory is of.

    True when the article's id occurs in the document the value's source names. A value whose
    document cannot be determined is kept, with nothing claimed about it: a card that names its
    sources no other way would otherwise match nothing at all. A value that names a different
    document is dropped, which is the whole point.
    """
    if not article or value.get('document') is None:
        return True
    return str(article) in value['document']


def values(card):
    """Every sourced value of the card as (pointer, paragraph, text, direction of its line)."""
    out = []
    lines = card.get('added', {}).get('layers', {}).get('evidence', {}).get('lines', [])

    def direction_of(pointer):
        m = re.match(r'/added/layers/evidence/lines/(\d+)', pointer)
        if not m:
            return None
        d = lines[int(m.group(1))].get('direction')
        return norm(d.get('value')) if isinstance(d, dict) else None

    def walk(node, pointer):
        if isinstance(node, dict):
            if 'src' in node and isinstance(node['src'], str):
                text = node.get('value')
                quotes = [node[k] for k in ('basis_quote', 'quote') if isinstance(node.get(k), str)]
                out.append({'pointer': pointer, 'paragraph': paragraph_of(card, node['src']),
                            'document': document_of(card, node['src']),
                            'text': text if isinstance(text, str) else json.dumps(text, ensure_ascii=False),
                            'quotes': quotes, 'direction': direction_of(pointer)})
            for k, v in node.items():
                walk(v, f'{pointer}/{k}')
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, f'{pointer}/{i}')

    walk(card.get('added', {}).get('layers', {}), '/added/layers')
    walk(card.get('author', {}).get('layers', {}), '/author/layers')
    for i, gap in enumerate(card.get('added', {}).get('gaps', [])):
        out.append({'pointer': f'/added/gaps/{i}', 'paragraph': None, 'text': gap.get('reason', ''),
                    'quotes': [], 'direction': None, 'path': gap.get('path')})
    return out


def in_place(pointer, item_type):
    """True when a value at this pointer is a place where an item of this type belongs."""
    tail = pointer.split('/layers', 1)[-1] if '/layers' in pointer else pointer
    return any(part in tail for part in PLACES.get(item_type, ()))


def direction_fits(value, item_type):
    """An evidence line answers an item of the type its direction bears on."""
    if value['direction'] is None:
        return True
    if item_type == 'evidence_for':
        return any(d in value['direction'] for d in FOR)
    if item_type == 'evidence_against':
        return any(d in value['direction'] for d in AGAINST)
    return True


def paragraphs_of(item):
    out = [item.get('paragraph')] + list(item.get('also_in') or [])
    return [p for p in out if isinstance(p, int)]


def match(item, vals):
    """(matches, how) for one inventory item. `how` is 'quote' when the item's quoted words occur
    in a matching value or its basis, else 'paragraph+type', else None."""
    paras = paragraphs_of(item)
    cand = [v for v in vals if v['paragraph'] in paras and in_place(v['pointer'], item['type'])
            and direction_fits(v, item['type'])]
    if not cand:
        return [], None
    quote = norm(item.get('quote') or '')
    if quote:
        strong = [v for v in cand
                  if quote in norm(v['text']) or any(quote in norm(q) or norm(q) in quote for q in v['quotes'])]
        if strong:
            return strong, 'quote'
    return cand, 'paragraph+type'


def held_elsewhere(vals, pointer, item, article=None):
    """(row, problem) for a claim that `pointer` holds this item at another locator.

    An article states the same thing twice — once in the abstract, once in the body paragraph that
    gives it in full — and a converter sources the value to the body. Matching is by paragraph, so
    the abstract item finds nothing, though the card holds it. The answer is the pointer, which this
    checks: it must be a sourced value of this card, in a place where an item of this type belongs,
    and in a paragraph other than the item's own, since a value in the item's own paragraph is an
    address match and is answered as one.

    `vals` here is every sourced value of the card, not only those reading the article the inventory
    is of. A review states a result and a careful card sources it to the study that reported it, in
    another document — a value under another locator in the fullest sense. A pointer names its value
    outright, so no paragraph number can be confused across documents, which is the only reason the
    address matcher is restricted to one document at all.
    """
    row = next((v for v in vals if v['pointer'] == pointer), None)
    if row is None:
        return None, f'{pointer!r} is not a sourced value of this card'
    if not in_place(pointer, item['type']):
        return row, f'{pointer!r} is not a place where a {item["type"]} belongs'
    # The same test the address matcher applies: an evidence line answers an item of the type its
    # direction bears on. Without it a pointer could answer an evidence_for item with a line the
    # card records as disputing or as neutral, which the matcher would have refused on its own.
    if not direction_fits(row, item['type']):
        return row, (f'{pointer!r} is a line whose direction is {row["direction"]!r}, which does not '
                     f'bear on a {item["type"]} item')
    if row['paragraph'] in paragraphs_of(item) and in_article(row, article):
        return row, (f'{pointer!r} is in the item\'s own paragraph, so it is an address match: '
                     'confirm it instead')
    return row, None


def reconcile(inventory, card, reasons=None, confirmations=None, held=None):
    """One row per inventory item: its match, how it matched, the confirmation of a weak match,
    the pointer that holds it at another locator, and the reason when the card does not hold it."""
    reasons, confirmations, held = reasons or {}, confirmations or {}, held or {}
    article = (inventory.get('article') or {}).get('id')
    every = values(card)
    vals = [v for v in every if in_article(v, article)]
    rows = []
    for item in inventory['items']:
        if not isinstance(item.get('type'), str) or item['type'] not in PLACES:
            rows.append({'item': item.get('id'), 'type': item.get('type'), 'how': None, 'matched': [],
                         'problem': f'type {item.get("type")!r} is not one of {sorted(PLACES)}'})
            continue
        if not paragraphs_of(item):
            rows.append({'item': item['id'], 'type': item['type'], 'how': None, 'matched': [],
                         'problem': 'the item names no paragraph (references/inventory.md: every item does)'})
            continue
        matched, how = match(item, vals)
        row = {'item': item['id'], 'type': item['type'], 'paragraph': item.get('paragraph'),
               'how': how, 'matched': [v['pointer'] for v in matched]}
        if not matched:
            row['reason'] = reasons.get(item['id'])
        elif how == 'paragraph+type':
            # Two answers are open to an address match, and until 0.8.10 only the first was read.
            # A confirmation says a value carries the item. A reason says the card read that
            # paragraph and still does not hold this item, which is the ordinary case when two
            # statements stand in one paragraph and the card carries one of them. The report has
            # always offered both ("or record a reason"); the code accepted only the confirmation,
            # so an item the card does not hold had no truthful answer.
            row['confirmation'] = confirmations.get(item['id'])
            row['reason'] = reasons.get(item['id'])
        if item['id'] in held:
            pointer = held[item['id']]
            found, problem = held_elsewhere(every, pointer, item, article)
            row['held'] = pointer
            row['held_paragraph'] = found['paragraph'] if found else None
            if problem:
                row['held_problem'] = problem
        rows.append(row)
    same = {}
    for row in rows:
        for key in (row.get('confirmation'),):
            if key:
                same.setdefault(key.strip().lower(), []).append(row['item'])
    for items in same.values():
        if len(items) > 1:
            for row in rows:
                if row['item'] in items:
                    row['shared_confirmation'] = items
    return rows


def report(rows):
    """(text, number of unanswered items). An item is unanswered when it has no match and no reason,
    or when it matched by address alone and no confirmation names what carries it."""
    out, open_items = [], 0
    for r in rows:
        where = f'({r.get("type")}, paragraph {r.get("paragraph")})'
        if r.get('problem'):
            out.append(f'P1 {r["item"]}: {r["problem"]}')
            open_items += 1
        elif r.get('held_problem'):
            out.append(f'P1 {r["item"]} {where}: the pointer given as holding it does not: '
                       f'{r["held_problem"]}')
            open_items += 1
        elif r.get('held') and (r.get('reason') or r.get('confirmation')):
            out.append(f'P1 {r["item"]} {where}: a pointer says the card holds it at another locator and '
                       'another answer says otherwise; they cannot both stand, so choose')
            open_items += 1
        elif r.get('held'):
            out.append(f'{r["item"]} {where}: held at another locator -> {r["held"]} (paragraph '
                       f'{r["held_paragraph"]}): the pointer resolves to a sourced value of this card in a '
                       f'place where a {r.get("type")} belongs. Whether that value keeps the item\'s hedge '
                       'is for the entailment pass and lens b')
        elif r['matched'] and r['how'] == 'quote':
            out.append(f'{r["item"]} {where}: matched on its quoted words -> {", ".join(r["matched"][:3])}'
                       f'{" ..." if len(r["matched"]) > 3 else ""} (the words are there; whether the value keeps '
                       'the item\'s hedge is for the entailment pass and lens b)')
        elif r['matched'] and r.get('confirmation') and r.get('reason'):
            out.append(f'P1 {r["item"]} {where}: both a confirmation and a reason are recorded. One says a '
                       'value carries the item and the other says the card does not hold it; they cannot '
                       'both stand, so choose')
            open_items += 1
        elif r['matched'] and r.get('reason'):
            out.append(f'{r["item"]} {where}: matched by paragraph and type only -> '
                       f'{", ".join(r["matched"][:3])}; the card read that paragraph and does not hold this '
                       f'item, reason recorded (judged): {r["reason"]}')
        elif r['matched'] and not r.get('confirmation'):
            out.append(f'P1 {r["item"]} {where}: matched by paragraph and type ONLY -> '
                       f'{", ".join(r["matched"][:3])}: that is an address, not coverage. Confirm which value '
                       'carries it and what in it does, or record a reason')
            open_items += 1
        elif r['matched']:
            shared = (' SHARED with ' + ', '.join(i for i in r['shared_confirmation'] if i != r['item'])
                      + ': one value cannot carry two items' if r.get('shared_confirmation') else '')
            out.append(f'{r["item"]} {where}: matched by paragraph and type, confirmed (judged): '
                       f'{r["confirmation"]}{shared}')
        elif r.get('reason'):
            out.append(f'P1 {r["item"]} {where}: not in the card, reason recorded (judged): {r["reason"]}')
        else:
            out.append(f'P1 {r["item"]} {where}: not in the card and no reason recorded (put it in the card, '
                       'or record a reason with its paragraph)')
            open_items += 1
    answered = [r for r in rows if not r.get('problem') and not r.get('held_problem')]
    quoted = sum(1 for r in answered if r.get('how') == 'quote' and not r.get('held'))
    elsewhere = sum(1 for r in answered
                    if r.get('held') and not r.get('reason') and not r.get('confirmation'))
    confirmed = sum(1 for r in answered
                    if r['matched'] and r.get('confirmation') and not r.get('reason') and not r.get('held'))
    excused = sum(1 for r in answered if r.get('reason') and not r.get('confirmation') and not r.get('held'))
    shared = sum(1 for r in rows if r.get('shared_confirmation'))
    out.append(f'COVERAGE {len(rows)} items: {quoted} on the quoted words, {elsewhere} held at another '
               f'locator by a checked pointer, {confirmed} by address with a judged confirmation, {excused} '
               f'the card does not hold with a judged reason, {open_items} unanswered'
               + (f'; {shared} confirmed to a value another item also claims' if shared else '')
               + '. No count here is a finding of complete coverage.')
    return '\n'.join(out), open_items


def main():
    ap = argparse.ArgumentParser(description='Reconcile an article inventory with a card.')
    ap.add_argument('inventory')
    ap.add_argument('card')
    ap.add_argument('--reasons', help='JSON {item id: why the card does not hold it}')
    ap.add_argument('--confirm', help='JSON {item id: which value carries it and what in it does}')
    ap.add_argument('--held', help='JSON {item id: card pointer that holds it, sourced to another '
                                   'paragraph than the item\'s}')
    a = ap.parse_args()
    inventory = json.loads(Path(a.inventory).read_text())
    card = json.loads(Path(a.card).read_text())
    reasons = json.loads(Path(a.reasons).read_text()) if a.reasons else {}
    confirmations = json.loads(Path(a.confirm).read_text()) if a.confirm else {}
    held = json.loads(Path(a.held).read_text()) if a.held else {}
    text, open_items = report(reconcile(inventory, card, reasons, confirmations, held))
    print(text)
    sys.exit(1 if open_items else 0)


if __name__ == '__main__':
    main()
