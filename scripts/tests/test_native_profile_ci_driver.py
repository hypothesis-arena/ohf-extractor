"""Closed CI identity input: invented hashes, no checkout or process dispatch."""
import json
import pytest
import native_profile_ci_driver as driver


def valid_heads():
    return {'extractor_commit':'a'*40, 'extractor_tree':'b'*40,
            'standard_commit':'c'*40, 'standard_tree':'d'*40}


def test_ci_identity_retains_every_exact_head_and_tree():
    pair=valid_heads()
    assert driver.heads(json.dumps(pair).encode())==pair


@pytest.mark.parametrize('change',['missing-tree','extra-member','short','uppercase','numeric','duplicate'])
def test_ci_identity_refuses_ambiguous_or_incomplete_heads(change):
    pair=valid_heads()
    if change=='missing-tree': pair.pop('standard_tree')
    elif change=='extra-member': pair['standard_tag']='latest'
    elif change=='short': pair['extractor_commit']='a'*7
    elif change=='uppercase': pair['standard_commit']='C'*40
    elif change=='numeric': pair['extractor_tree']=123
    raw=json.dumps(pair).encode()
    if change=='duplicate':raw=raw[:-1]+b',"extractor_commit":"'+b'e'*40+b'"}'
    with pytest.raises(ValueError):driver.heads(raw)


def test_existing_ci_evidence_is_not_adopted_or_reset(tmp_path,monkeypatch):
    pair=tmp_path/'heads.json';pair.write_text(json.dumps(valid_heads()))
    output=tmp_path/'existing';output.mkdir();sentinel=output/'evidence';sentinel.write_text('retained')
    monkeypatch.setenv('OHF_REPO',str(tmp_path))
    with pytest.raises(ValueError,match='existing evidence'):
        driver.run(pair,output,'scenario')
    assert sentinel.read_text()=='retained'


@pytest.mark.parametrize('changed', sorted({
    **json.loads((driver.REPO / 'references/native-profile-dependencies-4.json').read_bytes())['files'],
    **driver.BOOTSTRAP_PINS,
}))
def test_ci_source_drift_refuses_before_product_import(tmp_path,changed):
    import os
    from pathlib import Path
    import ohfkit
    if ohfkit.standard_line()!='1.4':
        pytest.skip('Pinned OHF 1.4 source check only')
    standard=Path(os.environ['OHF_REPO'])
    pins=driver.verify_standard(standard)
    assert pins
    for original in pins:
        path=Path(original);target=tmp_path/path.relative_to(standard)
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes(path.read_bytes())
    (tmp_path/changed).write_text('raise RuntimeError("UNPINNED_SOURCE_MUST_NOT_EXECUTE")')
    import re
    with pytest.raises(ValueError,match='CI_SOURCE: normative/bootstrap pin differs: '+re.escape(changed)):
        driver.verify_standard(tmp_path)


@pytest.mark.parametrize('load,count,refused', [
    (0.0, 16, False),
    (11.794921875, 16, False),
    (11.73046875, 16, False),
    (10.0654296875, 16, False),
    (14.399, 16, False),
    (14.4, 16, True),
    (14.401, 16, True),
    (9.0, 8, True),
    (0.89, 1, False),
    (0.9, 1, True),
])
def test_normalized_cpu_capacity_distinguishes_threshold_and_host_size(load, count, refused):
    result = driver.cpu_admission(load, count)
    assert result['cpu_policy'] == 'normalized_load'
    assert result['cpu_count'] == count
    assert result['load1_per_cpu'] == load / count
    assert result['cpu_threshold'] == 0.9
    assert result['cpu_refused'] is refused


@pytest.mark.parametrize('count', [None, 0, -1, True, 1.5, '16', 10**1000])
@pytest.mark.parametrize('load,refused', [(9.999, False), (10.0, True), (10.001, True)])
def test_unknown_cpu_count_uses_explicit_legacy_threshold(count, load, refused):
    result = driver.cpu_admission(load, count)
    assert result['cpu_policy'] == 'legacy_load_fallback'
    assert result['cpu_count'] is None
    assert result['load1_per_cpu'] is None
    assert result['cpu_threshold'] == 10
    assert result['cpu_reason'] == 'CPU_COUNT_UNAVAILABLE'
    assert result['cpu_refused'] is refused


@pytest.mark.parametrize('load', [None, True, False, -1, float('nan'),
                                  float('inf'), -float('inf'), '1', 10**1000])
@pytest.mark.parametrize('count', [16, None])
def test_invalid_load_never_becomes_an_optimistic_admission(load, count):
    result = driver.cpu_admission(load, count)
    assert result['cpu_refused'] is True
    assert result['cpu_policy'] == 'load_snapshot_refused'
    assert result['load1'] is None
    assert result['load1_per_cpu'] is None
    assert result['cpu_reason'] == 'LOAD_INVALID'
    json.dumps(result, allow_nan=False)


def test_cpu_snapshot_reads_pre_pin_affinity_without_count_overrides(monkeypatch):
    monkeypatch.setattr(driver.os, 'getloadavg', lambda: (11.794921875, 0, 0))
    monkeypatch.setattr(driver.os, 'sched_getaffinity', lambda pid: set(range(16)))
    monkeypatch.setattr(driver.os, 'cpu_count', lambda: pytest.fail('all CPUs are not the denominator'))
    monkeypatch.setenv('NPROC', '1')
    monkeypatch.setenv('OMP_NUM_THREADS', '1')
    original_read = driver.Path.read_text

    def no_psi(path, *args, **kwargs):
        assert str(path) != '/proc/pressure/cpu', 'there is no PSI branch'
        return original_read(path, *args, **kwargs)

    monkeypatch.setattr(driver.Path, 'read_text', no_psi)
    result = driver.sample_cpu_capacity()
    assert result['cpu_count'] == 16
    assert result['cpu_count_source'] == 'pre_pin_affinity'
    assert result['cpu_count_reason'] is None
    assert result['cpu_refused'] is False


@pytest.mark.parametrize('failure', ['os-error', 'missing-api'])
def test_expected_affinity_read_failure_has_a_typed_fallback(monkeypatch, failure):
    monkeypatch.setattr(driver.os, 'getloadavg', lambda: (9.0, 0, 0))

    def unavailable(pid):
        raise OSError('invented affinity read failure')

    if failure == 'missing-api':
        monkeypatch.delattr(driver.os, 'sched_getaffinity')
    else:
        monkeypatch.setattr(driver.os, 'sched_getaffinity', unavailable)
    result = driver.sample_cpu_capacity()
    assert result['cpu_policy'] == 'legacy_load_fallback'
    assert result['cpu_count'] is None
    assert result['cpu_count_source'] is None
    assert result['cpu_count_reason'] == 'AFFINITY_UNAVAILABLE'
    assert result['cpu_refused'] is False


def test_empty_affinity_has_a_typed_legacy_fallback(monkeypatch):
    monkeypatch.setattr(driver.os, 'getloadavg', lambda: (10.0, 0, 0))
    monkeypatch.setattr(driver.os, 'sched_getaffinity', lambda pid: set())
    result = driver.sample_cpu_capacity()
    assert result['cpu_count'] is None
    assert result['cpu_count_reason'] == 'AFFINITY_EMPTY'
    assert result['cpu_policy'] == 'legacy_load_fallback'
    assert result['cpu_refused'] is True


@pytest.mark.parametrize('operation', ['load', 'affinity'])
@pytest.mark.parametrize('error', [RuntimeError, AttributeError])
def test_unrelated_sampling_programming_fault_propagates(monkeypatch, operation, error):
    def broken(*args):
        raise error('invented programming fault')

    monkeypatch.setattr(driver.os, 'getloadavg', broken if operation == 'load' else lambda: (1, 0, 0))
    monkeypatch.setattr(driver.os, 'sched_getaffinity', broken if operation == 'affinity' else lambda pid: {0})
    with pytest.raises(error, match='programming fault'):
        driver.sample_cpu_capacity()


class AdmissionBoundary(RuntimeError):
    """Stop after verified pinning, before limits or product imports."""


@pytest.fixture
def capacity_run(tmp_path, monkeypatch):
    from types import SimpleNamespace

    pair = tmp_path / 'heads.json'
    pair.write_text(json.dumps(valid_heads()))
    output = tmp_path / 'capacity-output'
    monkeypatch.setenv('OHF_REPO', str(tmp_path))
    monkeypatch.setattr(driver, 'source_pins', lambda standard: {'invented-source': 'sha256:' + 'a' * 64})
    monkeypatch.setattr(driver, 'shutil', SimpleNamespace(
        disk_usage=lambda path: SimpleNamespace(total=8*1024**3, used=0, free=8*1024**3)))
    original_read = driver.Path.read_text

    def meminfo(path, *args, **kwargs):
        if str(path) == '/proc/meminfo':
            return 'MemAvailable: 8388608 kB\n'
        return original_read(path, *args, **kwargs)

    monkeypatch.setattr(driver.Path, 'read_text', meminfo)
    return pair, output


def logged_capacity(capsys):
    lines = capsys.readouterr().out.splitlines()
    rows = [json.loads(line.removeprefix('CAPACITY ')) for line in lines if line.startswith('CAPACITY ')]
    assert len(rows) == 1
    return rows[0], lines


@pytest.mark.parametrize('load', [1.0, 11.794921875, 11.73046875, 10.0654296875])
def test_public_capacity_admission_records_denominator_before_singleton_pin(
        capacity_run, monkeypatch, capsys, load):
    pair, output = capacity_run
    calls = []
    selected = 14  # Known scenario seed 4f240fc7... modulo 16.
    actual = set(range(16))
    monkeypatch.setattr(driver.os, 'getloadavg', lambda: (load, 0, 0))

    def affinity(pid):
        calls.append('read')
        return actual.copy()

    def pin(pid, cpus):
        calls.append('pin')
        assert cpus == {selected}
        assert json.loads((output / 'ADMISSION.json').read_text())['capacity']['cpu_count'] == 16
        actual.clear()
        actual.update(cpus)

    def boundary(*args):
        raise AdmissionBoundary('invented stop before limits, product import or dispatch')

    monkeypatch.setattr(driver.os, 'sched_getaffinity', affinity)
    monkeypatch.setattr(driver.os, 'sched_setaffinity', pin)
    monkeypatch.setattr(driver.resource, 'setrlimit', boundary)
    with pytest.raises(AdmissionBoundary):
        driver.run(pair, output, 'scenario')
    row, lines = logged_capacity(capsys)
    admission = json.loads((output / 'ADMISSION.json').read_text())['capacity']
    assert admission['cpu_placement']['status'] == 'NOT_ATTEMPTED'
    assert row['cpu_placement'] == json.loads((output / 'PIN.json').read_text())
    assert row['cpu_placement']['observed_after_pin'] == [selected]
    assert row['cpu_placement']['status'] == 'VERIFIED'
    assert row['cpu_count'] == 16
    assert row['load1_per_cpu'] == load / 16
    assert row['cpu_policy'] == 'normalized_load'
    assert row['cpu_refused'] is False
    assert calls == ['read', 'read', 'pin', 'read']
    assert not any(line.startswith('CAPACITY_REFUSED ') for line in lines)


@pytest.mark.parametrize('case', ['ratio-equality', 'smaller-affinity', 'missing-load',
                                  'nan-load', 'low-disk', 'low-memory', 'load-read-error'])
def test_public_capacity_refusals_are_finite_logged_and_pre_pin(
        capacity_run, monkeypatch, capsys, case):
    from types import SimpleNamespace

    pair, output = capacity_run
    load = {'ratio-equality': 14.4, 'smaller-affinity': 9.0,
            'missing-load': None, 'nan-load': float('nan')}.get(case, 1.0)

    def unavailable_load():
        raise OSError('invented load read failure')

    monkeypatch.setattr(driver.os, 'getloadavg', unavailable_load if case == 'load-read-error'
                        else lambda: (load, 0, 0))
    monkeypatch.setattr(driver.os, 'sched_getaffinity', lambda pid: set(range(8 if case == 'smaller-affinity' else 16)))
    monkeypatch.setattr(driver.os, 'sched_setaffinity', lambda *args: pytest.fail('refusal must precede pinning'))
    if case == 'low-disk':
        monkeypatch.setattr(driver, 'shutil', SimpleNamespace(
            disk_usage=lambda path: SimpleNamespace(total=8*1024**3, used=0, free=3*1024**3-1)))
    if case == 'low-memory':
        previous_read = driver.Path.read_text

        def low_meminfo(path, *args, **kwargs):
            return 'MemAvailable: 1 kB\n' if str(path) == '/proc/meminfo' else previous_read(path, *args, **kwargs)

        monkeypatch.setattr(driver.Path, 'read_text', low_meminfo)
    assert driver.run(pair, output, 'scenario') == 97
    row, lines = logged_capacity(capsys)
    assert row == json.loads((output / 'ADMISSION.json').read_text())['capacity']
    json.dumps(row, allow_nan=False)
    assert sum(line.startswith('CAPACITY_REFUSED ') for line in lines) == 1
    if case not in ('low-disk', 'low-memory'):
        assert row['cpu_refused'] is True
    else:
        assert row['cpu_refused'] is False
    if case == 'load-read-error':
        assert row['cpu_reason'] == 'LOAD_UNAVAILABLE'


def test_public_capacity_fallback_never_skips_required_singleton_pinning(
        capacity_run, monkeypatch, capsys):
    pair, output = capacity_run
    calls = []
    monkeypatch.setattr(driver.os, 'getloadavg', lambda: (1.0, 0, 0))

    def unavailable(pid):
        calls.append('read')
        raise OSError('invented affinity unavailable')

    monkeypatch.setattr(driver.os, 'sched_getaffinity', unavailable)
    monkeypatch.setattr(driver.os, 'sched_setaffinity', lambda *args: pytest.fail('no invented CPU is allowed'))
    assert driver.run(pair, output, 'scenario') == 97
    row, lines = logged_capacity(capsys)
    assert row['cpu_policy'] == 'legacy_load_fallback'
    assert row['cpu_count'] is None and row['load1_per_cpu'] is None
    assert row['cpu_refused'] is False
    assert calls == ['read']
    assert row['cpu_placement']['status'] == 'REFUSED'
    assert row['cpu_placement']['reason'] == 'PRE_PIN_AFFINITY_UNAVAILABLE'
    guards = [json.loads(line.removeprefix('GUARDS ')) for line in lines if line.startswith('GUARDS ')]
    assert guards[0]['cpu_placement'] == row['cpu_placement']
    assert guards[0]['exit_code'] == 97 and guards[0]['seconds'] is None


def test_stable_pair_batch_vector_uses_sorted_allowed_set_not_a_shared_minimum(monkeypatch):
    import hashlib
    # This literal is the public compact sorted seed, independent of the implementation.
    seed = ('{"batch":"scenario","pair":{"extractor_commit":"' + 'a'*40 +
            '","extractor_tree":"' + 'b'*40 + '","standard_commit":"' + 'c'*40 +
            '","standard_tree":"' + 'd'*40 + '"}}').encode('utf-8')
    digest = hashlib.sha256(seed).hexdigest()
    allowed = [2, 5, 9, 23, 48, 70, 91]
    selected = allowed[int(digest, 16) % len(allowed)]
    assert selected != min(allowed), 'the known vector must distinguish the original minimum'
    monkeypatch.setenv('NPROC', '1')
    monkeypatch.setenv('CPU', '999')
    for pair in (valid_heads(), dict(reversed(list(valid_heads().items())))):
        result = driver.cpu_placement(pair, 'scenario', allowed)
        assert result['algorithm'] == 'pair_batch_sha256_v1'
        assert result['seed_sha256'] == digest
        assert result['selected_cpu'] == selected
        assert result['pre_pin_allowed'] == allowed
        assert result['worker_count'] == 1
        assert result['status'] == 'NOT_ATTEMPTED'
    singleton = driver.cpu_placement(valid_heads(), 'scenario', [91])
    assert singleton['selected_cpu'] == 91
    seeds = {driver.cpu_placement(valid_heads(), batch, allowed)['seed_sha256'] for batch in driver.BATCHES}
    choices = {driver.cpu_placement(valid_heads(), batch, allowed)['selected_cpu'] for batch in driver.BATCHES}
    assert len(seeds) == len(driver.BATCHES) and len(choices) > 1
    assert choices <= set(allowed)  # Collisions are permitted; no reservation is claimed.


@pytest.mark.parametrize('allowed,reason', [({True}, 'AFFINITY_INVALID'),
    ({-1, 2}, 'AFFINITY_INVALID'), ({1.5}, 'AFFINITY_INVALID'),
    ([0, 1], 'AFFINITY_INVALID'), (None, 'AFFINITY_INVALID'),
    (set(), 'AFFINITY_EMPTY')])
def test_invalid_affinity_is_not_a_denominator_or_a_placement(monkeypatch, allowed, reason):
    monkeypatch.setattr(driver.os, 'getloadavg', lambda: (1, 0, 0))
    monkeypatch.setattr(driver.os, 'sched_getaffinity', lambda pid: allowed)
    capacity = driver.sample_cpu_capacity()
    assert capacity['cpu_count'] is None and capacity['pre_pin_allowed'] is None
    assert capacity['cpu_count_reason'] == reason
    assert capacity['cpu_policy'] == 'legacy_load_fallback'
    result = driver.cpu_placement(valid_heads(), 'scenario', capacity['pre_pin_allowed'])
    assert result['selected_cpu'] is None
    assert driver.pin_cpu(result)['status'] == 'REFUSED'


@pytest.mark.parametrize('case', ['changed-set', 'empty-set', 'read-error', 'missing-read',
    'missing-set', 'set-error', 'no-op', 'wrong-singleton', 'post-read-error', 'post-empty'])
def test_public_pin_failures_preserve_evidence_and_never_enter_product(
        capacity_run, monkeypatch, capsys, case):
    pair, output = capacity_run
    allowed = {2, 5, 9, 23, 48, 70, 91}
    selected = 5  # Known scenario seed 4f240fc7... selects index 1 of this sparse set.
    reads, sets = [], []
    monkeypatch.setattr(driver.os, 'getloadavg', lambda: (1, 0, 0))

    def read(pid):
        reads.append(pid)
        if len(reads) == 1:
            return allowed
        if len(reads) == 2:
            if case == 'changed-set': return {2, 5}
            if case == 'empty-set': return set()
            if case == 'read-error': raise OSError('invented pre-pin read error')
            return allowed
        if case == 'no-op': return allowed
        if case == 'wrong-singleton': return {999}
        if case == 'post-read-error': raise OSError('invented post-pin read error')
        if case == 'post-empty': return set()
        return {selected}

    def setter(pid, cpus):
        sets.append((pid, cpus))
        if case == 'set-error': raise OSError('invented pin OS error')

    monkeypatch.setattr(driver.os, 'sched_getaffinity', read)
    monkeypatch.setattr(driver.os, 'sched_setaffinity', setter)
    if case == 'missing-read':
        monkeypatch.delattr(driver.os, 'sched_getaffinity')
    if case == 'missing-set':
        monkeypatch.delattr(driver.os, 'sched_setaffinity')
    monkeypatch.setattr(driver.resource, 'setrlimit', lambda *args: pytest.fail('product/limits boundary reached'))
    assert driver.run(pair, output, 'scenario') == 97
    row, lines = logged_capacity(capsys)
    receipt = json.loads((output / 'PIN.json').read_text())
    assert receipt == row['cpu_placement']
    assert receipt['status'] == 'REFUSED' and receipt['reason']
    assert len(sets) <= 1
    if sets: assert sets == [(0, {selected})]
    guards = [json.loads(line.removeprefix('GUARDS ')) for line in lines if line.startswith('GUARDS ')]
    assert len(guards) == 1 and guards[0]['cpu_placement'] == receipt
    assert guards[0]['exit_code'] == 97
    assert not (output / 'RESULT.json').exists()
    assert not (output / 'PIN-AFTER.json').exists()
    assert not any(line.startswith('EXACT_PAIR ') for line in lines)
    original = {p.name: p.read_bytes() for p in output.iterdir()}
    with pytest.raises(ValueError, match='existing evidence'):
        driver.run(pair, output, 'scenario')
    assert {p.name: p.read_bytes() for p in output.iterdir()} == original


@pytest.mark.parametrize('observed,reason', [({23}, None), ({23, 48}, 'TERMINAL_AFFINITY_CHANGED'),
    ({48}, 'TERMINAL_AFFINITY_CHANGED'), (set(), 'AFFINITY_EMPTY')])
def test_terminal_affinity_is_actual_and_never_repinned(monkeypatch, observed, reason):
    result = driver.cpu_placement(valid_heads(), 'scenario', [23])
    result.update(status='VERIFIED', pin_attempted=True, observed_after_pin=[23])
    monkeypatch.setattr(driver.os, 'sched_getaffinity', lambda pid: observed)
    monkeypatch.setattr(driver.os, 'sched_setaffinity', lambda *args: pytest.fail('no repin'))
    terminal = driver.verify_final_affinity(result)
    assert terminal['reason'] == reason
    assert terminal['status'] == ('VERIFIED' if reason is None else 'REFUSED')
    assert terminal['observed_after_batch'] == (sorted(observed) if observed else None)
    assert result['observed_after_batch'] is None  # Initial evidence is not rewritten.


@pytest.mark.parametrize('terminal_drift', [False, True])
def test_public_batch_binds_actual_pin_to_both_rows_and_terminal_failure(
        capacity_run, monkeypatch, capsys, terminal_drift):
    _exercise_public_batch(capacity_run, monkeypatch, capsys, terminal_drift, 'driver')


def test_public_sharded_batch_uses_the_actual_partition(capacity_run, monkeypatch, capsys):
    _exercise_public_batch(capacity_run, monkeypatch, capsys, False, 'epoch2', 0)


def _exercise_public_batch(capacity_run, monkeypatch, capsys, terminal_drift, batch, shard_index=None,
                           missing_costs=False):
    import os
    import sys
    from types import SimpleNamespace

    pair, output = capacity_run
    initial = {2, 5, 9, 23, 48, 70, 91}
    actual = set(initial)
    shard = (batch, shard_index, driver.SHARD_COUNTS[batch]) if shard_index is not None else None
    selected = (5 if batch == 'driver' else
                driver.cpu_placement(valid_heads(), batch + '/' + str(shard_index), sorted(initial))['selected_cpu'])
    pins, limits, calls = [], [], []

    def pin(pid, cpus):
        pins.append((pid, cpus.copy()))
        actual.clear()
        actual.update(cpus)

    def fake_pytest(args, plugins):
        calls.append(args)
        assert args[-len(driver.BATCHES[batch]):] == driver.BATCHES[batch]
        assert len(plugins) == 2 and plugins[0].configuration == shard
        original_ids = (driver.load_relocations()['baseline_nodeids'] if shard else
                        [f'invented-{i}' for i in range(13)])
        items = [SimpleNamespace(nodeid=node) for node in original_ids]
        original_ids = [item.nodeid for item in items]
        config = SimpleNamespace(hook=SimpleNamespace(pytest_deselected=lambda **kwargs: None))
        plugins[0].pytest_collection_modifyitems(config, items)
        plugins[0].pytest_collection_finish(SimpleNamespace(items=items))
        expected = set(original_ids)
        if shard is not None:
            _name, index, count = shard
            expected = set(sorted(original_ids)[index::count])
            for move in driver.load_relocations()['relocations']:
                if index == move['from']: expected.remove(move['nodeid'])
                if index == move['to']: expected.add(move['nodeid'])
        assert {item.nodeid for item in items} == expected
        plugins[1].nodeids = [item.nodeid for item in items]
        plugins[1].rows = ([] if missing_costs else [[item.nodeid, 0.0, 0.0, 0.0] for item in items])
        assert actual == {selected}
        assert json.loads((output / 'PIN.json').read_text())['status'] == 'VERIFIED'
        if terminal_drift:
            actual.update(initial)
        return 0

    # The public run executes its complete control flow, but no product/test dispatch,
    # global audit hook, actual affinity, limits, environment or transport mutation.
    monkeypatch.setattr(driver, 'os', SimpleNamespace(
        getloadavg=lambda: (1, 0, 0), sched_getaffinity=lambda pid: actual.copy(),
        sched_setaffinity=pin, environ=dict(os.environ), chdir=lambda path: None,
        open=os.open, readlink=os.readlink, fsdecode=os.fsdecode, PathLike=os.PathLike,
        O_WRONLY=os.O_WRONLY, O_RDWR=os.O_RDWR, O_CREAT=os.O_CREAT, O_TRUNC=os.O_TRUNC))
    monkeypatch.setattr(driver, 'sys', SimpleNamespace(
        maxsize=sys.maxsize, base_prefix=sys.base_prefix, prefix=sys.prefix,
        path=[], addaudithook=lambda hook: None))
    monkeypatch.setattr(driver, 'socket', SimpleNamespace())
    monkeypatch.setattr(driver, 'subprocess', SimpleNamespace())
    usage_calls = {driver.resource.RUSAGE_SELF: 0, driver.resource.RUSAGE_CHILDREN: 0}
    def observed_usage(who):
        usage_calls[who] += 1
        before = usage_calls[who] == 1
        value = (1.0 if before else 4.0) if who == driver.resource.RUSAGE_SELF else (0.5 if before else 2.5)
        return SimpleNamespace(ru_utime=value, ru_stime=0.0)
    monkeypatch.setattr(driver.resource, 'getrusage', observed_usage)
    monkeypatch.setattr(driver.resource, 'setrlimit', lambda *args: limits.append(args))
    monkeypatch.setattr(driver.threading, 'Thread', lambda **kwargs: SimpleNamespace(start=lambda: None))
    monkeypatch.setattr(driver.tempfile, 'tempdir', None)
    monkeypatch.setitem(sys.modules, 'ohfkit', SimpleNamespace(rules_hash=lambda: 'sha256:'+'e'*64))
    monkeypatch.setitem(sys.modules, 'pytest', SimpleNamespace(main=fake_pytest, hookimpl=pytest.hookimpl))
    expected_status = 97 if terminal_drift else 95 if missing_costs else 0
    assert driver.run(pair, output, batch, 'sha256:'+'e'*64, shard_index) == expected_status
    row, lines = logged_capacity(capsys)
    guards = [json.loads(line.removeprefix('GUARDS ')) for line in lines if line.startswith('GUARDS ')]
    assert len(guards) == 1 and len(calls) == 1
    assert pins == [(0, {selected})]
    assert limits == [(driver.resource.RLIMIT_AS, (1024**3,)*2),
                      (driver.resource.RLIMIT_CPU, (180,)*2)]
    before = json.loads((output / 'PIN.json').read_text())
    after = json.loads((output / 'PIN-AFTER.json').read_text())
    assert row['cpu_count'] == len(initial) and row['pre_pin_allowed'] == sorted(initial)
    assert row['cpu_placement'] == before
    assert before['observed_before_pin'] == sorted(initial)
    assert before['observed_after_pin'] == [selected]
    assert before['status'] == 'VERIFIED'
    assert guards[0]['cpu_placement'] == after
    assert after['observed_after_batch'] == (sorted(initial) if terminal_drift else [selected])
    assert after['status'] == ('REFUSED' if terminal_drift else 'VERIFIED')
    assert guards[0]['exit_code'] == expected_status
    result = json.loads((output / 'RESULT.json').read_text())
    assert set(result) == {'pair', 'batch', 'exit_code', 'seconds', 'source_pins_after',
        'source_pins_exact', 'guard_violations', 'disk_minimum', 'scenario', 'scientific_acceptance',
        'wall_seconds_total', 'wall_scope', 'cpu_seconds', 'cpu_process_seconds', 'cpu_scope',
        'cpu_placement', 'test_cost_columns', 'test_costs', 'test_count', 'test_nodeids_sha256',
        'test_cost_scope', 'test_cost_summary', 'test_cost_error'} | ({'shard_index'} if shard else set())
    assert result['exit_code'] == guards[0]['exit_code']
    assert result['source_pins_exact'] is True and result['scientific_acceptance'] is False
    assert result['cpu_seconds'] == guards[0]['cpu_seconds'] == {'self': 3.0, 'children': 2.0, 'total': 5.0}
    assert result['cpu_process_seconds'] == guards[0]['cpu_process_seconds'] == {
        'self': 4.0, 'children': 2.5, 'total': 6.5}
    assert all(count == 2 for count in usage_calls.values())
    assert result['test_costs'] == guards[0]['test_costs']
    assert bool(result['test_cost_error']) is missing_costs
    assert 0 <= result['seconds'] <= result['wall_seconds_total']
    collection = json.loads((output / 'COLLECTION.json').read_text())
    assert collection['shard'] == (list(shard) if shard else None)
    assert result['test_costs'] == ([] if missing_costs else
        [[node, 0.0, 0.0, 0.0] for node in collection['selected_nodeids']])


def test_balanced_shards_have_exactly_once_membership():
    names = [f'case-{number}' for number in range(17)]
    parts = [driver.shard_nodeids(names, index) for index in range(driver.SHARD_COUNT)]
    assert sorted(name for part in parts for name in part) == sorted(names)
    assert max(map(len, parts)) - min(map(len, parts)) <= 1
    assert parts == [driver.shard_nodeids(list(reversed(names)), index)
                     for index in range(driver.SHARD_COUNT)]
    with pytest.raises(ValueError, match='duplicate'):
        driver.shard_nodeids(['same', 'same'], 0)


def test_actual_old_collections_land_once_in_new_batches(tmp_path, monkeypatch):
    import os
    from collections import Counter
    import ohfkit
    if ohfkit.standard_line() != '1.4':
        pytest.skip('Actual native collection census requires the pinned OHF 1.4 source')
    calls = [0]
    def collect(arguments, shard=None):
        calls[0] += 1
        captured = []
        class Capture:
            def pytest_collection_finish(self, session):
                captured.extend(item.nodeid for item in session.items)
        status = pytest.main(['--collect-only', '-q', '-p', 'no:cacheprovider',
                              '--basetemp', str(tmp_path / str(calls[0])), *arguments],
                             plugins=[driver.collection_plugin(pytest, shard), Capture()])
        assert status == 0
        return captured
    census = {}
    for original in driver.BATCH_ORDER:
        if original == 'scenario':
            assert driver.BATCHES[original] == driver.LEGACY_BATCHES[original] == []
            continue
        expected = collect(driver.LEGACY_BATCHES[original])
        names = ([name for name in driver.SHARDS if driver.SHARDS[name][0] == original]
                 if original in driver.SHARDED else [original])
        actual = []
        for name in names:
            selected = collect(driver.BATCHES[original], driver.SHARDS.get(name))
            assert selected
            if original == 'epoch2':
                assert sorted(expected) == driver.load_relocations()['baseline_nodeids']
                index = driver.SHARDS[name][1]
                assert set(selected) == _expected_relocated_epoch2(expected, index)
            actual.extend(selected)
        assert Counter(actual) == Counter(expected), original
        assert len(actual) == len(set(actual)), original
        census[original] = {'original': expected, 'new': actual, 'batches': names}
    # The three selectors themselves must cover the entire source test module.
    whole = collect(['scripts/tests/test_native_profile.py', 'scripts/tests/test_child_sourced_lists142.py'])
    selected = [node for group in ('schema-context', 'proofs-history', 'types-loader')
                for node in census[group]['original']]
    assert Counter(selected) == Counter(whole)
    (tmp_path / 'partition-census.json').write_text(json.dumps(census, indent=2)+'\n')


def test_workflow_runs_every_new_batch_once_with_unchanged_timeout():
    workflow = (driver.REPO / '.forgejo/workflows/check.yml').read_text()
    assert workflow.count('--parent --pair profile-ci/heads.json --output profile-ci') == 1
    assert 'timeout 5040s nice -n 15 .profile-venv/bin/python -I -B' in workflow
    assert 'timeout-minutes: 84' in workflow
    assert {name: driver.batch_wall_budget(name) for name in driver.BATCHES} == {
        'driver':240,'schema-context':480,'proofs-history':480,'types-loader':480,
        'epoch2':960,'io':240,'scenario':240}
    assert driver.PARENT_WALL_SECONDS == sum(driver.batch_wall_budget(n) for n in driver.BATCHES) + 1800 + 120 == 5040
    assert '--check-headroom profile-ci' in workflow


def test_cpu_observations_include_self_and_children(monkeypatch):
    from types import SimpleNamespace
    def usage(who):
        return (SimpleNamespace(ru_utime=7.5, ru_stime=2.5) if who == driver.resource.RUSAGE_SELF
                else SimpleNamespace(ru_utime=3.0, ru_stime=1.0))
    monkeypatch.setattr(driver.resource, 'getrusage', usage)
    after = driver.cpu_sample()
    assert after == {'self': 10.0, 'children': 4.0, 'total': 14.0}
    assert driver.cpu_elapsed({'self': 2.0, 'children': 1.0, 'total': 3.0}, after) == {
        'self': 8.0, 'children': 3.0, 'total': 11.0}
    with pytest.raises(ValueError, match='backwards'):
        driver.cpu_elapsed(after, {'self': 1.0, 'children': 4.0, 'total': 5.0})


@pytest.mark.parametrize('failure', ['missing', 'extra', 'cpu', 'wall', 'nonfinite', 'failed'])
def test_terminal_headroom_refuses_incomplete_or_over_half_cap(tmp_path, failure):
    for name in driver.BATCHES:
        output = tmp_path / name
        output.mkdir()
        result = {
            'batch': name, 'exit_code': 0, 'cpu_process_seconds': {'total': 20.0},
            'wall_seconds_total': 30.0}
        _with_test_costs(result)
        if name in driver.SHARDED:
            result['shards'] = [dict(result, shard_index=index) for index in range(driver.SHARD_COUNTS[name])]
        (output / 'RESULT.json').write_text(json.dumps(result))
    assert len(driver.verify_headroom(tmp_path)) == len(driver.SHARDS) + 3
    first = tmp_path / next(iter(driver.BATCHES)) / 'RESULT.json'
    if failure == 'missing':
        first.unlink()
    elif failure == 'extra':
        (tmp_path / 'unexpected').mkdir()
        (tmp_path / 'unexpected' / 'RESULT.json').write_text('{}')
    else:
        data = json.loads(first.read_text())
        if failure == 'cpu': data['cpu_process_seconds']['total'] = 90.001
        elif failure == 'wall': data['wall_seconds_total'] = 120.001
        elif failure == 'nonfinite': data['wall_seconds_total'] = float('nan')
        else: data['exit_code'] = 1
        first.write_text(json.dumps(data))
    with pytest.raises(ValueError, match='CI_HEADROOM'):
        driver.verify_headroom(tmp_path)


def _aggregate_with_fake_workers(capacity_run, monkeypatch, batch, failure=None, rules=None):
    from types import SimpleNamespace
    import subprocess
    pair_file, output = capacity_run
    pair = {**valid_heads(), 'rules_sha256': rules or 'sha256:'+'e'*64}
    calls = []
    nodeids = [f'invented-{i:02}' for i in range(16)]
    monkeypatch.setattr(driver.resource, 'setrlimit', lambda *args: None)
    monkeypatch.setattr(driver, 'sample_cpu_capacity', lambda: {
        'cpu_refused': False, 'pre_pin_allowed': list(range(16)), 'cpu_count': 16,
        'load1': 1.0, 'load1_per_cpu': 1/16, 'cpu_policy': 'normalized_load'})
    def worker(command, **kwargs):
        index = int(command[command.index('--shard-index')+1])
        child = driver.Path(command[command.index('--output')+1])
        assert command[:3] == [driver.sys.executable, '-I', '-B']
        assert command[command.index('--batch')+1] == batch
        assert command[command.index('--pair')+1] == str(pair_file)
        assert kwargs['timeout'] == 240 and kwargs['check'] is False and kwargs['cwd'] == driver.REPO
        assert index == len(calls)
        calls.append(index)
        kwargs['stdout'].write('invented worker output\n')
        if failure == 'timeout' and index == 1:
            raise subprocess.TimeoutExpired(command, 240)
        child.mkdir()
        selected = nodeids[index::driver.SHARD_COUNTS[batch]]
        if failure == 'duplicate' and index == 1: selected = nodeids[0::driver.SHARD_COUNTS[batch]]
        if failure == 'missing' and index == 1: selected = selected[1:]
        row = {'pair': dict(pair), 'batch': batch, 'shard_index': index, 'exit_code': 0,
               'seconds': 10.0, 'wall_seconds_total': 12.0,
               'cpu_seconds': {'self': 4.0, 'children': 1.0, 'total': 5.0},
               'cpu_process_seconds': {'self': 5.0, 'children': 1.0, 'total': 6.0},
               'source_pins_exact': True, 'source_pins_after': driver.source_pins(None),
               'guard_violations': [], 'disk_minimum': 8*1024**3, 'scenario': None,
               'cpu_placement': {'status': 'VERIFIED', 'selected_cpu': index,
                   'observed_after_pin': [index], 'observed_after_batch': [index], 'worker_count': 1}}
        _with_test_costs(row, selected)
        if failure == 'cost-census' and index == 1:
            _with_test_costs(row, ['invented-uncollected-cost'])
        if failure == 'source' and index == 1: row['source_pins_exact'] = False
        if failure == 'pin' and index == 1: row['cpu_placement']['status'] = 'REFUSED'
        if failure == 'cpu' and index == 1: row['cpu_process_seconds']['total'] = 90.01
        if failure == 'wall' and index == 1: row['wall_seconds_total'] = 120.01
        if failure == 'pair' and index == 1: row['pair']['standard_commit'] = 'f'*40
        (child/'RESULT.json').write_text(json.dumps(row))
        (child/'COLLECTION.json').write_text(json.dumps({'shard': [batch,index,driver.SHARD_COUNTS[batch]],
            'before_shard_nodeids': nodeids, 'selected_nodeids': selected}))
        return SimpleNamespace(returncode=1 if failure == 'exit' and index == 1 else 0)
    monkeypatch.setattr(driver.subprocess, 'run', worker)
    return pair_file, output, pair, calls


@pytest.mark.parametrize('batch', ['schema-context','proofs-history','types-loader','epoch2'])
def test_seven_batch_interface_aggregates_serial_bounded_workers(capacity_run, monkeypatch, batch):
    pair, output, expected, calls = _aggregate_with_fake_workers(capacity_run, monkeypatch, batch)
    assert driver.run(pair, output, batch) == 0
    result = json.loads((output/'RESULT.json').read_bytes())
    assert result['pair'] == expected and result['batch'] == batch and result['exit_code'] == 0
    assert calls == list(range(driver.SHARD_COUNTS[batch]))
    assert len(result['shards']) == driver.SHARD_COUNTS[batch]
    assert result['source_pins_exact'] is True and result['guard_violations'] == []
    census = json.loads((output/'COLLECTION.json').read_bytes())
    assert census['exactly_once'] is True
    assert sorted(census['selected_nodeids']) == census['before_shard_nodeids']
    assert set(driver.BATCHES) == {'driver','schema-context','proofs-history','types-loader','epoch2','io','scenario'}


@pytest.mark.parametrize('failure', ['exit','timeout','duplicate','missing','source','pin','cpu','wall','pair','cost-census'])
def test_aggregate_never_passes_failed_worker_or_incomplete_census(capacity_run, monkeypatch, failure):
    pair, output, _, calls = _aggregate_with_fake_workers(capacity_run, monkeypatch, 'epoch2', failure)
    if failure in ('exit','timeout'):
        assert driver.run(pair, output, 'epoch2') != 0
    else:
        with pytest.raises(ValueError, match='CI_SHARD|CI_HEADROOM|CI_TEST_COST'):
            driver.run(pair, output, 'epoch2')
    result = json.loads((output/'RESULT.json').read_bytes())
    assert result['exit_code'] != 0
    assert not (output/'COLLECTION.json').exists()
    if failure not in ('duplicate','missing'): assert calls == [0,1]


def test_aggregated_receipts_are_read_by_the_pinned_standard_verifier(tmp_path, capacity_run, monkeypatch):
    import ohfkit
    import hashlib
    import importlib.util
    from native_profile_ci import run as scenario
    if ohfkit.standard_line() != '1.4':
        pytest.skip('The pinned receipt reader belongs to the OHF 1.4 pair')
    name, digest = driver.RECEIPT_READER_PIN
    source = ohfkit.REPO / name
    assert 'sha256:'+hashlib.sha256(source.read_bytes()).hexdigest() == digest
    spec = importlib.util.spec_from_file_location('pinned_receipt_reader', source)
    api = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(api)
    pair = {**valid_heads(), 'rules_sha256': ohfkit.rules_hash()}
    root = tmp_path/'pair'
    root.mkdir()
    pair_file, _ = capacity_run
    fake_pair, actual_output, _, _ = _aggregate_with_fake_workers(
        (pair_file, root/'epoch2'), monkeypatch, 'epoch2', rules=pair['rules_sha256'])
    assert driver.run(fake_pair, actual_output, 'epoch2') == 0
    for batch in driver.BATCHES:
        if batch != 'epoch2': (root/batch).mkdir()
    (root/'scenario'/'scenario').mkdir()
    monkeypatch.setenv('OHF_REPO', str(ohfkit.REPO))
    receipt = scenario(root/'scenario'/'scenario', pair)
    association = {'pair': valid_heads(), 'rules_sha256': pair['rules_sha256'],
        'selector': receipt['validation']['profile'], 'normative_base': receipt['normative_base'],
        'validation_entrypoint': 'native_profile.validate_files -> validate_bundle',
        'normative_files': {'schema/hypothesis-1.schema.json': receipt['validation']['profile_contract']['schema_sha256']}}
    (root/'association.json').write_text(json.dumps(association))
    summary = {'status': receipt['status'], 'pair': pair,
        'validation_entrypoint': association['validation_entrypoint'], 'selector': association['selector'],
        'schema_valid': True, 'native_binding_valid': True, 'bare_reader_status': 'UNSUPPORTED_NATIVE_VALUES',
        'bare_error_count': 4, 'scientific_acceptance': False}
    for batch in driver.BATCHES:
        if batch == 'epoch2': continue
        result = {'pair': pair, 'batch': batch, 'exit_code': 0, 'seconds': 12.0,
            'source_pins_exact': True, 'guard_violations': [], 'scenario': summary if batch=='scenario' else None,
            'shards': [{'shard_index':i,'cpu_process_seconds':{'total':6.0},'wall_seconds_total':12.0}
                       for i in range(driver.SHARD_COUNTS.get(batch,0))]}
        (root/batch/'RESULT.json').write_text(json.dumps(result))
    actual = api.summarize(root)
    assert list(actual['batches']) == list(driver.BATCHES) == api.BATCHES
    assert actual['scenario']['status'] == 'PASS_SYNTHETIC_NATIVE_PROFILE'
    # Existing refusal still behaves through the unchanged Standard reader.
    bad = json.loads((root/'epoch2'/'RESULT.json').read_bytes());bad['exit_code']=1
    (root/'epoch2'/'RESULT.json').write_text(json.dumps(bad))
    with pytest.raises(api.PairError, match='batch result differs or refused: epoch2'):
        api.summarize(root)


def test_receipt_reader_is_separate_from_production_and_bootstrap_pins():
    import native_profile
    name, _ = driver.RECEIPT_READER_PIN
    assert name not in driver.BOOTSTRAP_PINS
    assert name not in native_profile.dependency_pins()
    assert len(driver.BOOTSTRAP_PINS) == 2 and len(native_profile.dependency_pins()) == 24


@pytest.mark.parametrize('failure', ['child-cpu','child-wall','missing-shard','duplicate-index','aggregate-wall'])
def test_aggregate_headroom_checks_every_child_and_the_controller_wall(tmp_path, failure):
    for name in driver.BATCHES:
        output = tmp_path/name
        output.mkdir()
        result = {'batch':name, 'exit_code':0, 'cpu_process_seconds':{'total':20.0},
                  'wall_seconds_total':30.0}
        _with_test_costs(result)
        if name in driver.SHARDED:
            result['shards'] = [dict(result, shard_index=i) for i in range(driver.SHARD_COUNTS[name])]
        (output/'RESULT.json').write_text(json.dumps(result))
    assert len(driver.verify_headroom(tmp_path)) == 31
    path = tmp_path/'epoch2'/'RESULT.json'
    result = json.loads(path.read_bytes())
    if failure=='child-cpu': result['shards'][-1]['cpu_process_seconds']['total'] = 90.001
    elif failure=='child-wall': result['shards'][-1]['wall_seconds_total'] = 120.001
    elif failure=='missing-shard': result['shards'].pop()
    elif failure=='duplicate-index': result['shards'][-1]['shard_index'] = 0
    else: result['wall_seconds_total'] = 480.001
    path.write_text(json.dumps(result))
    with pytest.raises(ValueError, match='CI_HEADROOM'):
        driver.verify_headroom(tmp_path)


def test_aggregate_guard_row_fits_log_transport_without_losing_worker_measurements(
        capacity_run, monkeypatch, capsys):
    pair, output, _, _ = _aggregate_with_fake_workers(capacity_run, monkeypatch, 'epoch2')
    big_pins = {f'invented-source-{i:04}': 'sha256:'+'a'*64 for i in range(2048)}
    monkeypatch.setattr(driver, 'source_pins', lambda standard: dict(big_pins))
    assert driver.run(pair, output, 'epoch2') == 0
    lines = capsys.readouterr().out.splitlines()
    emitted = next(line for line in lines if line.startswith('GUARDS '))
    assert len(emitted.encode()) < 16*1024
    guard = json.loads(emitted.removeprefix('GUARDS '))
    full = json.loads((output/'RESULT.json').read_bytes())
    assert (output/'RESULT.json').stat().st_size > 64*1024
    assert len(guard['shards']) == len(full['shards']) == 16
    required = {'batch','shard_index','exit_code','seconds','wall_seconds_total',
        'cpu_seconds','cpu_process_seconds','source_pins_exact','guard_violations',
        'disk_minimum','cpu_placement','test_cost_summary'}
    for brief, original in zip(guard['shards'], full['shards']):
        assert set(brief) == required
        assert brief == {key: original[key] for key in required}
        assert original['source_pins_after'] == big_pins
    assert full['source_pins_after'] == big_pins


def _require_standard_commit_binding(workflow, projection_source):
    import ast
    import re
    steps = re.split(r'(?m)^      - ', workflow)
    checkout = [step for step in steps
                if re.search(r'(?m)^\s+repository: ol/open-hypothesis-format$', step)
                and re.search(r'(?m)^\s+path: standard-profile-1\.4$', step)]
    assert len(checkout) == 1, 'one normative Standard checkout is required'
    refs = re.findall(r'(?m)^\s+ref: ([0-9a-f]{40})$', checkout[0])
    verified = re.findall(
        r'test "\$\(git -C standard-profile-1\.4 rev-parse HEAD\)" = ([0-9a-f]{40})',
        workflow)
    constants = [ast.literal_eval(node.value) for node in ast.parse(projection_source).body
                 if isinstance(node, ast.Assign)
                 and any(isinstance(target, ast.Name) and target.id == 'STANDARD_COMMIT'
                         for target in node.targets)]
    assert len(refs) == len(verified) == len(constants) == 1, 'one binding at each boundary is required'
    assert refs == verified == constants, 'Standard checkout ref, verify commit and projection binding differ'


def test_workflow_standard_checkout_verify_and_projection_commit_agree():
    _require_standard_commit_binding(
        (driver.REPO / '.forgejo/workflows/check.yml').read_text(),
        (driver.REPO / 'scripts/projection_binding.py').read_text())


@pytest.mark.parametrize('binding', ['checkout-ref', 'verify-commit', 'projection-commit'])
def test_standard_commit_binding_refuses_each_isolated_drift(binding):
    import ast
    import re
    workflow = (driver.REPO / '.forgejo/workflows/check.yml').read_text()
    projection = (driver.REPO / 'scripts/projection_binding.py').read_text()
    commit = next(ast.literal_eval(node.value) for node in ast.parse(projection).body
                  if isinstance(node, ast.Assign)
                  and any(isinstance(target, ast.Name) and target.id == 'STANDARD_COMMIT'
                          for target in node.targets))
    changed = '0' * 40 if commit != '0' * 40 else '1' * 40
    _require_standard_commit_binding(workflow, projection)
    if binding == 'checkout-ref':
        # The general job independently checks out the same active primary.
        # Mutate only the native boundary tested here, preserving the general ref.
        general, native = workflow.split('\n  native-profile-1-4:\n', 1)
        native, count = re.subn(r'(?m)^(\s+ref: )' + commit + r'$',
                               lambda match: match[1] + changed, native)
        workflow = general + '\n  native-profile-1-4:\n' + native
    elif binding == 'verify-commit':
        before = 'test "$(git -C standard-profile-1.4 rev-parse HEAD)" = ' + commit
        count = workflow.count(before)
        workflow = workflow.replace(before, before.removesuffix(commit) + changed)
    else:
        before = 'STANDARD_COMMIT = ' + repr(commit)
        count = projection.count(before)
        projection = projection.replace(before, 'STANDARD_COMMIT = ' + repr(changed))
    assert count == 1
    with pytest.raises(AssertionError, match='Standard checkout ref, verify commit and projection binding differ'):
        _require_standard_commit_binding(workflow, projection)


@pytest.mark.parametrize('count', [8, 16, 32])
def test_epoch2_outer_budget_and_headroom_do_not_grow_with_shards(tmp_path, monkeypatch, count):
    monkeypatch.setitem(driver.SHARD_COUNTS, 'epoch2', count)
    assert driver.batch_wall_budget('epoch2') == 960
    for name in driver.BATCHES:
        output = tmp_path / name
        output.mkdir()
        result = {'batch': name, 'exit_code': 0,
                  'cpu_process_seconds': {'total': 20.0}, 'wall_seconds_total': 30.0}
        _with_test_costs(result)
        if name in driver.SHARDED:
            result['shards'] = [dict(result, shard_index=i)
                                for i in range(driver.SHARD_COUNTS[name])]
        (output / 'RESULT.json').write_text(json.dumps(result))
    assert driver.verify_headroom(tmp_path)
    path = tmp_path / 'epoch2/RESULT.json'
    result = json.loads(path.read_text())
    result['wall_seconds_total'] = 480.001
    path.write_text(json.dumps(result))
    with pytest.raises(ValueError, match='CI_HEADROOM: aggregate wall margin differs: epoch2'):
        driver.verify_headroom(tmp_path)


def _expected_relocated_epoch2(nodeids, index):
    expected = set(sorted(nodeids)[index::16])
    moved = {
        'scripts/tests/test_native_profile14.py::test_source_version_change_cannot_hide_same_value_passage_worst_history': 6,
        'scripts/tests/test_native_profile14.py::test_public_files_refuse_malformed_ledger_json_containers[validate_files_null]': 14,
        'scripts/tests/test_native_profile14.py::test_n2_selected_release_accepts_explicit_unknown_totals[counter_failed-input_tokens]': 11,
        'scripts/tests/test_native_profile14.py::test_public_files_refuse_malformed_ledger_json_containers[input_manifest_null_element]': 8,
        'scripts/tests/test_native_profile14.py::test_n2_known_totals_refuse_invalid_counter_types[0-input_tokens]': 11,
    }
    if index == 0: expected -= moved.keys()
    expected.update(node for node, target in moved.items() if target == index)
    return expected


def test_pinned_relocations_move_only_five_of_205_ids_with_no_loss_or_duplicate():
    from collections import Counter
    manifest = driver.load_relocations()
    nodeids = manifest['baseline_nodeids']
    assert len(nodeids) == len(set(nodeids)) == 205
    parts = [driver.relocated_nodeids(nodeids, i, 16, manifest) for i in range(16)]
    assert Counter(node for part in parts for node in part) == Counter(nodeids)
    assert parts == [_expected_relocated_epoch2(nodeids, i) for i in range(16)]
    before = {node: i for i in range(16) for node in sorted(nodeids)[i::16]}
    after = {node: i for i, part in enumerate(parts) for node in part}
    changes = {node: (before[node], after[node]) for node in nodeids if before[node] != after[node]}
    assert changes == {
        'scripts/tests/test_native_profile14.py::test_source_version_change_cannot_hide_same_value_passage_worst_history': (0, 6),
        'scripts/tests/test_native_profile14.py::test_public_files_refuse_malformed_ledger_json_containers[validate_files_null]': (0, 14),
        'scripts/tests/test_native_profile14.py::test_n2_selected_release_accepts_explicit_unknown_totals[counter_failed-input_tokens]': (0, 11),
        'scripts/tests/test_native_profile14.py::test_public_files_refuse_malformed_ledger_json_containers[input_manifest_null_element]': (0, 8),
        'scripts/tests/test_native_profile14.py::test_n2_known_totals_refuse_invalid_counter_types[0-input_tokens]': (0, 11),
    }
    assert sum(before[node] == after[node] for node in nodeids) == 200
    assert parts == [driver.relocated_nodeids(list(reversed(nodeids)), i, 16, manifest)
                     for i in range(16)]


@pytest.mark.parametrize('case,reason', [
    ('unknown', 'unknown relocation id'),
    ('removed', 'stale relocation id'),
    ('renamed', 'stale relocation id'),
    ('duplicate', 'duplicate relocation id'),
    ('new-collected', 'collected census differs'),
    ('new-collected-sort-shift', 'collected census differs'),
])
def test_relocation_unknown_stale_and_duplicate_ids_refuse(case, reason):
    from copy import deepcopy
    manifest = deepcopy(driver.load_relocations())
    nodeids = list(manifest['baseline_nodeids'])
    first = manifest['relocations'][0]['nodeid']
    if case == 'unknown': manifest['relocations'][0]['nodeid'] = 'scripts/tests/test_native_profile14.py::unknown_case'
    elif case == 'removed': nodeids.remove(first)
    elif case == 'renamed': nodeids[nodeids.index(first)] += '_renamed'
    elif case == 'duplicate': manifest['relocations'].append(deepcopy(manifest['relocations'][0]))
    elif case == 'new-collected-sort-shift': nodeids.append('scripts/tests/test_native_profile14.py::new_unreviewed_case')
    else: nodeids.append('scripts/tests/test_native_profile14.py::zzz_new_unreviewed_case')
    with pytest.raises(ValueError, match='CI_RELOCATION: '+reason):
        driver.relocated_nodeids(nodeids, 0, 16, manifest)


@pytest.mark.parametrize('key,value,reason', [
    ('from', 1, 'source/destination differs'),
    ('to', 0, 'source/destination differs'),
    ('to', 16, 'source/destination differs'),
    ('to', True, 'source/destination differs'),
    ('cpu_seconds', 0, 'measured cost/provenance differs'),
    ('cpu_seconds', True, 'measured cost/provenance differs'),
    ('cpu_seconds', float('nan'), 'measured cost/provenance differs'),
    ('wall_seconds', -1, 'measured cost/provenance differs'),
    ('source_run', '', 'measured cost/provenance differs'),
    ('reason', '', 'measured cost/provenance differs'),
])
def test_relocations_require_honest_measured_weights_and_valid_destinations(key, value, reason):
    from copy import deepcopy
    manifest = deepcopy(driver.load_relocations())
    manifest['relocations'][0][key] = value
    with pytest.raises(ValueError, match='CI_RELOCATION: '+reason):
        driver.relocated_nodeids(manifest['baseline_nodeids'], 0, 16, manifest)


@pytest.mark.parametrize('case,reason', [
    ('format', 'manifest format/count differs'),
    ('count', 'manifest format/count differs'),
    ('baseline-duplicate', 'baseline census differs'),
    ('missing-move', 'exactly five moves required'),
])
def test_relocation_manifest_identity_and_inventory_refuse(case, reason):
    from copy import deepcopy
    manifest = deepcopy(driver.load_relocations())
    nodeids = list(manifest['baseline_nodeids'])
    if case == 'format': manifest['format'] = 'unknown/1'
    elif case == 'count': manifest['shard_count'] = 8
    elif case == 'baseline-duplicate': manifest['baseline_nodeids'][1] = manifest['baseline_nodeids'][0]
    else: manifest['relocations'].pop()
    with pytest.raises(ValueError, match='CI_RELOCATION: '+reason):
        driver.relocated_nodeids(nodeids, 0, 16, manifest)


def test_relocation_file_pin_refuses_tampering_before_selection(tmp_path, monkeypatch):
    name, digest = driver.RELOCATION_MANIFEST_PIN
    raw = (driver.REPO/name).read_bytes()
    path = tmp_path/name
    path.parent.mkdir(parents=True)
    path.write_bytes(raw)
    monkeypatch.setattr(driver, 'REPO', tmp_path)
    assert driver.load_relocations()['format'] == 'ohf-ci-epoch2-relocations/2'
    path.write_bytes(raw+b' ')
    with pytest.raises(ValueError, match='CI_RELOCATION: manifest pin differs'):
        driver.load_relocations()


def test_relocation_manifest_duplicate_json_key_refuses_even_with_matching_pin(tmp_path, monkeypatch):
    import hashlib
    raw = b'{"format":"one","format":"two"}'
    path = tmp_path/'manifest.json'
    path.write_bytes(raw)
    monkeypatch.setattr(driver, 'REPO', tmp_path)
    monkeypatch.setattr(driver, 'RELOCATION_MANIFEST_PIN', (path.name, 'sha256:'+hashlib.sha256(raw).hexdigest()))
    with pytest.raises(ValueError, match='CI_RELOCATION: duplicate manifest key'):
        driver.load_relocations()


def _with_test_costs(result, nodeids=None):
    nodeids = ['invented-case'] if nodeids is None else nodeids
    result.update(test_cost_columns=driver.TEST_COST_COLUMNS,
                  test_costs=[[node, 0.0, 0.0, 0.0] for node in nodeids],
                  test_count=len(nodeids), test_nodeids_sha256=driver.nodeids_digest(nodeids))
    result['test_cost_summary'] = driver.test_cost_summary(result) if nodeids else None
    return result


def test_public_leaf_refuses_missing_per_test_rows(capacity_run, monkeypatch, capsys):
    _exercise_public_batch(capacity_run, monkeypatch, capsys, False, 'driver', missing_costs=True)


def test_per_test_plugin_measures_protocol_self_children_and_wall(monkeypatch):
    from types import SimpleNamespace
    samples = iter([{'self': 1.0, 'children': 2.0, 'total': 3.0},
                    {'self': 4.0, 'children': 3.0, 'total': 7.0}])
    clocks = iter([10.0, 12.0])
    monkeypatch.setattr(driver, 'cpu_sample', lambda: next(samples))
    monkeypatch.setattr(driver, 'time', SimpleNamespace(monotonic=lambda: next(clocks)))
    plugin = driver.test_cost_plugin(pytest)
    item = SimpleNamespace(nodeid='invented-protocol')
    plugin.pytest_collection_finish(SimpleNamespace(items=[item]))
    protocol = plugin.pytest_runtest_protocol(item, None)
    next(protocol)
    assert plugin.rows == []
    with pytest.raises(StopIteration): next(protocol)
    assert plugin.nodeids == ['invented-protocol']
    assert plugin.rows == [['invented-protocol', 3.0, 1.0, 2.0]]


def _observed_test_cost_receipt():
    result = {'exit_code': 0, 'cpu_process_seconds': {'total': 20.0}, 'wall_seconds_total': 30.0}
    _with_test_costs(result, ['invented-one', 'invented-two'])
    result['test_costs'] = [['invented-one', 3.0, 1.0, 2.0], ['invented-two', 0.5, 1.5, 3.0]]
    return result


def test_leaf_summary_measures_heaviest_plus_non_test_residual_without_startup_guess():
    result = _observed_test_cost_receipt()
    summary = driver.measured_margin(result, 'invented-leaf')['test_cost_summary']
    assert summary['test_count'] == 2
    assert summary['heaviest_test'] == 'invented-one'
    assert summary['heaviest_test_cpu_seconds'] == 4.0
    assert summary['non_test_cpu_seconds'] == 14.0
    assert summary['non_test_wall_seconds'] == 25.0
    assert summary['measured_floor_cpu_seconds'] == 18.0
    changed = _observed_test_cost_receipt()
    changed['test_costs'][1][2] += 0.25
    assert driver.test_cost_summary(changed)['test_costs_sha256'] != summary['test_costs_sha256']


@pytest.mark.parametrize('case,reason', [
    ('missing', 'missing or incomplete per-test rows'),
    ('empty', 'missing or incomplete per-test rows'),
    ('incomplete', 'missing or incomplete per-test rows'),
    ('boolean-count', 'missing or incomplete per-test rows'),
    ('wrong-columns', 'missing or incomplete per-test rows'),
    ('duplicate', 'per-test collection differs'),
    ('foreign-id', 'per-test collection differs'),
    ('missing-digest', 'per-test collection differs'),
    ('negative', 'invalid per-test row'),
    ('boolean', 'invalid per-test row'),
    ('nan', 'invalid per-test row'),
    ('cpu-overlap', 'per-test sum exceeds leaf measurement'),
    ('wall-overlap', 'per-test sum exceeds leaf measurement'),
])
def test_headroom_refuses_absent_or_untrustworthy_per_test_measurements(case, reason):
    result = _observed_test_cost_receipt()
    if case == 'missing': result.pop('test_costs')
    elif case == 'empty': result['test_costs'] = []
    elif case == 'incomplete': result['test_costs'].pop()
    elif case == 'boolean-count': result['test_count'] = True
    elif case == 'wrong-columns': result['test_cost_columns'] = ['invented-other-columns']
    elif case == 'duplicate': result['test_costs'][1] = list(result['test_costs'][0])
    elif case == 'foreign-id': result['test_costs'][0][0] = 'invented-uncollected'
    elif case == 'missing-digest': result.pop('test_nodeids_sha256')
    elif case == 'negative': result['test_costs'][0][1] = -1.0
    elif case == 'boolean': result['test_costs'][0][1] = True
    elif case == 'nan': result['test_costs'][0][1] = float('nan')
    elif case == 'cpu-overlap': result['test_costs'][0][1] = 21.0
    else: result['test_costs'][0][3] = 31.0
    with pytest.raises(ValueError, match='CI_TEST_COST: '+reason):
        driver.measured_margin(result, 'invented-leaf')


def test_relocation_v2_preserves_and_identifies_the_original_manifest():
    import hashlib
    old = (driver.REPO/'scripts/tests/native_profile_relocations-1.json').read_bytes()
    digest = hashlib.sha256(old).hexdigest()
    assert digest == '3f6a359e5f7389789e80fc1d8c387e396de0ea98b4c226e46d0dd25c44f16084'
    active = json.loads((driver.REPO/'scripts/tests/native_profile_relocations-2.json').read_bytes())
    assert active['previous_manifest_sha256'] == digest
    original = json.loads(old)
    assert active['baseline_nodeids'] == original['baseline_nodeids']
    assert active['relocations'][:2] == original['relocations']
    assert len(active['relocations']) == 5


def test_relocation_v3_changes_only_the_explicit_dependency_record_parameter_ids():
    import hashlib
    old = (driver.REPO/'scripts/tests/native_profile_relocations-2.json').read_bytes()
    assert hashlib.sha256(old).hexdigest() == 'def88822c9c939896f16d7f51b0058a859481c23e63dbcee1607f7623944caff'
    previous = json.loads(old)
    active = driver.load_relocations()
    assert active['previous_manifest_sha256'] == hashlib.sha256(old).hexdigest()
    assert active['baseline_nodeids'] == [node.replace('native-relational-3.json', 'native-relational-4.json')
                                         for node in previous['baseline_nodeids']]
    assert {key: value for key, value in active.items() if key not in ('baseline_nodeids', 'previous_manifest_sha256')} == {
        key: value for key, value in previous.items() if key not in ('baseline_nodeids', 'previous_manifest_sha256')}


class ParentClock:
    def __init__(self, on_sleep=None):
        self.now = 0
        self.sleeps = []
        self.on_sleep = on_sleep

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds
        if self.on_sleep:
            self.on_sleep(self.now)


@pytest.fixture
def parent_lock(tmp_path, monkeypatch):
    path = tmp_path/'host-locks'/'native-profile.lock'
    monkeypatch.setattr(driver, 'HOST_LOCK', path)
    return path


def competing_lock(path):
    """A separate open description must conflict even in this same process."""
    import os
    import fcntl
    fd = os.open(path, os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return True
    finally:
        os.close(fd)
    return False


def test_parent_waits_for_load_then_admits_without_changing_threshold(parent_lock):
    import stat
    clock = ParentClock()
    loads = iter([14.4, 16.0, 14.399])
    with driver.host_admission(clock=clock, sleep=clock.sleep,
                               sample=lambda: driver.cpu_admission(next(loads), 16)) as row:
        assert row['reason'] == 'ADMITTED' and row['cpu_threshold'] == .9
        assert row['waited_seconds'] == 60 and row['poll_count'] == 4
        assert row['lock_poll_count'] == 1 and row['load_poll_count'] == 3
        assert clock.sleeps == [30, 30]
        assert competing_lock(parent_lock)
        assert stat.S_IMODE(parent_lock.parent.stat().st_mode) == 0o700
        assert stat.S_IMODE(parent_lock.stat().st_mode) == 0o600
    assert not competing_lock(parent_lock)


def test_parent_load_timeout_retains_fields_and_exact_shared_budget(parent_lock):
    clock = ParentClock()
    capacity = driver.cpu_admission(16.0, 16)
    with pytest.raises(driver.AdmissionRefused) as refused:
        with driver.host_admission(clock=clock, sleep=clock.sleep, sample=lambda: capacity):
            pytest.fail('busy host must not admit')
    row = refused.value.receipt
    assert row['reason'] == 'NORMALIZED_LOAD_LIMIT'
    assert row['waited_seconds'] == 1800 and row['poll_count'] == 61
    assert row['lock_poll_count'] == 1 and row['load_poll_count'] == 60
    assert clock.sleeps == [30]*60
    assert all(row[k] == v for k, v in capacity.items())
    assert not competing_lock(parent_lock)


def test_parent_second_holder_waits_and_times_out_without_entering(parent_lock):
    first, second = ParentClock(), ParentClock()
    with driver.host_admission(clock=first, sleep=first.sleep,
                               sample=lambda: driver.cpu_admission(0, 16)):
        with pytest.raises(driver.AdmissionRefused) as refused:
            with driver.host_admission(clock=second, sleep=second.sleep,
                                       sample=lambda: pytest.fail('load sampled before lock')):
                pytest.fail('second holder entered')
        row = refused.value.receipt
        assert row['reason'] == 'HOST_LOCK_TIMEOUT'
        assert row['waited_seconds'] == 1800 and row['poll_count'] == 60
        assert row['load_poll_count'] == 0 and second.sleeps == [30]*60
        assert competing_lock(parent_lock)
    assert not competing_lock(parent_lock)


def test_parent_lock_wait_can_finish_then_use_only_remaining_load_budget(parent_lock):
    import os
    import fcntl
    parent_lock.parent.mkdir()
    held = [os.open(parent_lock, os.O_CREAT | os.O_RDWR, 0o600)]
    fcntl.flock(held[0], fcntl.LOCK_EX | fcntl.LOCK_NB)

    def release(now):
        if now == 600:
            os.close(held.pop())

    clock = ParentClock(release)
    try:
        with pytest.raises(driver.AdmissionRefused) as refused:
            with driver.host_admission(clock=clock, sleep=clock.sleep,
                                       sample=lambda: driver.cpu_admission(16, 16)):
                pytest.fail('lock wait must not reset the load deadline')
        row = refused.value.receipt
        assert row['reason'] == 'NORMALIZED_LOAD_LIMIT' and row['waited_seconds'] == 1800
        assert row['lock_poll_count'] == 21 and row['load_poll_count'] == 40
        assert clock.sleeps == [30]*60
    finally:
        for fd in held:
            os.close(fd)
    assert not competing_lock(parent_lock)


def test_parent_second_holder_can_admit_after_first_releases(parent_lock):
    import os
    import fcntl
    parent_lock.parent.mkdir()
    held = os.open(parent_lock, os.O_CREAT | os.O_RDWR, 0o600)
    fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
    clock = ParentClock(lambda now: os.close(held))
    with driver.host_admission(clock=clock, sleep=clock.sleep,
                               sample=lambda: driver.cpu_admission(0, 16)) as row:
        assert row['waited_seconds'] == 30 and row['lock_poll_count'] == 2
        assert clock.sleeps == [30] and competing_lock(parent_lock)
    assert not competing_lock(parent_lock)


def test_parent_lock_release_on_exception(parent_lock):
    clock = ParentClock()
    with pytest.raises(RuntimeError, match='invented child error'):
        with driver.host_admission(clock=clock, sleep=clock.sleep,
                                   sample=lambda: driver.cpu_admission(0, 16)):
            assert competing_lock(parent_lock)
            raise RuntimeError('invented child error')
    assert not competing_lock(parent_lock)


@pytest.fixture
def parent_run(tmp_path, monkeypatch, parent_lock):
    clock = ParentClock()
    monkeypatch.setattr(driver.time, 'monotonic', clock)
    monkeypatch.setattr(driver.time, 'sleep', clock.sleep)
    monkeypatch.setattr(driver, 'sample_cpu_capacity', lambda: driver.cpu_admission(0, 16))
    original_read = driver.Path.read_text

    def meminfo(path, *args, **kwargs):
        if str(path) == '/proc/meminfo':
            return 'MemAvailable: 8388608 kB\n'
        return original_read(path, *args, **kwargs)

    monkeypatch.setattr(driver.Path, 'read_text', meminfo)
    pair = tmp_path/'heads.json'
    pair.write_text(json.dumps(valid_heads()))
    output = tmp_path/'parent-output'
    output.mkdir()
    return pair, output, clock


def test_parent_keeps_lock_across_seven_original_children_and_caps(parent_run, parent_lock, monkeypatch):
    from types import SimpleNamespace
    pair, output, clock = parent_run
    calls = []

    def child(command, stream, budget, lock_fd):
        assert competing_lock(parent_lock), 'whole-job lock must still be held'
        batch = command[command.index('--batch')+1]
        assert budget == driver.batch_wall_budget(batch)
        assert command[command.index('--lock-fd')+1] == str(lock_fd)
        assert '--parent' not in command
        assert command[1:3] == ['-I', '-B']
        assert command[command.index('--pair')+1] == str(pair)
        assert command[command.index('--output')+1] == str(output/batch)
        assert command[command.index('--expected-rules')+1] == 'sha256:'+'a'*64
        calls.append(batch)
        stream.write('invented child passed\n')
        return 0

    monkeypatch.setattr(driver, 'parent_child', child)
    assert driver.run_parent(pair, output, 'sha256:'+'a'*64) == 0
    assert calls == list(driver.BATCH_ORDER) and len(set(calls)) == 7
    assert not competing_lock(parent_lock) and clock.sleeps == []
    report = json.loads((output/'PARENT-RESULT.json').read_text())
    assert report['exit_code'] == 0 and report['host_lock_held_through_children'] is True
    assert [r['batch'] for r in report['batches']] == calls


@pytest.mark.parametrize('failure,expected', [('exit', 95), ('timeout', 124), ('signal', 137), ('exception', None)])
def test_parent_stops_once_and_releases_after_child_failure(parent_run, parent_lock, monkeypatch, failure, expected):
    from types import SimpleNamespace
    pair, output, clock = parent_run
    calls = []

    def child(command, stream, budget, lock_fd):
        assert competing_lock(parent_lock)
        calls.append(command[command.index('--batch')+1])
        stream.write('saved partial invented output\n')
        if failure == 'exception':
            raise OSError('invented child spawn failure')
        if failure == 'timeout':
            return 124
        return 137 if failure == 'signal' else 95

    monkeypatch.setattr(driver, 'parent_child', child)
    if failure == 'exception':
        with pytest.raises(OSError, match='invented child spawn failure'):
            driver.run_parent(pair, output)
    else:
        assert driver.run_parent(pair, output) == expected
    assert calls == ['driver'] and not competing_lock(parent_lock)
    assert (output/'PARENT-driver.log').read_text() == 'saved partial invented output\n'


@pytest.mark.parametrize('failure', ['mkdir', 'open', 'flock', 'symlink'])
def test_parent_lock_unavailable_refuses_named97_without_any_child(parent_run, parent_lock, monkeypatch, failure, capsys):
    import errno
    pair, output, clock = parent_run
    monkeypatch.setattr(driver, 'parent_child', lambda *a, **k: pytest.fail('no child without host lock'))

    def denied(*args, **kwargs):
        raise PermissionError(errno.EACCES, 'invented unwritable lock path')

    if failure == 'mkdir':
        original = driver.Path.mkdir
        monkeypatch.setattr(driver.Path, 'mkdir', lambda path, *a, **k: denied() if path == parent_lock.parent else original(path, *a, **k))
    elif failure == 'open':
        original = driver.os.open
        monkeypatch.setattr(driver.os, 'open', lambda path, *a, **k: denied() if path == parent_lock else original(path, *a, **k))
    elif failure == 'flock':
        monkeypatch.setattr(driver.fcntl, 'flock', denied)
    else:
        parent_lock.parent.mkdir()
        target = parent_lock.parent/'retained'
        target.write_text('unchanged')
        parent_lock.symlink_to(target)
    assert driver.run_parent(pair, output) == 97
    receipt = json.loads((output/'PARENT-ADMISSION.json').read_text())
    assert receipt['reason'] == 'HOST_LOCK_UNAVAILABLE'
    assert receipt['exit_code'] == 97 and receipt['waited_seconds'] == 0
    assert len([l for l in capsys.readouterr().out.splitlines() if l.startswith('CAPACITY_REFUSED ')]) == 1
    if failure == 'symlink':
        assert target.read_text() == 'unchanged'


@pytest.mark.parametrize('busy', ['load', 'lock'])
def test_parent_timeout_is97_and_never_dispatches(parent_run, parent_lock, monkeypatch, busy, capsys):
    import os
    import fcntl
    pair, output, clock = parent_run
    held = None
    if busy == 'lock':
        parent_lock.parent.mkdir()
        held = os.open(parent_lock, os.O_CREAT | os.O_RDWR, 0o600)
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
    else:
        monkeypatch.setattr(driver, 'sample_cpu_capacity', lambda: driver.cpu_admission(16, 16))
    monkeypatch.setattr(driver, 'parent_child', lambda *a, **k: pytest.fail('busy host dispatched'))
    try:
        assert driver.run_parent(pair, output) == 97
        receipt = json.loads((output/'PARENT-ADMISSION.json').read_text())
        assert receipt['reason'] == ('HOST_LOCK_TIMEOUT' if busy == 'lock' else 'NORMALIZED_LOAD_LIMIT')
        assert receipt['waited_seconds'] == 1800 and clock.sleeps == [30]*60
        assert 'CAPACITY_REFUSED ' in capsys.readouterr().out
    finally:
        if held is not None:
            os.close(held)


def test_parent_cli_dispatch_is_explicit_and_mutually_exclusive(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(driver, 'run_parent', lambda *args: calls.append(args) or 0)
    monkeypatch.setattr(driver.sys, 'argv', ['driver', '--parent', '--pair', 'p', '--output', 'o'])
    assert driver.main() == 0 and calls == [('p', 'o', None)]
    for extras in [ ['--batch', 'driver'], ['--shard-index', '0'], ['--wall-budget', 'driver'],
                    ['--check-headroom', str(tmp_path)], ['--lock-path', '/tmp/bypass'] ]:
        monkeypatch.setattr(driver.sys, 'argv', ['driver', '--parent', '--pair', 'p', '--output', 'o', *extras])
        with pytest.raises(SystemExit) as refused:
            driver.main()
        assert refused.value.code == 2
    assert len(calls) == 1


def test_parent_refuses_reused_evidence_before_lock_or_dispatch(parent_run, monkeypatch):
    pair, output, clock = parent_run
    (output/'scenario').mkdir()
    monkeypatch.setattr(driver, 'host_admission', lambda **kw: pytest.fail('existing output reached lock'))
    with pytest.raises(ValueError, match='fresh evidence root'):
        driver.run_parent(pair, output)


@pytest.mark.parametrize('outcome,expected', [('ok', 0), ('refusal', 97), ('signal', 137),
                                             ('timeout', 124), ('gone-group', 0), ('exception', None)])
def test_parent_child_stops_entire_owned_group_before_lock_release(
        tmp_path, parent_lock, monkeypatch, outcome, expected):
    events = []
    clock = ParentClock()

    class Child:
        pid = 123456

        def __enter__(self):
            return self

        def __exit__(self, *args):
            events.append('exit-context')

        def wait(self, timeout=None):
            assert competing_lock(parent_lock)
            events.append(('wait', timeout))
            if timeout == 480:
                if outcome == 'timeout':
                    raise driver.subprocess.TimeoutExpired(['invented'], timeout)
                if outcome == 'exception':
                    raise RuntimeError('invented wait error')
            return {'signal': -9, 'refusal': 97}.get(outcome, 0)

    def popen(command, **kwargs):
        assert command == ['invented'] and kwargs == {
            'cwd': driver.REPO, 'stdout': stream, 'stderr': driver.subprocess.STDOUT,
            'start_new_session': True, 'pass_fds': (admission['lock_fd'],)}
        assert competing_lock(parent_lock)
        events.append('new-group')
        return Child()

    def kill(group, sig):
        assert competing_lock(parent_lock)
        assert group == Child.pid and sig in (driver.signal.SIGTERM, driver.signal.SIGKILL)
        events.append(('kill-owned-group', sig))
        if outcome == 'gone-group':
            raise ProcessLookupError('already stopped')

    monkeypatch.setattr(driver.subprocess, 'Popen', popen)
    monkeypatch.setattr(driver.os, 'killpg', kill)
    with (tmp_path/'child.log').open('x') as stream:
        with driver.host_admission(clock=clock, sleep=clock.sleep,
                                   sample=lambda: driver.cpu_admission(0, 16)) as admission:
            if outcome == 'exception':
                with pytest.raises(RuntimeError, match='invented wait error'):
                    driver.parent_child(['invented'], stream, 480, admission['lock_fd'])
            else:
                assert driver.parent_child(['invented'], stream, 480, admission['lock_fd']) == expected
            assert competing_lock(parent_lock)
    assert events == ['new-group', ('wait', 480), ('kill-owned-group', driver.signal.SIGTERM), ('wait', 2), ('kill-owned-group', driver.signal.SIGKILL), ('wait', None)]
    assert not competing_lock(parent_lock)


@pytest.mark.parametrize('sig', [driver.signal.SIGTERM, driver.signal.SIGINT])
@pytest.mark.parametrize('phase', ['wait', 'spawn-pending'])
def test_parent_cancellation_unwinds_owned_child_before_unlock(parent_run, parent_lock, monkeypatch, sig, phase):
    pair, output, _ = parent_run
    original_handlers = {s: driver.signal.getsignal(s) for s in driver.PARENT_SIGNALS}
    original_mask = driver.signal.pthread_sigmask(driver.signal.SIG_BLOCK, [])
    events = []
    pending = []
    original_mask_call = driver.signal.pthread_sigmask

    class Child:
        pid = 123456

        def wait(self, timeout=None):
            assert competing_lock(parent_lock)
            if timeout == 240:
                driver.signal.getsignal(sig)(sig, None)
            events.append('grace-reaped' if timeout == 2 else 'reaped')
            return -9

    def popen(*args, **kwargs):
        assert competing_lock(parent_lock)
        assert set(driver.PARENT_SIGNALS) <= set(original_mask_call(driver.signal.SIG_BLOCK, []))
        events.append('spawned')
        if phase == 'spawn-pending':
            pending.append(sig)
        return Child()

    def mask(how, values):
        result = original_mask_call(how, values)
        if how == driver.signal.SIG_SETMASK and pending:
            driver.signal.getsignal(pending.pop())(sig, None)
        return result

    def kill(pid, signum):
        assert pid == Child.pid and signum in (driver.signal.SIGTERM, driver.signal.SIGKILL)
        assert competing_lock(parent_lock)
        assert all(driver.signal.getsignal(s) == driver.signal.SIG_IGN for s in driver.PARENT_SIGNALS)
        events.append(('killed-under-lock', signum))

    monkeypatch.setattr(driver.subprocess, 'Popen', popen)
    monkeypatch.setattr(driver.os, 'killpg', kill)
    monkeypatch.setattr(driver.signal, 'pthread_sigmask', mask)
    assert driver.run_parent(pair, output) == 128+sig
    assert events == ['spawned', ('killed-under-lock', driver.signal.SIGTERM), 'grace-reaped', ('killed-under-lock', driver.signal.SIGKILL), 'reaped']
    assert not competing_lock(parent_lock)
    assert {s: driver.signal.getsignal(s) for s in driver.PARENT_SIGNALS} == original_handlers
    assert original_mask_call(driver.signal.SIG_BLOCK, []) == original_mask
    row = json.loads((output/'PARENT-CANCELLATION.json').read_text())
    assert row['reason'] == 'PARENT_CANCELLED' and row['signal'] == sig and row['exit_code'] == 128+sig
    assert row['owned_child_cleanup_finished'] is True and row['completed_batches'] == []


def test_inherited_lease_outlives_parent_descriptor(parent_lock):
    import os
    clock = ParentClock()
    duplicate = None
    try:
        with driver.host_admission(clock=clock, sleep=clock.sleep,
                                   sample=lambda: driver.cpu_admission(0, 16)) as admission:
            duplicate = os.dup(admission['lock_fd'])
            assert driver.verify_host_lease(duplicate) == duplicate
        assert competing_lock(parent_lock), 'closing only the parent must retain the shared lease'
    finally:
        if duplicate is not None:
            os.close(duplicate)
    assert not competing_lock(parent_lock)


@pytest.mark.parametrize('fd', [-1, True, '3'])
def test_internal_lease_refuses_non_descriptor(parent_lock, fd):
    with pytest.raises(ValueError, match='CI_HOST_LEASE: invalid descriptor'):
        driver.verify_host_lease(fd)


def test_internal_lease_refuses_foreign_inode(tmp_path, parent_lock):
    parent_lock.parent.mkdir()
    parent_lock.write_text('')
    with (tmp_path/'foreign').open('w') as stream:
        with pytest.raises(ValueError, match='CI_HOST_LEASE: lock inode differs'):
            driver.verify_host_lease(stream.fileno())


def test_shards_inherit_the_same_host_lease(capacity_run, parent_lock, monkeypatch):
    pair_file, output, pair, calls = _aggregate_with_fake_workers(capacity_run, monkeypatch, 'types-loader')
    worker = driver.subprocess.run
    forwarded = []
    clock = ParentClock()
    with driver.host_admission(clock=clock, sleep=clock.sleep,
                               sample=lambda: driver.cpu_admission(0, 16)) as admission:
        fd = admission['lock_fd']

        def invoke(command, **kwargs):
            assert kwargs['pass_fds'] == (fd,)
            assert command[command.index('--lock-fd')+1] == str(fd)
            assert competing_lock(parent_lock)
            forwarded.append(fd)
            return worker(command, **kwargs)

        monkeypatch.setattr(driver.subprocess, 'run', invoke)
        assert driver.run(pair_file, output, 'types-loader', pair['rules_sha256'], lock_fd=fd) == 0
        assert forwarded == [fd]*4 and calls == list(range(4))
    assert not competing_lock(parent_lock)


def test_internal_batch_cli_keeps_verified_lease(parent_lock, monkeypatch):
    calls = []
    clock = ParentClock()
    with driver.host_admission(clock=clock, sleep=clock.sleep,
                               sample=lambda: driver.cpu_admission(0, 16)) as admission:
        fd = admission['lock_fd']
        monkeypatch.setattr(driver, 'run', lambda *args: calls.append(args) or 0)
        monkeypatch.setattr(driver.sys, 'argv', ['driver', '--pair', 'p', '--output', 'o',
                                                '--batch', 'scenario', '--lock-fd', str(fd)])
        assert driver.main() == 0 and calls == [('p', 'o', 'scenario', None, None, fd)]
        assert competing_lock(parent_lock)


def test_parent_fixture_never_opens_live_meminfo(parent_run, monkeypatch):
    pair, output, _ = parent_run
    import builtins

    def refuse_live_proc(original):
        def guarded(path, *args, **kwargs):
            if str(path) == '/proc/meminfo':
                pytest.fail('invented parent fixture must not open live meminfo')
            return original(path, *args, **kwargs)
        return guarded

    monkeypatch.setattr(driver.io, 'open', refuse_live_proc(driver.io.open))
    monkeypatch.setattr(builtins, 'open', refuse_live_proc(builtins.open))
    monkeypatch.setattr(driver, 'parent_child', lambda *args: 0)
    assert driver.run_parent(pair, output) == 0
    receipt = json.loads((output/'PARENT-ADMISSION.json').read_text())
    assert receipt['memory_available'] == 8*1024**3


def test_admission_final_sleep_uses_remaining_deadline(parent_lock):
    clock = ParentClock()

    def slow_sample():
        clock.now += 1795
        return driver.cpu_admission(16, 16)

    with pytest.raises(driver.AdmissionRefused) as refused:
        with driver.host_admission(clock=clock, sleep=clock.sleep, sample=slow_sample):
            pytest.fail('busy host admitted')
    assert clock.sleeps == [5]
    assert refused.value.receipt['waited_seconds'] == 1800
    assert refused.value.receipt['reason'] == 'NORMALIZED_LOAD_LIMIT'


def test_lock_wait_stdout_names_host_lock_reason(parent_lock, capsys):
    import os
    import fcntl
    parent_lock.parent.mkdir()
    held = [os.open(parent_lock, os.O_CREAT | os.O_RDWR, 0o600)]
    fcntl.flock(held[0], fcntl.LOCK_EX | fcntl.LOCK_NB)
    clock = ParentClock(lambda now: os.close(held.pop()))
    try:
        with driver.host_admission(clock=clock, sleep=clock.sleep,
                                   sample=lambda: driver.cpu_admission(0, 16)):
            rows = [json.loads(line[len('PARENT_WAIT '):]) for line in capsys.readouterr().out.splitlines()
                    if line.startswith('PARENT_WAIT ')]
            assert len(rows) == 1 and rows[0]['reason'] == 'HOST_LOCK_TIMEOUT'
            assert rows[0]['lock_poll_count'] == 1 and rows[0]['load_poll_count'] == 0
            assert clock.sleeps == [30]
    finally:
        for fd in held:
            os.close(fd)


def test_host_lease_refuses_second_description_of_locked_inode(parent_lock):
    import os
    clock = ParentClock()
    with driver.host_admission(clock=clock, sleep=clock.sleep,
                               sample=lambda: driver.cpu_admission(0, 16)):
        second = os.open(parent_lock, os.O_RDWR)
        try:
            with pytest.raises(ValueError, match='CI_HOST_LEASE: descriptor unavailable'):
                driver.verify_host_lease(second)
        finally:
            os.close(second)
        assert competing_lock(parent_lock)


def test_batch_main_refuses_invalid_lease_before_run(monkeypatch):
    calls = []
    monkeypatch.setattr(driver, 'run', lambda *args: calls.append(args) or 0)
    monkeypatch.setattr(driver.sys, 'argv', ['driver', '--pair', 'p', '--output', 'o',
                                            '--batch', 'scenario', '--lock-fd', '-1'])
    with pytest.raises(ValueError, match='CI_HOST_LEASE: invalid descriptor'):
        driver.main()
    assert calls == []


def test_verified_lease_unblocks_both_cancellation_signals(parent_lock):
    previous_mask = driver.signal.pthread_sigmask(driver.signal.SIG_BLOCK, driver.PARENT_SIGNALS)
    clock = ParentClock()
    try:
        assert set(driver.PARENT_SIGNALS) <= driver.signal.pthread_sigmask(driver.signal.SIG_BLOCK, [])
        with driver.host_admission(clock=clock, sleep=clock.sleep,
                                   sample=lambda: driver.cpu_admission(0, 16)) as admission:
            assert driver.verify_host_lease(admission['lock_fd']) == admission['lock_fd']
            after = driver.signal.pthread_sigmask(driver.signal.SIG_BLOCK, [])
            assert not set(driver.PARENT_SIGNALS).intersection(after)
    finally:
        driver.signal.pthread_sigmask(driver.signal.SIG_SETMASK, previous_mask)


def test_parent_cli_refuses_internal_lock_descriptor(monkeypatch):
    calls = []
    monkeypatch.setattr(driver, 'run_parent', lambda *args: calls.append(args) or 0)
    monkeypatch.setattr(driver.sys, 'argv', ['driver', '--parent', '--pair', 'p', '--output', 'o',
                                            '--lock-fd', '7'])
    with pytest.raises(SystemExit) as refused:
        driver.main()
    assert refused.value.code == 2 and calls == []


def _large_log_record():
    return 'GUARDS ' + json.dumps({'test_costs': [
        ['invented-' + str(i) + '-' + 'x' * 180, 0.01, 0.0, 0.02]
        for i in range(400)]})


def _chunk_rows():
    return [json.loads(line.removeprefix('CI_LOG_CHUNK '))
            for line in driver.log_frames(_large_log_record())]


def _chunk_lines(rows):
    return ['CI_LOG_CHUNK ' + json.dumps(row) for row in rows]


def test_log_chunks_over_64k_roundtrip_all_payload_bytes():
    import hashlib
    original = _large_log_record()
    assert len(original.encode()) > 64 * 1024
    lines = driver.log_frames(original)
    assert len(lines) > 1
    assert all(len(line.encode()) <= driver.LOG_LINE_BYTES < 64 * 1024 for line in lines)
    rows = _chunk_rows()
    assert [row['index'] for row in rows] == list(range(len(rows)))
    assert all(row['count'] == len(rows) and row['bytes'] == len(original.encode())
               and row['sha256'] == 'sha256:' + hashlib.sha256(original.encode()).hexdigest()
               for row in rows)
    assert list(driver.reassemble_log_lines(lines)) == [original]


def test_log_chunks_refuse_missing_chunk():
    with pytest.raises(ValueError, match='^CI_LOG_CHUNK: missing chunks$'):
        list(driver.reassemble_log_lines(driver.log_frames(_large_log_record())[:-1]))


def test_log_chunks_refuse_short_chunk():
    import base64
    rows = _chunk_rows()
    raw = base64.b64decode(rows[0]['data'])
    rows[0]['data'] = base64.b64encode(raw[:-1]).decode()
    # Keep the complete payload/hash valid: only the prescribed chunk boundaries differ.
    rows[1]['data'] = base64.b64encode(raw[-1:] + base64.b64decode(rows[1]['data'])).decode()
    with pytest.raises(ValueError, match='^CI_LOG_CHUNK: chunk length differs$'):
        list(driver.reassemble_log_lines(_chunk_lines(rows)))


def test_log_chunks_refuse_truncated_json_chunk():
    lines = driver.log_frames(_large_log_record())
    lines[1] = lines[1][:-11]
    with pytest.raises(ValueError, match='^CI_LOG_CHUNK: malformed chunk$'):
        list(driver.reassemble_log_lines(lines))


def test_log_chunks_refuse_sha_mismatch():
    rows = _chunk_rows()
    for row in rows:
        row['sha256'] = 'sha256:' + '0' * 64
    with pytest.raises(ValueError, match='^CI_LOG_CHUNK: sha256 differs$'):
        list(driver.reassemble_log_lines(_chunk_lines(rows)))


def test_log_chunks_refuse_count_mismatch():
    rows = _chunk_rows()
    for row in rows:
        row['count'] += 1
    with pytest.raises(ValueError, match='^CI_LOG_CHUNK: count differs$'):
        list(driver.reassemble_log_lines(_chunk_lines(rows)))


def test_log_chunks_refuse_duplicate_index():
    rows = _chunk_rows()
    rows[2]['index'] = rows[1]['index']  # Payload bytes/order/hash remain exact.
    with pytest.raises(ValueError, match='^CI_LOG_CHUNK: index differs$'):
        list(driver.reassemble_log_lines(_chunk_lines(rows)))


@pytest.mark.parametrize('mutation', ['out-of-order', 'changed-route', 'changed-sha',
                                      'boolean-index', 'unknown-format', 'foreign-key', 'bad-base64'])
def test_log_chunk_metadata_faults_refuse(mutation):
    rows = _chunk_rows()
    route = ''
    if mutation == 'out-of-order': rows[0], rows[1] = rows[1], rows[0]
    elif mutation == 'changed-route': route = 'SHARD epoch2/0 '
    elif mutation == 'changed-sha': rows[1]['sha256'] = 'sha256:' + '0' * 64
    elif mutation == 'boolean-index': rows[0]['index'] = False
    elif mutation == 'unknown-format': rows[0]['format'] = 'unknown'
    elif mutation == 'foreign-key': rows[0]['foreign'] = 1
    elif mutation == 'bad-base64': rows[0]['data'] = '!'
    lines = _chunk_lines(rows)
    if route: lines[1] = route + lines[1]
    with pytest.raises(ValueError, match='^CI_LOG_CHUNK:'):
        list(driver.reassemble_log_lines(lines))


def test_log_chunks_preserve_shard_routes_timestamps_and_legacy_lines():
    original = _large_log_record()
    framed = ['2026-11-02T00:00:00.1234567Z SHARD epoch2/15 ' + line
              for line in driver.log_frames(original)]
    legacy = ['CAPACITY {"invented": true}', 'plain readable pytest line']
    assert list(driver.reassemble_log_lines([legacy[0], *framed, legacy[1]], timestamped=True)) == [
        legacy[0], 'SHARD epoch2/15 ' + original, legacy[1]]
    assert list(driver.reassemble_log_lines([original])) == [original]  # Complete old record.


def test_plain_output_continuations_stay_readable_and_roundtrip_unicode():
    text = 'Readable invented output: alpha, square, λ / ◇ / 🟣. ' * 4000
    lines = driver.log_frames(text)
    assert len(text.encode()) > 64 * 1024
    assert all(line.startswith('CI_LOG_CONT ') and 'CI_LOG_CHUNK' not in line for line in lines)
    assert all(len(line.encode()) <= driver.LOG_LINE_BYTES for line in lines)
    assert 'Readable invented output:' in lines[0] and 'λ' in lines[0]
    assert list(driver.reassemble_log_lines(lines)) == [text]


def test_plain_continuations_refuse_a_dropped_piece():
    lines = driver.log_frames('readable glyph ' * 10000)
    with pytest.raises(ValueError, match='^CI_LOG_CHUNK: missing chunks$'):
        list(driver.reassemble_log_lines(lines[:-1]))


def test_main_python_stdout_and_stderr_are_readable_bounded_text(monkeypatch, capsys):
    import sys
    text = 'Readable traceback context ' * 4000
    def fake_parent(*args):
        print(text)
        print(text, file=sys.stderr)
        return 0
    monkeypatch.setattr(driver, 'run_parent', fake_parent)
    monkeypatch.setattr(sys, 'argv', ['driver', '--parent', '--pair', 'invented', '--output', 'invented'])
    assert driver.main() == 0
    captured = capsys.readouterr()
    for output in (captured.out, captured.err):
        lines = output.splitlines()
        assert all(line.startswith('CI_LOG_CONT ') for line in lines)
        assert all(len(line.encode()) <= driver.LOG_LINE_BYTES for line in lines)
        assert list(driver.reassemble_log_lines(lines)) == [text]


def test_public_guard_record_uses_chunk_transport(capacity_run, monkeypatch, capsys):
    from types import SimpleNamespace
    original_dumps = driver.json.dumps
    wire = []
    def large_guard(value, *args, **kwargs):
        text = original_dumps(value, *args, **kwargs)
        if isinstance(value, dict) and 'test_costs' in value and 'source_pins_exact' in value:
            text += ' ' * 100000  # Valid invented JSON whitespace; values unchanged.
        return text
    class Capture:
        def readouterr(self):
            captured = capsys.readouterr()
            lines = captured.out.splitlines()
            wire.extend(lines)
            return SimpleNamespace(out='\n'.join(driver.reassemble_log_lines(lines)) + '\n', err=captured.err)
    monkeypatch.setattr(driver.json, 'dumps', large_guard)
    _exercise_public_batch(capacity_run, monkeypatch, Capture(), False, 'driver')
    assert any(line.startswith('CI_LOG_CHUNK ') for line in wire)
    assert all(len(line.encode()) <= driver.LOG_LINE_BYTES for line in wire)


def test_shard_child_plain_output_is_wrapped_without_base64(capacity_run, monkeypatch, capsys):
    pair, output, _, _ = _aggregate_with_fake_workers(capacity_run, monkeypatch, 'types-loader')
    original_worker = driver.subprocess.run
    text = 'Readable child output ' * 4000
    def fake_worker(command, **kwargs):
        result = original_worker(command, **kwargs)
        kwargs['stdout'].write(text + '\n')
        return result
    monkeypatch.setattr(driver.subprocess, 'run', fake_worker)
    assert driver.run(pair, output, 'types-loader') == 0
    lines = capsys.readouterr().out.splitlines()
    assert any(line.startswith('CI_LOG_CONT ') for line in lines)
    assert all(len(line.encode()) <= driver.LOG_LINE_BYTES for line in lines)
    restored = list(driver.reassemble_log_lines(lines))
    assert all('SHARD types-loader/' + str(index) + ' ' + text in restored for index in range(4))


def test_log_chunks_refuse_lost_payload_byte():
    import base64
    rows = _chunk_rows()
    rows[0]['data'] = base64.b64encode(base64.b64decode(rows[0]['data'])[:-1]).decode()
    with pytest.raises(ValueError, match='^CI_LOG_CHUNK: chunk length differs$'):
        list(driver.reassemble_log_lines(_chunk_lines(rows)))


def test_plain_dates_are_preserved_without_timestamped_mode():
    text = '2026-11-02T00:00:00Z Readable original timestamp'
    assert list(driver.reassemble_log_lines(driver.log_frames(text))) == [text]


@pytest.mark.parametrize('kind', ['GUARDS', 'HEADROOM', 'CAPACITY', 'CAPACITY_REFUSED',
                                  'PARENT_WAIT', 'PARENT_ADMISSION', 'PARENT_CANCELLED',
                                  'EXACT_PAIR', 'SCENARIO'])
def test_log_chunking_covers_each_structured_record_kind(kind):
    payload = json.loads(_large_log_record().partition(' ')[2])
    if kind == 'HEADROOM': payload = payload['test_costs']
    text = kind + ' ' + json.dumps(payload)
    lines = driver.log_frames(text)
    assert len(text.encode()) > 64 * 1024
    assert all(line.startswith('CI_LOG_CHUNK ') for line in lines)
    assert all(len(line.encode()) <= driver.LOG_LINE_BYTES for line in lines)
    assert list(driver.reassemble_log_lines(lines)) == [text]


def test_lead_log_gap_D8_plain_line_interrupts_pending_record():
    lines = driver.log_frames(_large_log_record())
    assert list(driver.reassemble_log_lines(lines)) == [_large_log_record()]
    for foreign in ('readable interleaved output', 'CAPACITY {"invented":true}'):
        with pytest.raises(ValueError, match='^CI_LOG_CHUNK: missing chunks$'):
            list(driver.reassemble_log_lines([lines[0], foreign, *lines[1:]]))


def test_lead_log_gap_D10_duplicate_metadata_key_refuses():
    rows = _chunk_rows()
    for key, value in rows[0].items():
        lines = _chunk_lines(rows)
        lines[0] = lines[0][:-1] + ', ' + json.dumps(key) + ': ' + json.dumps(value) + '}'
        with pytest.raises(ValueError, match='^CI_LOG_CHUNK: malformed chunk$') as refused:
            list(driver.reassemble_log_lines(lines))
        assert str(refused.value.__cause__) == 'CI_LOG_CHUNK: duplicate metadata key'


def test_lead_log_gap_D11_reassembled_newline_refuses():
    import base64
    import hashlib
    raw = _large_log_record().encode()
    raw = raw[:10] + b'\n' + raw[11:]  # Same length, otherwise complete valid framing.
    rows = _chunk_rows()
    for row in rows:
        start = row['index'] * driver.LOG_CHUNK_BYTES
        row['data'] = base64.b64encode(raw[start:start + driver.LOG_CHUNK_BYTES]).decode()
        row['sha256'] = 'sha256:' + hashlib.sha256(raw).hexdigest()
    with pytest.raises(ValueError, match='^CI_LOG_CHUNK: multiline record$'):
        list(driver.reassemble_log_lines(_chunk_lines(rows)))


def test_lead_log_gap_D12_small_framed_record_refuses():
    import base64
    import hashlib
    minimal = b'GUARDS {"invented":true}'
    for size in (len(minimal), driver.LOG_LINE_BYTES):
        raw = minimal + b' ' * (size - len(minimal))
        pieces = [raw[i:i + driver.LOG_CHUNK_BYTES] for i in range(0, len(raw), driver.LOG_CHUNK_BYTES)]
        rows = [{'format': 'ohf-ci-log-chunk/1', 'index': i, 'count': len(pieces), 'bytes': len(raw),
                 'sha256': 'sha256:' + hashlib.sha256(raw).hexdigest(),
                 'data': base64.b64encode(piece).decode()} for i, piece in enumerate(pieces)]
        assert len(raw) <= driver.LOG_LINE_BYTES
        with pytest.raises(ValueError, match='^CI_LOG_CHUNK: invalid metadata$'):
            list(driver.reassemble_log_lines(_chunk_lines(rows)))


def test_lead_log_gap_D13_noncanonical_continuation_number_refuses():
    original = driver.log_frames('Readable continuation numbering ' * 4000)
    for field in ('index', 'count', 'bytes'):
        lines = list(original)
        parts = lines[1].split(' ', 4)
        index, count = parts[1].split('/')
        assert parts[0] == 'CI_LOG_CONT' and index == '1'
        if field == 'index': parts[1] = '0' + index + '/' + count
        elif field == 'count': parts[1] = index + '/0' + count
        else: parts[2] = '0' + parts[2]
        lines[1] = ' '.join(parts)
        with pytest.raises(ValueError, match='^CI_LOG_CHUNK: malformed continuation$'):
            list(driver.reassemble_log_lines(lines))


def test_lead_log_gap_D20_invalid_base64_characters_refuse():
    rows = _chunk_rows()
    rows[0]['data'] = rows[0]['data'][:8] + '!' + rows[0]['data'][8:]
    with pytest.raises(ValueError, match='^CI_LOG_CHUNK: invalid encoding$'):
        list(driver.reassemble_log_lines(_chunk_lines(rows)))


def test_lead_log_gap_D16_unterminated_output_tail_is_emitted(capsys):
    import sys
    large_tail = 'Readable final stderr tail: λ / 🟣 ' * 2400
    assert len(large_tail.encode()) > 64 * 1024
    with driver.bounded_log_output():
        print('complete readable line')
        sys.stdout.write('final stdout tail without newline')
        sys.stderr.write(large_tail)
    captured = capsys.readouterr()
    assert captured.out == 'complete readable line\nfinal stdout tail without newline\n'
    lines = captured.err.splitlines()
    assert lines and all(line.startswith('CI_LOG_CONT ') for line in lines)
    assert all(len(line.encode()) <= driver.LOG_LINE_BYTES for line in lines)
    assert list(driver.reassemble_log_lines(lines)) == [large_tail]


def test_lead_log_gap_D18_parent_relays_oversized_child_lines_readably(
        parent_run, monkeypatch, capsys):
    pair, output, _ = parent_run
    text = 'Readable oversized parent child output ' * 2400
    expected = [text + batch for batch in driver.BATCH_ORDER]
    calls = []
    def child(command, stream, budget, lock_fd):
        batch = command[command.index('--batch') + 1]
        calls.append(batch)
        stream.write(text + batch + '\n')
        return 0
    monkeypatch.setattr(driver, 'parent_child', child)
    assert driver.run_parent(pair, output) == 0
    assert calls == list(driver.BATCH_ORDER)
    lines = capsys.readouterr().out.splitlines()
    assert all(len(line.encode()) <= driver.LOG_LINE_BYTES for line in lines)
    assert any(line.startswith('CI_LOG_CONT ') for line in lines)
    assert not any(line.startswith('CI_LOG_CHUNK ') for line in lines)
    restored = list(driver.reassemble_log_lines(lines))
    assert all(restored.count(line) == 1 for line in expected)
    for batch, line in zip(driver.BATCH_ORDER, expected):
        assert (output / ('PARENT-' + batch + '.log')).read_text() == line + '\n'


@pytest.mark.parametrize('batch,index,count', [
    (batch, index, count)
    for batch, count in [('schema-context', 4), ('proofs-history', 4),
                         ('types-loader', 4), ('epoch2', 16)]
    for index in range(count)
])
@pytest.mark.parametrize('identity_field', [
    'result-index', 'collection-batch', 'collection-index', 'collection-count',
])
def test_aggregate_refuses_each_child_shard_identity_before_accepting_receipt(
        capacity_run, monkeypatch, batch, index, count, identity_field):
    assert driver.SHARD_COUNTS[batch] == count
    pair, output, _, calls = _aggregate_with_fake_workers(capacity_run, monkeypatch, batch)
    filename = 'RESULT.json' if identity_field == 'result-index' else 'COLLECTION.json'
    target = output / 'shards' / str(index) / filename
    original_write = driver.Path.write_text
    changed = []

    def mismatched_child(path, text, *args, **kwargs):
        if path == target:
            before = json.loads(text)
            row = json.loads(text)
            if identity_field == 'result-index':
                assert row['shard_index'] == index
                row['shard_index'] = (index + 1) % count
                inverse = {**row, 'shard_index': index}
            else:
                assert row['shard'] == [batch, index, count]
                component = {'collection-batch': 0, 'collection-index': 1,
                             'collection-count': 2}[identity_field]
                row['shard'][component] = ('io', (index + 1) % count, count + 1)[component]
                inverse = {**row, 'shard': [batch, index, count]}
            assert inverse == before  # Pair, pins, costs and census stay valid.
            changed.append(identity_field)
            text = json.dumps(row)
        return original_write(path, text, *args, **kwargs)

    monkeypatch.setattr(driver.Path, 'write_text', mismatched_child)
    with pytest.raises(ValueError, match='^CI_SHARD: child identity, source, guard or pin differs$'):
        driver.run(pair, output, batch)
    assert changed == [identity_field]
    assert calls == list(range(index + 1))
    result = json.loads((output / 'RESULT.json').read_bytes())
    assert result['exit_code'] == 1
    assert len(result['shards']) == index  # The bad child was not accepted.
    assert result['source_pins_exact'] is True and result['guard_violations'] == []
    assert not (output / 'COLLECTION.json').exists()
