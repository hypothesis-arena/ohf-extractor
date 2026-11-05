"""A rebuild that leaves an assessment byte-identical keeps its earlier assessed_at."""
import subprocess
import sys
import time

import check_card
import check_ledger
import ohfkit
from conftest import PMCID, SCRIPTS, build_card, load, run_pass

KEY = '/added/layers/core/testability|src'


def with_testability(card_path, workdir, assessed_at, justification='The paragraph names a test in mice.'):
    """Add an assessed value to the card, as a builder would, and rehash."""
    card = load(card_path)
    doc = ohfkit.Document(PMCID, workdir)
    card['added']['layers']['core']['testability'] = {
        'value': {'in_principle': 'testable', 'justification': justification}, 'src': 'p2',
        'assessment': ohfkit.assessment(doc, assessed_at)}
    ohfkit.rehash(card, card_path)
    return card_path


def tick():
    time.sleep(1.1)
    return ohfkit.now()


def carry(old, new, workdir):
    return subprocess.run([sys.executable, '-I', str(SCRIPTS / 'entailment.py'), 'carry', str(old), str(new),
                           str(workdir), str(workdir / 'rest.json')], capture_output=True, text=True)


def time_check(card_path):
    return subprocess.run([sys.executable, '-I', str(ohfkit.TIME_CHECK), str(card_path)], capture_output=True, text=True)


def assessed_at(card_path):
    return load(card_path)['added']['layers']['core']['testability']['assessment']['assessed_at']


def record(card_path):
    return next(r for r in load(card_path)['added']['integrity']['entailment'] if check_ledger.key_of(r) == KEY)


def test_identical_assessment_keeps_its_time_across_a_rebuild(xml_workdir):
    t1 = ohfkit.now()
    old = with_testability(build_card(xml_workdir, out=xml_workdir / 'old.json'), xml_workdir, tick())
    t1 = assessed_at(old)
    assert run_pass(old, xml_workdir).returncode == 0
    # The rebuild stamps a new time on an assessment it did not change.
    new = with_testability(build_card(xml_workdir, out=xml_workdir / 'card.json'), xml_workdir, tick())
    assert assessed_at(new) > t1
    r = carry(old, new, xml_workdir)
    assert '3 records kept, 0 items to check' in r.stdout, r.stdout + r.stderr
    assert assessed_at(new) == t1
    assert check_card.conversion_errors(load(new), xml_workdir) == []
    assert time_check(new).returncode == 0


def test_changed_assessment_keeps_the_new_time(xml_workdir):
    old = with_testability(build_card(xml_workdir, out=xml_workdir / 'old.json'), xml_workdir, tick())
    assert run_pass(old, xml_workdir).returncode == 0
    t2 = tick()
    new = with_testability(build_card(xml_workdir, out=xml_workdir / 'card.json'), xml_workdir, t2,
                           justification='The paragraph names a test in mice and in rats.')
    r = carry(old, new, xml_workdir)
    assert '2 records kept, 1 items to check' in r.stdout, r.stdout + r.stderr
    assert assessed_at(new) == t2
    # A change inside the assessment record alone (here the document it rests on) keeps the new
    # time too.
    card = load(new)
    card['added']['layers']['core']['testability']['value']['justification'] = 'The paragraph names a test in mice.'
    card['added']['layers']['core']['testability']['assessment']['evidence_ref']['sha256'] = 'sha256:' + '0' * 64
    import entailment
    assert entailment.keep_assessment_times(card, [load(old)]) == []


def test_new_kit_version_alone_is_not_a_reassessment(xml_workdir):
    # A rebuild under a newer kit writes a new assessor name on an unchanged judgement. The
    # judgement was made once, by the old version, so both the old assessor and time come back.
    old = with_testability(build_card(xml_workdir, out=xml_workdir / 'old.json'), xml_workdir, tick())
    before = load(old)['added']['layers']['core']['testability']['assessment']
    assert run_pass(old, xml_workdir).returncode == 0
    new = with_testability(build_card(xml_workdir, out=xml_workdir / 'card.json'), xml_workdir, tick())
    card = load(new)
    card['added']['layers']['core']['testability']['assessment']['assessor'] = 'ohf-extractor 9.9.9'
    ohfkit.rehash(card, new)
    r = carry(old, new, xml_workdir)
    assert '3 records kept, 0 items to check' in r.stdout, r.stdout + r.stderr
    after = load(new)['added']['layers']['core']['testability']['assessment']
    assert (after['assessor'], after['assessed_at']) == (before['assessor'], before['assessed_at'])
    assert time_check(new).returncode == 0


def test_old_partial_with_restamped_identical_assessment_passes_time_check_after_carry(xml_workdir):
    """The G8 shape: a 'partial' check, then a rebuild that re-stamps the unchanged assessment
    after that check, then a later 'entails'. The 'partial' stays shown and the times are true."""
    old = with_testability(build_card(xml_workdir, out=xml_workdir / 'old.json'), xml_workdir, tick())
    t1 = assessed_at(old)
    tick()
    assert run_pass(old, xml_workdir, verdict='partial', note='says less than the value').returncode == 0
    partial_at = record(old)['checked_at']
    new = with_testability(build_card(xml_workdir, out=xml_workdir / 'card.json'), xml_workdir, tick())
    assert assessed_at(new) > partial_at  # without the rule, the shown check would predate it
    r = carry(old, new, xml_workdir)
    assert '3 records kept' in r.stdout, r.stdout + r.stderr
    assert assessed_at(new) == t1
    tick()
    assert run_pass(new, xml_workdir, verdict='entails').returncode == 0
    rec = record(new)
    assert (rec['verdict'], rec['checked_at']) == ('partial', partial_at)
    keys, _, _, _ = check_ledger.summary(load(new), load(xml_workdir / check_ledger.LEDGER_NAME))
    assert any(k.startswith(KEY) for k in keys)
    assert check_card.conversion_errors(load(new), xml_workdir) == []
    r = time_check(new)
    assert r.returncode == 0, r.stdout
