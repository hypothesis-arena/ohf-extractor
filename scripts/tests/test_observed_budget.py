"""Invented counter records only; no runtime/model/HTTP measurement is claimed."""
from copy import deepcopy
import pytest
import ohfkit
from conftest import PMCID


def arguments(workdir):
    doc = ohfkit.Document(PMCID, workdir)
    return dict(ident='h_budget', doc=doc, citation='Invented counter fixture.',
                doi='10.0000/budget', topic=['test'], sources={'p1': doc.src(1)},
                author_names='Invented author')


class Counter:
    """A fake observed operation stream, explicitly complete only for this invented run."""
    def __init__(self, events):
        self.events = list(events)
        self.reads = 0

    def __call__(self):
        self.reads += 1
        return {'model_calls': self.events.count('model'),
                'http_requests': self.events.count('http'),
                'coverage': 'complete', 'scope': 'invented completed operation stream'}


def test_builder_without_counter_refuses_instead_of_zero(xml_workdir):
    with pytest.raises(ValueError, match='BUDGET_COUNTER_REQUIRED'):
        ohfkit.skeleton(**arguments(xml_workdir))
    assert not (xml_workdir / 'card.json').exists()


def test_imported_test_counter_cannot_become_a_production_default(xml_workdir):
    from conftest import invented_budget_counter

    args = arguments(xml_workdir)
    explicit = ohfkit.skeleton(**args, budget_counter=invented_budget_counter)
    assert explicit['added']['budget']['model_calls'] == 0
    assert explicit['added']['budget']['http_requests'] == 0
    with pytest.raises(ValueError, match='BUDGET_COUNTER_REQUIRED'):
        ohfkit.skeleton(**args)


@pytest.mark.parametrize('events,expected', [
    (['model', 'http', 'http', 'model', 'http'], (2, 3)),
    (['http'], (0, 1)), (['model'], (1, 0)), ([], (0, 0)),
])
def test_builder_keeps_complete_counter_totals_including_real_zero(xml_workdir, events, expected):
    counter = Counter(events)
    card = ohfkit.skeleton(**arguments(xml_workdir), budget_counter=counter)
    assert card['added']['budget'] == {'model_calls': expected[0], 'http_requests': expected[1],
                                      'input_tokens': None, 'output_tokens': None}
    assert counter.reads == 1
    # A later change to the fake stream cannot mutate the captured totals.
    counter.events.extend(['model', 'http'])
    assert (card['added']['budget']['model_calls'], card['added']['budget']['http_requests']) == expected


@pytest.mark.parametrize('field', ['model_calls', 'http_requests'])
@pytest.mark.parametrize('value', [None, False, True, -1, 0.0, 1.0, '0', [], {}])
def test_invalid_counter_totals_refuse_without_numeric_fallback(xml_workdir, field, value):
    snapshot = Counter([])()
    snapshot[field] = value
    with pytest.raises(ValueError, match='BUDGET_COUNTER_INVALID: ' + field):
        ohfkit.skeleton(**arguments(xml_workdir), budget_counter=lambda: snapshot)


@pytest.mark.parametrize('change', [
    lambda x: x.pop('model_calls'), lambda x: x.pop('http_requests'),
    lambda x: x.update(coverage='partial'), lambda x: x.update(coverage='unknown'),
    lambda x: x.update(scope=''), lambda x: x.update(scope='  '),
    lambda x: x.update(scope=None), lambda x: x.update(extra='unrecognized'),
])
def test_partial_or_missing_observations_refuse_before_card_build(xml_workdir, change):
    snapshot = Counter([])()
    change(snapshot)
    with pytest.raises(ValueError, match='BUDGET_COUNTER_INCOMPLETE'):
        ohfkit.skeleton(**arguments(xml_workdir), budget_counter=lambda: deepcopy(snapshot))


@pytest.mark.parametrize('value', [None, {}, [], 0, False])
def test_counter_must_be_explicit_callable(xml_workdir, value):
    with pytest.raises(ValueError, match='BUDGET_COUNTER_REQUIRED'):
        ohfkit.skeleton(**arguments(xml_workdir), budget_counter=value)


@pytest.mark.parametrize('value', [None, [], 'unknown', 0])
def test_unavailable_counter_snapshot_refuses(xml_workdir, value):
    with pytest.raises(ValueError, match='BUDGET_COUNTER_INCOMPLETE'):
        ohfkit.skeleton(**arguments(xml_workdir), budget_counter=lambda: value)


def test_counter_record_is_not_modified(xml_workdir):
    snapshot = Counter(['model', 'http'])()
    original = deepcopy(snapshot)
    card = ohfkit.skeleton(**arguments(xml_workdir), budget_counter=lambda: snapshot)
    assert snapshot == original
    assert card['added']['budget']['input_tokens'] is None
    assert card['added']['budget']['output_tokens'] is None
