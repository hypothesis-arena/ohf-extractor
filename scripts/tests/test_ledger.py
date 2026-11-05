"""Gate (1): each entailment verdict is bound to the value and passage that were checked."""
import json
import subprocess
from pathlib import Path
import sys

import check_card
import check_ledger
import entailment
import ohfkit
from conftest import SCRIPTS, build_card, load, run_pass
import pytest


def ledger_cli(card_path, ledger_path, workdir=None):
    args = [sys.executable, '-I', str(SCRIPTS / 'check_ledger.py'), str(card_path), str(ledger_path)]
    return subprocess.run(args + ([str(workdir)] if workdir else []), capture_output=True, text=True)


def plant(card_path, mutate, rehash=True):
    card = load(card_path)
    mutate(card)
    if rehash:
        ohfkit.rehash(card, card_path)
    else:
        card_path.write_text(json.dumps(card))


def test_merge_writes_a_ledger_that_passes(xml_workdir):
    card_path = build_card(xml_workdir)
    r = run_pass(card_path, xml_workdir)
    assert r.returncode == 0, r.stderr
    led = load(xml_workdir / check_ledger.LEDGER_NAME)
    card = load(card_path)
    assert led['format'] == 'ohf-entailment-ledger/2' and led['card_id'] == 'h_test'
    assert led['content_hash'] == card['content_hash']
    assert set(led['entries']) == {'/added/layers/core/scope|src', '/added/layers/core/scope|basis_quote'}
    [e] = led['entries']['/added/layers/core/scope|src']
    assert e['value_sha256'] == check_ledger.value_sha256('In mice, X may cause Y.')
    assert e['passage_sha256'] == check_ledger.passage_sha256(ohfkit.Document('PMC0000001', xml_workdir).para(2))
    assert check_card.conversion_errors(card, xml_workdir) == []
    for wd in (None, xml_workdir):
        r = ledger_cli(card_path, xml_workdir / check_ledger.LEDGER_NAME, wd)
        assert r.returncode == 0, r.stdout


def test_value_changed_after_merge_fails_check_card(xml_workdir):
    card_path = build_card(xml_workdir)
    assert run_pass(card_path, xml_workdir).returncode == 0
    plant(card_path, lambda c: c['added']['layers']['core']['scope'].update(value='X causes Y in humans.'))
    errors = check_card.conversion_errors(load(card_path), xml_workdir)
    print(errors)
    assert any('scope|src: the value differs from the value that was checked' in e for e in errors)
    assert any('ledger content_hash' in e for e in errors)
    # CI without the sources sees it too.
    r = ledger_cli(card_path, xml_workdir / check_ledger.LEDGER_NAME)
    assert r.returncode == 1 and 'the value differs' in r.stdout


def test_value_changed_without_rehash_fails(xml_workdir):
    card_path = build_card(xml_workdir)
    assert run_pass(card_path, xml_workdir).returncode == 0
    plant(card_path, lambda c: c['added']['layers']['core']['scope'].update(value='X causes Y.'), rehash=False)
    errors = check_card.conversion_errors(load(card_path), xml_workdir)
    assert any('is not its hash' in e for e in errors)
    assert any('the value differs' in e for e in errors)


def test_passage_changed_after_merge_fails_only_with_sources(xml_workdir):
    card_path = build_card(xml_workdir)
    assert run_pass(card_path, xml_workdir).returncode == 0
    # Same value, but its src now names another paragraph: the checker never saw that passage.
    plant(card_path, lambda c: c['added']['layers']['core']['scope'].update(src='p3'))
    errors = check_card.conversion_errors(load(card_path), xml_workdir)
    assert any('scope|src: the passage differs' in e for e in errors)
    led = xml_workdir / check_ledger.LEDGER_NAME
    without = ledger_cli(card_path, led).stdout
    assert 'the passage differs' not in without and 'src passages not checked' in without
    assert 'the passage differs' in ledger_cli(card_path, led, xml_workdir).stdout


def test_verdict_edited_by_hand_fails(xml_workdir):
    card_path = build_card(xml_workdir)
    assert run_pass(card_path, xml_workdir, verdict='partial', note='drops a hedge').returncode == 0

    def edit(c):
        r = c['added']['integrity']['entailment'][0]
        r['verdict'] = 'entails'
        del r['note']
    plant(card_path, edit)
    errors = check_card.conversion_errors(load(card_path), xml_workdir)
    assert any("verdict 'entails' in the card, 'partial' in the ledger" in e for e in errors)


def test_missing_ledger_and_missing_entry_fail(xml_workdir):
    card_path = build_card(xml_workdir)
    assert run_pass(card_path, xml_workdir).returncode == 0
    led_path = xml_workdir / check_ledger.LEDGER_NAME
    led = load(led_path)
    del led['entries']['/added/layers/core/scope|basis_quote']
    led_path.write_text(json.dumps(led))
    errors = check_card.conversion_errors(load(card_path), xml_workdir)
    assert any('scope|basis_quote: entailment record with no ledger entry' in e for e in errors)
    led_path.unlink()
    assert any('no entailment ledger' in e for e in check_card.conversion_errors(load(card_path), xml_workdir))


def test_change_between_input_and_merge_is_refused(xml_workdir):
    card_path = build_card(xml_workdir)
    card = load(card_path)
    items = entailment.build(card, entailment.docs_for(card, xml_workdir))
    (xml_workdir / 'in.json').write_text(json.dumps(items))
    (xml_workdir / 'out.json').write_text(json.dumps([{'id': x['id'], 'verdict': 'entails'} for x in items]))
    plant(card_path, lambda c: c['added']['layers']['core']['scope'].update(value='X causes Y in humans.'))
    before = card_path.read_bytes()
    r = subprocess.run([sys.executable, '-I', str(SCRIPTS / 'entailment.py'), 'merge', str(card_path),
                        str(xml_workdir), str(xml_workdir / 'in.json'), str(xml_workdir / 'out.json')],
                       capture_output=True, text=True)
    assert r.returncode != 0
    assert 'merge refused' in r.stderr and 'the value changed after the input was written' in r.stderr
    assert card_path.read_bytes() == before
    assert not (xml_workdir / check_ledger.LEDGER_NAME).exists()


def test_passage_change_between_input_and_merge_is_refused(xml_workdir):
    card_path = build_card(xml_workdir)
    card = load(card_path)
    items = entailment.build(card, entailment.docs_for(card, xml_workdir))
    plant(card_path, lambda c: c['added']['layers']['core']['scope'].update(src='p3'))
    card = load(card_path)
    led = entailment.read_ledger(card, xml_workdir)
    try:
        entailment.merge(card, items, [{'id': x['id'], 'verdict': 'entails'} for x in items],
                         entailment.docs_for(card, xml_workdir), led)
    except ValueError as e:
        assert 'the passage changed after the input was written' in str(e)
    else:
        raise AssertionError('merge accepted a stale input')


def carry_cli(old, new, workdir, rest):
    return subprocess.run([sys.executable, '-I', str(SCRIPTS / 'entailment.py'), 'carry', str(old), str(new),
                           str(workdir), str(rest)], capture_output=True, text=True)


def test_carry_keeps_only_records_whose_ledger_hash_matches(xml_workdir):
    old = build_card(xml_workdir, out=xml_workdir / 'old.json')
    assert run_pass(old, xml_workdir).returncode == 0
    # Unchanged rebuild: both records and both ledger entries are kept.
    new = build_card(xml_workdir, out=xml_workdir / 'card.json')
    r = carry_cli(old, new, xml_workdir, xml_workdir / 'rest.json')
    assert '2 records kept, 0 items to check' in r.stdout, r.stdout + r.stderr
    assert check_card.conversion_errors(load(new), xml_workdir) == []
    # Rebuild with a changed value: nothing is kept for it, and its history stays.
    before = load(xml_workdir / check_ledger.LEDGER_NAME)['entries']
    new2 = build_card(xml_workdir, scope='X causes Y in humans.', out=xml_workdir / 'card2.json')
    r = carry_cli(new, new2, xml_workdir, xml_workdir / 'rest.json')
    assert '0 records kept, 2 items to check' in r.stdout, r.stdout + r.stderr
    assert load(xml_workdir / check_ledger.LEDGER_NAME)['entries'] == before and len(before) == 2


def test_carry_does_not_launder_a_value_edited_after_merge(xml_workdir):
    """Review §4.1: an old card edited after its merge must not pass its record on."""
    old = build_card(xml_workdir, out=xml_workdir / 'old.json')
    assert run_pass(old, xml_workdir).returncode == 0
    plant(old, lambda c: c['added']['layers']['core']['scope'].update(value='X causes Y in humans.'))
    new = build_card(xml_workdir, scope='X causes Y in humans.', out=xml_workdir / 'card.json')
    r = carry_cli(old, new, xml_workdir, xml_workdir / 'rest.json')
    assert '0 records kept, 2 items to check' in r.stdout, r.stdout + r.stderr


def test_export_checks_then_copies(xml_workdir, tmp_path):
    card_path = build_card(xml_workdir)
    assert run_pass(card_path, xml_workdir).returncode == 0
    out = tmp_path / 'ledgers' / 'h_test.json'
    out.parent.mkdir()
    cmd = [sys.executable, '-I', str(SCRIPTS / 'entailment.py'), 'export', str(card_path), str(xml_workdir), str(out)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert load(out) == load(xml_workdir / check_ledger.LEDGER_NAME)
    out.unlink()
    plant(card_path, lambda c: c['added']['layers']['core']['scope'].update(value='X causes Y.'))
    r = subprocess.run(cmd, capture_output=True, text=True)
    assert r.returncode != 0 and 'export refused' in r.stderr and not out.exists()


def test_check_ledger_runs_alone_from_a_repository_tools_dir(xml_workdir, tmp_path):
    """Pre-1.4 single-file deployment keeps its original positive and refusal controls."""
    import shutil
    card_path = build_card(xml_workdir)
    # This is explicitly the historical standalone contract. Ordinary 1.4 needs
    # the pinned reader bundle; separate tests cover its refusal and positive.
    if load(card_path)['standard_version'] == '1.4':
        plant(card_path, lambda card: card.update(standard_version='1.3'))
    assert run_pass(card_path, xml_workdir).returncode == 0
    tools = tmp_path / 'repo' / 'tools'
    tools.mkdir(parents=True)
    for f in ('content_hash.py', 'strict_json.py'):
        shutil.copy(ohfkit.REPO / 'tools' / f, tools / f)
    shutil.copy(SCRIPTS / 'check_ledger.py', tools / 'check_ledger.py')
    led = xml_workdir / check_ledger.LEDGER_NAME
    args = [sys.executable, '-I', str(tools / 'check_ledger.py'), str(card_path), str(led)]
    r = subprocess.run(args, capture_output=True, text=True, cwd=tmp_path / 'repo')
    assert r.returncode == 0 and 'LEDGER CHECK PASS' in r.stdout, r.stdout + r.stderr
    plant(card_path, lambda c: c['added']['layers']['core']['scope'].update(value='X causes Y.'))
    r = subprocess.run(args, capture_output=True, text=True, cwd=tmp_path / 'repo')
    assert r.returncode == 1 and 'the value differs' in r.stdout
    r = subprocess.run(args + [str(xml_workdir)], capture_output=True, text=True, cwd=tmp_path / 'repo')
    assert r.returncode != 0 and 'needs the ohf-extractor readers' in r.stderr


def test_the_history_summary_survives_a_changed_value_the_card_has_no_record_for(xml_workdir):
    """0.8.15: check_ledger.summary passes records.get(k), which is None for a value the card has no
    record of — the ordinary state after a rebuild, since carry sets a record only for what it could
    carry. When that value also differs from every checked text, _active_for asks rendered_before
    whether an earlier rendering explains the difference, and rendered_before was handed the None
    record and raised AttributeError: the whole ledger check died on the history line instead of
    naming the value. Found merging a flagship's verdicts after rewriting values its checker had
    returned partial on."""
    card_path = build_card(xml_workdir)
    assert run_pass(card_path, xml_workdir).returncode == 0
    ledger = load(xml_workdir / check_ledger.LEDGER_NAME)
    card = load(card_path)
    # What a rebuild leaves behind: the value is rewritten and its record is gone, while the
    # ledger still holds the history of the old text under the same key.
    card['added']['layers']['core']['scope']['value'] = 'In mice, X causes Y under pressure.'
    card['added']['integrity']['entailment'] = [
        r for r in card['added']['integrity']['entailment'] if r['basis'] != 'src']
    disputed, entries, only_history, _ = check_ledger.summary(card, ledger)
    assert entries == 2 and disputed == []
    errors = check_ledger.check(card, ledger)
    assert any('no entailment record (run the entailment pass on it)' in e for e in errors), errors


def test_a_check_older_than_the_source_retrieval_is_not_the_check_a_record_shows(xml_workdir):
    """0.8.16: a check cannot have read a passage retrieved after it. The tie-break between checks
    of one text took account of the value's assessment only, so a stale check of the same verdict
    stayed the active one and the standard's check_refs refused the record (REF_TIME_ORDER,
    "checked_at is earlier than the access time of source record"). Re-checking did not help: the
    new check tied on verdict and lost on time. Measured on both flagships, where carry kept 3 and
    56 such records after version 2 re-fetched its added sources."""
    card_path = build_card(xml_workdir)
    assert run_pass(card_path, xml_workdir).returncode == 0
    ledger = load(xml_workdir / check_ledger.LEDGER_NAME)
    card = load(card_path)
    key = '/added/layers/core/scope|src'
    shown = next(r for r in card['added']['integrity']['entailment']
                 if check_ledger.key_of(r) == key)
    # The source was retrieved after that check: the card now says so.
    later = '2099-01-01T00:00:00Z'
    card['added']['sources']['p2']['accessed_at'] = later
    assert check_ledger.not_before(card, card['added']['layers']['core']['scope']) == later
    # A second check of the same text and verdict, made after the retrieval, is the active one.
    entry = dict(ledger['entries'][key][0])
    entry['checked_at'] = '2099-06-01T00:00:00Z'
    ledger['entries'][key].append(entry)
    act = check_ledger.active(ledger['entries'][key],
                              check_ledger.value_sha256(card['added']['layers']['core']['scope']['value']))
    chosen = check_ledger.choose(act, check_ledger.not_before(card, card['added']['layers']['core']['scope']))
    assert chosen['checked_at'] == '2099-06-01T00:00:00Z', chosen
    # Without the retrieval in the rule, the stale check would have stayed: that is the defect.
    stale = check_ledger.choose(act, check_ledger.latest_assessment(card['added']['layers']['core']['scope']))
    assert stale['checked_at'] == shown['checked_at']


def test_a_mid_list_insertion_is_warned_and_an_append_is_not(tmp_path, capsys):
    """K7: inserting a value into the middle of a list renumbers every later pointer, so the ledger
    records of those elements stop naming their own text. The build may do it; it may not do it
    silently. Measured cost on the second flagship: 59 needed re-checks became 171, and the same
    mistake repeated twice more in one night."""
    import json as _json
    import ohfkit

    def card_with(ids):
        return {'added': {'layers': {'evidence': {'lines': [{'id': i} for i in ids]}}}}

    out = tmp_path / 'card.json'
    out.write_text(_json.dumps(card_with(['a', 'b', 'c'])))

    # Appending: nothing is renumbered, nothing is said.
    assert ohfkit.warn_insertions(card_with(['a', 'b', 'c', 'd']), out) == []
    assert 'WARNING' not in capsys.readouterr().err

    # Inserting before the end: b and c change pointer, and the warning names them.
    moved = ohfkit.warn_insertions(card_with(['a', 'new', 'b', 'c']), out)
    assert moved == [('/added/layers/evidence/lines', ['new'], ['b', 'c'])]
    err = capsys.readouterr().err
    assert 'WARNING /added/layers/evidence/lines' in err and 'new' in err and 'checked again' in err

    # A first build has nothing to compare against.
    assert ohfkit.warn_insertions(card_with(['a']), tmp_path / 'absent.json') == []


def _card_with_a_line():
    """A card with one atom and one evidence line: enough for the renderings of a line field."""
    return {'added': {'layers': {
        'core': {'atoms': [{'id': 'a1', 'statement': {'value': 'X causes Y in mice.', 'src': 'p1'}}]},
        'evidence': {'lines': [{
            'id': 'e1', 'target_ref': 'a1',
            'quote': 'X raised Y in the treated group, while Z did not change',
            'direction': {'value': 'supports', 'src': 'p2'},
            'indirectness': {'value': {'system': 'some', 'endpoint': 'none',
                                       'intervention': 'none', 'comparison': 'none'}, 'src': 'p2'},
        }]}}}}


def test_an_indirectness_and_a_direction_are_sent_with_what_they_are_about():
    """K1: a direction is a relation between this line's finding and the target claim, and an
    indirectness is the distance between the study and that claim. Sent with the passage alone,
    both are judged against the paragraph's overall tenor — which is how a line that extracts one
    finding from a mixed paragraph collected a `partial`: 18 of the 49 partial records on the two
    accepted flagship cards were of this kind. Each is now sent with the target statement and with
    the line's own quotation."""
    import check_ledger
    card = _card_with_a_line()
    items = {check_ledger.key_of(x): x for x in check_ledger.value_items(card)}
    line = card['added']['layers']['evidence']['lines'][0]
    for field in ('direction', 'indirectness'):
        key = f'/added/layers/evidence/lines/0/{field}|src'
        assert key in items, sorted(items)
        value = items[key]['value']
        assert set(value) == {field, 'target_statement', 'line_quote'}, (field, value)
        assert value['line_quote'] == line['quote']
        assert value['target_statement'] == 'X causes Y in mice.'


def test_a_record_made_under_an_earlier_rendering_is_still_read():
    """A rendering is the kit's work, not the card's text, so a record made under an earlier one is
    honoured for reading and re-resolved at the next rebuild — otherwise every accepted card became
    unreadable the moment K1 landed, which is exactly what the accepted-card regression caught."""
    import check_ledger
    card = _card_with_a_line()
    node = card['added']['layers']['evidence']['lines'][0]['direction']
    renderings = check_ledger.earlier_renderings(card, '/added/layers/evidence/lines/0/direction', node)
    assert 'supports' in renderings, 'the bare value is an earlier rendering'
    assert {'direction': 'supports', 'target_statement': 'X causes Y in mice.'} in renderings, \
        'the 0.8.x rendering (direction with its target, without the line quote) must be remembered'
    # The order matters: the newest earlier rendering is tried first.
    assert renderings.index({'direction': 'supports', 'target_statement': 'X causes Y in mice.'}) \
        < renderings.index('supports')


def _card_with_groups():
    """Two lines on one dataset, and a reanalysis of that dataset citing its own paper."""
    def line(i, group, artifact):
        # each file has its own bytes: the digest is the one the saved source of that name hashes to
        return {'id': f'e{i}', 'target_ref': 'a1', 'quote': 'q', 'src': 'p1',
                'independence_group': {'value': group, 'src': 'p1'},
                'items': [{'value': {'artifact': artifact, 'sha256': artifact[0].lower() * 64,
                                     'locator': 'XML .//p[1]'}, 'src': 'p1'}]}
    return {'added': {
        'sources': {'s1': {'artifact': 'A.xml', 'sha256': 'a' * 64},
                    's2': {'artifact': 'B.xml', 'sha256': 'b' * 64},
                    'p1': {'source': 'https://example.org/A', 'locator': 'XML .//p[1]',
                           'accessed_at': '2026-10-20T00:00:00Z'}},
        'layers': {'core': {'atoms': [{'id': 'a1', 'statement': {'value': 'X.', 'src': 'p1'}}]},
                   'evidence': {'lines': [line(0, 'g_data', 'A.xml'), line(1, 'g_data', 'A.xml'),
                                          line(2, 'g_data', 'B.xml'), line(3, 'g_other', 'B.xml')]}}}}


class _Saved:
    """One saved source, as `docs_for` opens it: a file name, the digest of its bytes, its paragraphs."""

    def __init__(self, file, sha):
        self.file, self.sha = file, sha

    def para(self, n):
        return 'a paragraph'


def _saved_sources():
    """The manifest `docs_for` opens: three saved documents, C.xml cited by no item of the card."""
    return {'https://example.org/A': _Saved('A.xml', 'a' * 64), 'https://example.org/B': _Saved('B.xml', 'b' * 64),
            'https://example.org/C': _Saved('C.xml', 'c' * 64)}


def test_a_cited_item_resolves_against_the_saved_sources_and_is_not_asked_of_a_passage(xml_workdir):
    """K10: which work a line rests on is a fact about bytes, not about a paragraph. 80 such records
    across the two accepted cards were decided by a checker shown only a paragraph; 9 of them were
    partial or no for want of a study name in that paragraph, and 71 entailed because the paragraph
    happened to name one. It is decided here against the documents the card's manifest holds."""
    import entailment
    card, docs = _card_with_groups(), _saved_sources()
    item = {'pointer': '/added/layers/evidence/lines/0/items/0', 'basis': 'src',
            'value': {'artifact': 'A.xml', 'sha256': 'a' * 64, 'locator': 'XML .//p[1]'},
            'source_passage': 'anything at all'}
    assert entailment.is_resolved(item), 'a cited item is decided by resolution'
    verdict, note = entailment.resolve(item, card, docs)
    assert verdict == 'entails' and 'A.xml' in note
    # A digest that contradicts another item naming the same artifact is refused before membership is
    # looked at: two digests for one file mean one of them is stale whatever the manifest says.
    clash = dict(item, value={'artifact': 'A.xml', 'sha256': 'f' * 64, 'locator': 'XML .//p[1]'})
    verdict, note = entailment.resolve(clash, card, docs)
    assert verdict == 'no' and 'stale or mistyped' in note, note


def test_a_foreign_file_is_partial_and_not_entails(xml_workdir):
    """The permanent mutant of the independent review: `unknownC.xml` with a well-formed digest of its
    own is consistent with every item of the card and belongs to no source of it. The rule before this
    one asked only for consistency and answered `entails` — a verdict about bytes nothing had bound.

    It is `partial` and not `no` by the lead's decision of 2026-10-23: a missing manifest entry is a
    missing binding, not a finding that the line is wrong. Measured when the boundary moved: all 80
    cited items of the two accepted cards stay `entails` (27 and 53), because their sources are in the
    manifest, and the groups stay 50 `entails` and 29 `partial`."""
    import entailment
    card, docs = _card_with_groups(), _saved_sources()
    base = {'pointer': '/added/layers/evidence/lines/0/items/0', 'basis': 'src', 'source_passage': 'anything'}
    foreign = dict(base, value={'artifact': 'unknownC.xml', 'sha256': 'f' * 64, 'locator': 'XML .//p[1]'})
    verdict, note = entailment.resolve(foreign, card, docs)
    assert verdict == 'partial', note
    assert 'source_not_bound' in note and 'consistency is not membership' in note, note
    # the name of a saved source over bytes that are not its own, and bytes of one saved source under
    # the name of another: both are a wrong pair, which is a `no` about this line
    # C.xml is saved and cited by no item, so no clash hides the case: its name over A's bytes.
    crossed = dict(base, value={'artifact': 'C.xml', 'sha256': 'a' * 64, 'locator': 'XML .//p[1]'})
    verdict, note = entailment.resolve(crossed, card, docs)
    assert verdict == 'no' and 'A.xml' in note, note
    wrong_bytes = dict(base, value={'artifact': 'C.xml', 'sha256': 'f' * 64, 'locator': 'XML .//p[1]'})
    verdict, note = entailment.resolve(wrong_bytes, card, docs)
    assert verdict == 'no' and 'does not rest on the bytes it names' in note, note
    # the converted article's own recorded digest is a witness where the manifest has no such file
    witnessed = dict(base, value={'artifact': 'elsewhere.xml', 'sha256': 'd' * 64, 'locator': 'XML .//p[1]'})
    card['author'] = {'source': {'source_text_sha256': 'd' * 64}}
    verdict, note = entailment.resolve(witnessed, card, docs)
    assert verdict == 'entails' and 'source_text_sha256' in note, note
    # and with no manifest opened at all, membership cannot be shown: partial, never entails
    verdict, note = entailment.resolve(dict(base, value={'artifact': 'A.xml', 'sha256': 'a' * 64}), card)
    assert verdict == 'partial' and 'source_not_bound' in note, note


def test_a_group_holding_a_reanalysis_is_partial_and_not_refused():
    """A group says where the data come from, which is not the document a line cites: a reanalysis of
    another study's dataset belongs in that dataset's group while citing its own paper — the real
    case on the first flagship (`e_dujon_reanalysis` rests on Vincze's ZIMS data). The strict rule
    "one group, one artifact" would have turned 15 correct records into `no` on that card, which is
    how this was caught: by measuring before believing."""
    import entailment
    card = _card_with_groups()
    item = {'pointer': '/added/layers/evidence/lines/0/independence_group', 'basis': 'src',
            'value': 'g_data', 'source_passage': 'a paragraph naming no study'}
    verdict, note = entailment.resolve(item, card)
    assert verdict == 'partial' and 'A.xml' in note and 'B.xml' in note
    assert 'not a contradiction' in note and 'independence_key' in note
    alone = dict(item, pointer='/added/layers/evidence/lines/3/independence_group', value='g_other')
    verdict, note = entailment.resolve(alone, card)
    assert verdict == 'entails' and 'B.xml' in note


def test_a_resolution_from_an_earlier_binding_rule_holds_and_is_resolved_again(xml_workdir):
    """The independent review's second finding (K10-R3): the new boundary decided a **fresh** question
    correctly and changed nothing for a ledger that already held an answer. An `entails` written under
    binding rule 1 sat in the ledger under the same resolver identity, `active` found it, the key was
    skipped, and the card kept the old verdict - so the rule held for a card checked today and not for
    one checked yesterday. Worse, the record was then stamped with the **current** resolver, relabelling
    a version 1 verdict as a version 2 resolution.

    The resolver's identity now carries the binding rule, and the entry records it. An entry from an
    earlier rule stays in the history, which is only appended to, and authorises nothing:

    - the read side holds the key (`superseded_resolution`) instead of showing the old verdict,
    - `resolve_references` resolves it again, appending the new verdict beside the old,
    - the new verdict is `partial` where nothing binds the bytes, which is the case this is about.
    """
    import check_ledger
    import entailment
    card, docs = _card_with_groups(), _saved_sources()
    # a cited item that names a file no saved source holds: under rule 1 this was `entails`
    card['added']['layers']['evidence']['lines'][0]['items'][0]['value'] = {
        'artifact': 'unknownC.xml', 'sha256': 'f' * 64, 'locator': 'XML .//p[1]'}
    item = {'pointer': '/added/layers/evidence/lines/0/items/0', 'basis': 'src',
            'value': card['added']['layers']['evidence']['lines'][0]['items'][0]['value'],
            'source_passage': 'a paragraph'}
    old = {'name': check_ledger.RESOLVER_NAME, 'version': '1.0.0', 'prompt_sha256': 'sha256:' + 'a' * 64}
    record = {'pointer': item['pointer'], 'basis': item['basis'], 'verdict': 'entails',
              'checker': dict(old), 'checked_at': '2026-10-22T00:00:00Z'}
    led = check_ledger.new_ledger({**card, 'id': 'h_demo'})
    check_ledger.add_entry(led, check_ledger.key_of(item), check_ledger.entry(item, record), None)
    key = check_ledger.key_of(item)
    assert led['entries'][key][0]['resolver'] == {'name': check_ledger.RESOLVER_NAME, 'version': '1.0.0'}, \
        'the entry names the version it was made under, and the version carries the binding rule'
    assert not check_ledger.by_current_resolver(led['entries'][key][0])
    # an entry written before entries named a resolver at all - the shape in the ledgers that exist
    # today - carries no `resolver` member, and that absence is itself the answer
    before = {k: v for k, v in led['entries'][key][0].items() if k != 'resolver'}
    assert not check_ledger.by_current_resolver(before) and not check_ledger.by_resolver(before)

    # the read side: the old verdict is not shown, and the card that carries it is held
    assert entailment.shown_record(item, led) is None, 'an old resolution shows no record'
    card['added']['integrity'] = {'entailment': [record]}
    held = [e for e in check_ledger.check(card, led, {key: 'a paragraph'}) if 'superseded_resolution' in e]
    assert len(held) == 1 and 'saved-sources@2' in held[0], held

    # the write side: resolved again, and the new verdict is the honest one
    fresh = entailment.resolve_references(card, docs, led)
    mine = [r for r in fresh if r['pointer'] == item['pointer']]
    assert len(mine) == 1 and mine[0]['verdict'] == 'partial', fresh
    assert all(check_ledger.by_current_resolver(r) for r in fresh)
    history = led['entries'][key]
    assert len(history) == 2 and [e['verdict'] for e in history] == ['entails', 'partial'], \
        'the old entry stays: a history is appended to, never rewritten'
    assert check_ledger.superseded(history) == [history[0]]
    # and now that a current verdict exists, the key is not resolved a third time
    assert entailment.resolve_references(card, docs, led) == []


def test_carry_refuses_a_check_older_than_the_passage_it_claims_to_have_read():
    """K2: a check made before its source was retrieved cannot have read that passage, and the
    standard's `check_refs` refuses such a record. `choose` falls back to the earliest check when
    none is new enough, so before this the card was rebuilt, passed `carry`, and then failed the
    repository checkers with nothing the converter could do: re-running the pass did not help,
    because the tie-break preferred the stale check. Measured when it was found: 3 such records on
    one flagship and 56 on the other. They now go to the rest file and are checked again."""
    import check_ledger
    import entailment

    card = {'added': {
        'at': '2026-10-22T12:00:00Z',
        'sources': {'p1': {'source': 'u', 'locator': 'XML .//p[1]', 'accessed_at': '2026-10-22T10:00:00Z',
                           'tool': 'reading'}},
        'integrity': {'entailment': []},
        'layers': {'core': {'scope': {'value': 'X in mice.', 'src': 'p1'}},
                   'evidence': {'lines': []}}}}
    node = card['added']['layers']['core']['scope']
    item = {'pointer': '/added/layers/core/scope', 'basis': 'src', 'value': 'X in mice.',
            'source_passage': 'X in mice.'}
    key = check_ledger.key_of(item)
    stale = {'value_sha256': check_ledger.value_sha256(item['value']),
             'passage_sha256': check_ledger.passage_sha256(item['source_passage']),
             'checked_at': '2026-10-21T09:00:00Z', 'verdict': 'entails'}
    ledger = {'format': 'ohf-entailment-ledger/2', 'entries': {key: [stale]}, 'notes': {}}

    floor = check_ledger.not_before(card, node)
    assert floor == '2026-10-22T10:00:00Z', 'the floor is the access time of the cited source'
    assert check_ledger.choose([stale], floor) is stale, 'choose still falls back to the only check'

    class _Doc:
        def para(self, n):
            return 'X in mice.'

    docs = {'u': _Doc()}
    old_card = json.loads(json.dumps(card))
    kept, rest = entailment.carry(old_card, card, docs, ledger)
    assert kept == [], 'a check older than the retrieval of its passage is not carried'
    assert [x['pointer'] for x in rest] == ['/added/layers/core/scope']

    # A check made after the retrieval is carried as before.
    ledger['entries'][key] = [dict(stale, checked_at='2026-10-22T11:00:00Z')]
    kept, rest = entailment.carry(old_card, card, docs, ledger)
    assert [r['pointer'] for r in kept] == ['/added/layers/core/scope'] and rest == []


def test_a_cited_item_binds_the_exact_pair_and_refuses_a_missing_digest():
    """The three ways the first version of this check could be passed, found by an independent
    review of it: an artifact of the card carrying another source's digest; an artifact the card
    does not hold carrying a digest it does; and an empty digest, which bypassed the test
    altogether. The binding is the pair — this artifact with this digest — and a digest that is not
    a sha256 is refused, because a missing digest is exactly the case where nothing binds the line to
    any bytes.

    The last case here is the one a second review broke: the pair was taken from the card's own items,
    so a file no source of this card names passed on its own digest. The pairs are now taken from the
    saved sources, and such an item is `partial` with `source_not_bound`."""
    import entailment
    card = {'added': {'sources': {'s1': {'artifact': 'A.xml', 'sha256': 'a' * 64},
                                  's2': {'artifact': 'B.xml', 'sha256': 'b' * 64}},
                      'layers': {'core': {'atoms': [{'id': 'a1', 'statement': {'value': 'X.', 'src': 'p1'}}]},
                                 'evidence': {'lines': [
                                     {'id': 'e0', 'target_ref': 'a1', 'quote': 'q', 'src': 'p1',
                                      'items': [{'value': {'artifact': 'A.xml', 'sha256': 'a' * 64,
                                                           'locator': 'XML .//p[1]'}, 'src': 'p1'}]}]}}}}

    docs = {'https://example.org/A': _Saved('A.xml', 'a' * 64), 'https://example.org/B': _Saved('B.xml', 'b' * 64)}

    def verdict(value):
        item = {'pointer': '/added/layers/evidence/lines/0/items/0', 'basis': 'src',
                'value': value, 'source_passage': 'any passage at all'}
        return entailment.resolve(item, card, docs)

    assert verdict({'artifact': 'A.xml', 'sha256': 'a' * 64, 'locator': 'l'})[0] == 'entails'
    # No digest at all, and a digest that is not one: nothing binds the line to any bytes.
    for sha in ('', None, 'sha256:', 'not-a-digest', 'A' * 64):
        v, note = verdict({'artifact': 'C.xml', 'sha256': sha, 'locator': 'l'})
        assert v == 'no' and 'not a sha256 digest' in note, (sha, v, note)
    # Two digests for one artifact: one of them is stale or mistyped.
    v, note = verdict({'artifact': 'A.xml', 'sha256': 'b' * 64, 'locator': 'l'})
    assert v == 'no' and 'stale or mistyped' in note, note
    # An artifact no saved source of this card holds, on a digest of its own: consistent with every
    # item here and bound to nothing. A first version tested the pair against added.sources — where
    # 1.0 records no digest at all — and refused all 80 items of the two accepted cards; the version
    # after it answered `entails` here, which is the hole this is now the regression for.
    v, note = verdict({'artifact': 'C.xml', 'sha256': 'c' * 64, 'locator': 'l'})
    assert v == 'partial' and 'source_not_bound' in note, note


def test_a_resolution_remembers_the_sources_it_rested_on(xml_workdir):
    """The independent review's fourth finding (K10-R4), and the last of this class: a cached
    resolution of the rule in force did not know which manifest it was bound to.

    A ledger entry is keyed by the value and the passage, and a **source** can change without either
    moving: an item naming `(C.xml, digest C)` is the same value after C.xml is refetched and hashes to
    something else. The cached `entails` was then reused for a card whose own source no longer matched
    it, while a fresh resolution of the same item answered `no`.

    So a resolution now records the digests it rested on, and a cached one counts only while the rule
    version, the passage and those digests are all what they were. The lead's decision, general rather
    than one more case.
    """
    import check_ledger
    import entailment
    card, docs = _card_with_groups(), _saved_sources()
    card['added']['layers']['evidence']['lines'][0]['items'][0]['value'] = {
        'artifact': 'C.xml', 'sha256': 'c' * 64, 'locator': 'XML .//p[1]'}
    item = {'pointer': '/added/layers/evidence/lines/0/items/0', 'basis': 'src',
            'value': card['added']['layers']['evidence']['lines'][0]['items'][0]['value'],
            'source_passage': 'a paragraph'}
    key = check_ledger.key_of(item)
    led = check_ledger.new_ledger({**card, 'id': 'h_demo'})

    first = [r for r in entailment.resolve_references(card, docs, led) if r['pointer'] == item['pointer']]
    assert len(first) == 1 and first[0]['verdict'] == 'entails'
    assert led['entries'][key][0]['resolver_inputs'] == {'C.xml': 'c' * 64}, \
        'the entry records which bytes the verdict was about'
    assert entailment.resolve_references(card, docs, led) == [], 'nothing moved: not resolved again'

    # C.xml is refetched and hashes to something else. The item and its passage are untouched.
    docs['https://example.org/C'].sha = 'f' * 64
    inputs = entailment.resolution_inputs(card, item, docs)
    assert inputs == {'C.xml': 'f' * 64}
    # the read side holds the old verdict: it is about bytes the manifest no longer holds
    card_with_old = {**card, 'id': 'h_demo',
                     'added': {**card['added'], 'integrity': {'entailment': [first[0]]}}}
    held = [e for e in check_ledger.check(card_with_old, led, {key: 'a paragraph'}, None, {key: inputs})
            if 'superseded_resolution' in e]
    assert len(held) == 1 and 'now hash to' in held[0], held
    # and the write side resolves it again: the named file hashes to something else, so `no`
    again = [r for r in entailment.resolve_references(card, docs, led) if r['pointer'] == item['pointer']]
    assert len(again) == 1 and again[0]['verdict'] == 'no', again
    assert [e['verdict'] for e in led['entries'][key]] == ['entails', 'no'], 'the history keeps both'
    assert led['entries'][key][1]['resolver_inputs'] == {'C.xml': 'f' * 64}
    # a card shows no record for it until the new verdict is written in
    assert entailment.shown_record(item, led, inputs=inputs)['verdict'] == 'no'
    assert entailment.shown_record(item, led, inputs={'C.xml': 'a' * 64}) is None, \
        'a third set of bytes is a third question: no record is shown for it'


@pytest.mark.xfail(reason='K10-R5, known limitation of 279cd43: resolver_inputs records the digests of '
                          'the saved sources the verdict names, but a cited item is also resolved '
                          'against what its SIBLING items declare - the consistency check - and those '
                          'declarations are not among its recorded inputs. So a sibling re-declared '
                          'with another digest leaves this item\'s cached entails in force while a '
                          'fresh resolution answers no. Merged with the limitation by the lead\'s '
                          'decision of 2026-10-23; the fix (inputs over every source the verdict '
                          'reads, siblings included) is its own task. Until then: run the resolution '
                          'pass without the cache before accepting a card whose saved sources or item '
                          'declarations changed after its first resolution.', strict=True)
def test_a_changed_sibling_declaration_cannot_reuse_a_consistency_verdict(xml_workdir):
    """The independent review's fifth finding, reproduced here so that it cannot be forgotten and so
    that the day it starts passing is visible: this test is `strict`, so it fails the suite when the
    limitation is fixed, which is the signal to drop the marker.

    The shape: item 0 of line 0 names (A.xml, digest A) and resolves to `entails`. Line 1's item is
    then re-declared with another digest for the same artifact. Nothing about item 0's own value or
    passage has changed, and the saved sources have not moved, so its recorded inputs still match -
    but the verdict for item 0 reads the siblings, and a fresh resolution of it now answers `no`
    (two digests for one artifact). The card keeps the cached `entails`.
    """
    import check_ledger
    import entailment
    card, docs = _card_with_groups(), _saved_sources()
    card['id'] = 'h_sibling'
    card['added']['integrity'] = {'entailment': []}
    led = check_ledger.new_ledger(card)
    first = entailment.resolve_references(card, docs, led)
    pointer = '/added/layers/evidence/lines/0/items/0'
    item = next(x for x in entailment.build(card, docs) if x['pointer'] == pointer)
    assert entailment.resolve(item, card, docs)[0] == 'entails'
    inputs = dict(entailment.resolution_inputs(card, item, docs))

    card['added']['layers']['evidence']['lines'][1]['items'][0]['value']['sha256'] = 'f' * 64
    now = next(x for x in entailment.build(card, docs) if x['pointer'] == pointer)
    verdict, note = entailment.resolve(now, card, docs)
    assert verdict == 'no' and 'other items' in note, (verdict, note)
    assert now == item and entailment.resolution_inputs(card, now, docs) == inputs == {'A.xml': 'a' * 64}

    again = entailment.resolve_references(card, docs, led)
    entailment.write_records(card, docs, led, first + again)
    shown = next(r for r in card['added']['integrity']['entailment'] if r['pointer'] == pointer)
    assert shown['verdict'] == 'no', 'the cached verdict is reused although the question has changed'


def test_one_value_with_two_passages_is_two_questions_and_not_a_dispute(xml_workdir):
    """The acceptor's correction, measured on an accepted card: 11 keys there held verdicts that
    differ, and not one of them differed about the same passage. A value with a `src` paragraph and a
    `basis_quote`, or with two sources that state it, is asked a separate question for each; two
    answers to two questions are not a disagreement, and counting them as one over-reported the
    card's state. The kit still shows the worst verdict - that part was right."""
    import check_ledger
    item = {'pointer': '/added/layers/core/scope', 'basis': 'src', 'value': 'In mice.',
            'source_passage': 'a paragraph'}
    entails = {'value_sha256': check_ledger.value_sha256(item['value']), 'passage_sha256': 'sha256:' + 'a' * 64,
               'verdict': 'entails', 'checked_at': '2026-10-22T00:00:00Z'}
    partial_other = dict(entails, passage_sha256='sha256:' + 'b' * 64, verdict='partial',
                         checked_at='2026-10-22T01:00:00Z')
    partial_same = dict(entails, verdict='partial', checked_at='2026-10-22T02:00:00Z')
    assert check_ledger.several_passages([entails, partial_other]), 'two passages, two questions'
    assert not check_ledger.disputed([entails, partial_other])
    assert check_ledger.disputed([entails, partial_same]), 'one passage, two answers: a dispute'
    assert not check_ledger.several_passages([entails, partial_same])
    assert len(check_ledger.by_passage([entails, partial_other, partial_same])) == 2


def test_the_numbers_of_a_line_are_sent_with_the_quotation_they_are_read_from():
    """The OHF 1.1 members a line can carry whose value says nothing on its own.

    A bare `48` judged against a paragraph is unjudgeable - the checker cannot know what was counted -
    and the numbers of a `result_estimate` are read out of the line's quotation in the first place. So
    each goes to the checker with that quotation, and the question is whether the passage states it for
    this result. They are not sent with the target statement: that is what a direction or an
    indirectness is about, and these are about the study. The three merged OHF 1.1 patches left these
    questions to this step by name.
    """
    card = _card_with_a_line()
    line = card['added']['layers']['evidence']['lines'][0]
    line['sample'] = {'value': 'male C57BL/6 mice', 'src': 'p3'}
    line['sample_size'] = {'value': 48, 'src': 'p3'}
    line['multi_site_program'] = {'value': {'program': 'ITP', 'sites': ['UM', 'UT']}, 'src': 'p3'}
    line['result_estimate'] = {'value': {'kind': 'hazard_ratio', 'point': 0.8}, 'src': 'p3'}
    items = {check_ledger.key_of(x): x for x in check_ledger.value_items(card)}
    for field in ('sample', 'sample_size', 'multi_site_program', 'result_estimate'):
        key = f'/added/layers/evidence/lines/0/{field}|src'
        assert key in items, sorted(items)
        value = items[key]['value']
        assert set(value) == {field, 'line_quote'}, (field, value)
        assert value['line_quote'] == line['quote']
        assert value[field] == line[field]['value']


def test_a_taxon_id_is_sent_with_the_word_the_line_states_for_it():
    """A passage cannot entail an NCBI identifier.

    The id's truth is in the recorded efetch call that its `src` points at, which is resolution and not
    reading. What a reader of prose can answer is whether the passage names that taxon, so the item
    carries the id together with the prediction's own word for it.
    """
    card = {'added': {'layers': {'predictions': [{
        'id': 'p1',
        'system': {'kind': {'value': 'clade', 'src': 'p1'},
                   'taxon': {'value': 'Carnivora', 'src': 'p1'},
                   'taxon_id': {'value': 'NCBITaxon:33554', 'src': 'biodb_efetch_1'}},
    }]}}}
    items = {check_ledger.key_of(x): x for x in check_ledger.value_items(card)}
    key = '/added/layers/predictions/0/system/taxon_id|src'
    assert key in items, sorted(items)
    assert items[key]['value'] == {'taxon_id': 'NCBITaxon:33554', 'taxon': 'Carnivora'}


def test_a_taxon_id_whose_prediction_names_no_taxon_is_sent_alone():
    """The word is the prediction's, and a prediction that states none cannot supply one."""
    card = {'added': {'layers': {'predictions': [{
        'id': 'p1',
        'system': {'taxon_id': {'value': 'NCBITaxon:9606', 'src': 'biodb_efetch_2'}},
    }]}}}
    items = {check_ledger.key_of(x): x for x in check_ledger.value_items(card)}
    key = '/added/layers/predictions/0/system/taxon_id|src'
    assert items[key]['value'] == {'taxon_id': 'NCBITaxon:9606'}


# -- OHF 1.1: an element of a list may name its own paragraph ---------------------------------------

import os  # noqa: E402

STANDARD = os.environ.get('OHF_STANDARD')


def standard_release():
    """The release of the checkout OHF_STANDARD names, or None when there is none to read.

    The gate is the version, not the presence of the variable: a 1.1 card handed to a 1.0 checker is
    answered REF_STANDARD_VERSION, which made the negative test fail and - worse - let the positive
    one pass for the wrong reason. A review found that, and it is the same mistake as asserting the
    absence of one error code instead of validity."""
    if not STANDARD:
        return None
    try:
        return tuple(int(n) for n in (Path(STANDARD) / 'VERSION').read_text().strip().split('.')[:3])
    except (OSError, ValueError):
        return None


ELEMENT_SRC_SINCE = (1, 1)
_release = standard_release()
needs_11 = pytest.mark.skipif(
    _release is None or _release[:2] < ELEMENT_SRC_SINCE,
    reason=f'an element with its own src is OHF 1.1; OHF_STANDARD names {_release or "no checkout"}')


def with_two_uncertainties(xml_workdir):
    """A card whose uncertainties come from two paragraphs: the second names its own."""
    card = load(build_card(xml_workdir))
    card['standard_version'] = '1.1'
    # The skeleton leaves source_verification null until the build verifies the source, and null is
    # not valid there - the standard's checker reads it unconditionally, as it may. Filled as a built
    # card fills it, so this fixture is a card and not half of one.
    card['added']['source_verification'] = {
        'status': 'refetched_match',
        'fetched_from': card['author']['source'].get('url') or 'https://example.org/article',
        'fetched_at': '2026-10-24T05:00:00Z',
        'sha256': card['author']['source']['source_text_sha256'],
        'metadata_check': None}
    card['added']['layers']['core']['uncertainties'] = {
        'value': [
            {'id': 'u_from_the_lists_paragraph', 'kind': 'evidence',
             'question': 'What the first paragraph leaves open?'},
            {'id': 'u_from_elsewhere', 'kind': 'mechanism', 'src': 'p2',
             'question': 'What the other paragraph leaves open?'},
        ],
        'src': 'p1'}
    return card


def test_an_element_that_names_its_own_paragraph_is_read_against_that_paragraph(xml_workdir):
    """The standard's rule, and the half the kit did not do: an element with its own src is a sourced
    value in its own right. Before this it was invisible - `skip` dropped any dict without a `value`
    key - so the list went to a reader whole, against one paragraph, and an element the article states
    elsewhere was reported missing from a paragraph it was never in."""
    card = with_two_uncertainties(xml_workdir)
    pointers = [p for p, _ in check_ledger.sourced(card)]
    assert '/added/layers/core/uncertainties/value/1' in pointers
    assert '/added/layers/core/uncertainties/value/0' not in pointers, \
        'an element without its own src is read from the list, not separately'
    items = {i['pointer']: i for i in check_ledger.value_items(card)}
    assert items['/added/layers/core/uncertainties/value/1']['src'] == 'p2'
    assert items['/added/layers/core/uncertainties/value/1']['value']['id'] == 'u_from_elsewhere'
    assert 'src' not in items['/added/layers/core/uncertainties/value/1']['value'], \
        'the src says where to read the element; it is not part of what is read'


def test_parent_list_stays_complete_when_a_child_has_its_own_src(xml_workdir):
    """The parent has its own full-value obligation; the independent child does not replace it."""
    card = with_two_uncertainties(xml_workdir)
    items = {i['pointer']: i for i in check_ledger.value_items(card)}
    whole = items['/added/layers/core/uncertainties']['value']
    assert [e['id'] for e in whole] == ['u_from_the_lists_paragraph', 'u_from_elsewhere']
    assert whole == card['added']['layers']['core']['uncertainties']['value']
    assert items['/added/layers/core/uncertainties/value/1']['src'] == 'p2'


@needs_11
@pytest.mark.parametrize('index, valid', [(1, True), (0, False)])
def test_the_standard_accepts_a_record_on_an_element_only_when_it_names_its_own_src(
        xml_workdir, tmp_path, index, valid):
    """Both directions, by the standard's own checker: a record may name an element that carries its
    own src, and a record naming an element that does not is refused (REF_WRONG_TARGET), because such
    an element is read from the list and a record for it names the list."""
    card = with_two_uncertainties(xml_workdir)
    card['added']['integrity']['entailment'] = [{
        'pointer': f'/added/layers/core/uncertainties/value/{index}',
        'basis': 'src',
        'verdict': 'entails',
        'checker': {'name': 'ohf-entailment-check', 'version': '1.0.0',
                    'prompt_sha256': 'sha256:' + '0' * 64},
        'checked_at': '2026-10-24T05:00:00Z',
    }]
    path = tmp_path / 'card.json'
    path.write_text(json.dumps(card))
    out = subprocess.run([sys.executable, str(Path(STANDARD) / 'tools' / 'check_refs.py'), str(path)],
                         capture_output=True, text=True)
    assert out.stdout.strip(), f'check_refs printed nothing; stderr: {out.stderr[-400:]}'
    answer = json.loads(out.stdout)
    if valid:
        # Validity, not the absence of one code: a test that asks only whether WRONG_TARGET is missing
        # passes on a card the checker refused for some other reason entirely, which is how this one
        # passed against a 1.0 checkout that had answered REF_STANDARD_VERSION.
        assert answer['valid'] and not answer['errors'], answer['errors']
    else:
        codes = [e.get('code') for e in answer['errors']]
        assert 'REF_WRONG_TARGET' in codes, answer
        assert not answer['valid']


def test_a_field_with_a_closed_term_is_sent_with_that_term(xml_workdir):
    """`endpoint_kind` is the source's wording **and** a closed term, and the term is the half OHF 1.1
    added. Sent as the bare wording, it was checked only for whether the phrase was in the passage:
    on the amoebae card all sixteen were judged that way, and the reader said so - no item carried a
    term at any level. A reader must see all of what it is asked to judge, so the item now carries the
    term, the note that a term of `other` requires, and the line's own quotation."""
    card = load(build_card(xml_workdir))
    card['standard_version'] = '1.1'
    card['added']['layers']['evidence']['lines'] = [{
        'id': 'e_one',
        'src': 'p2',
        'quote': 'In mice, X may cause Y.',
        'endpoint_kind': {'value': 'X may cause Y in mice', 'src': 'p2', 'term': 'other',
                          'note': 'predation, for which this vocabulary has no term'},
    }]
    items = {i['pointer']: i for i in check_ledger.value_items(card)}
    sent = items['/added/layers/evidence/lines/0/endpoint_kind']['value']
    assert sent['endpoint_kind'] == 'X may cause Y in mice'
    assert sent['term'] == 'other', 'the term is the half 1.1 added, and a reader must see it'
    assert sent['note'].startswith('predation'), 'a term of other is only as good as its note'
    assert 'line_quote' in sent, 'what the line reports is the context the term is about'
