"""Invented ordinary checked-value components; no card, model or source retrieval."""
from copy import deepcopy

import pytest

import check_ledger
import entailment
import native_ledger
import ohfkit
import projection_binding
from conftest import PMCID


CASES = (
    ('sample', {'population': 'whole_sample', 'outcome': 'primary', 'analysis': 'pre_specified'}),
    ('sample_size', 48),
    ('multi_site_program', {'program': 'Invented panels', 'sites': 3}),
    ('result_estimate', {'reported': 'two panels', 'measure': 'count',
                         'contrast': 'blue versus blank', 'scale': 'absolute'}),
    ('result_estimate', 'two panels'),
)
FIELDS = ('sample', 'sample_size', 'multi_site_program', 'result_estimate')


@pytest.fixture
def standard_reader():
    if ohfkit.standard_line() != '1.4':
        pytest.skip('This conformance oracle requires the explicit pinned OHF 1.4 primary; '
                    'legacy renderings have separate positive controls.')
    return projection_binding.reference()


def component(field, value, version='1.4', quote=True):
    # Component API inputs, not a claim of whole-card schema validity. In particular,
    # the string probes the bare-value API independently of the field's wire schema.
    node = {'value': deepcopy(value), 'src': 'p1'}
    line = {field: node, 'src': 'p1'}
    if quote:
        line['quote'] = 'An invented panel observation.'
    card = {'id': 'h_invented', 'standard_version': version,
            'added': {'layers': {'core': {}, 'evidence': {'lines': [line]}},
                      'integrity': {'entailment': []}}}
    return card, f'/added/layers/evidence/lines/0/{field}', node, line


@pytest.mark.parametrize('field,value', CASES)
@pytest.mark.parametrize('quote', [False, True])
def test_each_ordinary_class_equals_the_standard_bare_value(standard_reader, field, value, quote):
    card, pointer, node, line = component(field, value, quote=quote)
    before = deepcopy((card, node))
    expected = standard_reader.checked_value(card, pointer, node)
    assert expected == value
    assert check_ledger.checked_value(card, pointer, node) == expected
    assert (card, node) == before
    # The separately defined native contract retains its exact conditioning.
    native = {field: value, **({'line_quote': line['quote']} if quote else {})}
    assert native_ledger.checked_value(card, pointer, node) == native


def test_all_quote_classes_are_in_the_conformance_cases():
    assert set(field for field, _value in CASES) == set(FIELDS) == set(check_ledger.WITH_QUOTE)


@pytest.mark.parametrize('version', ['1.0', '1.1', '1.2', '1.3'])
@pytest.mark.parametrize('field,value', CASES)
def test_pre_1_4_rendering_keeps_the_quote_and_field_name(version, field, value):
    card, pointer, node, line = component(field, value, version=version)
    assert check_ledger.checked_value(card, pointer, node) == {
        field: value, 'line_quote': line['quote']}


def test_full_ordinary_input_union_uses_reader_values_and_source_bindings(standard_reader, xml_workdir):
    doc = ohfkit.Document(PMCID, xml_workdir)
    card, _pointer, _node, line = component(*CASES[0])
    line.update({field: {'value': deepcopy(value), 'src': 'p1'} for field, value in CASES[:4]})
    card['added']['sources'] = {'p1': doc.src(1)}
    own = {check_ledger.key_of(x): x for x in check_ledger.value_items(card)}
    reference = {standard_reader.key_of(x): x for x in standard_reader.value_items(card)}
    assert set(own) == set(reference) == {
        f'/added/layers/evidence/lines/0/{field}|src' for field in FIELDS}
    assert own == reference
    inputs = entailment.build(card, {doc.url: doc})
    assert len(inputs) == 4
    for item in inputs:
        key = check_ledger.key_of(item)
        assert item['value'] == reference[key]['value']
        assert item['source_passage'] == doc.para(1)
        assert own[key]['src'] == 'p1'


@pytest.mark.parametrize('field,value', CASES)
def test_wrapped_history_stays_history_and_cannot_back_the_bare_value(standard_reader, field, value):
    card, pointer, node, line = component(field, value)
    passage = 'An invented panel observation.'
    item = {'pointer': pointer, 'basis': 'src', 'value': check_ledger.checked_value(card, pointer, node),
            'source_passage': passage}
    assert item['value'] == standard_reader.checked_value(card, pointer, node)
    record = {'pointer': pointer, 'basis': 'src', 'verdict': 'entails',
              'checked_at': '2026-01-01T00:00:00Z'}
    old = {**item, 'value': {field: value, 'line_quote': line['quote']}}
    history = [check_ledger.entry(old, record)]
    saved = deepcopy(history)
    active, error = check_ledger._active_for(node, check_ledger.key_of(item), item,
                                           record, history, None, legacy=[], card=card)
    assert active == []
    assert 'the value differs from the value that was checked' in error
    assert check_ledger.active(history, check_ledger.value_sha256(item['value'])) == []
    assert history == saved
    current = check_ledger.entry(item, record)
    assert current['value_sha256'] == standard_reader.value_sha256(value)
    assert check_ledger.active([current], current['value_sha256'], current['passage_sha256']) == [current]


@pytest.mark.parametrize('field,value', CASES[:4])
def test_old_wrapped_checker_input_refuses_before_any_merge_write(standard_reader, xml_workdir, field, value):
    doc = ohfkit.Document(PMCID, xml_workdir)
    card, pointer, node, line = component(field, value)
    card['added']['sources'] = {'p1': doc.src(1)}
    docs = {doc.url: doc}
    inputs = entailment.build(card, docs)
    assert len(inputs) == 1 and inputs[0]['value'] == standard_reader.checked_value(card, pointer, node)
    stale = deepcopy(inputs)
    stale[0]['value'] = {field: value, 'line_quote': line['quote']}
    ledger = check_ledger.new_ledger(card)
    before = deepcopy((card, ledger))
    with pytest.raises(ValueError, match='the card no longer matches the checker input'):
        entailment.merge(card, stale, [{'id': stale[0]['id'], 'verdict': 'entails'}], docs, ledger)
    assert (card, ledger) == before
