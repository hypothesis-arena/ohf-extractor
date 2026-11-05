"""Read ten article-derived exemplars and one invented mechanical fixture.

Every named card keeps its ledger, byte hash and content hash. The invented
switch-and-bin case preserves legacy object-reference coverage without carrying
article prose. It has no scientific acceptance; its support labels are fake test
inputs. CONTENT-HASHES.json keeps real and synthetic hashes in separate maps.
"""
import json
import os
from pathlib import Path

import pytest

import read_cards

FIXTURES = Path(__file__).resolve().parent / 'fixtures' / 'exemplars'

# The eight accepted cards (the wolbachia article yields two: the trial and its 2018 slice), and the
# pointer in each that the kit could not read before 0.8.0.
# The accepted set holds eight cards. The 2018 slice of the wolbachia trial
# (`wolbachia-dengue-awed-2018`) is **not** in it — it exists only in the other variant — so it is
# not listed here and is not expected among the fixtures.
ACCEPTED = {
    # Accepted 2026-10-23, after the pilot's eight, and here for the reason the acceptor gave when it
    # found the gap: the protection in check_card.version_errors reads this set, so a card that is not
    # in it can have its version reused over new content - which is exactly what happened to this card
    # between its acceptance and the correction its acceptance was conditional on. A card enters the
    # set when its act arrives, and `CONTENT-HASHES.json` names the act.
    'imprinting-maternal-offspring-coadaptation': None,
    # Version 2, accepted the same day by a short addendum to the act above. Both versions are in the
    # set, and the reason is the guard's purpose: an accepted version number must not be reused over
    # other content, which is as true of a superseded version as of the live one. The intermediate
    # content that prompted the condition is **not** here and must never be: no act accepted it.
    'imprinting-maternal-offspring-coadaptation-v2': None,
    # Version 3: version 2 rebuilt on the released kit, which is why a showcase example is not pinned
    # to a development version. All three accepted versions are here, so a further rebuild must take 4.
    'imprinting-maternal-offspring-coadaptation-v3': None,
    'alpha-gal-metformin-oit': None,
    'cancer-body-size-vertebrates': '/added/layers/predictions/0/also_expected_under|src',
    'inside-out-eukaryogenesis': '/added/layers/predictions/4/known_result_ref|src',
    'intermittent-rapamycin-mtorc2': None,
    'peto-paradox-mammals': None,
    'sleep-brain-clearance': None,
    'wolbachia-dengue-awed': '/added/layers/profile/dose_response/endpoint_ref|src',
}


SYNTHETIC = {'digit-patterning-turing': '/added/layers/predictions/0/known_result_ref|src'}
EXEMPLARS = {**ACCEPTED, **SYNTHETIC}

def accepted_dir():
    """The directory of accepted cards: the fixtures here, or the one OHF_ACCEPTED_CARDS names."""
    named = os.environ.get('OHF_EXEMPLAR_CARDS') or os.environ.get('OHF_ACCEPTED_CARDS')
    return Path(named) if named else FIXTURES


@pytest.fixture(scope='module')
def cards():
    root = accepted_dir()
    pairs = [(c, led) for c, led in read_cards.cards_and_ledgers(root) if led is not None]
    assert pairs, f'no card with a ledger beside it in {root}'
    return pairs


def test_every_accepted_card_is_read(cards):
    """The regression: not one accepted card may become unreadable."""
    unread = {}
    for card_path, ledger_path in cards:
        errors, _ = read_cards.read(card_path, ledger_path)
        if errors:
            unread[Path(card_path).name] = errors
    assert unread == {}


def test_every_accepted_card_is_still_in_the_set(cards):
    """A set that has lost a card would make the test above pass while reading less."""
    names = {Path(c).stem for c, _ in cards}
    missing = set(EXEMPLARS) - names
    if accepted_dir() != FIXTURES and missing:
        pytest.skip(f'the directory given is not the accepted set (missing {sorted(missing)})')
    assert missing == set()


def test_the_fixtures_are_the_bytes_that_were_accepted(cards):
    """The cards here are the accepted ones, by their own hashes: a fixture quietly edited to make a
    test pass would be the one way this regression could lie."""
    sums = FIXTURES / 'SHA256SUMS'
    if accepted_dir() != FIXTURES or not sums.exists():
        pytest.skip('reading a set given by OHF_EXEMPLAR_CARDS, which carries no hashes of its own')
    import hashlib
    wrong = []
    for line in sums.read_text().splitlines():
        digest, _, name = line.partition('  ')
        path = FIXTURES / name.strip()
        if not path.exists():
            wrong.append(f'{name}: missing')
        elif hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            wrong.append(f'{name}: changed since it was accepted')
    assert wrong == []


def test_the_pointers_that_broke_are_read_and_named(cards):
    """Each card that could not be read before 0.8.0 is read now, and says which record it read
    under the earlier rendering: read, and not silently."""
    by_name = {Path(c).stem: (c, led) for c, led in cards}
    for name, key in EXEMPLARS.items():
        if key is None or name not in by_name:
            continue
        errors, legacy = read_cards.read(*by_name[name])
        assert errors == [], (name, errors)
        assert key in set(legacy), (name, sorted(set(legacy)))


def test_the_fixtures_are_the_accepted_exemplars_by_content_hash(cards):
    """A path is not an identifier. Until 2026-10-22 this directory held the other variant of all
    eight cards — byte-identical to out/pilot-final/, which was never accepted — and every test here
    passed while reading the wrong set. The guard is the hash the judge manifest carries, so a swap
    of variants is caught by what the file says it is and not by where it sits."""
    registry = json.loads((FIXTURES / 'CONTENT-HASHES.json').read_text())
    assert set(registry['cards']) == set(ACCEPTED)
    assert set(registry['synthetic']) == set(SYNTHETIC)
    assert not set(registry['cards']) & set(registry['synthetic'])
    pins = {**registry['cards'], **registry['synthetic']}
    if accepted_dir() != FIXTURES:
        pytest.skip('reading a set given by OHF_EXEMPLAR_CARDS')
    wrong = []
    for card_path, _ in cards:
        name = Path(card_path).stem
        card = json.loads(Path(card_path).read_text())
        if name not in pins:
            wrong.append(f'{name}: not a pinned exemplar of the registry')
        elif card['content_hash'] != pins[name]:
            wrong.append(f'{name}: content_hash {card["content_hash"]} is not the accepted {pins[name]}')
    assert wrong == [], wrong
    assert set(pins) == set(EXEMPLARS), 'the pinned set and the expected set must name the same cards'


def test_synthetic_pair_is_named_without_article_acceptance():
    by_name = {Path(c).stem: (c, led) for c, led in read_cards.cards_and_ledgers(FIXTURES) if led is not None}
    assert len(ACCEPTED) == 10 and len(SYNTHETIC) == 1 and len(EXEMPLARS) == 11
    card_path, ledger_path = by_name['digit-patterning-turing']
    card = json.loads(Path(card_path).read_text())
    ledger = json.loads(Path(ledger_path).read_text())
    import search
    assert len(search.terms_of(search.card_text(card))) >= 200
    assert card['id'] == 'h_synthetic-switch-bins'
    assert card['author']['source']['kind'] == 'synthetic_fixture'
    assert card['author']['source']['rights_basis'] == 'own_synthetic_fixture'
    assert card['added']['source_verification']['status'] == 'not_refetchable'
    assert len(card['added']['integrity']['entailment']) == len(ledger['entries']) == 116
    assert {x['checker']['name'] for x in card['added']['integrity']['entailment']} == {'synthetic-fixture-not-a-model'}
    assert all('Invented mechanical' in x['note'] for x in card['added']['integrity']['entailment'])
    assert SYNTHETIC['digit-patterning-turing'] in read_cards.read(card_path, ledger_path)[1]
