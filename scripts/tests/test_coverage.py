"""coverage.py: an inventory item the card does not hold must be impossible to pass over.

The cases that matter here are the failing ones. A coverage script that reports a match wherever it
is unsure, or that lets an unanswered item through, would turn the second reader into a formality.
"""
import json
from pathlib import Path

import pytest

import coverage

FIXTURES = Path(__file__).resolve().parent / 'fixtures' / 'exemplars'

QUOTE = 'X may cause Y in mice'


def card(direction='supports', para=2, quote=QUOTE):
    """A card with one atom in paragraph 1 and one evidence line in paragraph `para`."""
    return {
        'id': 'h_x',
        'author': {'layers': {'core': {'statement': {'value': 'X causes Y.', 'src': 's1'}}}},
        'added': {
            'sources': {'s1': {'locator': 'XML .//p[1] (1-based document order)'},
                        's2': {'locator': f'XML .//p[{para}] (1-based document order)'}},
            'layers': {
                'core': {'atoms': [{'id': 'a1', 'statement': {'value': 'X causes Y.', 'src': 's1'}}],
                         'scope': {'value': 'mice', 'src': 's1'}},
                'evidence': {'lines': [{'id': 'e1', 'direction': {'value': direction, 'src': 's2'},
                                        'study_type': {'value': 'a trial', 'src': 's2',
                                                       'basis_quote': quote}}]}},
            'gaps': [{'path': 'core.falsification_condition', 'reason': 'The article states none.'}],
            'integrity': {'entailment': []}}}


def inventory(*items):
    return {'article': {'id': 'PMC1'}, 'items': [{'id': f'i{i + 1}', **it} for i, it in enumerate(items)]}


def run(inv, c, reasons=None, confirm=None, held=None):
    rows = coverage.reconcile(inv, c, reasons or {}, confirm or {}, held or {})
    text, open_items = coverage.report(rows)
    return rows, text, open_items


def test_an_item_whose_quoted_words_are_in_the_card_matches_with_the_quote():
    rows, text, open_items = run(inventory({'type': 'evidence_for', 'paragraph': 2, 'text': 't',
                                            'quote': QUOTE}), card())
    assert rows[0]['how'] == 'quote' and open_items == 0
    assert 'on the quoted words' in text and 'complete coverage' in text


def test_a_match_by_address_alone_is_not_coverage_until_it_is_confirmed():
    """F2: paragraph and type agreeing is an address. Unconfirmed, the item stays unanswered."""
    inv = inventory({'type': 'evidence_for', 'paragraph': 2, 'text': 't',
                     'quote': 'words the card does not carry'})
    rows, text, open_items = run(inv, card())
    assert rows[0]['how'] == 'paragraph+type' and open_items == 1
    assert 'that is an address, not coverage' in text
    rows, text, open_items = run(inv, card(), confirm={'i1': 'lines[0].study_type records this trial'})
    assert open_items == 0 and 'confirmed (judged)' in text


def test_an_address_match_is_answered_by_a_reason_that_the_card_does_not_hold_it():
    """0.8.10: two statements can stand in one paragraph with the card carrying one of them, so an
    address match is answered either by a confirmation or by a reason. Before 0.8.10 the code read
    only the confirmation, and an item the card does not hold had no truthful answer: the only way
    to clear it was a confirmation claiming a value carries it."""
    inv = inventory({'type': 'evidence_for', 'paragraph': 2, 'text': 't',
                     'quote': 'words the card does not carry'})
    rows, text, open_items = run(inv, card(),
                                 reasons={'i1': 'The paragraph holds two results and the card carries '
                                                'the other one; this one is in no value.'})
    assert rows[0]['how'] == 'paragraph+type' and open_items == 0
    assert 'does not hold this item, reason recorded (judged)' in text
    assert 'the card does not hold with a judged reason' in text


def test_an_item_of_the_abstract_is_answered_by_the_pointer_that_holds_it():
    """0.8.11: the card sources the statement to the body paragraph that gives it in full, so an
    item of the abstract matches nothing although the card holds it. The answer is a pointer, and
    the pointer is checked rather than believed."""
    inv = inventory({'type': 'claim', 'paragraph': 5, 'text': 'X causes Y', 'quote': 'X causes Y'})
    rows, text, open_items = run(inv, card(), held={'i1': '/added/layers/core/atoms/0/statement'})
    assert open_items == 0 and rows[0]['held_paragraph'] == 1
    assert 'held at another locator' in text and 'held at another locator by a checked pointer' in text


@pytest.mark.parametrize('pointer,says', [
    ('/added/layers/core/atoms/9/statement', 'is not a sourced value'),
    ('/added/layers/evidence/lines/0/study_type', 'is not a place where a claim belongs'),
])
def test_a_pointer_that_does_not_hold_the_item_is_not_an_answer(pointer, says):
    inv = inventory({'type': 'claim', 'paragraph': 5, 'text': 'X causes Y', 'quote': 'X causes Y'})
    _, text, open_items = run(inv, card(), held={'i1': pointer})
    assert open_items == 1 and says in text


def test_a_pointer_may_name_a_value_the_card_sources_to_another_document():
    """0.8.13: a review states a result and the card sources it to the study that reported it. That
    value reads another document, so the address matcher never sees it — but a pointer names it
    outright, and it is a value of this card under another locator in the fullest sense."""
    c = card()
    c['added']['sources']['s3'] = {'artifact': 'PMC9', 'locator': 'XML .//p[2] (1-based document order)'}
    c['added']['layers']['core']['atoms'].append(
        {'id': 'a2', 'statement': {'value': 'X causes Y in the primary study.', 'src': 's3'}})
    inv = inventory({'type': 'claim', 'paragraph': 2, 'text': 'X causes Y', 'quote': 'X causes Y'})
    for src in ('s1', 's2'):            # make the card's own paragraphs name the article
        c['added']['sources'][src]['artifact'] = 'PMC1'
    rows, text, open_items = run(inv, c, held={'i1': '/added/layers/core/atoms/1/statement'})
    assert open_items == 0, text
    assert 'held at another locator' in text


def test_a_pointer_to_a_line_of_the_wrong_direction_does_not_hold_an_evidence_item():
    """0.8.12: --held applies the direction test of the address matcher. A line the card records as
    neutral, or as disputing, does not answer an item the reader wrote as evidence for."""
    inv = inventory({'type': 'evidence_for', 'paragraph': 5, 'text': 't', 'quote': QUOTE})
    _, text, open_items = run(inv, card(direction='neutral'),
                              held={'i1': '/added/layers/evidence/lines/0/study_type'})
    assert open_items == 1 and "direction is 'neutral'" in text
    _, _, ok = run(inv, card(direction='supports'),
                   held={'i1': '/added/layers/evidence/lines/0/study_type'})
    assert ok == 0


def test_a_pointer_in_the_items_own_paragraph_is_an_address_match_not_another_locator():
    inv = inventory({'type': 'claim', 'paragraph': 1, 'text': 'X causes Y',
                     'quote': 'words the card does not carry'})
    _, text, open_items = run(inv, card(), held={'i1': '/added/layers/core/atoms/0/statement'})
    assert open_items == 1 and 'is an address match' in text


def test_a_confirmation_and_a_reason_for_one_item_contradict_each_other():
    inv = inventory({'type': 'evidence_for', 'paragraph': 2, 'text': 't',
                     'quote': 'words the card does not carry'})
    _, text, open_items = run(inv, card(), reasons={'i1': 'the card does not hold it'},
                              confirm={'i1': 'lines[0].study_type carries it'})
    assert open_items == 1 and 'they cannot' in text and 'both stand' in text


def test_an_item_the_card_does_not_hold_and_has_no_reason_is_unanswered():
    """The failing case this script exists for."""
    rows, text, open_items = run(inventory({'type': 'evidence_against', 'paragraph': 9, 'text': 't'}), card())
    assert rows[0]['matched'] == [] and open_items == 1
    assert 'no reason recorded' in text and '1 unanswered' in text


def test_a_recorded_reason_accounts_for_it_and_is_still_printed_as_a_p1():
    inv = inventory({'type': 'evidence_against', 'paragraph': 9, 'text': 't'})
    rows, text, open_items = run(inv, card(), {'i1': 'a result in zebrafish, outside the claim'})
    assert open_items == 0 and rows[0]['matched'] == []
    assert 'reason recorded (judged): a result in zebrafish' in text and text.count('P1') == 1


def test_an_argument_against_is_not_matched_by_a_line_that_supports():
    """A paragraph agreeing is not enough: a supporting line does not hold an argument against."""
    inv = inventory({'type': 'evidence_against', 'paragraph': 2, 'text': 't', 'quote': QUOTE})
    rows, _, open_items = run(inv, card(direction='supports'))
    assert rows[0]['matched'] == [] and open_items == 1
    rows, _, open_items = run(inv, card(direction='disputes'))
    assert rows[0]['how'] == 'quote' and open_items == 0


def test_a_claim_is_not_matched_by_an_evidence_line_in_the_same_paragraph():
    """Types are matched to their own places; otherwise every item in a used paragraph passes."""
    rows, _, open_items = run(inventory({'type': 'claim', 'paragraph': 2, 'text': 't'}), card())
    assert rows[0]['matched'] == [] and open_items == 1


def test_an_item_whose_type_is_not_a_type_is_a_problem():
    rows, text, open_items = run(inventory({'type': 'interesting', 'paragraph': 1, 'text': 't'}), card())
    assert open_items == 1 and 'is not one of' in text


def test_an_item_with_no_paragraph_is_a_problem():
    rows, text, open_items = run(inventory({'type': 'claim', 'text': 't'}), card())
    assert open_items == 1 and 'names no paragraph' in text


def test_a_second_paragraph_in_also_in_can_carry_the_match():
    inv = inventory({'type': 'evidence_for', 'paragraph': 7, 'also_in': [2], 'text': 't', 'quote': QUOTE})
    rows, _, open_items = run(inv, card())
    assert rows[0]['how'] == 'quote' and open_items == 0


def test_a_gap_does_not_match_an_item_of_another_type():
    """A gap's reason is text in the card, but a gap holds nothing of the article."""
    rows, _, open_items = run(inventory({'type': 'claim', 'paragraph': 1, 'text': 't'}), card())
    assert rows[0]['matched'] and all('/gaps/' not in p for p in rows[0]['matched'])


def test_the_exit_code_follows_the_unanswered_items(tmp_path):
    import subprocess
    import sys
    inv = tmp_path / 'inventory.json'
    crd = tmp_path / 'card.json'
    inv.write_text(json.dumps(inventory({'type': 'evidence_against', 'paragraph': 9, 'text': 't'})))
    crd.write_text(json.dumps(card()))
    script = str(Path(coverage.__file__))
    r = subprocess.run([sys.executable, '-I', script, str(inv), str(crd)], capture_output=True, text=True)
    assert r.returncode == 1 and 'unanswered' in r.stdout
    reasons = tmp_path / 'reasons.json'
    reasons.write_text(json.dumps({'i1': 'a result in another species'}))
    r = subprocess.run([sys.executable, '-I', script, str(inv), str(crd), '--reasons', str(reasons)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout


def test_it_reads_a_real_accepted_card():
    """The matcher runs on a card of the accepted set, not only on the shapes in this file."""
    path = FIXTURES / 'cards' / 'peto-paradox-mammals.json'
    if not path.exists():
        pytest.skip('the accepted fixtures are not here')
    c = json.loads(path.read_text())
    vals = coverage.values(c)
    assert len(vals) > 50 and any(v['paragraph'] for v in vals)
    para = next(v['paragraph'] for v in vals if v['paragraph'] and '/core/atoms/' in v['pointer'])
    # The inventory is of one article, and since 0.8.8 the match says which: this card cites
    # several, so an inventory of another one of them must not match these paragraphs.
    inv = inventory({'type': 'claim', 'paragraph': para, 'text': 'the central claim'})
    inv['article']['id'] = 'PMC8755536'
    rows, _, open_items = run(inv, c)
    assert rows[0]['matched'] and open_items == 1  # an address, until a converter confirms it
    _, _, open_items = run(inv, c, confirm={'i1': 'atoms[0].statement is that claim'})
    assert open_items == 0


# ------------------------------------------------------- F2: the two regressions master named

def test_two_claims_in_one_paragraph_with_only_one_carried():
    """Both items match the one value by address, so neither is covered until each is confirmed to a
    value of its own; confirming both to the same value is named in the output."""
    inv = inventory({'type': 'claim', 'paragraph': 1, 'text': 'X causes Y'},
                    {'type': 'claim', 'paragraph': 1, 'text': 'and only in mice'})
    rows, text, open_items = run(inv, card())
    assert open_items == 2 and all(r['how'] == 'paragraph+type' for r in rows)
    rows, text, open_items = run(inv, card(), confirm={'i1': 'atoms[0].statement', 'i2': 'atoms[0].statement'})
    assert open_items == 0  # each is answered...
    assert 'SHARED with' in text and 'one value cannot carry two items' in text  # ...and the clash is named
    assert 'complete coverage' in text


def test_a_quote_in_the_basis_with_the_hedge_lost_in_the_value():
    """The item's words are in the basis_quote while the value drops the hedge. The match is on the
    quoted words and the output says plainly that this is not a finding of fidelity."""
    c = card(quote='X may cause Y in mice')
    c['added']['layers']['evidence']['lines'][0]['study_type']['value'] = 'X causes Y'
    inv = inventory({'type': 'evidence_for', 'paragraph': 2, 'text': 'X may cause Y in mice',
                     'quote': 'X may cause Y in mice', 'hedge': 'may'})
    rows, text, open_items = run(inv, c)
    assert rows[0]['how'] == 'quote' and open_items == 0
    assert "whether the value keeps the item's hedge is for the entailment pass and lens b" in text
    assert 'complete coverage' in text


def test_a_condition_the_card_holds_as_an_assumption_is_found_there():
    """An assumption is where a condition belongs, so the item must match it rather than be
    reported absent.

    Until 0.8.6 `/core/assumptions` was in no type's places, so an item the card held as an
    assumption came out as "not in the card" — the strongest possible verdict, and wrong. The
    accepted eight carried no assumption at all, so nothing caught it until a card built with
    three of them was reconciled with a second reader's inventory. A limitation the authors state
    about their own analysis lands there too ("a missing cause of death is missing at random" is
    both a condition the result depends on and a limit of the analysis).
    """
    c = card()
    c['added']['sources']['s3'] = {'locator': 'XML .//p[3] (1-based document order)'}
    c['added']['layers']['core']['assumptions'] = [
        {'id': 'as_mar', 'text': {'value': 'A missing cause of death is missing at random.',
                                  'src': 's3'}}]
    for item_type in ('condition', 'limitation'):
        rows, text, _ = run(inventory({'type': item_type, 'paragraph': 3,
                                       'text': 'the analysis assumes data are missing at random'}), c)
        assert rows[0]['how'] == 'paragraph+type', item_type
        assert '/added/layers/core/assumptions/0/text' in text, item_type


def test_an_assumption_does_not_answer_an_item_of_another_type():
    """The place is for a condition and a limitation, not for everything standing in that
    paragraph: an argument for the claim is not answered by an assumption about the analysis."""
    c = card()
    c['added']['sources']['s3'] = {'locator': 'XML .//p[3] (1-based document order)'}
    c['added']['layers']['core']['assumptions'] = [
        {'id': 'as_mar', 'text': {'value': 'A missing cause of death is missing at random.',
                                  'src': 's3'}}]
    rows, _, open_items = run(inventory({'type': 'evidence_for', 'paragraph': 3,
                                         'text': 'the complete-case analysis found an effect'}), c)
    assert rows[0]['how'] is None and open_items == 1


def test_an_alternative_the_card_holds_as_a_reinterpretation_is_found_there():
    """A reinterpretation's current_interpretation is a rival reading of a finding, so an
    `alternative` item belongs there as well as in core.alternative_explanations.

    The standard's own example of the field is "Sheltering cannot cause Y-linked gene loss, so
    Muller's hypothesis is rejected" (spec/fields.md, core.reinterprets[]) — someone else's
    explanation, which is what an alternative is. Until 0.8.7 an alternative the card held that way
    was reported as not in the card at all.
    """
    c = card()
    c['added']['sources']['s3'] = {'locator': 'XML .//p[3] (1-based document order)'}
    c['added']['layers']['core']['reinterprets'] = {
        'value': [{'id': 'r1', 'finding': 'Z is observed in carnivores.',
                   'current_interpretation': 'Hormonal contraception explains Z.',
                   'proposed_interpretation': 'Z shows no sex bias, so contraception is not the driver.',
                   'atom_refs': ['a1']}],
        'src': 's3'}
    rows, text, _ = run(inventory({'type': 'alternative', 'paragraph': 3,
                                   'text': 'contraception may explain the carnivore result'}), c)
    assert rows[0]['how'] == 'paragraph+type'
    assert '/added/layers/core/reinterprets' in text


def test_an_observation_the_hypothesis_explains_is_not_an_argument_for_it():
    """The line held when the places were reviewed in 0.8.7: `core.explains` was NOT added to
    `evidence_for`. An `explains` item is an observation the hypothesis has to account for, not a
    result the authors offer in its support, and conflating the two would report coverage where the
    card carries the thing to be explained rather than the evidence for it."""
    c = card()
    c['added']['sources']['s3'] = {'locator': 'XML .//p[3] (1-based document order)'}
    c['added']['layers']['core']['explains'] = {
        'value': [{'id': 'x1', 'observation': 'Z is observed in carnivores.', 'status': 'contested',
                   'mode': 'direct', 'atom_refs': ['a1']}],
        'src': 's3'}
    rows, _, open_items = run(inventory({'type': 'evidence_for', 'paragraph': 3,
                                         'text': 'the authors report Z as support'}), c)
    assert rows[0]['how'] is None and open_items == 1


def test_a_paragraph_of_another_article_is_not_a_match():
    """A paragraph number means nothing without the document it is in.

    A card that cites four articles has a paragraph 7 in each of them, and the inventory is of one
    article. Until 0.8.8 the match was on the number alone, so a value read from paragraph 7 of a
    cited article was reported as covering an item in paragraph 7 of the article under conversion —
    a false match, and the kind the script is written to avoid: it says the card looked at a part of
    the article it never read. Found on a flagship card with four source documents, where five of
    its paragraph numbers collided.
    """
    c = card()
    c['added']['sources']['s1'] = {'locator': 'XML .//p[1] (1-based document order)',
                                   'source': '.../PMC999/fullTextXML'}
    c['added']['sources']['s2'] = {'locator': 'XML .//p[2] (1-based document order)',
                                   'source': '.../PMC1/fullTextXML'}
    inv = inventory({'type': 'claim', 'paragraph': 1, 'text': 'X causes Y'},
                    {'type': 'evidence_for', 'paragraph': 2, 'text': 'the trial', 'quote': QUOTE})
    rows, _, _ = run(inv, c)
    assert rows[0]['how'] is None, 'paragraph 1 belongs to the other article'
    assert rows[1]['how'] == 'quote', 'paragraph 2 is this article, and the words are there'


def test_a_source_that_names_no_document_is_still_matched():
    """Nothing is claimed about a source the card names no document for; dropping it would make a
    card whose sources carry only a locator match nothing at all."""
    c = card()
    inv = inventory({'type': 'claim', 'paragraph': 1, 'text': 'X causes Y'})
    rows, _, _ = run(inv, c)
    assert rows[0]['how'] == 'paragraph+type'
