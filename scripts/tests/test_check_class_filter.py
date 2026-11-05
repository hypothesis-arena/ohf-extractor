"""Invented ordinary passage/card/resolution selection, not whole-card admission."""
from copy import deepcopy

import pytest

import check_ledger
import entailment
import ohfkit
import projection_binding
from conftest import PMCID, RETRIEVED, jats


@pytest.fixture
def reader():
    if ohfkit.standard_line() != '1.4':
        pytest.skip('The catalogue oracle requires the explicit pinned OHF 1.4 primary; '
                    'historical selection has separate positive controls.')
    return projection_binding.reference()


def mixed_card(version='1.4'):
    return {
        'id': 'h_invented_classes', 'standard_version': version,
        'added': {'layers': {
            'core': {
                'scope': {'value': 'An invented panel scope.', 'src': 'p1',
                          'basis_quote': 'invented panel'},
                'atoms': [{'id': 'A1', 'statement': {
                    'value': 'An invented atom.', 'src': 'p1'}}],
            },
            'predictions': [{
                'id': 'P1',
                'population': {'value': 'Invented panels.', 'src': 'p1'},
                'derives_from_atom_refs': {
                    'value': ['A1'], 'src': 'not-a-passage',
                    'basis_quote': 'This is a card reference, not a quotation check.'},
                'system': {'taxon_id': {
                    'value': 'NCBI:0001', 'src': 'not-a-passage',
                    'basis_quote': 'This identifier requires resolution.'}},
            }],
            'evidence': {'lines': []},
        }, 'integrity': {'entailment': []}},
    }


EXCLUDED = (
    ('/added/layers/predictions/0/derives_from_atom_refs', 'card'),
    ('/added/layers/predictions/0/system/taxon_id', 'resolution'),
)
PASSAGE_KEYS = {
    '/added/layers/core/scope|src',
    '/added/layers/core/scope|basis_quote',
    '/added/layers/core/atoms/0/statement|src',
    '/added/layers/predictions/0/population|src',
}


@pytest.mark.parametrize('pointer,classification', EXCLUDED)
def test_nonpassage_wrapper_has_neither_src_nor_quote_checker_item(reader, pointer, classification):
    card = mixed_card()
    before = deepcopy(card)
    assert reader.check_class(card, pointer) == classification
    assert pointer not in dict(check_ledger.sourced(card))
    assert not any(item['pointer'] == pointer for item in check_ledger.value_items(card))
    assert card == before


def test_full_three_class_union_matches_reader_without_changing_passage_values(reader):
    card = mixed_card()
    before = deepcopy(card)
    own = check_ledger.value_items(card)
    expected = reader.value_items(card)
    assert own == expected
    assert {check_ledger.key_of(item) for item in own} == PASSAGE_KEYS
    assert dict(check_ledger.sourced(card)) == dict(reader.sourced(card))
    assert own[0] == {'pointer': '/added/layers/core/scope', 'basis': 'src',
                      'value': 'An invented panel scope.', 'src': 'p1'}
    assert own[1] == {'pointer': '/added/layers/core/scope', 'basis': 'basis_quote',
                      'value': 'An invented panel scope.', 'source_passage': 'invented panel'}
    assert card == before


def test_entailment_build_never_looks_up_nonpassage_wrapper_sources(reader, tmp_path):
    (tmp_path / f'{PMCID}.xml').write_bytes(jats(['An invented panel scope and atom.']))
    (tmp_path / f'{PMCID}.xml.retrieved').write_text(RETRIEVED)
    doc = ohfkit.Document(PMCID, tmp_path)
    card = mixed_card()
    card['added']['sources'] = {'p1': doc.src(1)}
    before = deepcopy(card)
    items = entailment.build(card, {doc.url: doc})
    expected = {reader.key_of(item): item for item in reader.value_items(card)}
    assert {check_ledger.key_of(item) for item in items} == PASSAGE_KEYS
    for item in items:
        row = expected[check_ledger.key_of(item)]
        assert item['value'] == row['value']
        assert item['source_passage'] == (doc.para(1) if item['basis'] == 'src'
                                          else row['source_passage'])
    assert card == before


def test_member_checked_wrapper_emits_only_its_passage_members(reader):
    card = mixed_card()
    wrapper = {'value': {'reason': 'invented', 'record_ref': 'record1', 'locator': 'p1',
                         'paraphrase': 'An invented paraphrase.',
                         'abstract_quote': 'An invented abstract quotation.'}, 'src': 'p1'}
    card['added']['layers']['evidence']['lines'] = [{'id': 'E1', 'quote_withheld': wrapper}]
    pointer = '/added/layers/evidence/lines/0/quote_withheld'
    before = deepcopy(card)
    assert reader.check_class(card, pointer) is None
    expected_members = {'paraphrase', 'abstract_quote'}
    assert {name for name, kind in reader.by_member(card, pointer).items()
            if kind == 'passage'} == expected_members
    own = check_ledger.value_items(card)
    assert own == reader.value_items(card)
    assert {item['pointer'] for item in own if item['pointer'].startswith(pointer)} == {
        pointer + '/value/' + name for name in expected_members}
    assert card == before


@pytest.mark.parametrize('version', [None, '1.0', '1.1', '1.2', '1.3', '1.5', '2.0'])
def test_non_1_4_selection_keeps_the_local_walk_without_new_projection_requirement(monkeypatch, version):
    card = mixed_card(version)
    def unexpected_reference():
        raise AssertionError('Non-1.4 selection must not acquire a new projection dependency')
    monkeypatch.setattr(check_ledger, '_projection_module', unexpected_reference)
    nodes = dict(check_ledger.sourced(card))
    assert all(pointer in nodes for pointer, _classification in EXCLUDED)
    assert nodes['/added/layers/core/scope']['value'] == 'An invented panel scope.'
