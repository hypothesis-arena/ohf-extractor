"""line_figures.py: what a 1.1 line's quote states in numbers, by the standard's own patterns and codes.

Run against the checkout in OHF_STANDARD, OHF 1.1.1 or later with the check_refs.py of
test_proximity's pin; skipped without it.
"""
import copy
import json
import os
from pathlib import Path

import pytest

import line_figures
from test_proximity import standard  # noqa: F401  (the checkout, checked once)

STANDARD = os.environ.get('OHF_STANDARD')
pytestmark = pytest.mark.skipif(not STANDARD, reason='set OHF_STANDARD to a checkout of OHF 1.1.1')
CARDS = ('intermittent-rapamycin-mtorc2', 'peto-paradox-mammals')


def example(standard, name):
    return json.loads((standard / 'examples' / 'cards' / f'{name}.json').read_text())


def lines_of(card):
    return card['added']['layers']['evidence']['lines']


@pytest.mark.parametrize('name', CARDS)
def test_without_its_estimates_a_released_example_is_flagged_on_exactly_those_lines(standard, name):  # noqa: F811
    card = example(standard, name)
    assert not any(v['codes'] for v in line_figures.figures(card, standard))
    had = {i: line['result_estimate']['value']['reported'] for i, line in enumerate(lines_of(card))
           if 'result_estimate' in line}
    for line in lines_of(card):
        line.pop('result_estimate', None)
    got = line_figures.figures(card, standard)
    flagged = {i for i, v in enumerate(got) if [x['code'] for x in v['codes']] == ['REF_ESTIMATE_IN_QUOTE']}
    assert flagged == set(had) and len(had) >= 5
    for i, reported in had.items():
        quote = line_figures.biodb._val(lines_of(card)[i]['quote'])
        # The sentences are words of the quote, and the estimate the example reports is cut from them.
        assert all(s in quote for s in got[i]['result']['sentences'])
        assert reported in ' '.join(got[i]['result']['sentences'])


def one_line(standard, quote, **members):  # noqa: F811
    card = example(standard, CARDS[0])
    line = copy.deepcopy(lines_of(card)[28])
    line['quote'] = {'value': quote, 'src': line['quote']['src']} if isinstance(line['quote'], dict) else quote
    for k in ('result_estimate', 'intervention'):
        line.pop(k, None)
    line.update(members)
    card['added']['layers']['evidence']['lines'] = [line]
    card['added']['gaps'] = []
    return card


def codes(card, standard):  # noqa: F811
    return [x['code'] for x in line_figures.figures(card, standard)[0]['codes']]


def test_a_gap_that_only_says_not_supplied_does_not_answer_a_number_in_the_quote(standard):  # noqa: F811
    card = one_line(standard, 'Mortality fell by 12% in the treated group. Weight did not change.')
    got = line_figures.figures(card, standard)[0]
    assert got['result']['sentences'] == ['Mortality fell by 12% in the treated group.']
    assert codes(card, standard) == ['REF_ESTIMATE_IN_QUOTE']
    gap = {'path': 'evidence.lines[0].result_estimate', 'reason': 'r', 'query_ids': [], 'inspected_artifacts': []}
    card['added']['gaps'] = [gap | {'disposition': 'not_supplied'}]
    assert codes(card, standard) == ['REF_ESTIMATE_IN_QUOTE']
    card['added']['gaps'] = [gap | {'disposition': 'unknown_source_scope'}]
    assert codes(card, standard) == [] and line_figures.figures(card, standard)[0]['result']['gaps']


def test_an_estimate_not_in_the_quote_and_a_dose_not_recorded_are_the_standards_codes(standard):  # noqa: F811
    quote = 'Rapamycin at 4.7 ppm extended median lifespan by 18%.'
    estimate = {'value': {'reported': 'by 81%', 'measure': 'median lifespan', 'contrast': 'not_stated',
                          'scale': 'not_stated'}, 'src': 's'}
    card = one_line(standard, quote, result_estimate=estimate)
    assert sorted(codes(card, standard)) == ['REF_CONDITION_IN_QUOTE', 'REF_ESTIMATE_NOT_QUOTED']
    got = line_figures.figures(card, standard)[0]
    assert got['dose'] == {'spans': ['4.7 ppm'], 'recorded': False, 'gaps': []}
    estimate['value']['reported'] = 'extended median lifespan by 18%'
    card = one_line(standard, quote, result_estimate=estimate,
                    intervention={'dose': {'value': '4.7 ppm', 'src': 's'}})
    assert codes(card, standard) == [] and line_figures.figures(card, standard)[0]['dose']['recorded']


def test_a_1_0_card_is_refused(standard):  # noqa: F811
    card = example(standard, CARDS[0])
    card['standard_version'] = '1.0'
    with pytest.raises(SystemExit, match='OHF 1.1 members'):
        line_figures.figures(card, standard)


def test_the_cli_exits_1_on_a_code_and_lists_the_lines(standard, tmp_path, capsys):  # noqa: F811
    card = one_line(standard, 'Mortality fell by 12%.')
    (tmp_path / 'c.json').write_text(json.dumps(card))
    assert line_figures.main([str(tmp_path / 'c.json'), '--standard', str(standard)]) == 1
    out = json.loads(capsys.readouterr().out)
    assert out['standard'] == (Path(standard) / 'VERSION').read_text().strip() and out['lines'][0]['codes'][0]['code'] == 'REF_ESTIMATE_IN_QUOTE'
    assert line_figures.main([str(Path(standard) / 'examples/cards' / f'{CARDS[0]}.json'), '--standard',
                              str(standard)]) == 0
