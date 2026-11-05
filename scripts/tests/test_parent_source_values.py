"""Invented full-list component cases; no historical card or article payloads."""
import copy

import pytest
import check_ledger
import ohfkit


PARENTS = (
    '/added/layers/core/uncertainties',
    '/added/layers/core/alternative_explanations',
    '/added/layers/core/opens',
    '/added/layers/core/explains',
    '/added/layers/evidence/excluded',
)


@pytest.mark.parametrize('pointer', PARENTS)
@pytest.mark.parametrize('all_children_sourced', [False, True])
def test_complete_parent_value_retains_every_child(pointer, all_children_sourced):
    # Direct checked_value contract for every kind. Serialized evidence.excluded is
    # a plain array, not a sourced wrapper: its wrapper here is a component input,
    # not a claimed schema-valid card or a new serialization accepted by the kit.
    children = [
        {'id': 'invented_first', 'text': 'An invented first item.', 'src': 'p_child'},
        {'id': 'invented_second', 'text': 'An invented second item.'},
    ]
    if all_children_sourced:
        children[1]['src'] = 'p_other_child'
    node = {'value': children, 'src': 'p_parent'}
    card = {'standard_version': '1.4', 'added': {'layers': {}}}
    before = copy.deepcopy((card, node))
    actual = check_ledger.checked_value(card, pointer, node)
    assert actual == children
    assert [item['id'] for item in actual] == ['invented_first', 'invented_second']
    assert actual[0]['src'] == 'p_child'
    if all_children_sourced:
        assert actual[1]['src'] == 'p_other_child'
    assert (card, node) == before
    if ohfkit.standard_line() == '1.4':
        from projection_binding import reference
        assert actual == reference().checked_value(card, pointer, node)
    # An old empty/filtered input is different history, never a check of this value.
    old_value = [item for item in children if 'src' not in item]
    assert check_ledger.value_sha256(actual) != check_ledger.value_sha256(old_value)
    passage_sha = check_ledger.passage_sha256('An invented parent passage.')
    history = [{'value_sha256': check_ledger.value_sha256(old_value),
                'passage_sha256': passage_sha, 'verdict': 'entails',
                'checked_at': '2026-10-31T00:00:00Z'}]
    assert check_ledger.active(history, check_ledger.value_sha256(actual), passage_sha) == []
    saved_history = copy.deepcopy(history)
    old_ledger = {'format': 'ohf-entailment-ledger/2', 'entries': {pointer + '|src': history},
                  'notes': {}, 'card_id': 'h_invented', 'content_hash': 'sha256:' + 'a' * 64}
    assert check_ledger.upgrade(old_ledger)['entries'][pointer + '|src'] == saved_history
    legacy = []
    current_item = {'pointer': pointer, 'basis': 'src', 'value': actual,
                    'source_passage': 'An invented parent passage.'}
    record = {'pointer': pointer, 'basis': 'src', 'verdict': 'entails',
              'checked_at': history[0]['checked_at']}
    active, error = check_ledger._active_for(
        node, pointer + '|src', current_item, record, history, None, legacy=legacy, card=card)
    assert active == []
    assert 'the value differs from the value that was checked' in error
    assert legacy == []  # Reading the old entry does not make the current record pass.
    assert history == saved_history
