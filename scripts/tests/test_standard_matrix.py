"""F2: every active primary gets the complete suite and the secondary context."""
import ast
import copy
import hashlib
import json
from pathlib import Path
import re

import pytest

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / '.forgejo/workflows/check.yml'
INVENTORY = ROOT / '.forgejo/standard-test-matrix.json'
FULL = '        run: .venv/bin/python -m pytest -q scripts/tests'


def literal(path, name):
    for node in ast.parse((ROOT / path).read_text()).body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name
                                               for t in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError('missing binding: ' + name)


def check_matrix(matrix, workflow):
    assert matrix['format'] == 'ohf-ci-standard-matrix/1'
    active = matrix['active_primary']
    assert len({r['commit'] for r in active}) == len(active)
    assert len({r['checkout'] for r in active}) == len(active)
    records = matrix['native_dependency_records']
    expected = {str(p.relative_to(ROOT)) for p in (ROOT / 'references').glob('native-profile-dependencies*.json')}
    assert len(records) == len(expected)
    assert {r['record'] for r in records} == expected
    source = ast.parse((ROOT / 'scripts/native_profile.py').read_text())
    definitions = {t.id: n.value for n in source.body if isinstance(n, ast.Assign)
                   for t in n.targets if isinstance(t, ast.Name)}
    # Resolve only the explicit literal path selections; no producer import or latest lookup.
    definition_name = definitions['DEFINITION'].right.value
    dependency_name = definitions['DEPENDENCIES'].args[0].value
    selected = str(Path(definition_name).with_name(dependency_name))
    modern = []
    for row in records:
        raw = (ROOT / row['record']).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == row['sha256']
        assert json.loads(raw)['standard_commit'] == row['commit']
        assert row['role'] == ('active-primary' if row['record'] == selected else 'historical')
        if row['role'] == 'active-primary':
            assert literal('scripts/native_profile.py', 'DEPENDENCIES_SHA256') == 'sha256:' + row['sha256']
            assert literal('scripts/projection_binding.py', 'STANDARD_COMMIT') == row['commit']
            modern.append(row['commit'])
    legacy = ['e3cd86c0386ce618187a786ecc78293332d5f462',
              'fc554f691d6cf0092182bb306c769c5e217f6165']
    assert [r['commit'] for r in active] == legacy + modern
    assert len(modern) == 1
    secondary = matrix['secondary']
    raw = (ROOT / secondary['record']).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == secondary['sha256']
    assert {k: json.loads(raw)[k] for k in ('commit', 'tree')} == {
        k: secondary[k] for k in ('commit', 'tree')}
    general = workflow.split('\n  check:\n', 1)[1].split('\n  native-profile-1-4:\n', 1)[0]
    steps = re.split(r'^      - ', general, flags=re.M)[1:]
    full_steps = [s for s in steps if 'scripts/tests' in s]
    assert len(full_steps) == len(active)
    seen = []
    for step in full_steps:
        assert FULL.removeprefix('      - ') in step.splitlines()
        primary = re.findall(r'^          OHF_REPO: \$\{\{ github.workspace \}\}/([^\s]+)$', step, re.M)
        companion = re.findall(r'^          OHF_RESEARCH_STANDARD: \$\{\{ github.workspace \}\}/([^\s]+)$', step, re.M)
        assert len(primary) == 1
        assert companion == [secondary['checkout']]
        assert "          PYTEST_DISABLE_PLUGIN_AUTOLOAD: '1'" in step.splitlines()
        seen.append(primary[0])
    assert sorted(seen) == sorted(r['checkout'] for r in active)
    first_full = general.index(FULL)
    before_tests = general[:first_full]
    for row in [*active, secondary]:
        checkout, commit = row['checkout'], row['commit']
        verify = f'          test "$(git -C {checkout} rev-parse HEAD)" = {commit}'
        assert verify in before_tests.splitlines()
        if 'tree' in row:
            assert f'          test "$(git -C {checkout} rev-parse HEAD^{{tree}})" = {row["tree"]}' in before_tests.splitlines()
            assert f'          git -C {checkout} diff --exit-code' in before_tests.splitlines()
            candidates = [s for s in steps if f'          path: {checkout}' in s.splitlines()]
            assert len(candidates) == 1
            assert f'          ref: {commit}' in candidates[0].splitlines()
            assert '          persist-credentials: false' in candidates[0].splitlines()


def test_active_primary_matrix_is_complete_and_bound_to_selected_records():
    check_matrix(json.loads(INVENTORY.read_bytes()), WORKFLOW.read_text())


@pytest.mark.parametrize('fault', [
    'missing-modern-run', 'duplicate-run', 'partial-run', 'wrong-primary', 'missing-secondary',
    'wrong-secondary', 'wrong-ref', 'wrong-verify', 'missing-tree-check',
    'inactive-modern', 'omitted-history', 'duplicate-primary', 'stale-record-digest',
])
def test_matrix_refuses_missing_partial_or_stale_coverage(fault):
    matrix = copy.deepcopy(json.loads(INVENTORY.read_bytes()))
    workflow = WORKFLOW.read_text()
    if fault in ('missing-modern-run', 'duplicate-run'):
        start = workflow.index('      - name: Full tests against the active OHF 1.4 primary')
        end = workflow.index('      - name: Report the rules hash', start)
        block = workflow[start:end]
        workflow = workflow[:start] + ('' if fault == 'missing-modern-run' else block * 2) + workflow[end:]
    elif fault == 'partial-run': workflow = workflow.replace(FULL, FULL + ' -k smoke', 1)
    elif fault == 'wrong-primary': workflow = workflow.replace('OHF_REPO: ${{ github.workspace }}/standard-primary-1.4', 'OHF_REPO: ${{ github.workspace }}/historical')
    elif fault == 'missing-secondary': workflow = workflow.replace('          OHF_RESEARCH_STANDARD: ${{ github.workspace }}/standard-research\n', '', 1)
    elif fault == 'wrong-secondary': workflow = workflow.replace('OHF_RESEARCH_STANDARD: ${{ github.workspace }}/standard-research', 'OHF_RESEARCH_STANDARD: ${{ github.workspace }}/historical', 1)
    elif fault == 'wrong-ref': workflow = workflow.replace('ref: ' + matrix['active_primary'][-1]['commit'], 'ref: ' + 'a' * 40, 1)
    elif fault == 'wrong-verify': workflow = workflow.replace('standard-primary-1.4 rev-parse HEAD)" = ' + matrix['active_primary'][-1]['commit'], 'standard-primary-1.4 rev-parse HEAD)" = ' + 'a' * 40, 1)
    elif fault == 'missing-tree-check': workflow = '\n'.join(s for s in workflow.split('\n') if 'standard-primary-1.4 rev-parse HEAD^{tree}' not in s)
    elif fault == 'inactive-modern': matrix['native_dependency_records'][-1]['role'] = 'historical'
    elif fault == 'omitted-history': matrix['native_dependency_records'].pop(0)
    elif fault == 'duplicate-primary': matrix['active_primary'].append(matrix['active_primary'][0])
    elif fault == 'stale-record-digest': matrix['native_dependency_records'][-1]['sha256'] = 'a' * 64
    with pytest.raises(AssertionError):
        check_matrix(matrix, workflow)


def _matrix_fault_replace_once(text, old, new):
    assert text.count(old) == 1, 'fault must change exactly its intended input'
    return text.replace(old, new, 1)


@pytest.mark.parametrize(('fault', 'checkout'), [
    ('persist-credentials', 'standard-primary-1.4'),
    ('persist-credentials', 'standard-research'),
    ('missing-diff', 'standard-primary-1.4'),
    ('missing-diff', 'standard-research'),
    ('missing-autoload', 'standard'),
    ('missing-autoload', 'standard-1.1.4'),
    ('missing-autoload', 'standard-primary-1.4'),
    ('secondary-ref', 'standard-research'),
])
def test_matrix_refuses_each_bound_checkout_and_full_run_fault(fault, checkout):
    matrix = copy.deepcopy(json.loads(INVENTORY.read_bytes()))
    workflow = WORKFLOW.read_text()
    if fault == 'persist-credentials':
        old = f'          path: {checkout}\n          persist-credentials: false'
        new = f'          path: {checkout}\n          persist-credentials: true'
        workflow = _matrix_fault_replace_once(workflow, old, new)
    elif fault == 'missing-diff':
        workflow = _matrix_fault_replace_once(
            workflow, f'          git -C {checkout} diff --exit-code\n', '')
    elif fault == 'missing-autoload':
        start = workflow.index(f'          OHF_REPO: ${{{{ github.workspace }}}}/{checkout}\n')
        end = workflow.index(FULL, start)
        block = _matrix_fault_replace_once(
            workflow[start:end], "          PYTEST_DISABLE_PLUGIN_AUTOLOAD: '1'\n", '')
        workflow = workflow[:start] + block + workflow[end:]
    else:
        assert fault == 'secondary-ref'
        old = '          ref: ' + matrix['secondary']['commit'] + '\n'
        workflow = _matrix_fault_replace_once(workflow, old, '          ref: ' + '0' * 40 + '\n')
    with pytest.raises(AssertionError):
        check_matrix(matrix, workflow)


@pytest.mark.parametrize('fault', [
    'secondary-sha256', 'secondary-commit', 'secondary-tree',
    'dependencies-sha256-binding', 'standard-commit-binding',
])
def test_matrix_refuses_each_record_and_literal_binding_fault(fault, monkeypatch):
    matrix = copy.deepcopy(json.loads(INVENTORY.read_bytes()))
    workflow = WORKFLOW.read_text()
    if fault == 'secondary-sha256':
        matrix['secondary']['sha256'] = '0' * 64
    elif fault in ('secondary-commit', 'secondary-tree'):
        member = fault.removeprefix('secondary-')
        old = matrix['secondary'][member]
        changed = '0' * 40
        assert old != changed
        matrix['secondary'][member] = changed
        checkout = matrix['secondary']['checkout']
        if member == 'commit':
            workflow = _matrix_fault_replace_once(
                workflow, '          ref: ' + old + '\n', '          ref: ' + changed + '\n')
            before = f'          test "$(git -C {checkout} rev-parse HEAD)" = {old}\n'
            after = f'          test "$(git -C {checkout} rev-parse HEAD)" = {changed}\n'
        else:
            before = f'          test "$(git -C {checkout} rev-parse HEAD^{{tree}})" = {old}\n'
            after = f'          test "$(git -C {checkout} rev-parse HEAD^{{tree}})" = {changed}\n'
        # Keep the workflow consistent with the faulty matrix expectation. Only
        # comparing it with the actual secondary record may refuse this input.
        workflow = _matrix_fault_replace_once(workflow, before, after)
    else:
        target = {
            'dependencies-sha256-binding': ('scripts/native_profile.py', 'DEPENDENCIES_SHA256'),
            'standard-commit-binding': ('scripts/projection_binding.py', 'STANDARD_COMMIT'),
        }[fault]
        original_literal = literal

        def wrong_binding(path, name):
            value = original_literal(path, name)
            if (path, name) == target:
                changed = 'sha256:' + '0' * 64 if name == 'DEPENDENCIES_SHA256' else '0' * 40
                assert value != changed
                return changed
            return value

        monkeypatch.setitem(globals(), 'literal', wrong_binding)
    with pytest.raises(AssertionError):
        check_matrix(matrix, workflow)
