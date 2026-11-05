"""A rebuild that leaves a recorded outcome byte-identical keeps its earlier recorded_at, and the
model and contact come from the environment rather than from the kit."""
import entailment
import ohfkit
import pytest

T1 = '2026-10-20T11:12:13Z'
T2 = '2026-10-21T14:15:16Z'
POINTER = '/added/layers/predictions/0/resolution/value/outcome'


def card_with_outcome(recorded_at, status='refuted', recorded_by='ohf-extractor 0.7.0'):
    """A card-shaped dict with one prediction whose outcome carries a stamp, as a builder writes it."""
    return {'added': {'layers': {'predictions': [
        {'id': 'p_test',
         'resolution': {'value': {'criterion': 'The breeding experiment reports no altered breed.',
                                  'outcome': {'status': status, 'recorded_at': recorded_at,
                                              'recorded_by': recorded_by}}}}]}}}


def test_identical_outcome_keeps_its_recorded_at():
    old, new = card_with_outcome(T1), card_with_outcome(T2)
    assert entailment.keep_recorded_times(new, [old]) == [POINTER]
    outcome = new['added']['layers']['predictions'][0]['resolution']['value']['outcome']
    assert outcome['recorded_at'] == T1


def test_a_changed_outcome_keeps_the_new_recorded_at():
    old, new = card_with_outcome(T1), card_with_outcome(T2, status='supported')
    assert entailment.keep_recorded_times(new, [old]) == []
    assert new['added']['layers']['predictions'][0]['resolution']['value']['outcome']['recorded_at'] == T2


def test_a_new_kit_version_alone_is_not_a_new_record():
    # A rebuild under a newer kit writes its own name into recorded_by on an outcome it did not
    # record again; the earlier stamp and recorder both come back.
    old = card_with_outcome(T1, recorded_by='ohf-extractor 0.6.3')
    new = card_with_outcome(T2, recorded_by='ohf-extractor 0.7.0')
    assert entailment.keep_recorded_times(new, [old]) == [POINTER]
    outcome = new['added']['layers']['predictions'][0]['resolution']['value']['outcome']
    assert (outcome['recorded_at'], outcome['recorded_by']) == (T1, 'ohf-extractor 0.6.3')


def test_an_earlier_card_without_that_outcome_changes_nothing():
    new = card_with_outcome(T2)
    assert entailment.keep_recorded_times(new, [{'added': {'layers': {}}}]) == []
    assert new['added']['layers']['predictions'][0]['resolution']['value']['outcome']['recorded_at'] == T2


def test_the_earliest_identical_record_wins():
    olds = [card_with_outcome(T2), card_with_outcome(T1)]
    new = card_with_outcome('2026-10-22T09:00:01Z')
    assert entailment.keep_recorded_times(new, olds) == [POINTER]
    assert new['added']['layers']['predictions'][0]['resolution']['value']['outcome']['recorded_at'] == T1


def test_model_comes_from_the_environment(monkeypatch):
    monkeypatch.setattr(ohfkit, 'MODEL', None)
    with pytest.raises(ValueError, match='OHF_MODEL'):
        ohfkit.model()
    monkeypatch.setattr(ohfkit, 'MODEL', 'a-model')
    assert ohfkit.model() == 'a-model'


def test_the_user_agent_carries_a_contact_only_when_one_is_given(monkeypatch):
    monkeypatch.setattr(ohfkit, 'CONTACT', None)
    # Without a contact the header is the kit and its version, and carries no address at all:
    # the kit has none of its own to leak.
    assert ohfkit.user_agent() == f"ohf-extractor/{ohfkit.CONVERTER['version']}"
    assert '@' not in ohfkit.user_agent()
    monkeypatch.setattr(ohfkit, 'CONTACT', 'someone@example.org')
    assert ohfkit.user_agent().endswith('(mailto:someone@example.org)')
