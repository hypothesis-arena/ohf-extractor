"""Bounded local CI batches for an explicitly verified extractor/standard pair.

The trusted workflow checks Git heads and trees before calling this driver.
No checker, fetcher, provider or product CLI is dispatched here.
"""
import argparse
import base64
import builtins
from contextlib import contextmanager, redirect_stdout, redirect_stderr
import datetime
import fcntl
import hashlib
import http.client
import io
import json
import math
import os
from pathlib import Path
import re
import resource
import shutil
import signal
import socket
import ssl
import stat
import subprocess
import sys
import threading
import tempfile
import time
import urllib.request

REPO = Path(__file__).resolve().parents[2]
BOOTSTRAP_PINS = {
    'tools/__init__.py': 'sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
    'examples/cards/ENTAILMENT-PROMPT.md': 'sha256:46716d7b4fc070b952d7ace5ae597c64b9414e63b15e38a94e719a2eb4fae146',
}
HEAD_KEYS = {'extractor_commit', 'extractor_tree', 'standard_commit', 'standard_tree'}
LEGACY_BATCHES = {
    'schema-context': ['scripts/tests/test_native_profile.py', 'scripts/tests/test_child_sourced_lists142.py', '-k',
                       'full_schema_constraints or current_conditions or card_only_references or child_sourced'],
    'proofs-history': ['scripts/tests/test_native_profile.py', '-k',
                       'proof_roster_and_legacy or actual_frozen_wrong or worst_history or missing_binding or unsupported_scientific'],
    'types-loader': ['scripts/tests/test_native_profile.py', '-k',
                    'json_types or requires_integer_epoch or missing_unknown_and_stale_profile or pinned_source_namespace or fixture_is_full or positive_single or bare_normative'],
    'epoch2': ['scripts/tests/test_native_profile14.py'],
    'io': ['scripts/tests/test_projection_adapter.py', 'scripts/tests/test_checker_durability.py'],
    'driver': ['scripts/tests/test_native_profile_ci_driver.py'],
    'scenario': [],
}

SHARD_COUNT = 4
SHARDED = ('schema-context', 'proofs-history', 'types-loader', 'epoch2')
SHARD_COUNTS = {name: (16 if name == 'epoch2' else SHARD_COUNT) for name in SHARDED}
# Preserve the accepted outer batch budgets independently of the partition size.
AGGREGATE_WALL_BUDGETS = {'schema-context': 480, 'proofs-history': 480,
                          'types-loader': 480, 'epoch2': 960}
BATCH_ORDER = ('driver', *SHARDED, 'io', 'scenario')
SHARDS = {f'{name}-{index}': (name, index, SHARD_COUNTS[name])
          for name in SHARDED for index in range(SHARD_COUNTS[name])}
BATCHES = {name: list(LEGACY_BATCHES[name]) for name in BATCH_ORDER}
# A CI receipt reader, separate from the production24/bootstrap2 closure.
RECEIPT_READER_PIN = ('tools/native_pair_validation.py',
    'sha256:a9ebf2bf3d4b74b3cf48882161a7aad846d2649114bfd2edae03ce0cb04ba7ee')
RELOCATION_MANIFEST_PIN = ('scripts/tests/native_profile_relocations-3.json',
    'sha256:df08a5e8f876618f65c4900019ecbbe788a6cd1cea5bebdb2d3dab86bb18c9bc')
HOST_LOCK = Path('/var/lib/forgejo-runner/locks/native-profile.lock')
ADMISSION_WAIT_SECONDS = 1800
ADMISSION_POLL_SECONDS = 30
PARENT_WALL_SECONDS = 5040


# The retained CI log path caps physical lines at64KiB (exact stage unknown).
# Structured records are framed; ordinary output uses readable continuations.
LOG_LINE_BYTES = 16 * 1024
LOG_CHUNK_BYTES = 4096
_LOG_LOCK = threading.RLock()
_JSON_LOG_NAMES = {'GUARDS', 'HEADROOM', 'CAPACITY', 'CAPACITY_REFUSED',
                   'PARENT_WAIT', 'PARENT_ADMISSION', 'PARENT_CANCELLED',
                   'EXACT_PAIR', 'SCENARIO'}


def log_frames(text):
    """Bound one logical UTF-8 line, preserving exact bytes behind its digest."""
    if type(text) is not str or '\n' in text:
        raise ValueError('CI_LOG_CHUNK: expected one text line')
    raw = text.encode('utf-8')
    if len(raw) <= LOG_LINE_BYTES:
        return [text]
    body = re.sub(r'^SHARD [a-z0-9-]+/[0-9]+ ', '', text)
    name, _, value = body.partition(' ')
    structured = name in _JSON_LOG_NAMES and value.startswith(('{', '['))
    if structured:
        try:
            json.loads(value)
        except ValueError:
            structured = False
    digest = 'sha256:' + hashlib.sha256(raw).hexdigest()
    if structured:
        pieces = [raw[i:i + LOG_CHUNK_BYTES] for i in range(0, len(raw), LOG_CHUNK_BYTES)]
        return ['CI_LOG_CHUNK ' + json.dumps({
            'format': 'ohf-ci-log-chunk/1', 'index': i, 'count': len(pieces),
            'bytes': len(raw), 'sha256': digest,
            'data': base64.b64encode(piece).decode('ascii')}, separators=(',', ':'))
                for i, piece in enumerate(pieces)]
    # Split only on code-point boundaries. The payload remains literal readable text.
    pieces = []
    while raw:
        end = min(len(raw), LOG_CHUNK_BYTES)
        while True:
            try:
                piece = raw[:end].decode('utf-8')
                break
            except UnicodeDecodeError:
                end -= 1
        pieces.append(piece)
        raw = raw[end:]
    size = len(text.encode('utf-8'))
    return [f'CI_LOG_CONT {i}/{len(pieces)} {size} {digest} {piece}'
            for i, piece in enumerate(pieces)]


def emit_log(*parts, flush=False, stream=None):
    """Use bounded physical lines for every driver record and forwarded child line."""
    with _LOG_LOCK:
        for line in ' '.join(str(part) for part in parts).split('\n'):
            for frame in log_frames(line):
                print(frame, file=stream, flush=flush)


def reassemble_log_lines(lines, *, timestamped=False):
    """Read old plain lines or complete frames; never return a partial framed record.

    Timestamps and the aggregate's SHARD prefix are transport context. No native
    code, file, subprocess or model is used. Consumers still validate their full
    expected record inventory and semantic contracts after this transport check.
    """
    pending, pieces, expected_index = None, [], 0
    def unique(pairs):
        obj = {}
        for key, value in pairs:
            if key in obj:
                raise ValueError('CI_LOG_CHUNK: duplicate metadata key')
            obj[key] = value
        return obj
    for line in lines:
        line = line.rstrip('\n')
        if timestamped:
            line = re.sub(r'^\d{4}-\d\d-\d\dT\S+Z\s?', '', line)
        match = re.match(r'^(SHARD [a-z0-9-]+/[0-9]+ )(.*)$', line)
        route, body = (match[1], match[2]) if match else ('', line)
        if body.startswith('CI_LOG_CHUNK'):
            try:
                row = json.loads(body[len('CI_LOG_CHUNK '):], object_pairs_hook=unique)
            except (ValueError, TypeError) as error:
                raise ValueError('CI_LOG_CHUNK: malformed chunk') from error
            if (type(row) is not dict or set(row) != {'format', 'index', 'count', 'bytes', 'sha256', 'data'}
                    or row['format'] != 'ohf-ci-log-chunk/1' or type(row['data']) is not str):
                raise ValueError('CI_LOG_CHUNK: malformed chunk')
            try:
                piece = base64.b64decode(row['data'], validate=True)
            except ValueError as error:
                raise ValueError('CI_LOG_CHUNK: invalid encoding') from error
            mode = 'structured'
        elif body.startswith('CI_LOG_CONT'):
            try:
                marker, position, size, digest, text = body.split(' ', 4)
                index, count = position.split('/')
                if marker != 'CI_LOG_CONT' or any(str(int(x)) != x for x in (index, count, size)):
                    raise ValueError('noncanonical number')
                row = {'index': int(index), 'count': int(count), 'bytes': int(size), 'sha256': digest}
                piece = text.encode('utf-8')
            except (ValueError, TypeError) as error:
                raise ValueError('CI_LOG_CHUNK: malformed continuation') from error
            mode = 'text'
        else:
            if pending is not None:
                raise ValueError('CI_LOG_CHUNK: missing chunks')
            yield line
            continue
        if (any(type(row[k]) is not int for k in ('index', 'count', 'bytes'))
                or row['bytes'] <= LOG_LINE_BYTES or row['count'] < 1
                or type(row['sha256']) is not str
                or not re.fullmatch(r'sha256:[0-9a-f]{64}', row['sha256'])):
            raise ValueError('CI_LOG_CHUNK: invalid metadata')
        if mode == 'structured' and row['count'] != (row['bytes'] + LOG_CHUNK_BYTES - 1) // LOG_CHUNK_BYTES:
            raise ValueError('CI_LOG_CHUNK: count differs')
        identity = (route, mode, row['count'], row['bytes'], row['sha256'])
        if pending is not None and identity != pending:
            raise ValueError('CI_LOG_CHUNK: metadata differs')
        if row['index'] != expected_index or row['index'] >= row['count']:
            raise ValueError('CI_LOG_CHUNK: index differs')
        expected_size = min(LOG_CHUNK_BYTES, row['bytes'] - row['index'] * LOG_CHUNK_BYTES)
        if (not 0 < len(piece) <= LOG_CHUNK_BYTES
                or mode == 'structured' and len(piece) != expected_size):
            raise ValueError('CI_LOG_CHUNK: chunk length differs')
        pending = identity
        pieces.append(piece)
        expected_index += 1
        if expected_index == row['count']:
            raw = b''.join(pieces)
            if len(raw) != row['bytes']:
                raise ValueError('CI_LOG_CHUNK: record length differs')
            if 'sha256:' + hashlib.sha256(raw).hexdigest() != row['sha256']:
                raise ValueError('CI_LOG_CHUNK: sha256 differs')
            try:
                restored = raw.decode('utf-8')
            except UnicodeDecodeError as error:
                raise ValueError('CI_LOG_CHUNK: invalid UTF-8') from error
            if '\n' in restored:
                raise ValueError('CI_LOG_CHUNK: multiline record')
            yield route + restored
            pending, pieces, expected_index = None, [], 0
    if pending is not None:
        raise ValueError('CI_LOG_CHUNK: missing chunks')


class _BoundedLogWriter:
    def __init__(self, target):
        self.target, self.pending = target, ''
        self.encoding = getattr(target, 'encoding', 'utf-8')

    def write(self, text):
        with _LOG_LOCK:
            self.pending += text
            while '\n' in self.pending:
                line, self.pending = self.pending.split('\n', 1)
                emit_log(line, stream=self.target)
        return len(text)

    def flush(self):
        self.target.flush()

    def isatty(self):
        return self.target.isatty()

    def fileno(self):
        return self.target.fileno()

    def finish(self):
        with _LOG_LOCK:
            if self.pending:
                emit_log(self.pending, stream=self.target)
                self.pending = ''
            self.flush()


@contextmanager
def bounded_log_output():
    # Use the real runtime streams even in tests that replace driver.sys with a stub.
    import sys as runtime_sys
    out, err = _BoundedLogWriter(runtime_sys.stdout), _BoundedLogWriter(runtime_sys.stderr)
    try:
        with redirect_stdout(out), redirect_stderr(err):
            yield
    finally:
        out.finish()
        err.finish()


def load_relocations():
    name, digest = RELOCATION_MANIFEST_PIN
    raw = (REPO/name).read_bytes()
    if 'sha256:'+hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError('CI_RELOCATION: manifest pin differs')
    def unique(values):
        result = {}
        for key, value in values:
            if key in result:
                raise ValueError('CI_RELOCATION: duplicate manifest key')
            result[key] = value
        return result
    return json.loads(raw.decode('utf-8'), object_pairs_hook=unique)


def relocated_nodeids(nodeids, index, count, manifest):
    """Retain the exact baseline; apply only the five versioned measured moves."""
    selected = shard_nodeids(nodeids, index, count)
    if (type(manifest) is not dict
            or set(manifest) != {'format', 'shard_count', 'baseline_nodeids', 'source_run', 'relocations', 'previous_manifest_sha256'}
            or manifest['format'] != 'ohf-ci-epoch2-relocations/2'
            or type(manifest['shard_count']) is not int or manifest['shard_count'] != count):
        raise ValueError('CI_RELOCATION: manifest format/count differs')
    baseline, moves = manifest['baseline_nodeids'], manifest['relocations']
    if (type(baseline) is not list or len(baseline) != 205
            or any(type(node) is not str for node in baseline)
            or len(baseline) != len(set(baseline)) or baseline != sorted(baseline)):
        raise ValueError('CI_RELOCATION: baseline census differs')
    if type(moves) is not list:
        raise ValueError('CI_RELOCATION: moves must be a list')
    seen = set()
    for move in moves:
        if (type(move) is not dict
                or set(move) != {'nodeid', 'from', 'to', 'cpu_seconds', 'wall_seconds', 'source_run', 'reason'}
                or type(move['nodeid']) is not str):
            raise ValueError('CI_RELOCATION: invalid move')
        node = move['nodeid']
        if node in seen:
            raise ValueError('CI_RELOCATION: duplicate relocation id')
        seen.add(node)
        if node not in baseline:
            raise ValueError('CI_RELOCATION: unknown relocation id: '+node)
        if node not in nodeids:
            raise ValueError('CI_RELOCATION: stale relocation id: '+node)
        if (any(type(move[key]) is not int or not 0 <= move[key] < count for key in ('from', 'to'))
                or move['from'] == move['to'] or baseline.index(node) % count != move['from']):
            raise ValueError('CI_RELOCATION: source/destination differs')
        if (any(type(move[key]) not in (int, float) or not math.isfinite(move[key]) or move[key] <= 0
                for key in ('cpu_seconds', 'wall_seconds'))
                or type(move['source_run']) is not str or not move['source_run']
                or type(move['reason']) is not str or not move['reason']):
            raise ValueError('CI_RELOCATION: measured cost/provenance differs')
    if len(moves) != 5:
        raise ValueError('CI_RELOCATION: exactly five moves required')
    if sorted(nodeids) != baseline:
        raise ValueError('CI_RELOCATION: collected census differs')
    for move in moves:
        node = move['nodeid']
        if index == move['from']:
            selected.remove(node)
        if index == move['to']:
            selected.add(node)
    return selected


def shard_nodeids(nodeids, index, count=SHARD_COUNT):
    """Balanced deterministic membership; preserve each selected case exactly once."""
    if type(index) is not int or type(count) is not int or count < 1 or not 0 <= index < count:
        raise ValueError('CI_SHARD: invalid index/count')
    ordered = sorted(nodeids)
    if len(ordered) != len(set(ordered)):
        raise ValueError('CI_SHARD: duplicate collected node id')
    return set(ordered[index::count])


def collection_plugin(pytest, shard=None, record=None):
    class Partition:
        configuration = shard
        before = None

        @pytest.hookimpl(trylast=True)
        def pytest_collection_modifyitems(self, config, items):
            self.before = [item.nodeid for item in items]
            if shard is None:
                return
            name, index, count = shard
            selected = (relocated_nodeids(self.before, index, count, load_relocations())
                        if name == 'epoch2' else shard_nodeids(self.before, index, count))
            removed = [item for item in items if item.nodeid not in selected]
            items[:] = [item for item in items if item.nodeid in selected]
            config.hook.pytest_deselected(items=removed)

        def pytest_collection_finish(self, session):
            if record is not None:
                record({'shard': list(shard) if shard else None,
                        'before_shard_nodeids': self.before,
                        'selected_nodeids': [item.nodeid for item in session.items]})
    return Partition()


def cpu_sample():
    result = {}
    for name, who in (('self', resource.RUSAGE_SELF), ('children', resource.RUSAGE_CHILDREN)):
        usage = resource.getrusage(who)
        value = usage.ru_utime + usage.ru_stime
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
            raise ValueError('CI_CPU: invalid getrusage sample')
        result[name] = value
    result['total'] = result['self'] + result['children']
    return result


def cpu_elapsed(before, after):
    result = {name: after[name] - before[name] for name in ('self', 'children')}
    if any(not math.isfinite(value) or value < 0 for value in result.values()):
        raise ValueError('CI_CPU: counter moved backwards')
    result['total'] = result['self'] + result['children']
    return result


TEST_COST_COLUMNS = ['nodeid', 'cpu_self_seconds', 'cpu_children_seconds', 'wall_seconds']


def nodeids_digest(nodeids):
    raw = json.dumps(sorted(nodeids), separators=(',', ':'), ensure_ascii=False).encode()
    return 'sha256:'+hashlib.sha256(raw).hexdigest()


def test_cost_plugin(pytest):
    class Costs:
        def __init__(self):
            self.nodeids = []
            self.rows = []

        def pytest_collection_finish(self, session):
            self.nodeids = [item.nodeid for item in session.items]

        @pytest.hookimpl(hookwrapper=True, tryfirst=True)
        def pytest_runtest_protocol(self, item, nextitem):
            before, started = cpu_sample(), time.monotonic()
            yield
            elapsed = cpu_elapsed(before, cpu_sample())
            self.rows.append([item.nodeid, elapsed['self'], elapsed['children'],
                              time.monotonic()-started])
    return Costs()


def test_cost_summary(result):
    """Account for every collected test; non-test cost is measured, not guessed startup."""
    rows, count = result.get('test_costs'), result.get('test_count')
    if (type(rows) is not list or not rows or type(count) is not int or count != len(rows)
            or result.get('test_cost_columns') != TEST_COST_COLUMNS):
        raise ValueError('CI_TEST_COST: missing or incomplete per-test rows')
    nodeids = []
    for row in rows:
        if (type(row) is not list or len(row) != 4 or type(row[0]) is not str or not row[0]
                or any(type(value) not in (int, float) or not math.isfinite(value) or value < 0
                       for value in row[1:])):
            raise ValueError('CI_TEST_COST: invalid per-test row')
        nodeids.append(row[0])
    if len(nodeids) != len(set(nodeids)) or nodeids_digest(nodeids) != result.get('test_nodeids_sha256'):
        raise ValueError('CI_TEST_COST: per-test collection differs')
    cpu = result['cpu_process_seconds']['total']
    wall = result['wall_seconds_total']
    test_cpu = math.fsum(row[1]+row[2] for row in rows)
    test_wall = math.fsum(row[3] for row in rows)
    if test_cpu > cpu+1e-6 or test_wall > wall+1e-6:
        raise ValueError('CI_TEST_COST: per-test sum exceeds leaf measurement')
    heaviest = max(rows, key=lambda row: row[1]+row[2])
    overhead = max(0.0, cpu-test_cpu)
    return {'test_count': count,
            'test_costs_sha256': 'sha256:'+hashlib.sha256(json.dumps(rows, separators=(',', ':')).encode()).hexdigest(),
            'heaviest_test': heaviest[0], 'heaviest_test_cpu_seconds': heaviest[1]+heaviest[2],
            'non_test_cpu_seconds': overhead, 'non_test_wall_seconds': max(0.0, wall-test_wall),
            'measured_floor_cpu_seconds': heaviest[1]+heaviest[2]+overhead}


def measured_margin(result, name):
    if type(result) is not dict or type(result.get('cpu_process_seconds')) is not dict:
        raise ValueError('CI_HEADROOM: malformed batch measurement: ' + name)
    cpu = result['cpu_process_seconds'].get('total')
    wall = result.get('wall_seconds_total')
    if (type(result.get('exit_code')) is not int or result['exit_code'] != 0
            or type(cpu) not in (int, float) or type(wall) not in (int, float)
            or not math.isfinite(cpu) or not math.isfinite(wall)
            or not 0 <= cpu <= 90 or not 0 <= wall <= 120):
        raise ValueError('CI_HEADROOM: less than twofold measured margin: ' + name)
    return {'batch': name, 'cpu_process_seconds': cpu, 'wall_seconds_total': wall,
            'cpu_cap_seconds': 180, 'outer_wall_cap_seconds': 240,
            'test_cost_summary': test_cost_summary(result)}


def batch_wall_budget(batch):
    if batch not in BATCHES:
        raise ValueError('CI_BATCH: unsupported batch')
    return AGGREGATE_WALL_BUDGETS[batch] if batch in SHARDED else 240


def worker_guard(row):
    """Keep transport-sized measurements; full source maps stay in RESULT.json."""
    return {**{key: row[key] for key in (
        'batch', 'shard_index', 'exit_code', 'seconds', 'wall_seconds_total',
        'cpu_seconds', 'cpu_process_seconds', 'source_pins_exact',
        'guard_violations', 'disk_minimum', 'cpu_placement')},
        'test_cost_summary': test_cost_summary(row)}


def verify_headroom(root):
    """Post-run acceptance gate; safety caps remain CPU180 and outer wall240."""
    root = Path(root)
    expected = set(BATCHES)
    actual = {path.parent.name for path in root.glob('*/RESULT.json')}
    if actual != expected:
        raise ValueError('CI_HEADROOM: missing or unexpected batch result')
    rows = []
    for name in BATCHES:
        result = json.loads((root/name/'RESULT.json').read_bytes())
        if result.get('batch') != name or result.get('exit_code') != 0:
            raise ValueError('CI_HEADROOM: batch refused: ' + name)
        if name in SHARDED:
            children = result.get('shards')
            if (type(children) is not list or len(children) != SHARD_COUNTS[name]
                    or [x.get('shard_index') for x in children] != list(range(SHARD_COUNTS[name]))):
                raise ValueError('CI_HEADROOM: incomplete shard inventory: ' + name)
            wall = result.get('wall_seconds_total')
            if (type(wall) not in (int, float) or not math.isfinite(wall)
                    or not 0 <= wall <= batch_wall_budget(name)/2):
                raise ValueError('CI_HEADROOM: aggregate wall margin differs: ' + name)
            rows.extend(measured_margin(x, name + '/' + str(x['shard_index'])) for x in children)
        else:
            rows.append(measured_margin(result, name))
    return rows



def heads(raw):
    def pairs(values):
        result = {}
        for key, value in values:
            if key in result:
                raise ValueError('CI_PAIR: duplicate identity member')
            result[key] = value
        return result
    result = json.loads(raw.decode('utf-8'), object_pairs_hook=pairs)
    if (type(result) is not dict or result.keys() != HEAD_KEYS
            or any(type(value) is not str or not re.fullmatch('[0-9a-f]{40}', value)
                   for value in result.values())):
        raise ValueError('CI_PAIR: four exact Git object identities required')
    return result


def verify_standard(standard):
    dependencies = json.loads((REPO/'references/native-profile-dependencies-4.json').read_bytes())
    expected = {**dependencies['files'], **BOOTSTRAP_PINS}
    pins = {}
    for name, digest in expected.items():
        path = standard/name
        actual = 'sha256:'+hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != digest:
            raise ValueError('CI_SOURCE: normative/bootstrap pin differs: '+name)
        pins[str(path)] = actual
    return pins


def source_pins(standard):
    # Verify the entire normative closure, including the empty package initializer
    # imported by the ordinary native helper, BEFORE any product import.
    standard_pins = verify_standard(standard)
    name, digest = RECEIPT_READER_PIN
    if 'sha256:'+hashlib.sha256((standard/name).read_bytes()).hexdigest() != digest:
        raise ValueError('CI_SOURCE: receipt reader differs')
    standard_pins[str(standard/name)] = digest
    files = [REPO/'SKILL.md', REPO/'requirements.txt', REPO/'.forgejo/workflows/check.yml']
    files.append(REPO/RELOCATION_MANIFEST_PIN[0])
    files += [REPO/'scripts/tests'/name for name in ('native_profile_relocations-1.json',
                                                    'native_profile_relocations-2.json')]
    files += [p for p in (REPO/'references').rglob('*') if p.is_file()]
    files += list((REPO/'scripts').glob('*.py'))
    files += [REPO/'scripts/tests'/name for name in (
        'conftest.py', 'profile_fixture.py', 'native_profile_ci.py', 'native_profile_ci_driver.py',
        'test_native_profile.py', 'test_native_profile14.py', 'test_projection_adapter.py',
        'test_checker_durability.py', 'test_native_profile_ci_driver.py', 'test_child_sourced_lists142.py')]
    return {**{str(p): 'sha256:'+hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(set(files))},
            **standard_pins}


def cpu_admission(load1, cpu_count):
    """Decide CPU admission from a load sample and the pre-pin affinity count."""
    count = cpu_count if type(cpu_count) is int and 0 < cpu_count <= sys.maxsize else None
    try:
        load = float(load1) if type(load1) in (int, float) else None
    except OverflowError:
        load = None
    if load is None or not math.isfinite(load) or load < 0:
        return {'load1': None, 'cpu_count': count, 'load1_per_cpu': None,
                'cpu_policy': 'load_snapshot_refused', 'cpu_threshold': None,
                'cpu_refused': True, 'cpu_reason': 'LOAD_INVALID'}
    if count is None:
        return {'load1': load, 'cpu_count': None, 'load1_per_cpu': None,
                'cpu_policy': 'legacy_load_fallback', 'cpu_threshold': 10,
                'cpu_refused': load >= 10, 'cpu_reason': 'CPU_COUNT_UNAVAILABLE'}
    ratio = load / count
    refused = ratio >= 0.9
    return {'load1': load, 'cpu_count': count, 'load1_per_cpu': ratio,
            'cpu_policy': 'normalized_load', 'cpu_threshold': 0.9,
            'cpu_refused': refused,
            'cpu_reason': 'NORMALIZED_LOAD_LIMIT' if refused else 'NORMALIZED_LOAD_OK'}


def read_affinity():
    """Return the actual allowed IDs; expected OS failures remain typed."""
    reader = getattr(os, 'sched_getaffinity', None)
    if reader is None:
        return None, 'AFFINITY_UNAVAILABLE'
    try:
        allowed = reader(0)
    except OSError:
        return None, 'AFFINITY_UNAVAILABLE'
    if type(allowed) not in (set, frozenset) or any(
            type(cpu) is not int or not 0 <= cpu <= sys.maxsize for cpu in allowed):
        return None, 'AFFINITY_INVALID'
    if not allowed:
        return None, 'AFFINITY_EMPTY'
    return sorted(allowed), None


def cpu_placement(pair, batch, allowed):
    """Stable singleton choice, without reserving a CPU or avoiding collisions."""
    seed = json.dumps({'pair': pair, 'batch': batch}, sort_keys=True,
                      separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode('utf-8')
    digest = hashlib.sha256(seed).hexdigest()
    return {'algorithm': 'pair_batch_sha256_v1', 'seed_sha256': digest,
            'pre_pin_allowed': allowed, 'worker_count': 1,
            'selected_cpu': allowed[int(digest, 16) % len(allowed)] if allowed else None,
            'observed_before_pin': None, 'observed_after_pin': None,
            'observed_after_batch': None, 'pin_attempted': False,
            'status': 'NOT_ATTEMPTED', 'reason': None}


def pin_cpu(placement):
    """Fail closed on a changed set or an unverified singleton; never repin."""
    result = dict(placement)
    result['status'] = 'REFUSED'
    if result['pre_pin_allowed'] is None:
        result['reason'] = 'PRE_PIN_AFFINITY_UNAVAILABLE'
        return result
    observed, reason = read_affinity()
    result['observed_before_pin'] = observed
    if reason or observed != result['pre_pin_allowed']:
        result['reason'] = reason or 'PRE_PIN_AFFINITY_CHANGED'
        return result
    setter = getattr(os, 'sched_setaffinity', None)
    if setter is None:
        result['reason'] = 'PIN_API_UNAVAILABLE'
        return result
    result['pin_attempted'] = True
    try:
        setter(0, {result['selected_cpu']})
    except OSError:
        result['reason'] = 'PIN_OS_ERROR'
        return result
    observed, reason = read_affinity()
    result['observed_after_pin'] = observed
    if reason or observed != [result['selected_cpu']]:
        result['reason'] = reason or 'PIN_NOT_SINGLETON'
        return result
    result['status'], result['reason'] = 'VERIFIED', None
    return result


def verify_final_affinity(placement):
    """Record terminal affinity drift without retrying or changing placement."""
    result = dict(placement)
    observed, reason = read_affinity()
    result['observed_after_batch'] = observed
    if reason or observed != [result['selected_cpu']]:
        result['status'] = 'REFUSED'
        result['reason'] = reason or 'TERMINAL_AFFINITY_CHANGED'
    return result


def sample_cpu_capacity():
    """Sample before singleton pinning; unavailable affinity retains legacy-10."""
    load, count = None, None
    load_reason, count_reason = None, None
    load_reader = getattr(os, 'getloadavg', None)
    if load_reader is None:
        load_reason = 'LOAD_UNAVAILABLE'
    else:
        try:
            load = load_reader()[0]
        except OSError:
            load_reason = 'LOAD_UNAVAILABLE'
    allowed, count_reason = read_affinity()
    count = len(allowed) if allowed else None
    result = cpu_admission(load, count)
    result['cpu_count_source'] = 'pre_pin_affinity' if result['cpu_count'] is not None else None
    result['cpu_count_reason'] = count_reason
    result['pre_pin_allowed'] = allowed
    if load_reason:
        result['cpu_reason'] = load_reason
    return result


class AdmissionRefused(Exception):
    def __init__(self, receipt):
        self.receipt = receipt
        super().__init__(receipt['reason'])


PARENT_SIGNALS = (signal.SIGTERM, signal.SIGINT)


class ParentCancelled(BaseException):
    def __init__(self, signum):
        self.signum = signum
        super().__init__('PARENT_CANCELLED: ' + str(signum))


@contextmanager
def parent_cancellation():
    """Convert catchable cancellation into unwinding; repeated signals cannot cut cleanup short."""
    previous_mask = signal.pthread_sigmask(signal.SIG_BLOCK, PARENT_SIGNALS)
    previous_handlers = {sig: signal.getsignal(sig) for sig in PARENT_SIGNALS}

    def cancel(signum, frame):
        signal.pthread_sigmask(signal.SIG_BLOCK, PARENT_SIGNALS)
        for sig in PARENT_SIGNALS:
            signal.signal(sig, signal.SIG_IGN)
        raise ParentCancelled(signum)

    try:
        for sig in PARENT_SIGNALS:
            signal.signal(sig, cancel)
        try:
            signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)
            yield
        finally:
            signal.pthread_sigmask(signal.SIG_BLOCK, PARENT_SIGNALS)
            for sig, handler in previous_handlers.items():
                signal.signal(sig, handler)
    finally:
        signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)


@contextmanager
def host_admission(*, clock=None, sleep=None, sample=None):
    """One lock and one deadline for the parent's lock/load admission phase."""
    clock, sleep = clock or time.monotonic, sleep or time.sleep
    sample = sample or sample_cpu_capacity
    started = clock()
    deadline = started + ADMISSION_WAIT_SECONDS
    lock_polls, load_polls = 0, 0
    capacity = {}
    fd = None

    def receipt(reason):
        return {**capacity, 'reason': reason, 'waited_seconds': clock()-started,
                'poll_count': lock_polls+load_polls, 'lock_poll_count': lock_polls,
                'load_poll_count': load_polls, 'wait_budget_seconds': ADMISSION_WAIT_SECONDS,
                'poll_interval_seconds': ADMISSION_POLL_SECONDS, 'lock_path': str(HOST_LOCK)}

    def pause(reason):
        remaining = deadline-clock()
        if remaining <= 0:
            raise AdmissionRefused(receipt(reason))
        emit_log('PARENT_WAIT', json.dumps(receipt(reason), allow_nan=False), flush=True)
        sleep(min(ADMISSION_POLL_SECONDS, remaining))

    try:
        try:
            HOST_LOCK.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            fd = os.open(HOST_LOCK, os.O_CREAT | os.O_RDWR | os.O_CLOEXEC | os.O_NOFOLLOW, 0o600)
        except OSError as error:
            raise AdmissionRefused({**receipt('HOST_LOCK_UNAVAILABLE'), 'errno': error.errno}) from error
        while True:
            if clock() >= deadline:
                raise AdmissionRefused(receipt('HOST_LOCK_TIMEOUT'))
            lock_polls += 1
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                pause('HOST_LOCK_TIMEOUT')
            except OSError as error:
                raise AdmissionRefused({**receipt('HOST_LOCK_UNAVAILABLE'), 'errno': error.errno}) from error
        while True:
            if clock() >= deadline:
                raise AdmissionRefused(receipt(capacity.get('cpu_reason', 'NORMALIZED_LOAD_LIMIT')))
            load_polls += 1
            capacity = sample()
            if not capacity['cpu_refused']:
                break
            pause(capacity['cpu_reason'])
        yield {**receipt('ADMITTED'), 'lock_fd': fd}
    finally:
        if fd is not None:
            # Closing this parent's fd releases its lock, including exceptional exits.
            os.close(fd)


def parent_child(command, stream, budget, lock_fd):
    """Keep the lock until an expired batch's whole process group is stopped."""
    previous_mask = signal.pthread_sigmask(signal.SIG_BLOCK, PARENT_SIGNALS)
    try:
        child = subprocess.Popen(command, cwd=REPO, stdout=stream, stderr=subprocess.STDOUT,
                                 start_new_session=True, pass_fds=(lock_fd,))
        try:
            # A cancellation pending during Popen is delivered only after cleanup owns the child.
            signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)
            try:
                status = child.wait(timeout=budget)
                return 128-status if status < 0 else status
            except subprocess.TimeoutExpired:
                return 124
        finally:
            signal.pthread_sigmask(signal.SIG_BLOCK, PARENT_SIGNALS)
            # Allow a short orderly stop, then stop every remaining descendant.
            try:
                os.killpg(child.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                child.wait(timeout=2)
            except subprocess.TimeoutExpired:
                pass
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            child.wait()
    finally:
        signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)


def run_parent(pair_file, output, expected_rules=None):
    """Serialize whole native jobs; dispatch each original batch once, with its old cap."""
    pair_file, output = Path(pair_file).absolute(), Path(output).absolute()
    pair = heads(pair_file.read_bytes())
    if expected_rules is not None and not re.fullmatch(r'sha256:[0-9a-f]{64}', expected_rules):
        raise ValueError('CI_PAIR: invalid expected rules hash')
    if not output.is_dir() or any((output/name).exists() or (output/name).is_symlink()
                                  for name in (*BATCH_ORDER, 'PARENT-ADMISSION.json', 'PARENT-RESULT.json', 'PARENT-CANCELLATION.json')):
        raise ValueError('CI_OUTPUT: parent requires an existing fresh evidence root')
    results = []

    def save(name, value):
        with (output/name).open('x') as stream:
            json.dump(value, stream, indent=2, allow_nan=False)
            stream.write('\n')

    def sample():
        return {'at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                **sample_cpu_capacity(), 'disk_free': shutil.disk_usage(output).free,
                'memory_available': int(Path('/proc/meminfo').read_text().split('MemAvailable:')[1].split()[0])*1024}

    try:
        with parent_cancellation(), host_admission(sample=sample) as admission:
            save('PARENT-ADMISSION.json', {**admission, 'pair': pair})
            emit_log('PARENT_ADMISSION', json.dumps(admission, allow_nan=False), flush=True)
            status = 0
            for batch in BATCH_ORDER:
                budget = batch_wall_budget(batch)
                command = [sys.executable, '-I', '-B', str(Path(__file__).resolve()),
                           '--pair', str(pair_file), '--output', str(output/batch), '--batch', batch,
                           '--lock-fd', str(admission['lock_fd'])]
                if expected_rules is not None:
                    command += ['--expected-rules', expected_rules]
                emit_log('PARENT_BATCH', batch, 'wall_budget_seconds', budget, flush=True)
                log = output/('PARENT-'+batch+'.log')
                with log.open('x') as stream:
                    status = parent_child(command, stream, budget, admission['lock_fd'])
                for line in log.read_text().splitlines():
                    emit_log(line, flush=True)
                results.append({'batch': batch, 'exit_code': status, 'wall_budget_seconds': budget})
                if status:
                    break
            save('PARENT-RESULT.json', {'pair': pair, 'exit_code': status, 'batches': results,
                                      'admission': admission, 'host_lock_held_through_children': True})
            return status
    except ParentCancelled as error:
        receipt = {'reason': 'PARENT_CANCELLED', 'signal': error.signum,
                   'exit_code': 128+error.signum, 'completed_batches': results,
                   'owned_child_cleanup_finished': True}
        save('PARENT-CANCELLATION.json', receipt)
        emit_log('PARENT_CANCELLED', json.dumps(receipt), flush=True)
        return receipt['exit_code']
    except AdmissionRefused as error:
        save('PARENT-ADMISSION.json', {**error.receipt, 'pair': pair, 'exit_code': 97})
        emit_log('CAPACITY_REFUSED', json.dumps(error.receipt, allow_nan=False), flush=True)
        return 97


def run_sharded(pair_file, output, batch, expected_rules, lock_fd=None):
    """Seven-batch interface; only the bounded internal workers import pytest."""
    from collections import Counter
    started, before_cpu = time.monotonic(), cpu_sample()
    pair_file = Path(pair_file).absolute()
    pair = heads(pair_file.read_bytes())
    if expected_rules is not None and not re.fullmatch(r'sha256:[0-9a-f]{64}', expected_rules):
        raise ValueError('CI_PAIR: invalid expected rules hash')
    standard = Path(os.environ['OHF_REPO']).resolve(strict=True)
    output = Path(output).absolute()
    if output.exists() or output.is_symlink():
        raise ValueError('CI_OUTPUT: existing evidence is never reset or reused')
    capacity = {'at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                **sample_cpu_capacity(), 'disk_free': shutil.disk_usage(output.parent).free,
                'memory_available': int(Path('/proc/meminfo').read_text().split('MemAvailable:')[1].split()[0])*1024}
    pins = source_pins(standard)
    output.mkdir(mode=0o700)
    def save(name, value):
        with (output/name).open('x') as stream:
            json.dump(value, stream, indent=2, allow_nan=False)
            stream.write('\n')
    save('ADMISSION.json', {'pair': pair, 'batch': batch, 'capacity': capacity, 'source_pins_before': pins})
    emit_log('CAPACITY', json.dumps({**capacity, 'internal_serial_shards': SHARD_COUNTS[batch]}), flush=True)
    if capacity['cpu_refused'] or min(capacity['disk_free'], capacity['memory_available']) < 3*1024**3:
        emit_log('CAPACITY_REFUSED', json.dumps(capacity), flush=True)
        return 97
    resource.setrlimit(resource.RLIMIT_AS, (1024**3,)*2)
    resource.setrlimit(resource.RLIMIT_CPU, (180,)*2)
    workers = output/'shards'
    workers.mkdir(mode=0o700)
    results, collections = [], []
    status = 1
    try:
        for index in range(SHARD_COUNTS[batch]):
            child = workers/str(index)
            command = [sys.executable, '-I', '-B', str(Path(__file__).resolve()),
                       '--pair', str(pair_file), '--output', str(child), '--batch', batch,
                       '--shard-index', str(index)]
            if expected_rules is not None:
                command += ['--expected-rules', expected_rules]
            lease = {}
            if lock_fd is not None:
                command += ['--lock-fd', str(lock_fd)]
                lease['pass_fds'] = (lock_fd,)
            with (output/f'SHARD-{index}.log').open('x') as stream:
                try:
                    completed = subprocess.run(command, cwd=REPO, stdout=stream,
                                               stderr=subprocess.STDOUT, timeout=240, check=False, **lease)
                except subprocess.TimeoutExpired:
                    status = 124
                    break
            for line in (output/f'SHARD-{index}.log').read_text().splitlines():
                emit_log(f'SHARD {batch}/{index} {line}', flush=True)
            if completed.returncode != 0:
                status = completed.returncode or 1
                break
            result = json.loads((child/'RESULT.json').read_bytes())
            collection = json.loads((child/'COLLECTION.json').read_bytes())
            expected_pair = {**pair, 'rules_sha256': result['pair']['rules_sha256']}
            if (results and expected_pair != results[0]['pair']
                    or result['pair'] != expected_pair or result['batch'] != batch
                    or result.get('shard_index') != index or result['source_pins_exact'] is not True
                    or result['source_pins_after'] != pins or result['guard_violations']
                    or collection['shard'] != [batch, index, SHARD_COUNTS[batch]]
                    or result.get('test_count') != len(collection['selected_nodeids'])
                    or result.get('test_nodeids_sha256') != nodeids_digest(collection['selected_nodeids'])
                    or result['cpu_placement']['status'] != 'VERIFIED'
                    or result['cpu_placement']['observed_after_batch'] != [result['cpu_placement']['selected_cpu']]):
                raise ValueError('CI_SHARD: child identity, source, guard or pin differs')
            measured_margin(result, batch + '/' + str(index))
            results.append(result)
            collections.append(collection)
        if len(results) == SHARD_COUNTS[batch]:
            baseline = collections[0]['before_shard_nodeids']
            selected = [node for row in collections for node in row['selected_nodeids']]
            if (not baseline or any(row['before_shard_nodeids'] != baseline for row in collections)
                    or len(selected) != len(set(selected)) or Counter(selected) != Counter(baseline)):
                raise ValueError('CI_SHARD: original collection not covered exactly once')
            save('COLLECTION.json', {'before_shard_nodeids': baseline, 'selected_nodeids': selected,
                                     'exactly_once': True, 'shards': collections})
            status = 0
    finally:
        after = source_pins(standard)
        after_cpu = cpu_sample()
        if results:
            pair = results[0]['pair']
        report = {'pair': pair, 'batch': batch, 'exit_code': status,
                  'seconds': time.monotonic()-started, 'wall_seconds_total': time.monotonic()-started,
                  'wall_scope': 'serial batch controller including workers; each worker measured separately',
                  'cpu_seconds': cpu_elapsed(before_cpu, after_cpu), 'cpu_process_seconds': after_cpu,
                  'cpu_scope': 'controller getrusage self + reaped workers; not the per-worker CPU cap',
                  'outer_wall_budget_seconds': batch_wall_budget(batch),
                  'source_pins_after': after, 'source_pins_exact': pins == after,
                  'guard_violations': [v for row in results for v in row['guard_violations']],
                  'disk_minimum': min([capacity['disk_free']] + [row['disk_minimum'] for row in results]),
                  'scenario': None, 'scientific_acceptance': False, 'shards': results}
        save('RESULT.json', report)
        if results:
            emit_log('EXACT_PAIR', json.dumps(pair, sort_keys=True), flush=True)
        guard_row = {key: report[key] for key in (
            'exit_code', 'seconds', 'source_pins_exact', 'guard_violations', 'disk_minimum',
            'wall_seconds_total', 'wall_scope', 'cpu_seconds', 'cpu_process_seconds', 'cpu_scope')}
        guard_row['shards'] = [worker_guard(row) for row in results]
        emit_log('GUARDS', json.dumps(guard_row), flush=True)
    return status or (95 if pins != after else bool(report['guard_violations']))


def run(pair_file, output, batch, expected_rules=None, shard_index=None, lock_fd=None):
    if batch not in BATCHES:
        raise ValueError('CI_BATCH: unsupported batch')
    if shard_index is not None and (batch not in SHARDED or type(shard_index) is not int
                                    or not 0 <= shard_index < SHARD_COUNTS[batch]):
        raise ValueError('CI_SHARD: invalid internal shard')
    if batch in SHARDED and shard_index is None:
        return run_sharded(pair_file, output, batch, expected_rules, lock_fd)
    shard = (batch, shard_index, SHARD_COUNTS[batch]) if shard_index is not None else None
    run_started = time.monotonic()
    cpu_before = cpu_sample()
    pair = heads(Path(pair_file).read_bytes())
    if expected_rules is not None and not re.fullmatch(r'sha256:[0-9a-f]{64}', expected_rules):
        raise ValueError('CI_PAIR: invalid expected rules hash')
    standard = Path(os.environ['OHF_REPO']).resolve(strict=True)
    output = Path(output).absolute()
    if output.exists() or output.is_symlink():
        raise ValueError('CI_OUTPUT: existing evidence is never reset or reused')
    capacity = {'at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                **sample_cpu_capacity(), 'disk_free': shutil.disk_usage(output.parent).free,
                'memory_available': int(Path('/proc/meminfo').read_text().split('MemAvailable:')[1].split()[0])*1024}
    placement_name = batch if shard is None else batch + '/' + str(shard_index)
    capacity['cpu_placement'] = cpu_placement(pair, placement_name, capacity['pre_pin_allowed'])
    output.mkdir(mode=0o700)
    pins = source_pins(standard)
    def save(name, value):
        with (output/name).open('x') as stream:
            json.dump(value, stream, indent=2, allow_nan=False)
            stream.write('\n')
    save('ADMISSION.json', {'pair': pair, 'batch': batch, 'capacity': capacity, 'source_pins_before': pins})
    if capacity['cpu_refused'] or capacity['disk_free'] < 3*1024**3 or capacity['memory_available'] < 3*1024**3:
        emit_log('CAPACITY', json.dumps(capacity, allow_nan=False), flush=True)
        emit_log('CAPACITY_REFUSED', json.dumps(capacity), flush=True)
        return 97
    placement = pin_cpu(capacity['cpu_placement'])
    save('PIN.json', placement)
    capacity['cpu_placement'] = placement
    emit_log('CAPACITY', json.dumps(capacity, allow_nan=False), flush=True)
    if placement['status'] != 'VERIFIED':
        emit_log('GUARDS', json.dumps({'exit_code': 97, 'seconds': None, 'source_pins_exact': None,
                                   'guard_violations': [], 'disk_minimum': capacity['disk_free'],
                                   'cpu_placement': placement}), flush=True)
        return 97
    resource.setrlimit(resource.RLIMIT_AS, (1024**3,)*2)
    resource.setrlimit(resource.RLIMIT_CPU, (180,)*2)
    stop = threading.Event()
    minimum = [capacity['disk_free']]
    def monitor():
        while not stop.wait(.02):
            minimum[0] = min(minimum[0], shutil.disk_usage(output).free)
            if minimum[0] < 3*1024**3:
                emit_log('CAPACITY_STOP disk below 3GiB; evidence preserved', flush=True)
                os._exit(98)
    threading.Thread(target=monitor, daemon=True).start()
    scratch = output/'scratch'
    scratch.mkdir(mode=0o700)
    tempfile.tempdir = str(scratch)
    violations = []
    # Bootstrap stdlib transports before replacement; imports above make this
    # independent of ssl subclass initialization after socket denial.
    def deny(*args, **kwargs):
        violations.append('network/process')
        raise RuntimeError('CI_OFFLINE: network/process dispatch refused')
    for name in ('socket', 'socketpair', 'create_connection', 'getaddrinfo'):
        setattr(socket, name, deny)
    for name in ('Popen', 'run', 'call', 'check_call', 'check_output'):
        setattr(subprocess, name, deny)
    for name in ('system', 'fork', 'forkpty', 'posix_spawn', 'posix_spawnp'):
        if hasattr(os, name):
            setattr(os, name, deny)
    library_roots = {Path(sys.base_prefix).resolve()/'lib', Path(sys.prefix).resolve()/'lib'}
    allowed_files = {Path(p).resolve() for p in pins}
    allowed_files.add(Path(pair_file).resolve())
    openat_context = threading.local()
    original_os_open = os.open
    def anchored_open(path, flags, mode=0o777, *, dir_fd=None):
        previous = getattr(openat_context, "target", None)
        if dir_fd is not None and isinstance(path, (str, bytes, os.PathLike)):
            base = Path(os.readlink("/proc/self/fd/"+str(dir_fd)))
            openat_context.target = (base/os.fsdecode(path)).resolve()
        try:
            return original_os_open(path, flags, mode, dir_fd=dir_fd)
        finally:
            openat_context.target = previous
    os.open = anchored_open
    def guard(event, args):
        if event.startswith(('socket.', 'subprocess.', 'os.exec', 'os.posix_spawn', 'os.fork', 'os.spawn', 'os.system')):
            violations.append(event)
            raise RuntimeError('CI_OFFLINE: dispatch refused')
        if event == 'open' and isinstance(args[0], (str, bytes, os.PathLike)):
            path = getattr(openat_context, "target", None) or Path(os.fsdecode(args[0])).resolve()
            mode, flags = args[1:3]
            writing = (isinstance(mode, str) and any(k in mode for k in 'wax+')
                       or isinstance(flags, int) and bool(flags & (os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC)))
            if path == Path('/dev/null'):
                return
            if writing:
                allowed = path.is_relative_to(output)
            else:
                allowed = (path in allowed_files or path.is_relative_to(output)
                           or any(path.is_relative_to(root) for root in library_roots)
                           or path.parent == REPO and path.name in ('pytest.ini', 'pyproject.toml', 'setup.cfg', 'tox.ini'))
            if not allowed:
                violations.append('open:'+str(path))
                raise RuntimeError('CI_OFFLINE: file outside explicit source/fixture/runtime allowlist')
    sys.addaudithook(guard)
    # Ignore ambient bytecode without deleting it. A fresh output owns the
    # redirected cache namespace; -B/no-write forces source fallback there.
    sys.pycache_prefix = str(output/'unused-bytecode')
    sys.dont_write_bytecode = True
    os.chdir(REPO)
    sys.path[:0] = [str(REPO/'scripts'), str(REPO/'scripts/tests')]
    os.environ['PYTEST_DISABLE_PLUGIN_AUTOLOAD'] = '1'
    started = time.monotonic()
    status = 1
    summary = None
    costs = None
    test_nodeids, test_rows = [], []
    try:
        import ohfkit
        pair['rules_sha256'] = ohfkit.rules_hash()
        if expected_rules is not None and pair['rules_sha256'] != expected_rules:
            raise ValueError('CI_PAIR: expected rules differs')
        emit_log('EXACT_PAIR', json.dumps(pair, sort_keys=True), flush=True)
        if batch == 'scenario':
            from native_profile_ci import run as scenario
            scenario_root = output/'scenario'
            scenario_root.mkdir(mode=0o700)
            test_nodeids = ['scenario/native_profile']
            scenario_cpu, scenario_started = cpu_sample(), time.monotonic()
            receipt = scenario(scenario_root, pair)
            elapsed = cpu_elapsed(scenario_cpu, cpu_sample())
            test_rows = [[test_nodeids[0], elapsed['self'], elapsed['children'],
                          time.monotonic()-scenario_started]]
            summary = {'status': receipt['status'], 'pair': receipt['pair'],
                       'validation_entrypoint': 'native_profile.validate_files -> validate_bundle',
                       'selector': receipt['validation']['profile'],
                       'schema_valid': receipt['validation']['schema_valid'],
                       'native_binding_valid': receipt['validation']['native_binding_valid'],
                       'bare_reader_status': receipt['bare_reader_status'],
                       'bare_error_count': len(receipt['bare_errors']),
                       'scientific_acceptance': False}
            emit_log('SCENARIO', json.dumps(summary, sort_keys=True), flush=True)
            status = 0
        else:
            import pytest
            costs = test_cost_plugin(pytest)
            status = int(pytest.main(['-v', '-p', 'no:cacheprovider', '--basetemp', str(output/'pytest'),
                                     '--junitxml', str(output/'TESTS.xml'), *BATCHES[batch]],
                                     plugins=[collection_plugin(pytest, shard,
                                         lambda row: save('COLLECTION.json', row)), costs]))
    finally:
        stop.set()
        placement = verify_final_affinity(placement)
        save('PIN-AFTER.json', placement)
        if placement['status'] != 'VERIFIED':
            status = 97
        after = source_pins(standard)
        cpu_after = cpu_sample()
        if costs is not None:
            test_nodeids, test_rows = costs.nodeids, costs.rows
        report = {'pair': pair, 'batch': batch, 'exit_code': status, 'seconds': time.monotonic()-started,
                  'wall_seconds_total': time.monotonic()-run_started,
                  'wall_scope': 'run invocation through terminal sampling; excludes interpreter startup, CLI parsing and receipt emission',
                  'cpu_seconds': cpu_elapsed(cpu_before, cpu_after),
                  'cpu_process_seconds': cpu_after,
                  'cpu_scope': 'getrusage self + reaped children; run delta and process lifetime snapshot before receipt emission',
                  'source_pins_after': after, 'source_pins_exact': pins == after,
                  'guard_violations': violations, 'disk_minimum': minimum[0], 'scenario': summary,
                  'scientific_acceptance': False, 'cpu_placement': placement,
                  'test_cost_columns': TEST_COST_COLUMNS, 'test_costs': test_rows,
                  'test_count': len(test_nodeids), 'test_nodeids_sha256': nodeids_digest(test_nodeids),
                  'test_cost_scope': 'pytest protocol including setup/teardown, or one scenario operation; residual includes startup/import/collection/inter-test work, not proven fixed startup'}
        try:
            report['test_cost_summary'] = test_cost_summary(report)
            report['test_cost_error'] = None
        except ValueError as error:
            report['test_cost_summary'], report['test_cost_error'] = None, str(error)
            status = status or 95
            report['exit_code'] = status
        if shard is not None:
            report['shard_index'] = shard_index
        save('RESULT.json', report)
        emit_log('GUARDS', json.dumps({**{k:report[k] for k in ('exit_code', 'seconds', 'source_pins_exact', 'guard_violations', 'disk_minimum', 'wall_seconds_total', 'wall_scope', 'cpu_seconds', 'cpu_process_seconds', 'cpu_scope', 'test_cost_columns', 'test_costs', 'test_count', 'test_nodeids_sha256', 'test_cost_scope', 'test_cost_summary', 'test_cost_error')},
                                    'cpu_placement': placement}), flush=True)
    return status or (95 if pins != after else bool(violations))


def verify_host_lease(fd):
    """The internal batch/shard descriptor names the same locked host inode."""
    if type(fd) is not int or fd < 0:
        raise ValueError('CI_HOST_LEASE: invalid descriptor')
    try:
        actual, expected = os.fstat(fd), HOST_LOCK.stat(follow_symlinks=False)
        if not stat.S_ISREG(actual.st_mode) or (actual.st_dev, actual.st_ino) != (expected.st_dev, expected.st_ino):
            raise ValueError('CI_HOST_LEASE: lock inode differs')
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as error:
        raise ValueError('CI_HOST_LEASE: descriptor unavailable') from error
    # The parent blocks cancellation only during spawn; its exec children restore normal delivery.
    signal.pthread_sigmask(signal.SIG_UNBLOCK, PARENT_SIGNALS)
    return fd


@bounded_log_output()
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check-headroom')
    parser.add_argument('--wall-budget', choices=tuple(BATCHES))
    parser.add_argument('--pair')
    parser.add_argument('--output')
    parser.add_argument('--batch', choices=tuple(BATCHES))
    parser.add_argument('--shard-index', type=int, help=argparse.SUPPRESS)
    parser.add_argument('--expected-rules')
    parser.add_argument('--parent', action='store_true', help='Hold the host lock through all seven batches')
    parser.add_argument('--lock-fd', type=int, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.wall_budget:
        if any((args.parent, args.check_headroom, args.pair, args.output, args.batch, args.expected_rules,
                args.shard_index is not None, args.lock_fd is not None)):
            parser.error('wall budget lookup cannot dispatch a batch')
        emit_log(batch_wall_budget(args.wall_budget))
        return 0
    if args.check_headroom:
        if any((args.parent, args.pair, args.output, args.batch, args.expected_rules, args.shard_index is not None, args.lock_fd is not None)):
            parser.error('headroom verification cannot dispatch a batch')
        emit_log('HEADROOM', json.dumps(verify_headroom(args.check_headroom), sort_keys=True))
        return 0
    if args.parent:
        if not all((args.pair, args.output)) or args.batch or args.shard_index is not None or args.lock_fd is not None:
            parser.error('--parent requires --pair and --output, without batch/shard selection')
        return run_parent(args.pair, args.output, args.expected_rules)
    if not all((args.pair, args.output, args.batch)):
        parser.error('--pair, --output and --batch are required')
    lock_fd = verify_host_lease(args.lock_fd) if args.lock_fd is not None else None
    return run(args.pair, args.output, args.batch, args.expected_rules, args.shard_index, lock_fd)


if __name__ == '__main__':
    raise SystemExit(main())
