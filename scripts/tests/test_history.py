"""Ledger /2: every check is kept, and a record shows the worst check of the current text."""
import json
import shutil
import subprocess
import sys
import time

import check_card
import check_ledger
import ohfkit
from conftest import SCRIPTS, build_card, load, run_pass

SCOPE = '/added/layers/core/scope|src'


def ledger(workdir):
    return load(workdir / check_ledger.LEDGER_NAME)


def record(card_path, key=SCOPE):
    return next(r for r in load(card_path)['added']['integrity']['entailment'] if check_ledger.key_of(r) == key)


def passes(card_path, workdir, *verdicts):
    """One merge per verdict, each in its own second so that their times differ."""
    for v in verdicts:
        r = run_pass(card_path, workdir, verdict=v, note=None if v == 'entails' else f'{v}: the passage says less')
        assert r.returncode == 0, r.stdout + r.stderr
        time.sleep(1.1)


def test_merge_never_drops_an_entry(xml_workdir):
    card_path = build_card(xml_workdir)
    passes(card_path, xml_workdir, 'entails', 'partial')
    first = ledger(xml_workdir)['entries']
    assert [e['verdict'] for e in first[SCOPE]] == ['entails', 'partial']
    # The value changes; its old checks stay as history next to the new one.
    card_path = build_card(xml_workdir, scope='X causes Y in mice.')
    passes(card_path, xml_workdir, 'entails')
    after = ledger(xml_workdir)['entries']
    for k, history in first.items():
        assert history == after[k][:len(history)], k
    assert [e['verdict'] for e in after[SCOPE]] == ['entails', 'partial', 'entails']
    assert record(card_path)['verdict'] == 'entails'  # the old checks are of other text: not active
    assert check_card.conversion_errors(load(card_path), xml_workdir) == []


def test_later_entails_on_identical_text_leaves_no_and_disputed(xml_workdir):
    card_path = build_card(xml_workdir)
    passes(card_path, xml_workdir, 'no', 'entails')
    no_entry = ledger(xml_workdir)['entries'][SCOPE][0]
    r = record(card_path)
    assert (r['verdict'], r['checked_at'], r['note']) == ('no', no_entry['checked_at'], 'no: the passage says less')
    card = load(card_path)
    assert check_card.conversion_errors(card, xml_workdir) == []  # disputed is not a failure
    keys, n, _, several = check_ledger.summary(card, ledger(xml_workdir))
    assert n == 4 and len(keys) == 2 and keys[1].startswith(SCOPE + ': no ')
    assert several == [], 'these two disagree about one passage, which is a dispute and not two questions'
    out = subprocess.run([sys.executable, '-I', str(SCRIPTS / 'check_ledger.py'), str(card_path),
                          str(xml_workdir / check_ledger.LEDGER_NAME), str(xml_workdir)],
                         capture_output=True, text=True).stdout
    assert f'DISPUTED {SCOPE}: no ' in out and 'LEDGER HISTORY 4 entries, 2 disputed keys' in out
    assert 'LEDGER CHECK PASS' in out


def test_hand_edited_better_verdict_fails(xml_workdir):
    card_path = build_card(xml_workdir)
    passes(card_path, xml_workdir, 'no', 'entails')
    entails_at = ledger(xml_workdir)['entries'][SCOPE][1]['checked_at']
    card = load(card_path)
    for r in card['added']['integrity']['entailment']:
        if check_ledger.key_of(r) == SCOPE:  # point the record at the later, convenient check
            r.update(verdict='entails', checked_at=entails_at)
            del r['note']
    ohfkit.rehash(card, card_path)
    errors = check_card.conversion_errors(load(card_path), xml_workdir)
    assert any(f"{SCOPE}: verdict 'entails' in the card, 'no' in the ledger is the worst" in e for e in errors), errors
    out = subprocess.run([sys.executable, '-I', str(SCRIPTS / 'check_ledger.py'), str(card_path),
                          str(xml_workdir / check_ledger.LEDGER_NAME)], capture_output=True, text=True)
    assert out.returncode == 1 and "is the worst check of this text" in out.stdout


def test_record_no_active_entry_backs_fails(xml_workdir):
    card_path = build_card(xml_workdir)
    passes(card_path, xml_workdir, 'no')
    card = load(card_path)
    for r in card['added']['integrity']['entailment']:
        if check_ledger.key_of(r) == SCOPE:
            r['checked_at'] = '2026-10-20T23:59:59Z'
    ohfkit.rehash(card, card_path)
    errors = check_card.conversion_errors(load(card_path), xml_workdir)
    assert any(f'{SCOPE}: no ledger entry for this text backs the record' in e for e in errors), errors


def test_restore_re_adds_an_archived_no_with_its_checked_at(xml_workdir, tmp_path):
    card_path = build_card(xml_workdir)
    passes(card_path, xml_workdir, 'no')
    archived = tmp_path / 'card.merged.round1.json'
    shutil.copy(card_path, archived)
    no_at = record(card_path)['checked_at']
    # The planted loss: a ledger that kept one check per value, overwritten by a re-check.
    (xml_workdir / check_ledger.LEDGER_NAME).unlink()
    passes(card_path, xml_workdir, 'entails')
    assert record(card_path)['verdict'] == 'entails'
    r = subprocess.run([sys.executable, '-I', str(SCRIPTS / 'entailment.py'), 'restore', str(card_path),
                        str(xml_workdir), str(archived)], capture_output=True, text=True)
    assert r.returncode == 0 and '2 entries restored' in r.stdout, r.stdout + r.stderr
    rec = record(card_path)
    assert (rec['verdict'], rec['checked_at'], rec['note']) == ('no', no_at, 'no: the passage says less')
    assert [e['checked_at'] for e in ledger(xml_workdir)['entries'][SCOPE]][0] == no_at  # in time order
    assert f'DISPUTED {SCOPE}: no {no_at}' in r.stdout
    assert check_card.conversion_errors(load(card_path), xml_workdir) == []
    # Restoring again adds nothing.
    r = subprocess.run([sys.executable, '-I', str(SCRIPTS / 'entailment.py'), 'restore', str(card_path),
                        str(xml_workdir), str(archived)], capture_output=True, text=True)
    assert '0 entries restored' in r.stdout


def test_v1_ledger_still_reads_before_1_4(xml_workdir):
    card_path = build_card(xml_workdir)
    card = load(card_path)
    if card['standard_version'] == '1.4':
        # This is the legacy compatibility control, not a format-1.4 projection record.
        card['standard_version'] = '1.3'
        ohfkit.rehash(card, card_path)
    passes(card_path, xml_workdir, 'partial')
    led_path = xml_workdir / check_ledger.LEDGER_NAME
    v2 = ledger(xml_workdir)
    v1 = {'format': 'ohf-entailment-ledger/1', 'canonicalisation': 'as /1', 'card_id': v2['card_id'],
          'content_hash': v2['content_hash'],
          'entries': {k: {f: e[f] for f in ('value_sha256', 'passage_sha256', 'checked_at', 'verdict')}
                      for k, [e] in v2['entries'].items()}}
    led_path.write_text(json.dumps(v1))
    assert check_card.conversion_errors(load(card_path), xml_workdir) == []
    out = subprocess.run([sys.executable, '-I', str(SCRIPTS / 'check_ledger.py'), str(card_path), str(led_path)],
                         capture_output=True, text=True).stdout
    assert 'LEDGER CHECK PASS' in out and 'LEDGER HISTORY 2 entries' in out
    # The next merge writes /2 and keeps the /1 entry (with the note taken from the card record).
    passes(card_path, xml_workdir, 'entails')
    after = ledger(xml_workdir)
    assert after['format'] == 'ohf-entailment-ledger/2'
    assert [e['verdict'] for e in after['entries'][SCOPE]] == ['partial', 'entails']
    assert record(card_path)['note'] == 'partial: the passage says less'


def test_carry_keeps_history_and_the_worst_record(xml_workdir):
    old = build_card(xml_workdir, out=xml_workdir / 'old.json')
    passes(old, xml_workdir, 'no', 'entails')
    before = ledger(xml_workdir)['entries']
    new = build_card(xml_workdir, out=xml_workdir / 'card.json')
    r = subprocess.run([sys.executable, '-I', str(SCRIPTS / 'entailment.py'), 'carry', str(old), str(new),
                        str(xml_workdir), str(xml_workdir / 'rest.json')], capture_output=True, text=True)
    assert '2 records kept, 0 items to check' in r.stdout, r.stdout + r.stderr
    assert ledger(xml_workdir)['entries'] == before
    assert record(new)['verdict'] == 'no'
    assert check_card.conversion_errors(load(new), xml_workdir) == []


def test_choose_worst_then_earliest_not_older_than_the_assessment():
    e = lambda v, t: {'verdict': v, 'checked_at': f'2026-10-20T20:{t}:01Z'}  # noqa: E731
    checks = [e('entails', 10), e('partial', 20), e('entails', 30), e('partial', 40)]
    assert check_ledger.choose(checks) == e('partial', 20)
    assert check_ledger.choose(checks, '2026-10-20T20:35:00Z') == e('partial', 40)
    assert check_ledger.choose(checks, '2026-10-20T20:45:00Z') == e('partial', 20)  # never a better verdict
    assert check_ledger.choose([e('entails', 10), e('entails', 30)], '2026-10-20T20:15:00Z') == e('entails', 30)
