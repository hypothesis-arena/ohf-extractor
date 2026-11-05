"""Invented source-mode conformance; no model, network or real-card input."""
from copy import deepcopy
import json
from pathlib import Path
import pytest
import ohfkit

if ohfkit.standard_line() != '1.4' or ohfkit.standard_release() < (1, 4, 2):
    pytest.skip('Explicit pinned OHF 1.4.2 source required', allow_module_level=True)

import check_ledger as ordinary
import entailment
import native_profile
import projection_binding as projection
from conftest import PMCID
from profile_fixture import ProfileFixture

KINDS = ('uncertainties', 'alternative_explanations', 'opens', 'explains')


def child(kind, number, atom='a_main'):
    source = 'p1' if number == 0 else 'p2'
    if kind == 'uncertainties':
        return {'id': 'q'+str(number), 'question': 'Does the invented square remain?', 'src': source}
    if kind == 'alternative_explanations':
        return {'id': 'alt'+str(number), 'claim_or_ref': {'kind': 'literal', 'text': 'An invented alternate panel.'}, 'src': source}
    if kind == 'opens':
        return {'id': 'o'+str(number), 'new_question': 'Could the invented panel change?',
                'why_not_askable_today': 'The invented instrument is absent.', 'atom_refs': [atom], 'src': source}
    return {'id': 'e'+str(number), 'observation': 'The invented circle appears.',
            'status': 'unexplained', 'mode': 'consequence', 'atom_refs': [atom], 'src': source}


def case(workdir, kind, mode='child-only'):
    doc = ohfkit.Document(PMCID, workdir)
    wrapper = {'value': [child(kind, 0), child(kind, 1)]}
    if mode != 'child-only': wrapper['src'] = 'p3'
    if mode == 'mixed-parent': wrapper['value'][1].pop('src')
    card = {'schema': 'ohf:hypothesis@1', 'id': 'invented_child_modes', 'version': 1,
            'standard_version': '1.4', 'identity': {'proposition_id': 'invented_child_modes', 'version': 1},
            'added': {'by': {'standard_release': {'version': '1.4.2'}},
                      'sources': {f'p{i}': doc.src(i) for i in (1, 2, 3)},
                      'layers': {'core': {kind: wrapper}}}}
    return card, {doc.url: doc}, wrapper


def semantic_items(items):
    return {(row['pointer'], row['basis']): (ordinary.value_sha256(row['value']), row.get('src'), row.get('source_passage'))
            for row in items}


@pytest.mark.parametrize('kind', KINDS)
@pytest.mark.parametrize('mode,expected', [('child-only', 2), ('parent', 3), ('mixed-parent', 2)])
def test_child_sourced_full_item_union_matches_reader_and_keeps_parent_whole(xml_workdir, kind, mode, expected):
    card, docs, wrapper = case(xml_workdir, kind, mode)
    saved = deepcopy(card)
    api = projection.reference()
    assert api.source_mode_errors(card) == []
    actual, wanted = ordinary.value_items(card), api.value_items(card)
    assert len(actual) == len(wanted) == expected
    assert semantic_items(actual) == semantic_items(wanted)
    parent = '/added/layers/core/'+kind
    parents = [row for row in actual if row['pointer'] == parent]
    if mode == 'child-only': assert parents == []
    else:
        assert len(parents) == 1 and parents[0]['value'] == wrapper['value']
        assert parents[0]['src'] == 'p3'
    built = entailment.checker_items(entailment.build(card, docs))
    assert len(built) == expected
    assert {(x['pointer'], x['basis']) for x in built} == {(x['pointer'], x['basis']) for x in actual}
    assert card == saved


@pytest.mark.parametrize('kind', KINDS)
@pytest.mark.parametrize('release', [None, '1.4.0', '1.4.1', '1.4.3', '1.5.0'])
def test_child_sourced_requires_the_explicit_known_patch_on_direct_producer_routes(xml_workdir, kind, release):
    card, docs, _ = case(xml_workdir, kind)
    if release is None: card['added']['by'].pop('standard_release')
    else: card['added']['by']['standard_release']['version'] = release
    api = projection.reference()
    assert api.source_mode_errors(card)[0]['code'] == 'REF_SOURCE_MODE'
    for route in (lambda: ordinary.value_items(card), lambda: entailment.build(card, docs)):
        with pytest.raises(ValueError, match='REF_SOURCE_MODE: /added/layers/core/'+kind): route()
    assert ordinary.check(card, None)[0].startswith('REF_SOURCE_MODE:')


@pytest.mark.parametrize('kind', KINDS)
@pytest.mark.parametrize('change', ['empty', 'no-child-src', 'blank-child-src', 'unresolved-src', 'assessment', 'extra'])
def test_child_sourced_wrapper_and_child_source_boundaries_refuse(xml_workdir, kind, change):
    card, docs, wrapper = case(xml_workdir, kind)
    if change == 'empty': wrapper['value'] = []
    elif change == 'no-child-src': wrapper['value'][1].pop('src')
    elif change == 'blank-child-src': wrapper['value'][1]['src'] = '  '
    elif change == 'unresolved-src': wrapper['value'][1]['src'] = 'invented-missing-source'
    elif change == 'assessment': wrapper['assessment'] = {'assessor': 'Invented'}
    else: wrapper['basis_quote'] = 'Invented extra wrapper member.'
    with pytest.raises(ValueError, match='REF_SOURCE_MODE: /added/layers/core/'+kind):
        entailment.build(card, docs)


@pytest.mark.parametrize('kind', KINDS)
@pytest.mark.parametrize('version', ['1.0', '1.1', '1.2', '1.3', '1.5'])
def test_child_sourced_does_not_extend_older_or_future_formats(xml_workdir, kind, version):
    card, docs, _ = case(xml_workdir, kind)
    card['standard_version'] = version
    with pytest.raises(ValueError, match='REF_SOURCE_MODE:'):
        entailment.build(card, docs)


@pytest.mark.parametrize('kind', KINDS)
def test_child_sourced_remains_outside_the_selected_native_subset(tmp_path, kind):
    fixture = ProfileFixture(tmp_path)
    fixture.card['added']['layers']['core'][kind] = {'value': [child(kind, 0)]}
    fixture.rehash()
    assert native_profile.schema_errors(fixture.card, fixture.selected) == []
    with pytest.raises(ValueError, match='UNSUPPORTED_SHAPE'):
        native_profile.build(fixture.card, fixture.docs, fixture.selected)


def test_child_sourced_definition4_preserves_scientific_contract_and_refuses_selector3():
    references = Path(native_profile.DEFINITION).parent
    previous = json.loads((references/'native-renderer-profile-3.json').read_bytes())
    current = json.loads(native_profile.DEFINITION.read_bytes())
    assert previous['standard_release'] == '1.4.1' and current['standard_release'] == '1.4.2'
    assert {k: v for k, v in previous.items() if k not in ('dependencies', 'standard_release')} == {
        k: v for k, v in current.items() if k not in ('dependencies', 'standard_release')}
    with pytest.raises(ValueError, match='UNSUPPORTED_PROFILE'):
        native_profile.require_profile({'id': 'ohf-native-relational@1', 'epoch': 2,
            'definition_sha256': projection.value_sha256(previous)})


def pinned_source_copy(tmp_path, monkeypatch):
    import os
    source = Path(os.environ['OHF_REPO'])
    for name in ('tools/check_ledger.py', 'tools/content_hash.py', 'schema/hypothesis-1.schema.json',
                 'spec/field-catalogue.json'):
        target = tmp_path/name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((source/name).read_bytes())
    monkeypatch.setenv('OHF_REPO', str(tmp_path))
    monkeypatch.setattr(projection, '_modules', {})
    return tmp_path/'schema/hypothesis-1.schema.json'


@pytest.mark.parametrize('warm', [False, True])
@pytest.mark.parametrize('change', ['tampered', 'missing'])
def test_child_sourced_schema_pin_refuses_drift_before_cold_or_cached_use(tmp_path, monkeypatch, warm, change):
    schema = pinned_source_copy(tmp_path, monkeypatch)
    if warm:
        projection.reference()
    if change == 'tampered':
        schema.write_bytes(schema.read_bytes()+b' ')
    else:
        schema.unlink()
    reason = 'projection schema pin differs' if change == 'tampered' else 'pinned projection schema unavailable'
    with pytest.raises(ValueError, match=reason):
        projection.reference()


def test_child_sourced_gate_uses_the_verified_schema_snapshot(xml_workdir, tmp_path, monkeypatch):
    card, _, _ = case(xml_workdir, 'uncertainties')
    schema = pinned_source_copy(tmp_path, monkeypatch)
    changed = json.loads(schema.read_bytes())
    changed['$defs']['added:core.uncertainties[]:children']['properties']['value']['maxItems'] = 0
    api = projection.reference()
    # Change actual bytes after capture, before the Standard rule's data read.
    schema.write_bytes(json.dumps(changed).encode())
    assert api.source_mode_errors(card) == []
    assert len(api.value_items(card)) == 2
    with pytest.raises(ValueError, match='projection schema pin differs'):
        projection.reference()


@pytest.mark.parametrize('kind', KINDS)
def test_child_sourced_does_not_widen_author_wrappers(xml_workdir, kind):
    card, _, wrapper = case(xml_workdir, kind)
    # A value-only wrapper in the author zone is not the new added-zone form.
    card['author'] = {'layers': {'core': {kind: deepcopy(wrapper)}}}
    card['added']['layers']['core'] = {}
    schema = json.loads((Path(__import__('os').environ['OHF_REPO'])/'schema/hypothesis-1.schema.json').read_bytes())
    from jsonschema import Draft202012Validator
    author = schema['$defs']['author:core.'+kind+'[]']
    assert list(Draft202012Validator({'$defs': schema['$defs'], **author}).iter_errors(wrapper))


@pytest.mark.parametrize('version', [None, '1.0', '1.1', '1.2', '1.3', '1.5'])
def test_child_sourced_local_format_refusal_is_independent_of_the_standard_guard(xml_workdir, monkeypatch, version):
    card, _, _ = case(xml_workdir, 'uncertainties')
    api = ordinary._projection_module().reference()
    calls = []
    monkeypatch.setattr(api, 'require_source_modes', lambda value: calls.append(value['standard_version']))
    card['standard_version'] = version
    with pytest.raises(ValueError, match='REF_SOURCE_MODE: /added/layers/core/uncertainties'):
        ordinary.require_source_modes(card)
    assert calls == []
    # The same no-op really is selected when the local format condition permits it.
    card['standard_version'] = '1.4'
    assert ordinary.require_source_modes(card) is None
    assert calls == ['1.4']


@pytest.mark.parametrize('kind', KINDS)
def test_child_sourced_direct_checked_value_refuses_before_returning_an_invalid_mode(xml_workdir, monkeypatch, kind):
    card, _, wrapper = case(xml_workdir, kind)
    pointer = '/added/layers/core/'+kind+'/value/0'
    node = wrapper['value'][0]
    def no_prior_route(*args, **kwargs):
        raise AssertionError('direct checked_value must not depend on sourced/check admission')
    monkeypatch.setattr(ordinary, 'sourced', no_prior_route)
    monkeypatch.setattr(ordinary, 'check', no_prior_route)
    card['added']['by']['standard_release']['version'] = '1.4.1'
    saved = deepcopy(card)
    with pytest.raises(ValueError, match='REF_SOURCE_MODE: /added/layers/core/'+kind):
        ordinary.checked_value(card, pointer, node)
    assert card == saved
    card['added']['by']['standard_release']['version'] = '1.4.2'
    assert ordinary.checked_value(card, pointer, node) == {key: value for key, value in node.items() if key != 'src'}
