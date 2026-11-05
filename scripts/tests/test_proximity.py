"""biodb.py proximity: OHF 1.1 human_proximity derived by the standard's own check_refs, or a gap.

The derivation is the standard's, so these tests run against a checkout of it, given in OHF_STANDARD,
and pin what they rest on, not a version string: the checkout's VERSION is OHF 1.1.1 or later, and its
tools/check_refs.py is the one they were written against (the same bytes in 1.1.1 and 1.1.2). A
checkout whose check_refs.py differs is skipped with the reason. Without OHF_STANDARD they are skipped.
"""
import copy
import hashlib
import json
import os
from pathlib import Path

import pytest

import biodb

STANDARD = os.environ.get('OHF_STANDARD')
pytestmark = pytest.mark.skipif(not STANDARD, reason='set OHF_STANDARD to a checkout of OHF 1.1.1')
RELEASE = {'VERSION': '1.1.1',
           'tools/check_refs.py': '7973141b5c39272f3180d5dabde065c9221276def9102347651c18385fdc6bee'}
RAPA = 'examples/cards/intermittent-rapamycin-mtorc2.json'


def release(version):
    return tuple(int(x) for x in version.split('.'))


@pytest.fixture(scope='module')
def standard():
    root = Path(STANDARD)
    version = (root / 'VERSION').read_text().strip()
    # A checkout older than the release these tests pin is a reason to skip, not to fail: the
    # derivation they exercise does not exist there. Asserting it turned a legitimate combination -
    # OHF_STANDARD pointing at 1.0.1 - into twelve errors that said nothing about the code. The same
    # finding a review had just made about my element tests, in another module.
    if release(version) < release(RELEASE['VERSION']):
        pytest.skip(f'these tests are written against OHF {RELEASE["VERSION"]} or later; '
                    f'OHF_STANDARD names {version}')
    if hashlib.sha256((root / 'tools/check_refs.py').read_bytes()).hexdigest() != RELEASE['tools/check_refs.py']:
        pytest.skip(f'OHF {version}: tools/check_refs.py is not the one these tests were written against')
    return root


def stripped(standard):
    card = json.loads((standard / RAPA).read_text())
    declared = [(line.pop('human_proximity', None) or {}).get('value')
                for line in card['added']['layers']['evidence']['lines']]
    return card, declared


def with_lines(card, *lines):
    card = copy.deepcopy(card)
    card['added']['layers']['evidence']['lines'] = list(lines)
    return card


def line(taxon_id=None, term=None, declared=None, taxon='subjects'):
    system = {'taxon': {'value': taxon, 'src': 's1'}}
    if taxon_id:
        system['taxon_id'] = {'value': taxon_id, 'src': 'biodb_0123456789ab'}
    out = {'id': f'e_{taxon_id}_{term}', 'system': system}
    if term:
        out['endpoint_kind'] = {'value': 'an endpoint', 'src': 's1', 'term': term}
    if declared:
        out['human_proximity'] = {'value': declared, 'src': 'biodb_0123456789ab'}
    return out


def test_the_rapa_example_gets_back_every_rung_the_standard_derives_and_a_gap_for_the_rest(standard, tmp_path):
    card, declared = stripped(standard)
    (tmp_path / 'card.json').write_text(json.dumps(card))
    report = biodb.card_proximity(tmp_path / 'card.json', standard, out=tmp_path / 'placed.json')
    values = [v['value'] for v in report['lines']]
    # Every line with a taxon id gets the rung the example declares, sourced to its taxon id's call.
    assert sum(v is not None for v in values) == 47
    assert all(v == d for v, d in zip(values, declared) if v is not None)
    # The three lines naming a group (flies, mammalian, mice and marmosets) declare a rung in the example,
    # which check_refs cannot derive (a warning). The kit gives a gap instead, never a default.
    gaps = {v['line']: v['gap']['reason'] for v in report['lines'] if v['value'] is None}
    assert len(gaps) == 8
    assert {k for k, r in gaps.items() if 'names no one taxon by id' in r} == {
        'e_mtorc2_models', 'e_hallmarks_adverse', 'e_osteo_akt'}
    assert sum('states no system' in r for r in gaps.values()) == 5
    assert report['placed'] == {'values': 47, 'gaps': 8, 'kept': 0}
    assert report['check_refs'] == {'valid': True, 'proximity': []}
    placed = json.loads((tmp_path / 'placed.json').read_text())
    assert placed['content_hash'] == report['content_hash'] != card['content_hash']
    first = placed['added']['layers']['evidence']['lines'][0]
    assert first['human_proximity'] == {'value': 'mammal', 'src': first['system']['taxon_id']['src']}


def test_the_human_rung_follows_the_endpoint_kind_as_released(standard):
    card, _ = stripped(standard)
    human = 'NCBITaxon:9606'
    lines = [line(human, 'molecular'), line(human, 'lifespan'), line(human, 'biomarker'), line(human, 'mortality'),
             line(human, 'behaviour'), line(human, 'other'), line(human)]
    got = biodb.proximity_values(with_lines(card, *lines), standard)
    assert [v['value'] for v in got] == ['human_marker', 'human_clinical', 'human_marker', 'human_clinical',
                                         None, None, None]
    assert all('a human line with endpoint kind' in v['gap']['reason'] for v in got[4:])


def test_a_taxa_row_adds_a_taxon_and_a_taxon_without_a_rung_gets_a_gap(standard):
    card, _ = stripped(standard)
    taxa = {'taxa': [{'id': 'NCBITaxon:9598', 'label': 'Pan troglodytes', 'proximity': 'mammal',
                      'by': 'NCBITaxon:40674 Mammalia', 'call_id': 'c0ffee000001'},
                     {'id': 'NCBITaxon:4932', 'label': 'Saccharomyces cerevisiae', 'proximity': None,
                      'by': 'not an animal', 'call_id': 'c0ffee000002'},
                     # A row never overrides the pinned table.
                     {'id': 'NCBITaxon:10090', 'label': 'Mus musculus', 'proximity': 'invertebrate', 'by': 'wrong'}]}
    got = biodb.proximity_values(with_lines(card, line('NCBITaxon:9598', 'lifespan'), line('NCBITaxon:4932', 'lifespan'),
                                            line('NCBITaxon:10090', 'lifespan'), line('NCBITaxon:1423', 'lifespan')),
                                 standard, taxa)
    assert got[0]['value'] == 'mammal' and 'taxa.json row (call c0ffee000001)' in got[0]['by']
    assert got[1]['value'] is None and 'has no rung: not an animal' in got[1]['gap']['reason']
    assert got[2]['value'] == 'mammal' and got[2]['by'] == 'pinned table of the standard'
    assert got[3]['value'] is None and 'neither the pinned taxon table nor taxa.json' in got[3]['gap']['reason']


def test_a_declared_rung_is_kept_and_a_disagreement_is_said(standard):
    card, _ = stripped(standard)
    lines = [line('NCBITaxon:9606', 'molecular', declared='mammal'), line(declared='in_vitro'),
             line('NCBITaxon:7227', 'lifespan')]
    got = biodb.proximity_values(with_lines(card, *lines), standard)
    assert got[0]['value'] == 'human_marker' and 'left as declared' in got[0]['disagrees']
    assert got[1]['value'] == 'in_vitro' and 'disagrees' not in got[1]
    placed, counts = biodb.place_proximity(with_lines(card, *lines), got)
    out = placed['added']['layers']['evidence']['lines']
    assert out[0]['human_proximity']['value'] == 'mammal' and out[2]['human_proximity']['value'] == 'invertebrate'
    assert counts == {'values': 1, 'gaps': 0, 'kept': 2}


def test_a_gap_already_there_is_not_written_twice(standard):
    card = with_lines(stripped(standard)[0], line())
    card['added']['gaps'] = [{'path': 'evidence.lines[0].human_proximity', 'disposition': 'not_supplied',
                              'reason': 'given by the converter', 'query_ids': [], 'inspected_artifacts': []}]
    placed, counts = biodb.place_proximity(card, biodb.proximity_values(card, standard))
    assert counts['gaps'] == 0 and len(placed['added']['gaps']) == 1


def test_a_1_0_card_and_a_1_0_checkout_are_refused(standard, tmp_path):
    card = json.loads((standard / RAPA).read_text())
    card['standard_version'] = '1.0'
    with pytest.raises(SystemExit, match='1.1 member'):
        biodb.proximity_values(card, standard)
    (tmp_path / 'VERSION').write_text('1.0.3\n')
    with pytest.raises(SystemExit, match='needs a checkout of OHF 1.1'):
        biodb.standard_version(tmp_path)
