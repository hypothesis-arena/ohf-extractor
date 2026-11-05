"""Invented text/index mutations for the standalone source-language gate."""
import copy
import importlib.util
import json
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('extractor_language_gate', ROOT / 'tools/check_language.py')
gate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gate)


def git(root, *args):
    subprocess.run(['git', '-C', str(root), *args], check=True, capture_output=True)


@pytest.fixture
def invented(tmp_path):
    git(tmp_path, 'init', '-q')
    entries = []
    for index in range(7):
        path = f'fixture{index}.txt'
        text = chr(0x410 + index) + '\n'
        if index == 0:
            text += chr(0x430) + '\n'
        raw = text.encode()
        (tmp_path / path).write_bytes(raw)
        entries.append({'path': path, 'class': 'synthetic-fixture',
                        'inventory_row_id': f'rows/{166 + index}', 'source_sha256': gate.sha(raw),
                        'units': [{'sha256': digest, 'count': 1}
                                  for digest in gate.line_units(raw, path)]})
    policy = {'schema': 'ohf-extractor-language-allowlist/1',
              'inventory': {'sha256': 'a' * 64, 'base_commit': 'b' * 40,
                            'rows': list(range(166, 173))},
              'classification_plan_sha256': 'c' * 64, 'entries': entries}
    git(tmp_path, 'add', '.')
    return tmp_path, policy


def load(root, policy):
    path = root / 'policy.json'
    path.write_text(json.dumps(policy))
    return gate.load_policy(path)


def test_real_tracked_source_matches_policy():
    policy = gate.load_policy(ROOT / 'data/policy/language-allowlist.json')
    assert gate.check(ROOT, policy) == []


def test_exact_invented_allowances_pass(invented):
    root, policy = invented
    assert gate.check(root, load(root, policy)) == []
    # Ordinary English edits outside the allowed lines do not grant an exemption.
    with (root / 'fixture0.txt').open('a') as stream:
        stream.write('An English annotation.\n')
    assert gate.check(root, load(root, policy)) == []


@pytest.mark.parametrize('change', ['elsewhere', 'same-file-copy', 'other-file-copy',
                                  'changed-literal', 'count-two', 'dropped-unit', 'untracked-allowance'])
def test_extra_missing_or_overbroad_allowances_fail(invented, change):
    root, policy = invented
    path = root / 'fixture0.txt'
    if change == 'elsewhere':
        (root / 'new.md').write_text(chr(0x410))
        git(root, 'add', 'new.md')
    elif change == 'same-file-copy':
        path.write_bytes(path.read_bytes() + path.read_bytes().splitlines(keepends=True)[0])
    elif change == 'other-file-copy':
        (root / 'copy.txt').write_bytes(path.read_bytes())
        git(root, 'add', 'copy.txt')
    elif change == 'changed-literal':
        path.write_text(chr(0x450))
    elif change == 'count-two':
        policy['entries'][0]['units'][0]['count'] = 2
    elif change == 'dropped-unit':
        policy['entries'][0]['units'].pop()
    else:
        git(root, 'rm', '--cached', 'fixture0.txt')
    errors = gate.check(root, load(root, policy))
    assert errors
    if change == 'count-two':
        assert any('count mismatch' in error for error in errors)
    if change in ('elsewhere', 'same-file-copy', 'other-file-copy', 'dropped-unit'):
        assert any('outside exact line/count' in error for error in errors)


@pytest.mark.parametrize('change', ['duplicate-path', 'duplicate-unit', 'dropped-entry',
                                  'glob', 'parent-path', 'bool-count', 'zero-count',
                                  'extra-member', 'foreign-row', 'invalid-class',
                                  'row-container', 'class-container'])
def test_policy_is_closed_and_has_no_duplicate_or_wildcard_escape(invented, change):
    root, policy = invented
    if change == 'duplicate-path':
        policy['entries'][1]['path'] = policy['entries'][0]['path']
    elif change == 'duplicate-unit':
        policy['entries'][0]['units'].append(copy.deepcopy(policy['entries'][0]['units'][0]))
    elif change == 'dropped-entry':
        policy['entries'].pop()
    elif change == 'glob':
        policy['entries'][0]['path'] = '*.txt'
    elif change == 'parent-path':
        policy['entries'][0]['path'] = '../fixture.txt'
    elif change == 'bool-count':
        policy['entries'][0]['units'][0]['count'] = True
    elif change == 'zero-count':
        policy['entries'][0]['units'][0]['count'] = 0
    elif change == 'extra-member':
        policy['entries'][0]['whole_file'] = True
    elif change == 'foreign-row':
        policy['entries'][0]['inventory_row_id'] = 'rows/1000'
    elif change == 'row-container':
        policy['entries'][0]['inventory_row_id'] = []
    elif change == 'class-container':
        policy['entries'][0]['class'] = []
    else:
        policy['entries'][0]['class'] = 'developer-prose'
    with pytest.raises(ValueError):
        load(root, policy)


@pytest.mark.parametrize('name,raw', [
    ('extra.txt', chr(0x1e030).encode()),
    ('extra.json', json.dumps({chr(0x410): 'English'}).encode()),
    ('extra.json', json.dumps({'outer': json.dumps({chr(0x410): 'English'})}).encode()),
    ('extra.html', b'<p>&#x410;</p>'),
    ('extra.txt', chr(0x410).encode('utf-16')),
    ('extra.txt', chr(0x410).encode('utf-32')),
    ('extra.md', b'\xc0'),
])
def test_decoded_keys_markup_unicode_and_invalid_text_cannot_bypass(invented, name, raw):
    root, policy = invented
    (root / name).write_bytes(raw)
    git(root, 'add', name)
    assert gate.check(root, load(root, policy))


def test_symlink_is_not_a_tracked_text_exemption(invented):
    root, policy = invented
    (root / 'link.txt').symlink_to(root / 'fixture0.txt')
    git(root, 'add', 'link.txt')
    assert any('symlink' in error for error in gate.check(root, load(root, policy)))


def test_cli_reports_failure_and_pass_without_rewriting_source(invented, capsys):
    root, policy = invented
    load(root, policy)
    before = (root / 'fixture0.txt').read_bytes()
    args = ['--root', str(root), '--policy', str(root / 'policy.json')]
    assert gate.main(args) == 0
    assert json.loads(capsys.readouterr().out)['status'] == 'PASS'
    policy['entries'][0]['units'][0]['count'] = 2
    load(root, policy)
    assert gate.main(args) == 1
    assert json.loads(capsys.readouterr().out)['status'] == 'FAIL'
    assert (root / 'fixture0.txt').read_bytes() == before
