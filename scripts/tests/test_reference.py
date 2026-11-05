"""A reference to a value in the same card is decided by resolution, not by the checker."""
import copy

import pytest

import check_ledger
import entailment

PLAN = '/author/layers/appendix/experiment_plan'


class Doc:
    def __init__(self, paras):
        self.paras = paras

    def para(self, n):
        return self.paras[n - 1]


def card(plan='Measure flux after calibration.', pointer=PLAN):
    return {'id': 'h_x', 'author': {'layers': {'appendix': {'experiment_plan': {'value': plan}}}},
            'added': {'sources': {'s': {'source': 'u', 'locator': 'API record field 1 /plan'}},
                      'layers': {'predictions': [{'id': 'p1', 'test_plan_ref': {
                          'value': {'kind': 'card', 'pointer': pointer}, 'src': 's'}}]},
                      'integrity': {'entailment': []}}}


DOCS = {'u': Doc(['First,  measure flux after calibration. Then compare.'])}


def test_reference_is_not_sent_to_the_checker():
    items = entailment.build(card(), DOCS)
    assert len(items) == 1 and entailment.is_resolved(items[0])
    assert items[0]['value']['target'] == 'Measure flux after calibration.'
    assert entailment.checker_items(items) == []


def test_reference_whose_target_is_in_the_passage_entails():
    c = card(plan='measure flux after calibration.')
    led = check_ledger.new_ledger(c)
    recs = entailment.resolve_references(c, DOCS, led)
    assert [(r['verdict'], r['checker']['name']) for r in recs] == [('entails', 'ohf-reference-resolution')]
    assert entailment.resolve_references(c, DOCS, led) == []  # same text: not resolved twice


def test_reference_whose_target_is_not_in_the_passage_is_no_with_a_note():
    c = card(plan='Something the record never says.')
    recs = entailment.resolve_references(c, DOCS, check_ledger.new_ledger(c))
    assert recs[0]['verdict'] == 'no' and PLAN in recs[0]['note']


def test_unresolvable_pointer_stops_the_build():
    with pytest.raises(ValueError, match='does not resolve'):
        entailment.build(card(pointer='/author/layers/appendix/missing'), DOCS)


def test_merge_writes_the_resolution_record_and_refuses_it_in_the_input():
    c = card(plan='measure flux after calibration.')
    led = check_ledger.new_ledger(c)
    entailment.merge(c, [], [], DOCS, led)
    [r] = c['added']['integrity']['entailment']
    assert r['verdict'] == 'entails' and r['checker'] == entailment.RESOLVER
    inp = [dict(x, id='r1') for x in entailment.build(c, DOCS)]
    with pytest.raises(ValueError, match='decided by resolution'):
        entailment.merge(c, inp, [{'id': 'r1', 'verdict': 'entails'}], DOCS, led)


def test_changed_target_is_resolved_again_and_history_is_kept():
    c = card(plan='measure flux after calibration.')
    led = check_ledger.new_ledger(c)
    entailment.merge(c, [], [], DOCS, led)
    old = copy.deepcopy(c)
    c['author']['layers']['appendix']['experiment_plan']['value'] = 'A plan the record does not state.'
    kept, rest = entailment.carry(old, c, DOCS, led)
    assert rest == [] and [r['verdict'] for r in kept] == ['no']
    assert [e['verdict'] for e in led['entries']['/added/layers/predictions/0/test_plan_ref|src']] == ['entails', 'no']


def test_recheck_does_not_drop_a_reference_record():
    c = card(plan='measure flux after calibration.')
    led = check_ledger.new_ledger(c)
    entailment.merge(c, [], [], DOCS, led)
    kept, rest = entailment.carry(copy.deepcopy(c), c, DOCS, led, recheck='test_plan_ref')
    assert rest == [] and len(kept) == 1


def test_references_inside_a_list_go_to_the_checker_with_their_targets():
    c = card()
    c['added']['layers']['core'] = {'alternative_explanations': {
        'value': [{'claim_or_ref': {'kind': 'literal', 'text': 'An independent mixture.'}}], 'src': 's'}}
    c['added']['layers']['predictions'][0]['also_expected_under'] = {
        'value': [{'kind': 'alternative', 'ref': {'kind': 'card',
                                                   'pointer': '/added/layers/core/alternative_explanations/value/0'}}],
        'src': 's'}
    items = {x['pointer']: x for x in entailment.build(c, DOCS)}
    x = items['/added/layers/predictions/0/also_expected_under']
    assert x['value']['targets'] == {'/added/layers/core/alternative_explanations/value/0': 'An independent mixture.'}
    assert not entailment.is_resolved(x) and x in [dict(i, id=i['id']) for i in entailment.build(c, DOCS)]
    assert any(i['pointer'].endswith('also_expected_under') for i in entailment.checker_items(entailment.build(c, DOCS)))
