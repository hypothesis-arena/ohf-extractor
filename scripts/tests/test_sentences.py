"""Gate (3): an author-zone value starts and ends on a sentence boundary of its paragraph."""
import pytest

import check_card
import ohfkit
from conftest import PMCID, build_card, jats, load, put

PARA = ('Under the model, X causes Y when recombination stops. As Smith et al. showed, the rate is 3.5 per '
        'cent (Fig. 2). He wrote "Z holds." Then e.g. W follows! Does it? (Yes, it does.) End without a stop')


@pytest.fixture
def doc(tmp_path):
    put(tmp_path, f'{PMCID}.xml', jats([PARA]))
    return ohfkit.Document(PMCID, tmp_path)


@pytest.mark.parametrize('value', [
    'Under the model, X causes Y when recombination stops.',
    'As Smith et al. showed, the rate is 3.5 per cent (Fig. 2).',
    'He wrote "Z holds."',
    'Then e.g. W follows!',
    'Does it?',
    '(Yes, it does.)',
    'End without a stop',
    'Under the model, X causes Y when recombination stops. As Smith et al. showed, the rate is 3.5 per cent (Fig. 2).',
])
def test_whole_sentences_pass(doc, value):
    assert doc.author(1, value)['value'] == value


@pytest.mark.parametrize('value', [
    'Under the model, X causes Y',  # the planted truncation: drops "when recombination stops"
    'X causes Y when recombination stops.',  # starts inside the sentence
    'As Smith et al.',  # "et al." is not a sentence end
    'As Smith et al. showed, the rate is 3.',  # a decimal point is not a sentence end
    'the rate is 3.5 per cent (Fig.',  # starts inside, "Fig." is not an end
    'Then e.g.',
])
def test_cut_values_fail(doc, value):
    with pytest.raises(ValueError, match='sentence boundary'):
        doc.author(1, value)


def test_author_part_records_the_cut(doc):
    v = doc.author_part(1, 'X causes Y when recombination stops.', 'the opening clause names the model, not the claim')
    assert v['locator'] == ('XML .//p[1] (1-based document order); part of a sentence, cut by the converter: '
                            'the opening clause names the model, not the claim')
    with pytest.raises(ValueError, match='needs a reason'):
        doc.author_part(1, 'X causes Y', ' ')
    with pytest.raises(ValueError, match='use author'):
        doc.author_part(1, 'Does it?', 'no cut')


def test_check_card_fails_a_truncated_author_value(xml_workdir):
    card_path = build_card(xml_workdir)
    card = load(card_path)
    card['author']['layers']['core']['statement']['value'] = 'We propose that X causes Y'
    errors = check_card.conversion_errors(card, xml_workdir)
    assert any('/author/layers/core/statement: author value does not start and end on a sentence boundary' in e
               for e in errors), errors


def test_check_card_accepts_a_recorded_cut(xml_workdir):
    card_path = build_card(xml_workdir)
    card = load(card_path)
    doc = ohfkit.Document(PMCID, xml_workdir)
    card['author']['layers']['core']['statement'] = doc.author_part(1, 'X causes Y when recombination stops',
                                                                     'test of a recorded cut')
    errors = check_card.conversion_errors(card, xml_workdir)
    assert not any('/author/layers' in e for e in errors), errors
