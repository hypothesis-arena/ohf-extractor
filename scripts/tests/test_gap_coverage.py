"""Every empty applicable field has a gap, and a rebuilt card is a new version.

Two absences the kit could not see before. A field left empty with no gap beside it said nothing
and failed nothing, because the kit demanded a gap only where one had been written; and two cards
of one id and one version stood over different content hashes, each claiming to be that version.

The numbers for the accepted cards are pinned here rather than fixed in them: those cards are not
rebuilt, and what matters is that their count cannot drift unnoticed.
"""
import json
import sys

import pytest

import check_card
import gap_coverage
import ohfkit
from conftest import SCRIPTS

ACCEPTED = SCRIPTS / 'tests' / 'fixtures' / 'exemplars' / 'cards'

# Counted on 2026-10-21, against the cards as accepted. A card is never edited to move a number
# here: a changed count means the card changed, or the standard's gap paths did.
#
# Recounted on 2026-10-21 under 0.8.4, which stopped demanding a gap at a path of a domain profile
# the card does not select, because the standard's own checker refuses a gap there. No card was
# touched. The first count is kept beside the new one so that the drop can be read rather than
# taken on trust; it is the number of profile paths each card's domain leaves unselected.
#   alpha-gal-metformin-oit 81 -> 81 (domain allergen_immunotherapy: its own profile stays selected)
#   cancer-body-size-vertebrates 77 -> 75    digit-patterning-turing 76 -> 74
#   inside-out-eukaryogenesis 77 -> 75       intermittent-rapamycin-mtorc2 75 -> 75 (domain set)
#   peto-paradox-mammals 77 -> 75            sleep-brain-clearance 45 -> 44
#   wolbachia-dengue-awed 69 -> 69           wolbachia-dengue-awed-2018 72 -> 72
KNOWN_UNRECORDED = {
    'alpha-gal-metformin-oit': 81,
    'cancer-body-size-vertebrates': 75,
    'digit-patterning-turing': 74,
    'inside-out-eukaryogenesis': 75,
    'intermittent-rapamycin-mtorc2': 75,
    'peto-paradox-mammals': 75,
    'sleep-brain-clearance': 44,
    'wolbachia-dengue-awed': 69,
    'wolbachia-dengue-awed-2018': 72,
}


def accepted(name):
    path = ACCEPTED / f'{name}.json'
    if not path.exists():
        pytest.skip(f'the accepted fixtures are not here: {path.name}')
    return json.loads(path.read_text())


@pytest.mark.parametrize('name,count', sorted(KNOWN_UNRECORDED.items()))
def test_the_accepted_cards_keep_their_known_count(name, count):
    """The accepted eight are not rebuilt for this check; their number is recorded as it stands."""
    assert len(gap_coverage.unrecorded(accepted(name))) == count


def test_an_empty_field_with_a_gap_is_not_reported():
    """The check asks for a gap, not for a value: a recorded gap answers it."""
    card = accepted('peto-paradox-mammals')
    before = {r['path'] for r in gap_coverage.unrecorded(card)}
    assert 'core.base_rate' in before
    card['added']['gaps'].append({'path': 'core.base_rate', 'disposition': 'not_supplied',
                                  'reason': 'The article gives no base rate.',
                                  'query_ids': [], 'inspected_artifacts': []})
    after = {r['path'] for r in gap_coverage.unrecorded(card)}
    assert 'core.base_rate' not in after and after == before - {'core.base_rate'}


def test_a_filled_field_is_not_reported():
    card = accepted('peto-paradox-mammals')
    assert 'core.statement' not in {r['path'] for r in gap_coverage.unrecorded(card)}


def test_a_layer_the_card_does_not_use_is_absent_rather_than_empty():
    """A field whose parent is not in the card needs no gap, as check_gaps.py states for a profile
    a card does not select."""
    card = accepted('peto-paradox-mammals')
    paths = {r['path'] for r in gap_coverage.unrecorded(card)}
    card['added']['layers'].pop('profile', None)
    card['author']['layers'].pop('profile', None)
    fewer = {r['path'] for r in gap_coverage.unrecorded(card)}
    assert {p for p in paths if p.startswith('profile.')}
    assert not {p for p in fewer if p.startswith('profile.')}


def test_an_empty_list_is_reported_but_not_demanded():
    """The standard has no gap path for an empty list (GAP_PATH_UNKNOWN), so the kit names it and
    does not ask for a gap it knows would be refused."""
    card = accepted('peto-paradox-mammals')
    assert 'core.assumptions' in gap_coverage.empty_lists(card)
    assert 'core.assumptions' not in {r['path'] for r in gap_coverage.unrecorded(card)}
    text, ok = gap_coverage.report(card)
    assert 'NOTE core.assumptions' in text and not ok


@pytest.mark.parametrize('name', sorted(KNOWN_UNRECORDED))
def test_every_demanded_gap_is_one_the_standard_would_accept(name):
    """What this check asks for must be satisfiable.

    `check_gaps.py` refuses a gap at a path of a domain profile the card does not select
    (GAP_PROFILE_FIELD). Until 0.8.4 this check demanded one there anyway, so a card that
    answered every demand failed the standard's checker and a card that passed the checker failed
    here: the two halves of step 4 could not both be satisfied. Found on the first card built to
    reach zero. The demand is now the satisfiable one.
    """
    card = accepted(name)
    sys.path.insert(0, str(ohfkit.REPO / 'tools'))
    import check_gaps  # noqa: PLC0415
    profiles = json.loads((ohfkit.REPO / 'vocabularies/profiles-1.json').read_text())
    unselected = check_gaps.unselected_paths(card, profiles)
    demanded = {r['path'] for r in gap_coverage.unrecorded(card)}
    assert not (demanded & unselected)


def test_the_known_count_passes_and_a_changed_one_does_not():
    card = accepted('sleep-brain-clearance')
    _, ok = gap_coverage.report(card, known=KNOWN_UNRECORDED['sleep-brain-clearance'])
    assert ok
    text, ok = gap_coverage.report(card, known=KNOWN_UNRECORDED['sleep-brain-clearance'] - 1)
    assert not ok and 'KNOWN COUNT' in text


# ------------------------------------------------------------------ the version guard

def test_a_rebuilt_card_may_not_keep_the_accepted_version():
    card = accepted('peto-paradox-mammals')
    assert check_card.version_errors(card) == []
    card['content_hash'] = 'sha256:' + '0' * 64
    [error] = check_card.version_errors(card)
    assert 'is a new version' in error and 'peto-paradox-mammals' in error


def test_a_new_version_of_the_same_card_is_allowed():
    """A new version raises **both** version members and names what it replaces. This test used to
    raise only the top-level one, which is the mistake it was later caught making in a real revision:
    `identity.version` stayed behind, so the new card still named the accepted version."""
    card = accepted('peto-paradox-mammals')
    card['content_hash'] = 'sha256:' + '0' * 64
    was = card.get('version') or 1
    card['version'] = card['identity']['version'] = was + 1
    card['identity']['supersedes'] = [f"{card['id']}@{was}"]
    assert check_card.version_errors(card) == []
    # raising one member and not the other is refused, whatever the content hash says
    card['version'] = was + 2
    assert any('move together' in e for e in check_card.version_errors(card))


def test_another_card_with_another_id_is_not_touched():
    card = accepted('peto-paradox-mammals')
    card['id'] = 'h_something_else'
    card['content_hash'] = 'sha256:' + '0' * 64
    assert check_card.version_errors(card) == []


# --------------------------------------------------- a source nothing cites

def test_a_source_no_value_cites_is_named():
    card = accepted('peto-paradox-mammals')
    card['added']['sources']['never_used'] = {
        'source': 'https://www.ebi.ac.uk/europepmc/webservices/rest/PMC8755536/fullTextXML',
        'locator': 'XML .//p[99] (1-based document order)', 'accessed_at': '2026-10-21T00:00:01Z'}
    assert gap_coverage.uncited_sources(card) == ['never_used']
    text, _ = gap_coverage.report(card)
    assert 'NOTE source never_used' in text and 'p[99]' in text


def test_a_source_cited_only_through_component_sources_is_not_reported():
    """A value can name its sources per component; those are citations too."""
    card = accepted('peto-paradox-mammals')
    card['added']['sources']['by_component'] = {'locator': 'XML .//p[98] (1-based document order)'}
    card['added']['layers']['core']['statement'] = {
        'value': 'X.', 'src': 'peto', 'component_sources': {'/value': 'by_component'}}
    assert 'by_component' not in gap_coverage.uncited_sources(card)


@pytest.mark.parametrize('name', sorted(KNOWN_UNRECORDED))
def test_the_accepted_cards_keep_their_uncited_sources_recorded(name):
    """Counted on 2026-10-21 against the cards as accepted. Five of the nine declare a source no
    value cites; the note names them rather than failing a card nobody is rebuilding."""
    known = {'alpha-gal-metformin-oit': 4, 'cancer-body-size-vertebrates': 3,
             'digit-patterning-turing': 2, 'inside-out-eukaryogenesis': 1,
             'intermittent-rapamycin-mtorc2': 2, 'peto-paradox-mammals': 0,
             'sleep-brain-clearance': 0, 'wolbachia-dengue-awed': 0,
             'wolbachia-dengue-awed-2018': 0}
    assert len(gap_coverage.uncited_sources(accepted(name))) == known[name]


def test_a_field_newer_than_the_card_is_not_demanded():
    """Found while building a card: with OHF_REPO pointing at a 1.1 checkout, a 1.0 card was told to
    record gaps for fields that belong to 1.1 - taxon_id, human_proximity, sample_size, quote_withheld,
    excluded[], atoms[].requires and the rest - and the standard's own check_gaps then refused every one
    of those gaps as GAP_PATH_UNKNOWN. The two halves of the check contradicted each other and no card
    could satisfy both.

    The version is in the standard's field catalogue, in `since`, which is where its own checker reads
    it; the kit joins the gap-path policy to the catalogue on the path rather than keeping a second copy
    that could drift. A field newer than the card's own version is not demanded."""
    card = accepted('peto-paradox-mammals')
    assert card['standard_version'] == '1.0'
    demanded = {row['path'] for row in gap_coverage.unrecorded(card)}
    since = gap_coverage._since()
    newer = {path for path, added in since.items() if gap_coverage._after(added, '1.0')}
    if not newer:
        pytest.skip('this checkout\'s catalogue names no field newer than the card, so there is nothing '
                    'for the join to exclude: the case this test is about only arises against a newer '
                    'standard (run it with OHF_REPO pointing at 1.1 or later)')
    assert not (demanded & newer), sorted(demanded & newer)
    # and the same paths are demanded of a card that declares the newer version, where they exist
    card['standard_version'] = '1.1'
    assert {row['path'] for row in gap_coverage.unrecorded(card)} >= demanded


def test_the_guard_covers_a_card_accepted_after_the_pilot():
    """The half of the acceptor's finding that is larger than the version it was about.

    The guard reads the set of accepted cards, so it protects only the cards that set knows. A card
    accepted today is unprotected in exactly the window where it gets corrected - between its act and
    its entry into the set - and that is what happened: version 1 of the imprinting card was accepted,
    the acceptor's condition changed it, and it was reissued as version 1 again, one version over two
    contents, with this kit silent because the card was not in the set. It is in the set now, and this
    test is the proof that being in the set is what makes the rule fire.
    """
    card = accepted('imprinting-maternal-offspring-coadaptation')
    assert check_card.version_errors(card) == []
    card['content_hash'] = 'sha256:' + '1' * 64
    [error] = check_card.version_errors(card)
    assert 'is a new version' in error and 'imprinting' in error
    # And the correction it should have been: both members raised to a version no act has taken,
    # naming what they replace. Version 2 is not that version - it is accepted too, at its own content
    # hash - so a rebuild of version 1 goes to 3, and the guard says so if it goes to 2 with other
    # bytes. That is the rule doing its work twice over, on the live version and on the superseded one.
    was = card['version']
    card['version'] = card['identity']['version'] = 2
    card['identity']['supersedes'] = [f"{card['id']}@{was}"]
    assert any('is a new version' in e for e in check_card.version_errors(card))
    card['version'] = card['identity']['version'] = 3
    card['identity']['supersedes'] = [f"{card['id']}@2"]
    assert any('is a new version' in e for e in check_card.version_errors(card))
    # Three acts, three accepted numbers: the first free one is 4. Each acceptance moves this number,
    # and the test says so by going to the set rather than by hard-coding a count.
    card['version'] = card['identity']['version'] = 4
    card['identity']['supersedes'] = [f"{card['id']}@3"]
    assert check_card.version_errors(card) == []


def test_both_versions_of_an_accepted_card_are_guarded():
    """A superseded version is still an accepted version, and its number must not be reused.

    The set holds version 1 and version 2 of the imprinting card. A card that says version 1 with other
    content is refused by the first; one that says version 2 with other content is refused by the
    second. Without both, reissuing the superseded number over new content would pass.
    """
    for name, other in (('imprinting-maternal-offspring-coadaptation', 1),
                        ('imprinting-maternal-offspring-coadaptation-v2', 2)):
        card = accepted(name)
        assert card['version'] == other and check_card.version_errors(card) == []
        card['content_hash'] = 'sha256:' + '2' * 64
        assert any('is a new version' in e for e in check_card.version_errors(card)), name
