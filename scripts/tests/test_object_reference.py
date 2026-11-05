"""A reference to a part of the card: an evidence line, a prediction, an atom.

Until 0.8.0 a card reference had to lead to a string, and a card that pointed at a whole evidence
line or a whole prediction could not be read at all: `check_ledger.check` raised. Half of the first
eight accepted cards point that way, so the kit had lost the ability to read what it had already
produced. These are the cases of the rule that replaces it.
"""
import copy

import pytest

import check_ledger
import entailment


class Doc:
    def __init__(self, paras):
        self.paras = paras

    def para(self, n):
        return self.paras[n - 1]


DOCS = {'u': Doc(['Mutants show branching of digits. The known result is that one.'])}
LINE = '/added/layers/evidence/lines/0'
PRED = '/added/layers/predictions/0'


def card(pointer=LINE, from_field='known_result_ref'):
    """A card whose prediction points at a part of the card rather than at a string."""
    return {'id': 'h_x', 'author': {'layers': {}},
            'added': {'sources': {'s': {'source': 'u', 'locator': 'PDF page 1'}},
                      'layers': {
                          'evidence': {'lines': [{'id': 'e_mutants', 'target_ref': 'p1',
                                                  'study_type': {'value': 'mutant phenotypes', 'src': 's'}}]},
                          'predictions': [{'id': 'p1',
                                           'population': {'value': 'mutants', 'src': 's'},
                                           'endpoint': {'value': 'branching of digits', 'src': 's'},
                                           from_field: {'value': {'kind': 'card', 'pointer': pointer},
                                                        'src': 's'}}]},
                      'integrity': {'entailment': []}}}


def test_a_reference_to_an_evidence_line_names_it_by_id():
    kind, text = check_ledger.card_reference(card(), LINE)
    assert (kind, text) == ('object', 'e_mutants')


def test_the_item_carries_the_id_under_names_and_is_decided_by_resolution():
    items = {x['pointer']: x for x in entailment.build(card(), DOCS)}
    x = items['/added/layers/predictions/0/known_result_ref']
    assert x['value'] == {'reference': {'kind': 'card', 'pointer': LINE}, 'names': 'e_mutants'}
    assert entailment.is_resolved(x)
    assert all(not i['pointer'].endswith('known_result_ref') for i in entailment.checker_items(items.values()))


def test_the_verdict_entails_and_its_note_says_it_claims_nothing_about_the_source():
    c = card()
    recs = entailment.resolve_references(c, DOCS, check_ledger.new_ledger(c))
    [r] = [r for r in recs if r['pointer'].endswith('known_result_ref')]
    assert r['verdict'] == 'entails' and r['checker']['name'] == 'ohf-reference-resolution'
    assert 'e_mutants' in r['note'] and 'nothing about the source' in r['note']


def test_a_reference_to_a_prediction_names_the_prediction():
    c = card(pointer=PRED, from_field='endpoint_ref')
    items = {x['pointer']: x for x in entailment.build(c, DOCS)}
    assert items['/added/layers/predictions/0/endpoint_ref']['value']['names'] == 'p1'


def test_pointing_the_reference_at_another_part_is_a_changed_value():
    """The id is what is hashed, so a repointed reference stops binding and is resolved again."""
    c = card()
    c['added']['layers']['evidence']['lines'].append({'id': 'e_other', 'target_ref': 'p1',
                                                      'study_type': {'value': 'another study', 'src': 's'}})
    led = check_ledger.new_ledger(c)
    entailment.merge(c, [], [], DOCS, led)
    old = copy.deepcopy(c)
    c['added']['layers']['predictions'][0]['known_result_ref']['value']['pointer'] = \
        '/added/layers/evidence/lines/1'
    key = '/added/layers/predictions/0/known_result_ref|src'
    kept, rest = entailment.carry(old, c, DOCS, led)
    assert all(not x['pointer'].endswith('known_result_ref') for x in rest)  # resolved, never checked
    [kept_ref] = [r for r in kept if r['pointer'].endswith('known_result_ref')]
    assert kept_ref['verdict'] == 'entails' and 'e_other' in kept_ref['note']
    first, second = led['entries'][key]  # the earlier check stays in the history
    assert first['value_sha256'] != second['value_sha256']


def test_a_part_with_neither_text_nor_an_id_stops_the_build():
    c = card(pointer='/added/sources/s')
    with pytest.raises(ValueError, match='neither text nor a part of the card with an id'):
        entailment.build(c, DOCS)


def test_a_pointer_that_leads_nowhere_stops_the_build():
    with pytest.raises(ValueError, match='does not resolve in the card'):
        entailment.build(card(pointer='/added/layers/evidence/lines/9'), DOCS)


# ----------------------------------------------------------- a record made under an earlier rendering

def legacy_card():
    """A card whose reference record was made before resolution existed: the checker is the
    entailment checker and the hashed value is the card's own bare value."""
    c = card()
    led = check_ledger.new_ledger(c)
    item = [x for x in entailment.build(c, DOCS) if x['pointer'].endswith('known_result_ref')][0]
    key = check_ledger.key_of(item)
    bare = c['added']['layers']['predictions'][0]['known_result_ref']['value']
    record = {'pointer': item['pointer'], 'basis': 'src', 'verdict': 'entails',
              'checker': {'name': 'ohf-entailment-check', 'version': '1.0.0', 'prompt_sha256': 'sha256:00'},
              'checked_at': '2026-10-20T18:31:01Z'}
    check_ledger.add_entry(led, key, {'value_sha256': check_ledger.value_sha256(bare),
                                      'passage_sha256': check_ledger.passage_sha256(item['source_passage']),
                                      'checked_at': record['checked_at'], 'verdict': 'entails'}, None)
    c['added']['integrity']['entailment'] = [record]
    for x in entailment.build(c, DOCS):
        if x['pointer'].endswith('known_result_ref'):
            continue
        k = check_ledger.key_of(x)
        r = {'pointer': x['pointer'], 'basis': x['basis'], 'verdict': 'entails',
             'checker': {'name': 'ohf-entailment-check', 'version': '1.0.0', 'prompt_sha256': 'sha256:00'},
             'checked_at': '2026-10-20T18:31:01Z'}
        check_ledger.add_entry(led, k, check_ledger.entry(x, r), None)
        c['added']['integrity']['entailment'].append(r)
    return c, led, key


def test_a_record_made_under_the_earlier_rendering_is_read_and_named():
    c, led, key = legacy_card()
    legacy = []
    errors = [e for e in check_ledger.check(c, led, None, legacy) if 'content_hash' not in e]
    assert errors == []
    assert legacy == [key]


def test_a_record_of_the_resolver_itself_gets_no_such_allowance():
    """The allowance is for a record that predates resolution. A resolver's own record whose
    value no longer matches is a changed value, and fails."""
    c, led, key = legacy_card()
    c['added']['integrity']['entailment'][0]['checker'] = copy.deepcopy(entailment.RESOLVER)
    errors = [e for e in check_ledger.check(c, led) if 'content_hash' not in e]
    assert any(key in e and 'differs from the value that was checked' in e for e in errors)


def test_the_next_rebuild_resolves_it_again():
    c, led, key = legacy_card()
    recs = entailment.resolve_references(c, DOCS, led)
    assert [r['pointer'] for r in recs] == ['/added/layers/predictions/0/known_result_ref']
    assert recs[0]['checker']['name'] == 'ohf-reference-resolution'
    assert len(led['entries'][key]) == 2  # the record read under the earlier rendering stays in the history
    legacy = []
    [e for e in check_ledger.check(c, led, None, legacy) if 'content_hash' not in e]
    assert legacy == []  # and is no longer read that way


def test_an_edited_card_is_still_caught_by_its_content_hash():
    """The allowance never hides an edit: a card changed after it was hashed fails on the hash,
    which is what binds the ledger to the card."""
    c, led, _ = legacy_card()
    c['content_hash'] = check_ledger._content_hash()(c)
    led['content_hash'] = c['content_hash']
    assert [e for e in check_ledger.check(c, led)] == []
    c['added']['layers']['evidence']['lines'][0]['study_type']['value'] = 'something else'
    assert any('content_hash' in e for e in check_ledger.check(c, led))
