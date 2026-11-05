"""Invented standalone packaging contracts; no real card, model or source retrieval."""
import ast
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

import check_ledger
import entailment
import ohfkit
import projection_binding
from conftest import SCRIPTS, build_card, load


ROUTES = ('require_source_modes', 'checked_value', 'sourced', 'entry', 'new_ledger', 'active')


def reader_route(name):
    card = {'id': 'invented_packaging', 'standard_version': '1.4',
            'added': {'layers': {'core': {}, 'evidence': {'lines': []}}}}
    node = {'value': 'supports', 'src': 'p1'}
    pointer = '/added/layers/evidence/lines/0/direction'
    item = {'pointer': pointer, 'basis': 'src', 'source_passage': 'An invented passage.',
            'value': {'target_statement': {'format': 'ohf-target-projection/1', 'kind': 'atom'}}}
    record = {'checked_at': '2026-01-01T00:00:00Z', 'verdict': 'entails'}
    if name == 'require_source_modes':
        card['added']['layers']['core']['uncertainties'] = {'value': []}
        return lambda: check_ledger.require_source_modes(card)
    if name == 'checked_value':
        return lambda: check_ledger.checked_value(card, pointer, node)
    if name == 'sourced':
        return lambda: check_ledger.sourced(card)
    if name == 'entry':
        return lambda: check_ledger.entry(item, record)
    if name == 'new_ledger':
        return lambda: check_ledger.new_ledger(card)
    assert name == 'active'
    return lambda: check_ledger.active([], 'sha256:' + '0' * 64, item=item)


@pytest.mark.parametrize('route', ROUTES)
@pytest.mark.parametrize('missing', ['adapter', 'OHF_REPO', 'empty_OHF_REPO'])
def test_every_reader_route_refuses_missing_packaging(tmp_path, monkeypatch, route, missing):
    if missing == 'adapter':
        monkeypatch.setattr(check_ledger, '__file__', str(tmp_path / 'check_ledger.py'))
        monkeypatch.setenv('OHF_REPO', str(tmp_path / 'explicit-source'))
        expected = ('PINNED_READER_REQUIRED: OHF 1.4 requires pinned '
                    'projection_binding.py beside check_ledger.py')
    elif missing == 'empty_OHF_REPO':
        monkeypatch.setenv('OHF_REPO', '')
        expected = ('PINNED_READER_REQUIRED: OHF 1.4 requires explicit OHF_REPO '
                    'selecting the pinned Standard reader')
    else:
        monkeypatch.delenv('OHF_REPO', raising=False)
        expected = ('PINNED_READER_REQUIRED: OHF 1.4 requires explicit OHF_REPO '
                    'selecting the pinned Standard reader')
    with pytest.raises(check_ledger.PinnedReaderRequired) as refusal:
        reader_route(route)()
    assert str(refusal.value) == expected


def test_all_projection_loading_routes_are_covered():
    tree = ast.parse((SCRIPTS / 'check_ledger.py').read_text())
    callers = {function.name for function in tree.body if isinstance(function, ast.FunctionDef)
               and any(isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                       and node.func.id == '_projection_module' for node in ast.walk(function))}
    assert callers == set(ROUTES) | {'main'}  # The main CLI is exercised below.


@pytest.fixture
def pinned_card(xml_workdir, monkeypatch):
    # CI already checks out the explicit modern primary for all three full runs.
    # The local targeted harness supplies this test-only path explicitly.
    primary = (ohfkit.REPO if ohfkit.standard_line() == '1.4' else
               Path(os.environ.get('OHF_TEST_PRIMARY_14', SCRIPTS.parents[0] / 'standard-primary-1.4')))
    assert 'sha256:' + hashlib.sha256((primary / 'tools/check_ledger.py').read_bytes()).hexdigest() == (
        projection_binding.STANDARD_MODULE_SHA256)
    monkeypatch.setenv('OHF_REPO', str(primary))
    monkeypatch.setattr(ohfkit, 'REPO', primary)
    card_path = build_card(xml_workdir)
    card = load(card_path)
    assert card['standard_version'] == '1.4'
    docs = entailment.docs_for(card, xml_workdir)
    inputs = entailment.build(card, docs)
    ledger = check_ledger.new_ledger(card)
    entailment.merge(card, inputs, [{'id': item['id'], 'verdict': 'entails'} for item in inputs],
                     docs, ledger)
    ohfkit.rehash(card, card_path)
    entailment.write_ledger(card, xml_workdir, ledger)
    return card_path, xml_workdir / check_ledger.LEDGER_NAME, primary


def copy_checker(root, primary, adapter):
    tools = root / 'tools'
    tools.mkdir(parents=True)
    for name in ('content_hash.py', 'strict_json.py'):
        shutil.copyfile(primary / 'tools' / name, tools / name)
    shutil.copyfile(SCRIPTS / 'check_ledger.py', tools / 'check_ledger.py')
    if adapter:
        shutil.copyfile(SCRIPTS / 'projection_binding.py', tools / 'projection_binding.py')
    return tools / 'check_ledger.py'


@pytest.mark.parametrize('missing', ['adapter', 'OHF_REPO', 'both', 'empty_OHF_REPO'])
def test_1_4_standalone_cli_refuses_incomplete_packaging_without_traceback(
        tmp_path, pinned_card, missing):
    card, ledger, primary = pinned_card
    before = (card.read_bytes(), ledger.read_bytes())
    root = tmp_path / 'standalone'
    script = copy_checker(root, primary, adapter=missing in ('OHF_REPO', 'empty_OHF_REPO'))
    env = dict(os.environ)
    if missing == 'empty_OHF_REPO':
        env['OHF_REPO'] = ''
    elif missing != 'adapter':
        env.pop('OHF_REPO', None)
    result = subprocess.run([sys.executable, '-I', '-B', str(script), str(card), str(ledger)],
                            cwd=root, env=env, capture_output=True, text=True, timeout=20)
    assert result.returncode == 1
    assert result.stdout.startswith('LEDGER CHECK REFUSE PINNED_READER_REQUIRED: ')
    assert ('projection_binding.py beside check_ledger.py' if missing == 'adapter'
            else 'requires explicit OHF_REPO') in result.stdout
    assert result.stderr == ''
    assert 'Traceback' not in result.stdout and 'FileNotFoundError' not in result.stdout
    assert (card.read_bytes(), ledger.read_bytes()) == before


def test_1_4_standalone_cli_with_adapter_and_pinned_source_passes(tmp_path, pinned_card):
    card, ledger, primary = pinned_card
    root = tmp_path / 'standalone'
    script = copy_checker(root, primary, adapter=True)
    before = (card.read_bytes(), ledger.read_bytes())
    result = subprocess.run([sys.executable, '-I', '-B', str(script), str(card), str(ledger)],
                            cwd=root, env={**os.environ, 'OHF_REPO': str(primary)},
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0 and 'LEDGER CHECK PASS' in result.stdout, result.stdout + result.stderr
    assert result.stderr == ''
    assert (card.read_bytes(), ledger.read_bytes()) == before


def test_cli_does_not_turn_unrelated_value_errors_into_packaging_refusals(tmp_path, monkeypatch):
    card = tmp_path / 'invented-card.json'
    card.write_text(json.dumps({'standard_version': '1.3'}))
    def unexpected(*args, **kwargs):
        raise ValueError('unrelated invented check failure')
    monkeypatch.setattr(check_ledger, 'check', unexpected)
    with pytest.raises(ValueError, match='^unrelated invented check failure$'):
        check_ledger.main([str(card), str(tmp_path / 'absent-ledger.json')])


def test_main_reports_the_packaging_refusal_as_a_status(tmp_path, monkeypatch, capsys):
    card = tmp_path / 'invented-card.json'
    card.write_text(json.dumps({'standard_version': '1.4'}))
    monkeypatch.delenv('OHF_REPO', raising=False)
    assert check_ledger.main([str(card), str(tmp_path / 'absent-ledger.json')]) == 1
    output = capsys.readouterr()
    assert output.out == ('LEDGER CHECK REFUSE PINNED_READER_REQUIRED: OHF 1.4 requires '
                          'explicit OHF_REPO selecting the pinned Standard reader\n')
    assert output.err == ''


@pytest.mark.parametrize('route', ['library', 'CLI'])
def test_changed_adjacent_adapter_refuses_before_use(tmp_path, monkeypatch, pinned_card, route):
    card, ledger, primary = pinned_card
    root = tmp_path / 'changed-adapter'
    script = copy_checker(root, primary, adapter=True)
    adapter = script.with_name('projection_binding.py')
    before = (card.read_bytes(), ledger.read_bytes())
    if route == 'library':
        monkeypatch.setattr(check_ledger, '__file__', str(script))
        assert check_ledger.sourced(load(card))
    else:
        positive = subprocess.run([sys.executable, '-I', '-B', str(script), str(card), str(ledger)],
                                  cwd=root, env={**os.environ, 'OHF_REPO': str(primary)},
                                  capture_output=True, text=True, timeout=20)
        assert positive.returncode == 0 and 'LEDGER CHECK PASS' in positive.stdout
        assert positive.stderr == ''
    # Even a harmless, executable change must refuse, including after a warm load.
    adapter.write_bytes(adapter.read_bytes() + b'\n# Invented adapter drift.\n')
    if route == 'library':
        with pytest.raises(ValueError) as refusal:
            check_ledger.sourced(load(card))
        assert str(refusal.value) == 'ordinary projection source pin differs'
    else:
        result = subprocess.run([sys.executable, '-I', '-B', str(script), str(card), str(ledger)],
                                cwd=root, env={**os.environ, 'OHF_REPO': str(primary)},
                                capture_output=True, text=True, timeout=20)
        assert result.returncode == 1
        assert result.stdout == ''
        assert result.stderr.splitlines()[-1] == 'ValueError: ordinary projection source pin differs'
        assert 'LEDGER CHECK PASS' not in result.stdout + result.stderr
    assert (card.read_bytes(), ledger.read_bytes()) == before
