"""Known result or duplicate: the detector decides only on a reader's verdict with evidence the kit checks.

The Europe PMC records are synthetic (fixtures/search/known-records.json: invented titles and abstracts);
the cards are one arena hypothesis record and two cards of the OHF shape, also invented."""
import json

import pytest

import search
from test_search import Net

TEXT = 'Transient low-pH stress converts mammalian somatic cells into pluripotent cells.'
CARDS = [
    {'id': 'h-acid', 'version': 1, 'statement': 'Brief exposure of somatic cells to low pH converts them into '
     'pluripotent stem cells.', 'mechanism': 'Acid stress reprograms somatic cells.', '_file_sha256': 'sha256:aa'},
    {'id': 'h_sleep', 'version': 1, 'content_hash': 'sha256:bb', 'author': {'source': {}, 'layers': {'core': {
        'statement': {'value': 'Brain clearance is reduced during sleep.', 'locator': 'x'}}}}},
    {'id': 'h_cancer', 'version': 2, 'content_hash': 'sha256:cc', 'author': {'source': {}, 'layers': {'core': {
        'statement': {'value': 'Larger species have a higher cancer prevalence.', 'locator': 'x'}}}}},
]
QUOTE = 'Exposure of somatic cells to low pH did not produce pluripotent cells in any of 133 attempts.'
QUOTE4 = 'Fibroblasts exposed to low pH became pluripotent cells in 24 of 30 cultures.'  # record 1004
# the selection criterion each test enrolled, a passage of its abstract, as a reader gives it
POPULATION = {1: 'somatic cells', 4: 'Fibroblasts'}
# how precise each test is, with its passage: both pre-specified and completed
PRIMARY = 'The primary outcome was prespecified.'
COMPLETED = {1: 'All 133 planned attempts were completed.', 4: 'Enrolment of the planned 30 cultures was completed.'}
STOPPED = 'A second series stopped early for lack of funding.'  # record 1001: an operational stop
FUTILITY = 'A third series was stopped for futility at an interim analysis.'  # record 1001
UNDERPOWERED = {1: 'The study was underpowered for small effects.', 4: 'The trial was underpowered for secondary outcomes.'}
EXCLUDES = 'The 95% interval excluded the null.'  # record 1004
EFFICACY = 'An extension series was stopped early for efficacy.'  # record 1004
EXCLUDES1 = 'In the second series the 95% interval excluded no effect.'  # record 1001
# how each work assigned the intervention, with its passage: record 1001 randomised, record 1004 an experiment
DESIGN = {1: ('randomized', 'Cultures were randomised to low pH or a control buffer.'),
          4: ('experimental', 'In a controlled laboratory experiment, fibroblasts were exposed to low pH.')}
OBSERVATIONAL = {1: 'An observational series of archived lines was also reviewed.', 4: 'A matched observational cohort was followed.'}


def with_population(works):
    """A reader's verdicts with a population, its match and a precise test's precision on every test that does
    not give its own."""
    return [{**({'population': POPULATION.get(w['item'], 'somatic cells'), 'population_match': 'same',
                 'design': DESIGN.get(w['item'], DESIGN[1])[0], 'design_quote': DESIGN.get(w['item'], DESIGN[1])[1],
                 'primary_prespecified': 'yes', 'primary_quote': PRIMARY, 'stop_reason': 'completed',
                 'stop_quote': COMPLETED.get(w['item'], COMPLETED[1]),
                 # a support decides only through its interval: records 1001 and 1004 state one that excludes none
                 **({'effect_excludes_null': 'yes', 'effect_quote': EXCLUDES if w['item'] == 4 else EXCLUDES1}
                    if w.get('verdict') == 'tests_supports' else {})}
                if w.get('verdict', '').startswith('tests_') else {}), **w} for w in works]


def lit(s, outcome='ok', fourth=False):
    works = [{'source_id': 'MED:1001', 'pmid': '1001', 'doi': '10.9999/test.1', 'title': 't1'},
             {'source_id': 'MED:1002', 'pmid': '1002', 'title': 't2'},
             {'source_id': 'MED:1003', 'pmid': '1003', 'title': 't3'}]
    if fourth:  # a supporting test of the same claim
        works.append({'source_id': 'MED:1004', 'pmid': '1004', 'doi': '10.9999/test.4', 'title': 't4'})
    s.log({'call_id': f'lit-{outcome}', 'tool': 'literature', 'outcome': outcome, 'started_at': 't',
           'ask': {'query': 'low pH pluripotency', 'source': 'europepmc', 'variant': 'as_given'},
           'hit_count': 3 if outcome == 'ok' else None, 'found': 3 if outcome == 'ok' else 0,
           'works': works if outcome == 'ok' else [], 'responses': []})


def made(tmp_path, failed=False, fourth=False):
    s = search.Searcher(tmp_path, get=Net([('EXT_ID', 'known-records.json')]), sleep=lambda _: None,
                        clock=lambda: 0.0)
    lit(s, fourth=fourth)
    if failed:
        lit(s, 'failed')
    return search.known_input(TEXT, CARDS, tmp_path, searcher=s)


def reader(name='reader-1', session='s1', works=None, cards=None):
    return {'checker': {'name': name, 'model': 'm', 'session': session},
            'works': with_population(works if works is not None else [
                {'item': 1, 'verdict': 'tests_refutes', 'quote': QUOTE, 'locator': 'abstract'},
                {'item': 2, 'verdict': 'proposes_or_discusses', 'locator': 'abstract'},
                {'item': 3, 'verdict': 'not_retrievable'}]),
            'cards': cards if cards is not None else [{'item': 1, 'relation': 'variant', 'locator': 'statement'}]}


def second(work1='tests_refutes', card='variant', more=()):
    """The second reader's verdicts on every item: work 1 as given, the others as the first reader has them."""
    return reader('reader-2', 's2', works=[{'item': 1, 'verdict': work1}, {'item': 2, 'verdict': 'proposes_or_discusses'},
                                           {'item': 3, 'verdict': 'not_retrievable'}, *more],
                  cards=[{'item': 1, 'relation': card}])


def test_input_has_the_works_with_their_abstracts_and_the_candidate_cards(tmp_path):
    inp = made(tmp_path)
    assert [w['work']['pmid'] for w in inp['works']] == ['1001', '1002', '1003']
    assert inp['works'][0]['abstract'].startswith('Background We repeated')  # tags removed
    assert inp['works'][0]['date'] == '2016-06-13' and inp['works'][2]['abstract'] == ''
    assert [c['card'] for c in inp['cards']] == ['h-acid']  # the arena record shape is read too
    assert inp['cards'][0]['file_sha256'] == 'sha256:aa' and inp['card_score']['scale'].startswith('0 to 1')
    assert inp['searched']['completion'] == 'complete'
    assert inp['population_matches'] == ['broader', 'narrower', 'not_comparable', 'same']
    assert inp['precision']['stop_reason'] == list(search.STOP_REASONS)
    assert inp['precision']['primary_prespecified'] == ['yes', 'no', 'not_stated']
    # the log holds identifiers, never the abstracts
    log = (tmp_path / search.LOG).read_text()
    assert 'We repeated' not in log and '133 attempts' not in log


def test_a_test_with_a_verified_quote_is_a_known_result_that_stands_on_a_second_reader(tmp_path):
    inp = made(tmp_path)
    out = search.known_merge(TEXT, inp, reader(), 'writer', tmp_path, second(), 'w1')
    assert (out['result'], out['standing'], out['direction']) == ('known_result', 'second_reader_agrees', 'tests_refutes')
    assert out['evidence'] == [{'kind': 'work', 'index': 0, 'decisive': True, 'direction': 'tests_refutes',
                                'second_reader_agrees': True}]
    assert out['directions'] == {'tests_supports': 0, 'tests_refutes': 1}
    assert out['disputed'] == [] and [r['role'] for r in out['readers']] == ['first', 'second']
    assert out['readers'][0]['verdicts_sha256'].startswith('sha256:') and out['merge_calls'][0] == out['works'][0]['call_id']
    w = out['works'][0]
    assert (w['quote'], w['date'], w['doi'], w['quote_check']) == (QUOTE, '2016-06-13', '10.9999/test.1', 'verified')
    assert w['quote_verification']['in'] == 'abstract' and w['quote_verification']['response_sha256'].startswith('sha256:')
    assert out['input']['text_sha256'] == search.sha256(TEXT.encode())
    assert out['finder']['session'] == 'w1' and out['finder']['query_calls'] == ['lit-ok']
    assert [r['session'] for r in out['readers']] == ['s1', 's2']
    # not_retrievable: no quote, no locator invented
    assert 'quote' not in out['works'][2] and 'locator' not in out['works'][2]


def test_without_a_second_reader_it_is_a_recommendation(tmp_path):
    out = search.known_merge(TEXT, made(tmp_path), reader(), 'writer', tmp_path)
    assert (out['result'], out['standing']) == ('known_result', 'recommendation')


def test_a_test_the_second_reader_does_not_see_is_disputed_not_evidence(tmp_path):
    """Mutant: the first reader's item counts although the second reader rejects it."""
    out = search.known_merge(TEXT, made(tmp_path), reader(), 'writer', tmp_path, second('unrelated'))
    assert (out['result'], out['evidence'], out['disputed']) == (
        'new', [], [{'kind': 'work', 'index': 0, 'raised_by': 'first'}])


def test_an_agreed_mixed_test_is_tested_unresolved(tmp_path):
    """Mutant: tests_mixed makes a known result."""
    works = [{'item': 1, 'verdict': 'tests_mixed', 'quote': QUOTE, 'locator': 'abstract'},
             {'item': 2, 'verdict': 'unrelated'}, {'item': 3, 'verdict': 'not_retrievable'}]
    out = search.known_merge(TEXT, made(tmp_path), reader(works=works), 'writer', tmp_path, second('tests_mixed'))
    assert (out['result'], out['standing'], out['direction']) == ('tested_unresolved', 'second_reader_agrees', None)
    assert out['evidence'][0]['decisive'] is False


@pytest.mark.parametrize('first_v, second_v', [
    ('tests_supports', 'tests_refutes'),   # readers differ on the direction
    ('tests_refutes', 'tests_mixed'),
    ('tests_mixed', 'tests_refutes'),
])
def test_a_test_the_readers_judge_differently_is_disputed_not_a_result(tmp_path, first_v, second_v):
    """Mutant: one reader's decisive verdict makes a known result, or two readers who disagree make
    tested_unresolved (run 3: an adjacent study, mixed for one reader and supporting for the other, made
    two untested claims tested)."""
    works = [{'item': 1, 'verdict': first_v, 'quote': QUOTE, 'locator': 'abstract'},
             {'item': 2, 'verdict': 'unrelated'}, {'item': 3, 'verdict': 'not_retrievable'}]
    out = search.known_merge(TEXT, made(tmp_path), reader(works=works), 'writer', tmp_path, second(second_v))
    assert (out['result'], out['evidence'], out['disputed']) == (
        'new', [], [{'kind': 'work', 'index': 0, 'raised_by': 'first'}])


def test_a_review_is_context_never_evidence(tmp_path):
    """Record 1002 states the publication type review. Both readers call it a supporting test; it is
    listed as context, and the refuting trial decides. Mutant: the type is ignored and the result is
    tested_unresolved (decisive tests both ways), or known_result rests on the review."""
    review = 'We discuss whether stress can induce pluripotency.'
    works = [{'item': 1, 'verdict': 'tests_refutes', 'quote': QUOTE, 'locator': 'abstract'},
             {'item': 2, 'verdict': 'tests_supports', 'quote': review, 'locator': 'abstract'},
             {'item': 3, 'verdict': 'not_retrievable'}]
    sec = reader('reader-2', 's2', works=[{'item': 1, 'verdict': 'tests_refutes'}, {'item': 2, 'verdict': 'tests_supports'},
                                          {'item': 3, 'verdict': 'not_retrievable'}], cards=[{'item': 1, 'relation': 'variant'}])
    inp = made(tmp_path)
    assert inp['works'][1]['pub_types'] == ['review']  # the checker sees the type too
    out = search.known_merge(TEXT, inp, reader(works=works), 'writer', tmp_path, sec)
    assert (out['result'], out['direction']) == ('known_result', 'tests_refutes')
    assert out['context'] == [{'kind': 'work', 'index': 1, 'pub_types': ['review']}]
    assert out['works'][1]['secondary'] == ['review'] and [e['index'] for e in out['evidence']] == [0]
    # a review alone is no evidence either: with it as the only test, the result is new
    works[0] = {'item': 1, 'verdict': 'unrelated'}
    sec['works'][0] = {'item': 1, 'verdict': 'unrelated'}
    out = search.known_merge(TEXT, inp, reader(works=works), 'writer', tmp_path, sec)
    assert (out['result'], out['evidence']) == ('new', [])


def test_the_trial_probe_comes_first_into_the_input(tmp_path):
    """A trial the publication-type probe found at rank 3 gets in before the other searches' rank 1;
    mutant: the limit on works cuts it (run 3: 5 of 8 gold works the searches found were cut)."""
    s = search.Searcher(tmp_path, get=Net([('EXT_ID', 'known-records.json')]), sleep=lambda _: None,
                        clock=lambda: 0.0)
    other = [{'source_id': f'MED:{n}', 'pmid': str(n), 'title': 'x'} for n in (1001, 1002)]
    trial = [{'source_id': f'MED:{n}', 'pmid': str(n), 'title': 'x'} for n in (9001, 9002, 1004)]
    for cid, probe, works in (('lit-a', 'as_given', other), ('lit-r', 'rct', trial)):
        s.log({'call_id': cid, 'tool': 'literature', 'outcome': 'ok', 'started_at': 't',
               'ask': {'query': 'q', 'source': 'europepmc', 'variant': 'as_given', 'probe': probe},
               'hit_count': len(works), 'found': len(works), 'works': works, 'responses': []})
    inp = search.known_input(TEXT, CARDS, tmp_path, max_works=3, searcher=s)
    assert [w['work']['pmid'] for w in inp['works']] == ['9001', '9002', '1004']
    assert inp['searched']['rct_first'] == search.RCT_FIRST


def both(tmp_path, v1, v4, s1=None, s4=None):
    """Both readers on an input with two tests of the claim: work 1 (refuting, QUOTE) and work 4 (QUOTE4)."""
    quote = {'tests_supports': QUOTE4, 'tests_refutes': QUOTE, 'tests_mixed': QUOTE}
    works = [{'item': 1, 'verdict': v1, 'quote': QUOTE, 'locator': 'abstract'},
             {'item': 2, 'verdict': 'proposes_or_discusses'}, {'item': 3, 'verdict': 'not_retrievable'},
             {'item': 4, 'verdict': v4, **({'quote': QUOTE4, 'locator': 'abstract'} if v4 in quote else {})}]
    return search.known_merge(TEXT, made(tmp_path, fourth=True), reader(works=works), 'writer', tmp_path,
                              second(s1 or v1, more=[{'item': 4, 'verdict': s4 or v4}]))


def test_decisive_tests_in_both_directions_across_works_are_tested_unresolved(tmp_path):
    """Mutant: one agreed decisive test is enough for a known result although another, also agreed,
    points the other way (run 2, k012: two works support, one refutes)."""
    out = both(tmp_path, 'tests_refutes', 'tests_supports')
    assert (out['result'], out['standing'], out['direction']) == ('tested_unresolved', 'second_reader_agrees', None)
    assert out['directions'] == {'tests_supports': 1, 'tests_refutes': 1}
    assert [(e['index'], e['direction']) for e in out['evidence']] == [(0, 'tests_refutes'), (3, 'tests_supports')]


def test_decisive_tests_that_agree_across_works_are_a_known_result(tmp_path):
    for v in ('tests_refutes', 'tests_supports'):  # the kit checks a quote's passage, the readers its direction
        out = both(tmp_path / v, v, v)
        assert (out['result'], out['direction'], out['directions'][v]) == ('known_result', v, 2)


def test_a_mixed_test_beside_a_decisive_one_leaves_the_decisive_direction(tmp_path):
    out = both(tmp_path, 'tests_refutes', 'tests_mixed')
    assert (out['result'], out['direction']) == ('known_result', 'tests_refutes')


def test_a_direction_only_one_reader_gives_does_not_make_a_conflict(tmp_path):
    """Work 4 supports for the first reader only: it is disputed, and work 1 decides."""
    out = both(tmp_path, 'tests_refutes', 'tests_supports', s4='unrelated')
    assert (out['result'], out['direction']) == ('known_result', 'tests_refutes')
    assert out['disputed'] == [{'kind': 'work', 'index': 3, 'raised_by': 'first'}]


def test_a_test_only_the_second_reader_sees_is_listed_not_evidence(tmp_path):
    """The second reader reads every work; a test the first did not see is disputed, raised by the second."""
    out = both(tmp_path, 'tests_refutes', 'unrelated', s4='tests_supports')
    assert (out['result'], out['direction']) == ('known_result', 'tests_refutes')
    assert out['disputed'] == [{'kind': 'work', 'index': 3, 'raised_by': 'second'}]


@pytest.mark.parametrize('quote, check', [
    ('Exposure of somatic cells to low pH produced pluripotent cells.', 'not_found'),  # not in the abstract
    (' '.join(['word'] * 26), 'too_long'),
    (None, 'missing'),
])
def test_a_quote_the_kit_cannot_find_is_not_evidence(tmp_path, quote, check):
    """Mutant: the quote is taken on the reader's word."""
    works = [{'item': 1, 'verdict': 'tests_refutes', 'quote': quote, 'locator': 'abstract'},
             {'item': 2, 'verdict': 'unrelated'}, {'item': 3, 'verdict': 'not_retrievable'}]
    out = search.known_merge(TEXT, made(tmp_path), reader(works=works), 'writer', tmp_path)
    assert out['works'][0]['quote_check'] == check and out['works'][0]['quote'] is None
    assert (out['result'], out['evidence']) == ('new', [])


def matched(tmp_path, m1, m4, s1=None, s4=None, v1='tests_refutes', v4='tests_supports', p1=POPULATION[1]):
    """Both readers on the two tests of the claim, each with a population match: work 1 (refuting) and work 4
    (supporting)."""
    works = [{'item': 1, 'verdict': v1, 'quote': QUOTE, 'locator': 'abstract', 'population': p1, 'population_match': m1},
             {'item': 2, 'verdict': 'proposes_or_discusses'}, {'item': 3, 'verdict': 'not_retrievable'},
             {'item': 4, 'verdict': v4, 'quote': QUOTE4, 'locator': 'abstract', 'population': POPULATION[4],
              'population_match': m4}]
    sec = second(v1, more=[{'item': 4, 'verdict': v4, 'population': POPULATION[4], 'population_match': s4 or m4}])
    sec['works'][0].update(population=POPULATION[1], population_match=s1 or m1)
    return search.known_merge(TEXT, made(tmp_path, fourth=True), reader(works=works), 'writer', tmp_path, sec)


def test_a_test_of_a_broader_population_is_context_not_a_test(tmp_path):
    """Mutant: a trial of a wider population counts against the claim (run 4: COVACTA and EMPACTA, which did not
    select by inflammation, against tocilizumab in COVID-19 with systemic inflammation). Only the test of the
    claim's own population decides."""
    for m in ('broader', 'not_comparable'):
        out = matched(tmp_path / m, m, 'same')
        assert (out['result'], out['direction']) == ('known_result', 'tests_supports')
        assert out['context'] == [{'kind': 'work', 'index': 0, 'population_match': m}]
        assert [e['index'] for e in out['evidence']] == [3] and out['disputed'] == []
        assert out['works'][0]['population_match'] == m


def test_a_broader_match_the_second_reader_does_not_share_is_listed_as_disputed(tmp_path):
    """Mutant: a test the second reader holds to be of the claim's own population vanishes from the result
    when the first reader calls its population broader; the result stays new, but the disagreement shows."""
    out = matched(tmp_path, 'broader', 'same', s1='same', v4='unrelated')
    assert (out['result'], out['evidence']) == ('new', [])
    assert out['context'] == [{'kind': 'work', 'index': 0, 'population_match': 'broader'}]
    assert out['disputed'] == [{'kind': 'work', 'index': 0, 'raised_by': 'second'}]


def test_a_test_of_a_narrower_population_is_tested_unresolved_never_known(tmp_path):
    """Mutant: a test of a part of the claim's population decides the whole claim."""
    out = matched(tmp_path, 'narrower', 'narrower', v1='unrelated')
    assert (out['result'], out['direction'], out['standing']) == ('tested_unresolved', None, 'second_reader_agrees')
    assert out['evidence'] == [{'kind': 'work', 'index': 3, 'decisive': False, 'direction': None,
                                'second_reader_agrees': True}]


def test_a_narrower_test_beside_a_decisive_one_leaves_its_direction(tmp_path):
    """Run 4, n001: a trial of a wider population (moderate and severe ARDS) refuted a claim about severe ARDS;
    read as broader it is context, read as narrower it does not point the other way."""
    out = matched(tmp_path, 'narrower', 'same')
    assert (out['result'], out['direction'], out['directions']) == (
        'known_result', 'tests_supports', {'tests_supports': 1, 'tests_refutes': 0})


def test_readers_who_differ_on_the_population_leave_the_test_disputed(tmp_path):
    """Mutant: the readers need only agree on the verdict."""
    out = matched(tmp_path, 'same', 'same', s4='narrower')
    assert (out['result'], out['direction']) == ('known_result', 'tests_refutes')
    assert out['disputed'] == [{'kind': 'work', 'index': 3, 'raised_by': 'first'}]
    assert out['works'][3]['second_population_match'] == 'narrower'


@pytest.mark.parametrize('population, match, check', [
    ('somatic cells', None, 'verified'),           # no match given
    (None, 'same', 'missing'),
    ('human embryos', 'same', 'not_found'),        # not in the abstract
    (' '.join(['word'] * 26), 'same', 'too_long'),
])
def test_a_test_without_a_population_found_in_the_work_is_not_evidence(tmp_path, population, match, check):
    """Mutant: the population is taken on the reader's word, or a test without one counts."""
    works = [{'item': 1, 'verdict': 'tests_refutes', 'quote': QUOTE, 'locator': 'abstract', 'population': population,
              'population_match': match}, {'item': 2, 'verdict': 'unrelated'}, {'item': 3, 'verdict': 'not_retrievable'}]
    out = search.known_merge(TEXT, made(tmp_path), reader(works=works), 'writer', tmp_path, second())
    w = out['works'][0]
    assert (w['population_check'], w['population_match'], w['quote_check']) == (check, match, 'verified')
    assert w['population'] == (population if check == 'verified' else None)
    assert (out['result'], out['evidence'], out['context']) == ('new', [], [])
    # only the second reader's test is left, and it is not evidence either
    assert out['disputed'] == [{'kind': 'work', 'index': 0, 'raised_by': 'second'}]


def test_a_population_match_off_the_list_is_refused(tmp_path):
    works = [{'item': 1, 'verdict': 'tests_refutes', 'quote': QUOTE, 'locator': 'abstract', 'population_match': 'wider'},
             {'item': 2, 'verdict': 'unrelated'}, {'item': 3, 'verdict': 'not_retrievable'}]
    with pytest.raises(search.SearchError, match='population_match one of'):
        search.known_merge(TEXT, made(tmp_path), reader(works=works), 'writer', tmp_path)


def precision_of(tmp_path, first, second_=None, item=1, v='tests_refutes'):
    """Both readers on one test (work 1, refuting, or work 4, supporting), with the precision each gives."""
    quote = {1: QUOTE, 4: QUOTE4}[item]
    works = [{'item': 1, 'verdict': 'unrelated'}, {'item': 2, 'verdict': 'unrelated'},
             {'item': 3, 'verdict': 'not_retrievable'}]
    if item == 1:
        works[0] = {'item': 1, 'verdict': v, 'quote': quote, 'locator': 'abstract', **first}
    else:
        works.append({'item': 4, 'verdict': v, 'quote': quote, 'locator': 'abstract', **first})
    sec = second(v if item == 1 else 'unrelated',
                 more=[{'item': 4, 'verdict': v, **(second_ if second_ is not None else first)}] if item == 4 else ())
    if item == 1:
        sec['works'][0].update(second_ if second_ is not None else first)
    return search.known_merge(TEXT, made(tmp_path, fourth=item == 4), reader(works=works), 'writer', tmp_path, sec)


@pytest.mark.parametrize('first', [
    {'stop_reason': 'operational', 'stop_quote': STOPPED},               # closed for lack of funding
    {'primary_prespecified': 'not_stated', 'primary_quote': None},
    {'stop_reason': 'operational', 'stop_quote': 'Closed for lack of staff.'},  # passage not in the work
])
def test_an_imprecise_refutation_is_tested_unresolved_never_known(tmp_path, first):
    """Mutant: a test stopped for operational reasons, or whose primary outcome is not stated as pre-specified,
    decides the claim (run 5: a 50-patient arm of a platform trial closed for operational reasons refuted a
    known result). A stop reason whose passage is not found is unverified: read as not_stated, the operational
    stop would decide."""
    out = precision_of(tmp_path, first)
    assert (out['result'], out['direction'], out['standing']) == ('tested_unresolved', None, 'second_reader_agrees')
    assert out['evidence'][0]['decisive'] is False


@pytest.mark.parametrize('stop', [
    {'stop_reason': 'completed'},
    {'stop_reason': 'futility', 'stop_quote': FUTILITY},
    {'stop_reason': 'not_stated', 'stop_quote': None},
])
def test_a_null_refutation_decides_unless_it_stopped_for_operational_reasons(tmp_path, stop):
    """Mutant: a refutation needs completed enrolment stated in the abstract (run 6: PROWESS-SHOCK, TRISS and
    VIOLET, whose abstracts do not say enrolment completed, and SAILS, stopped for futility, all lost)."""
    out = precision_of(tmp_path, stop)
    assert (out['result'], out['direction']) == ('known_result', 'tests_refutes')


def test_a_refutation_never_decides_through_its_interval(tmp_path):
    """Mutant: a null result counts as excluding no effect."""
    first = {'stop_reason': 'operational', 'stop_quote': 'Closed for lack of staff.',  # unverified: never decides
             'effect_excludes_null': 'yes', 'effect_quote': EXCLUDES}
    out = precision_of(tmp_path, first, item=4)
    assert (out['result'], out['direction']) == ('tested_unresolved', None)


@pytest.mark.parametrize('stop', [
    {'stop_reason': 'not_stated', 'stop_quote': None},     # silence decides a refutation, not support
    {'stop_reason': 'completed', 'stop_quote': COMPLETED[4]},
    {'stop_reason': 'efficacy', 'stop_quote': EFFICACY},
])
def test_a_supporting_test_never_decides_by_its_stop_alone(tmp_path, stop):
    """Mutant: a support decides on completion or an efficacy stop with no effect that excludes none (an
    efficacy stop whose interval includes no effect is not decisive)."""
    out = precision_of(tmp_path, {**stop, 'effect_excludes_null': 'not_stated', 'effect_quote': None}, item=4,
                       v='tests_supports')
    assert out['works'][3]['precision']['stop_reason'] == stop['stop_reason']
    assert (out['result'], out['direction']) == ('tested_unresolved', None)


@pytest.mark.parametrize('stop', [{'stop_reason': 'completed', 'stop_quote': COMPLETED[4]},
                                  {'stop_reason': 'efficacy', 'stop_quote': EFFICACY}])
def test_a_support_stopped_on_completion_or_efficacy_decides_through_its_interval(tmp_path, stop):
    out = precision_of(tmp_path, {**stop, 'effect_excludes_null': 'yes', 'effect_quote': EXCLUDES}, item=4,
                       v='tests_supports')
    assert (out['result'], out['direction']) == ('known_result', 'tests_supports')


def test_a_supporting_test_is_decisive_through_an_effect_that_excludes_none(tmp_path):
    first = {'stop_reason': 'not_stated', 'stop_quote': None, 'effect_excludes_null': 'yes', 'effect_quote': EXCLUDES}
    out = precision_of(tmp_path, first, item=4, v='tests_supports')
    assert (out['result'], out['direction']) == ('known_result', 'tests_supports')
    assert out['works'][3]['precision'] == {'design': 'experimental', 'primary_prespecified': 'yes', 'stop_reason': 'not_stated',
                                            'effect_excludes_null': 'yes', 'underpowered_stated': 'no'}


@pytest.mark.parametrize('first, second_', [
    ({}, {'stop_reason': 'operational', 'stop_quote': STOPPED}),
    ({'stop_reason': 'operational', 'stop_quote': STOPPED}, {}),
])
def test_a_test_is_decisive_only_when_it_is_precise_for_both_readers(tmp_path, first, second_):
    """Mutant: one reader's precision alone decides. Readers who agree on the verdict and the population but
    differ on precision leave the test standing without an outcome."""
    out = precision_of(tmp_path, first, second_)
    assert (out['result'], out['direction']) == ('tested_unresolved', None)
    assert {out['works'][0]['precision']['stop_reason'],
            out['works'][0]['second_precision']['stop_reason']} == {'completed', 'operational'}


def test_an_operational_stop_blocks_a_support_whose_interval_excludes_none(tmp_path):
    """Mutant: an operational stop blocks only a refutation (run 7: Treat Stroke to Target, stopped for lack of
    funding, decided a support by its interval; an interrupted enrolment overstates an effect)."""
    first = {'stop_reason': 'operational', 'stop_quote': 'A matched observational cohort was followed.',
             'effect_excludes_null': 'yes', 'effect_quote': EXCLUDES}
    out = precision_of(tmp_path, first, item=4, v='tests_supports')
    assert out['works'][3]['precision']['stop_reason'] == 'operational'
    assert (out['result'], out['direction']) == ('tested_unresolved', None)


@pytest.mark.parametrize('item, v, extra', [
    (1, 'tests_refutes', {}),
    (4, 'tests_supports', {'stop_reason': 'not_stated', 'stop_quote': None, 'effect_excludes_null': 'yes',
                           'effect_quote': EXCLUDES}),
])
def test_an_observational_association_is_a_test_that_never_decides(tmp_path, item, v, extra):
    """Mutant: a study that did not assign the intervention decides like a trial (run 7: a real-world cohort,
    "associated with lower risks", decided a support beside a refuting trial)."""
    out = precision_of(tmp_path, {'design': 'observational', 'design_quote': OBSERVATIONAL[item], **extra},
                       item=item, v=v)
    assert out['works'][item - 1]['precision']['design'] == 'observational'
    assert (out['result'], out['direction'], out['standing']) == ('tested_unresolved', None, 'second_reader_agrees')


@pytest.mark.parametrize('first', [
    {'design': 'not_stated', 'design_quote': None},
    {'design': 'randomized', 'design_quote': 'Patients were randomly assigned.'},  # passage not in the work
])
def test_a_design_not_stated_or_not_found_never_decides(tmp_path, first):
    out = precision_of(tmp_path, first)
    assert out['works'][0]['precision']['design'] == 'not_stated'
    assert (out['result'], out['direction']) == ('tested_unresolved', None)


def test_a_design_off_the_list_is_refused(tmp_path):
    works = [{'item': 1, 'verdict': 'tests_refutes', 'quote': QUOTE, 'locator': 'abstract', 'design': 'rct'},
             {'item': 2, 'verdict': 'unrelated'}, {'item': 3, 'verdict': 'not_retrievable'}]
    with pytest.raises(search.SearchError, match='design one of'):
        search.known_merge(TEXT, made(tmp_path), reader(works=works), 'writer', tmp_path)


def test_known_check_lists_the_passages_merge_would_not_verify(tmp_path):
    """Mutant: the check passes a passage over 25 words, or one not in the work, and the reader loses the test at
    the merge (run 7: ALIAS Part 2, a 31-word primary passage)."""
    inp = made(tmp_path, fourth=True)
    long = PRIMARY + ' ' + ' '.join(['word'] * 25)
    works = [{'item': 1, 'verdict': 'tests_refutes', 'quote': QUOTE, 'locator': 'abstract', 'primary_quote': long},
             {'item': 2, 'verdict': 'unrelated'}, {'item': 3, 'verdict': 'not_retrievable'},
             {'item': 4, 'verdict': 'tests_supports', 'quote': QUOTE4, 'locator': 'abstract', 'population': 'Mice',
              'underpowered_stated': 'yes', 'underpowered_quote': None}]
    assert search.known_check(inp, reader(works=works), tmp_path) == [
        {'item': 1, 'field': 'primary_quote', 'check': 'too_long'},
        {'item': 4, 'field': 'population', 'check': 'not_found'},
        {'item': 4, 'field': 'underpowered_quote', 'check': 'missing'}]
    # a reader whose passages are all found has nothing listed, and nothing is logged
    before = len(search.read_log(tmp_path))
    clean = reader()
    clean['works'].append({'item': 4, 'verdict': 'unrelated'})
    assert search.known_check(inp, clean, tmp_path) == []
    assert len(search.read_log(tmp_path)) == before


def test_known_check_exits_1_when_a_passage_is_listed(tmp_path, capsys):
    inp = made(tmp_path)
    (tmp_path / 'in.json').write_text(json.dumps(inp))
    (tmp_path / 'ok.json').write_text(json.dumps(reader()))
    bad = reader(works=[{'item': 1, 'verdict': 'tests_refutes', 'quote': 'Not in the work.', 'locator': 'abstract'},
                        {'item': 2, 'verdict': 'unrelated'}, {'item': 3, 'verdict': 'not_retrievable'}])
    (tmp_path / 'bad.json').write_text(json.dumps(bad))
    args = ['known-check', str(tmp_path / 'in.json'), '--workdir', str(tmp_path)]
    assert search.main(args[:2] + [str(tmp_path / 'ok.json')] + args[2:]) == 0
    assert search.main(args[:2] + [str(tmp_path / 'bad.json')] + args[2:]) == 1
    assert json.loads(capsys.readouterr().out.splitlines()[-1]) == [{'item': 1, 'field': 'quote', 'check': 'not_found'}]


def test_a_refutation_the_work_calls_underpowered_never_decides(tmp_path):
    """Mutant: a completed trial that says it was underpowered refutes decisively (run 6: VALISH, whatever its
    stop, said so in its abstract)."""
    out = precision_of(tmp_path, {'underpowered_stated': 'yes', 'underpowered_quote': UNDERPOWERED[1]})
    assert (out['result'], out['direction']) == ('tested_unresolved', None)
    assert out['works'][0]['precision']['underpowered_stated'] == 'yes'


def test_an_underpowered_statement_does_not_touch_a_support_by_its_interval(tmp_path):
    first = {'stop_reason': 'not_stated', 'stop_quote': None, 'effect_excludes_null': 'yes', 'effect_quote': EXCLUDES,
             'underpowered_stated': 'yes', 'underpowered_quote': UNDERPOWERED[4]}
    out = precision_of(tmp_path, first, item=4, v='tests_supports')
    assert (out['result'], out['direction']) == ('known_result', 'tests_supports')


@pytest.mark.parametrize('item, v, first', [
    (1, 'tests_refutes', {'underpowered_stated': 'yes', 'underpowered_quote': 'Too few were enrolled.'}),
    (4, 'tests_supports', {'stop_reason': 'not_stated', 'stop_quote': None, 'effect_excludes_null': 'yes',
                           'effect_quote': EXCLUDES, 'underpowered_stated': 'yes', 'underpowered_quote': 'Too few.'}),
])
def test_an_underpowered_statement_the_kit_cannot_find_never_decides(tmp_path, item, v, first):
    """Mutant: an unverified statement is read as not stated, and the test decides either way."""
    out = precision_of(tmp_path, first, item=item, v=v)
    assert out['result'] == 'tested_unresolved'
    assert out['works'][item - 1]['precision']['underpowered_stated'] == 'unverified'


def test_an_underpowered_value_off_the_list_is_refused(tmp_path):
    works = [{'item': 1, 'verdict': 'tests_refutes', 'quote': QUOTE, 'locator': 'abstract',
              'underpowered_stated': 'not_stated'}, {'item': 2, 'verdict': 'unrelated'},
             {'item': 3, 'verdict': 'not_retrievable'}]
    with pytest.raises(search.SearchError, match='underpowered_stated one of'):
        search.known_merge(TEXT, made(tmp_path), reader(works=works), 'writer', tmp_path)


def test_a_precision_off_the_list_is_refused(tmp_path):
    works = [{'item': 1, 'verdict': 'tests_refutes', 'quote': QUOTE, 'locator': 'abstract',
              'stop_reason': 'partly'}, {'item': 2, 'verdict': 'unrelated'},
             {'item': 3, 'verdict': 'not_retrievable'}]
    with pytest.raises(search.SearchError, match='stop_reason one of'):
        search.known_merge(TEXT, made(tmp_path), reader(works=works), 'writer', tmp_path)


def test_a_same_claim_card_makes_a_duplicate_and_the_known_result_evidence_stays(tmp_path):
    cards = [{'item': 1, 'relation': 'same_claim', 'locator': 'statement'}]
    out = search.known_merge(TEXT, made(tmp_path), reader(cards=cards), 'writer', tmp_path, second(card='same_claim'))
    assert (out['result'], out['standing']) == ('duplicate', 'second_reader_agrees')
    assert {e['kind'] for e in out['evidence']} == {'card', 'work'}
    assert out['cards'][0]['card'] == 'h-acid' and out['cards'][0]['file_sha256'] == 'sha256:aa'
    # a record with no content_hash is named by its id, version and file bytes, never a made-up hash
    assert out['cards'][0]['content_hash'] is None and out['cards'][0]['identity'] == 'id, version and file_sha256'


def test_an_incomplete_search_is_never_new(tmp_path):
    """Mutant: a failed query is ignored and the result says new."""
    inp = made(tmp_path, failed=True)
    assert inp['searched']['completion'] == 'partial' and inp['searched']['failed_calls'] == ['lit-failed']
    works = [{'item': i, 'verdict': 'unrelated'} for i in (1, 2, 3)]
    assert search.known_merge(TEXT, inp, reader(works=works), 'writer', tmp_path)['result'] == 'incomplete'


def test_a_known_result_from_an_incomplete_search_does_not_stand(tmp_path):
    inp = made(tmp_path, failed=True)
    out = search.known_merge(TEXT, inp, reader(), 'writer', tmp_path, second())
    assert (out['result'], out['standing']) == ('known_result', 'recommendation')


def test_cards_only_compares_cards_and_is_never_new(tmp_path):
    inp = search.known_input(TEXT, CARDS, tmp_path, literature=False)
    assert inp['works'] == [] and inp['searched']['completion'] == 'cards_only'
    out = search.known_merge(TEXT, inp, reader(works=[]), 'writer', tmp_path)
    assert out['result'] == 'incomplete'


@pytest.mark.parametrize('change, error', [
    (lambda a: a.update(query_writer='reader-1'), 'must not be the query writer'),
    (lambda a: a.update(second=reader('reader-1', 's2', cards=[])), 'another reader'),
    (lambda a: a.update(second=reader('reader-2', 's1', cards=[])), 'another session'),
    (lambda a: a['first']['works'].append({'item': 9, 'verdict': 'unrelated'}), 'no such item'),
    (lambda a: a['first']['works'][1].update(verdict='supports_claim'), 'verdict one of'),
    (lambda a: a['first']['works'][1].update(note='x'), 'are kept'),
    (lambda a: a['first']['works'].pop(), 'no verdict on'),
    (lambda a: a['first']['checker'].update(name=' '), 'needs a name'),
    (lambda a: a.update(second={'checker': {'name': 'reader-2', 'session': 's2'}, 'works': [], 'cards': []}),
     'no verdict on'),  # the second reader skipped the evidence item
    (lambda a: a.update(text=TEXT + ' '), 'not the one the input'),
])
def test_refused_with_nothing_logged(tmp_path, change, error):
    inp = made(tmp_path)
    args = {'text': TEXT, 'first': reader(), 'query_writer': 'writer', 'second': None}
    change(args)
    before = (tmp_path / search.LOG).read_text()
    with pytest.raises(search.SearchError, match=error):
        search.known_merge(args['text'], inp, args['first'], args['query_writer'], tmp_path, args['second'])
    assert (tmp_path / search.LOG).read_text() == before


def test_a_kept_response_that_changed_is_refused(tmp_path):
    inp = made(tmp_path)
    body = next((tmp_path / search.RESPONSES).glob('*.body'))
    body.write_bytes(body.read_bytes().replace(b'133', b'134'))
    with pytest.raises(search.SearchError, match='not the one the log names'):
        search.known_merge(TEXT, inp, reader(), 'writer', tmp_path)


def test_cli_writes_the_result_beside_the_verdicts(tmp_path):
    inp = made(tmp_path)
    (tmp_path / 'text.txt').write_text(TEXT)
    (tmp_path / 'in.json').write_text(json.dumps(inp))
    (tmp_path / 'v1.json').write_text(json.dumps(reader()))
    assert search.main(['known-merge', str(tmp_path / 'text.txt'), str(tmp_path / 'in.json'), str(tmp_path / 'v1.json'),
                        '--query-writer', 'writer', '--workdir', str(tmp_path)]) == 0
    assert json.loads((tmp_path / 'v1-result.json').read_text())['result'] == 'known_result'


def test_known_search_runs_each_query_as_given_and_narrowed_to_trials_and_null_results(tmp_path):
    """Run 2 found one side of a mixed claim, or neither trial: each query is also sent narrowed to trials
    and to null results, each way to both services, with and without reviews, every record logged."""
    from test_search import LITERATURE, searcher
    s, _ = searcher(tmp_path, [('search?query=%28%28peto', 'lookup.json')] + LITERATURE)  # a probe without reviews
    out = s.known_search(['peto paradox body size'], limit=6)
    assert [(r['ask']['probe'], r['ask']['source'], r['ask']['variant']) for r in out] == [
        (p, src, v) for p in ('as_given', 'trial', 'null', 'rct') for src in ('europepmc', 'pubmed')
        for v in ('as_given', 'no_reviews')]
    # the trial probe asks each service by publication type, most cited first
    rct = out[12:]
    assert 'PUB_TYPE:"randomized controlled trial"' in rct[0]['ask']['query'] and rct[0]['ask']['sort'] == 'CITED desc'
    assert 'randomized controlled trial[pt]' in rct[2]['ask']['query'] and rct[2]['ask']['sort'] == 'relevance'
    assert all(r['outcome'] == 'ok' and r['ask']['limit'] == 6 for r in out)
    assert out[4]['ask']['query'] == search.PROBES['trial']['europepmc'].format('peto paradox body size')
    assert '"no effect"' in out[8]['ask']['query'] and out[0]['ask']['query'] == 'peto paradox body size'
    inp = search.known_input(TEXT, CARDS, tmp_path, searcher=s)
    assert [q['probe'] for q in inp['searched']['queries']][::4] == ['as_given', 'trial', 'null', 'rct']
    assert inp['searched']['max_works'] == 60
    with pytest.raises(search.SearchError, match='non-empty query'):
        s.known_search(['peto', ' '])
