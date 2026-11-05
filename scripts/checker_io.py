"""Freeze exact checker-visible bytes and bind a returned response to that request.

The only execution seam is an explicitly supplied callback. There is no provider,
process, network or model implementation here. Receipts bind bytes/configuration;
they do not authenticate a checker, prove reading, or establish scientific truth.
"""
import copy
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import stat

import projection_binding as projection

INPUT_FORMAT = 'ohf-native-checker-input/1'
RESULT_FORMAT = 'ohf-native-checker-result/1'
MAX_BYTES = 32 * 1024 * 1024
_VERIFIED = object()


def now():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def strict_json(raw):
    def pairs(rows):
        result = {}
        for key, value in rows:
            if key in result:
                raise ValueError('duplicate JSON member')
            result[key] = value
        return result
    def bad(value):
        raise ValueError('nonfinite JSON number')
    def floating(value):
        result = float(value)
        if not math.isfinite(result):
            bad(value)
        return result
    try:
        return json.loads(raw, object_pairs_hook=pairs, parse_constant=bad, parse_float=floating)
    except (UnicodeError, TypeError) as error:
        raise ValueError('invalid checker JSON encoding') from error


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, indent=1, allow_nan=False) + '\n').encode('utf-8')


def read(path):
    path = Path(path)
    try:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > MAX_BYTES:
            raise ValueError('checker artifact must be a bounded regular non-aliased file')
        with path.open('rb') as stream:
            raw = stream.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise ValueError('checker artifact exceeds byte limit')
        return raw
    except (OSError, ValueError) as error:
        raise ValueError('checker artifact unavailable or unsafe: ' + path.name) from error


def write_once(path, raw):
    """Exclusive POSIX commit: flush, read-only mode, file fsync, directory fsync.

    A successful return is required before a dependent phase can start. An
    unsupported/failed barrier raises; partial evidence is never removed/reset.
    The containing directory must already exist.
    """
    if not isinstance(raw, bytes) or len(raw) > MAX_BYTES:
        raise ValueError('checker bytes exceed the bounded contract')
    path = Path(path)
    try:
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            descriptor = os.open(path.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                                 0o600, dir_fd=directory)
            with os.fdopen(descriptor, 'wb') as stream:
                if stream.write(raw) != len(raw):
                    raise OSError('short checker artifact write')
                stream.flush()
                os.fchmod(stream.fileno(), 0o444)
                os.fsync(stream.fileno())
            os.fsync(directory)
        finally:
            os.close(directory)
    except (OSError, ValueError) as error:
        # Partial evidence is preserved; no reset or automatic replacement.
        raise ValueError('checker artifact already exists or cannot be durably frozen: ' + path.name) from error


def commit_inputs(pins):
    """Check and sync the actual saved prerequisites again before dispatch.

    This covers a packet saved before this durability fix, without relabelling
    or modifying its bytes. No callback begins on an uncertain input barrier.
    """
    files = [Path(p) for p in pins]
    if not files or len({p.parent for p in files}) != 1:
        raise ValueError('frozen inputs require one explicit containing directory')
    try:
        directory = os.open(files[0].parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            for path in files:
                descriptor = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
                with os.fdopen(descriptor, 'rb') as stream:
                    info = os.fstat(stream.fileno())
                    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > MAX_BYTES:
                        raise ValueError('unsafe frozen input at durability barrier')
                    raw = stream.read(MAX_BYTES + 1)
                    if len(raw) > MAX_BYTES or projection.sha(raw) != pins[str(path)]:
                        raise ValueError('frozen input changed before durability barrier')
                    os.fsync(stream.fileno())
            os.fsync(directory)
        finally:
            os.close(directory)
    except (OSError, ValueError) as error:
        raise ValueError('frozen checker prerequisites cannot be durably committed') from error


def paths(path):
    path = Path(path)
    return path, path.with_name(path.name + '.request'), path.with_name(path.name + '.binding.json')


def result_paths(path):
    path = Path(path)
    return path, path.with_name(path.name + '.binding.json')


def dispatch_path(path):
    path = Path(path)
    return path.with_name(path.name + '.dispatch.json')


def absent(files):
    if any(p.exists() or p.is_symlink() for p in files):
        raise ValueError('checker output/freeze evidence already exists; no replacement')


def valid_items(items):
    if not isinstance(items, list) or not items:
        raise ValueError('nonempty checker item list required')
    seen = set()
    for item in items:
        if (not isinstance(item, dict) or set(item) != {'id', 'pointer', 'basis', 'value', 'source_passage'}
                or not isinstance(item['id'], str) or not item['id'] or item['id'] in seen
                or item['basis'] not in ('src', 'basis_quote')
                or not isinstance(item['pointer'], str) or not item['pointer'].startswith('/')
                or not isinstance(item['source_passage'], str)):
            raise ValueError('invalid or duplicate checker item')
        seen.add(item['id'])
        if projection.is_projected(item):
            projection.target_of(item)


def valid_results(items, results):
    if not isinstance(results, list) or [i['id'] for i in items] != [r.get('id') if isinstance(r, dict) else None for r in results]:
        raise ValueError('checker results do not match frozen input IDs/order')
    for row in results:
        if (set(row) - {'id', 'verdict', 'note'} or not {'id', 'verdict'} <= set(row)
                or row['verdict'] not in ('entails', 'partial', 'no')
                or ('note' in row and (not isinstance(row['note'], str) or not row['note'].strip()))
                or (row['verdict'] != 'entails' and not row.get('note'))):
            raise ValueError('invalid checker result/verdict/note')


def item_manifest(items):
    return [{'id':x['id'], 'pointer':x['pointer'], 'basis':x['basis'],
             'value_sha256':projection.value_sha256(x['value']),
             'passage_sha256':projection.sha(x['source_passage'].encode('utf-8')),
             'item_identity':projection.item_identity(x, projection.sha(x['source_passage'].encode('utf-8')))}
            for x in items]


def result_manifest(results):
    return [{'id':r['id'], 'verdict':r['verdict'],
             'note_sha256':projection.sha(r['note'].encode('utf-8')) if r.get('note') else None,
             'result_item_sha256':projection.value_sha256(r)} for r in results]


def freeze(items, path, prompt, checker, configuration, envelope):
    valid_items(items)
    if (not isinstance(configuration, dict) or not configuration
            or projection.sha(prompt) != checker.get('prompt_sha256')):
        raise ValueError('explicit checker configuration and exact pinned prompt required')
    files = paths(path)
    absent(files)
    raw = encoded(items)
    request = prompt + b'\n\n' + raw
    meta = {'format': INPUT_FORMAT, 'producer_contract': projection.PRODUCER_CONTRACT,
            'target_projection': projection.TARGET_PROJECTION,
            'standard_module_sha256': projection.STANDARD_MODULE_SHA256,
            'checker': copy.deepcopy(checker), 'configuration': copy.deepcopy(configuration),
            'configuration_sha256': projection.value_sha256(configuration),
            'envelope': copy.deepcopy(envelope), 'created_at': now(),
            'input_sha256': projection.sha(raw), 'request_sha256': projection.sha(request),
            'prompt_sha256': projection.sha(prompt), 'item_manifest': item_manifest(items)}
    write_once(files[0], raw)
    write_once(files[1], request)
    write_once(files[2], encoded(meta))
    return meta


def load_input(path):
    files = paths(path)
    raw, request, metadata = (read(p) for p in files)
    items, meta = strict_json(raw), strict_json(metadata)
    valid_items(items)
    expected_keys = {'format', 'producer_contract', 'target_projection', 'standard_module_sha256',
                     'checker', 'configuration', 'configuration_sha256', 'envelope', 'created_at',
                     'input_sha256', 'request_sha256', 'prompt_sha256', 'item_manifest'}
    if (not isinstance(meta, dict) or set(meta) != expected_keys
            or metadata != encoded(meta)
            or meta['format'] != INPUT_FORMAT or meta['producer_contract'] != projection.PRODUCER_CONTRACT
            or meta['target_projection'] != projection.TARGET_PROJECTION
            or meta['standard_module_sha256'] != projection.STANDARD_MODULE_SHA256
            or meta['input_sha256'] != projection.sha(raw) or meta['request_sha256'] != projection.sha(request)
            or not request.endswith(b'\n\n' + raw)
            or projection.sha(request[:-len(raw)-2]) != meta['prompt_sha256']
            or not isinstance(meta['checker'], dict) or meta['checker'].get('prompt_sha256') != meta['prompt_sha256']
            or not isinstance(meta['configuration'], dict) or not meta['configuration']
            or meta['configuration_sha256'] != projection.value_sha256(meta['configuration'])):
        raise ValueError('frozen checker input/request/configuration binding differs')
    if meta['item_manifest'] != item_manifest(items):
        raise ValueError('frozen item manifest differs from actual checker-visible items')
    projection.reference()  # refuse dependency drift even for a packet without relational items
    return items, meta, request, {str(p): projection.sha(b) for p, b in zip(files, (raw, request, metadata))}


def run(path, output_path, checker_callback):
    """Callback gets EXACT frozen request bytes + explicit configuration.

    It must return its observed request/config digests and result_bytes. This is
    an IO contract, not authentication against a dishonest callback/operator.
    """
    items, meta, request, pins = load_input(path)
    if Path(path).parent.resolve() != Path(output_path).parent.resolve():
        raise ValueError('input and result must share one explicit artifact directory')
    files = result_paths(output_path)
    dispatch = dispatch_path(path)
    absent((*files, dispatch))
    commit_inputs(pins)
    started = now()
    dispatch_raw = encoded({'format': 'ohf-native-checker-dispatch/1',
                            'input_binding_sha256': pins[str(paths(path)[2])],
                            'request_sha256': meta['request_sha256'],
                            'configuration_sha256': meta['configuration_sha256'],
                            'output_name': Path(output_path).name, 'started_at': started})
    # Durable attempt before the callback. A failure/interruption never permits
    # a second callback on this frozen input, even with another output filename.
    write_once(dispatch, dispatch_raw)
    response = checker_callback(request, copy.deepcopy(meta['configuration']))
    if (not isinstance(response, dict) or set(response) != {'request_sha256', 'configuration_sha256', 'result_bytes'}
            or response['request_sha256'] != meta['request_sha256']
            or response['configuration_sha256'] != meta['configuration_sha256']
            or not isinstance(response['result_bytes'], bytes)):
        raise ValueError('returned checker result names another request/configuration')
    raw = response['result_bytes']
    if len(raw) > MAX_BYTES:
        raise ValueError('checker result exceeds byte limit')
    results = strict_json(raw)
    valid_results(items, results)
    if any(projection.sha(read(p)) != digest for p, digest in pins.items()):
        raise ValueError('frozen input changed while checker was running')
    receipt = {'format': RESULT_FORMAT, 'producer_contract': projection.PRODUCER_CONTRACT,
               'input_binding_sha256': pins[str(paths(path)[2])],
               'dispatch_sha256': projection.sha(dispatch_raw),
               'request_sha256': meta['request_sha256'], 'configuration_sha256': meta['configuration_sha256'],
               'result_sha256': projection.sha(raw), 'started_at': started, 'returned_at': now(),
               'result_manifest': result_manifest(results)}
    write_once(files[0], raw)
    write_once(files[1], encoded(receipt))
    return receipt


class VerifiedPair:
    def __init__(self, items, results, meta, receipt, dispatch, pins, receipt_sha, *, _token=None):
        if _token is not _VERIFIED:
            raise ValueError('VerifiedPair must be loaded from frozen checker IO, not constructed from verdicts')
        self.items, self.results = copy.deepcopy(items), copy.deepcopy(results)
        self.meta, self.receipt = copy.deepcopy(meta), copy.deepcopy(receipt)
        self.dispatch = copy.deepcopy(dispatch)
        self.pins, self.receipt_sha = dict(pins), receipt_sha
        self._file_pins = tuple(sorted(pins.items()))
        self._frozen = tuple(projection.canonical(x) for x in (self.items, self.results, self.meta, self.receipt, self.dispatch))

    def verify_arguments(self, items, results):
        if (projection.canonical(items) != self._frozen[0]
                or projection.canonical(results) != self._frozen[1]
                or tuple(projection.canonical(x) for x in (self.items, self.results, self.meta, self.receipt, self.dispatch)) != self._frozen
                or any(projection.sha(read(p)) != digest for p, digest in self._file_pins)):
            raise ValueError('merge input/result differs from frozen checker IO')

    def proof(self):
        self.verify_arguments(self.items, self.results)
        return copy.deepcopy({'input':self.meta, 'dispatch':self.dispatch, 'result':self.receipt})

    def binding_for(self, item, result):
        index = self.items.index(item)
        if self.results[index] != result:
            raise ValueError('result not returned for this frozen item')
        data = {'contract': projection.PRODUCER_CONTRACT,
                'standard_module_sha256': projection.STANDARD_MODULE_SHA256,
                'input_sha256': self.meta['input_sha256'], 'request_sha256': self.meta['request_sha256'],
                'input_binding_sha256': self.receipt['input_binding_sha256'],
                'result_sha256': self.receipt['result_sha256'], 'result_binding_sha256': self.receipt_sha,
                'dispatch_sha256': self.receipt['dispatch_sha256'],
                'result_item_sha256': projection.value_sha256(result),
                'item_identity': projection.item_identity(item, projection.sha(item['source_passage'].encode('utf-8'))),
                'item_id': item['id'], 'checker': copy.deepcopy(self.meta['checker']),
                'input_envelope': copy.deepcopy(self.meta['envelope']),
                'configuration_sha256': self.meta['configuration_sha256'],
                'started_at': self.receipt['started_at'], 'returned_at': self.receipt['returned_at'],
                'result': {'verdict': result['verdict'], 'note_sha256': projection.sha(result['note'].encode('utf-8')) if result.get('note') else None}}
        return ItemBinding(data, self.proof(), _token=_VERIFIED)


class ItemBinding:
    def __init__(self, data, proof, *, _token=None):
        if _token is not _VERIFIED:
            raise ValueError('item binding must originate from a verified checker response')
        self.data, self.proof = copy.deepcopy(data), copy.deepcopy(proof)


def binding_proven(item, entry, proofs):
    """Verify membership in the original hash-linked IO headers, no passages retained.

    Rewriting an entry's hashes cannot change the frozen input/result manifest.
    This is producer assertion integrity, not authentication of an operator who
    deliberately rewrites both the original IO evidence and all its commitments.
    """
    try:
        b = entry['checker_binding'];proof = proofs[b['result_binding_sha256']]
        if set(proof) != {'input','dispatch','result'}:
            return False
        meta, dispatch, result = proof['input'], proof['dispatch'], proof['result']
        if (projection.sha(encoded(meta)) != b['input_binding_sha256']
                or projection.sha(encoded(result)) != b['result_binding_sha256']
                or projection.sha(encoded(dispatch)) != b['dispatch_sha256']
                or result['dispatch_sha256'] != b['dispatch_sha256']
                or meta['format'] != INPUT_FORMAT or result['format'] != RESULT_FORMAT
                or meta['producer_contract'] != projection.PRODUCER_CONTRACT
                or result['producer_contract'] != projection.PRODUCER_CONTRACT
                or meta['standard_module_sha256'] != projection.STANDARD_MODULE_SHA256
                or meta['target_projection'] != projection.TARGET_PROJECTION
                or meta['checker'] != b['checker'] or meta['envelope'] != b['input_envelope']
                or projection.value_sha256(meta['configuration']) != b['configuration_sha256']):
            return False
        for key in ('request_sha256','configuration_sha256'):
            if meta[key] != result[key] or meta[key] != dispatch[key] or meta[key] != b[key]:
                return False
        if (meta['input_sha256'] != b['input_sha256'] or result['result_sha256'] != b['result_sha256']
                or dispatch['input_binding_sha256'] != b['input_binding_sha256']
                or result['input_binding_sha256'] != b['input_binding_sha256']
                or result['started_at'] != b['started_at'] or result['returned_at'] != b['returned_at']
                or dispatch['started_at'] != result['started_at']):
            return False
        inputs = [r for r in meta['item_manifest'] if r['id']==b['item_id']]
        outputs = [r for r in result['result_manifest'] if r['id']==b['item_id']]
        expected_input = {'id':b['item_id'], 'pointer':item['pointer'], 'basis':item['basis'],
                          'value_sha256':entry['value_sha256'], 'passage_sha256':entry['passage_sha256'],
                          'item_identity':b['item_identity']}
        expected_output = {'id':b['item_id'], 'verdict':entry['verdict'],
                           'note_sha256':entry.get('note_sha256'),'result_item_sha256':b['result_item_sha256']}
        return inputs == [expected_input] and outputs == [expected_output]
    except (KeyError, TypeError, ValueError):
        return False


def load_pair(path, output_path, checker, envelope):
    items, meta, request, pins = load_input(path)
    files = result_paths(output_path)
    raw, receipt_raw = (read(p) for p in files)
    results, receipt = strict_json(raw), strict_json(receipt_raw)
    valid_results(items, results)
    dispatch_file = dispatch_path(path)
    dispatch_raw = read(dispatch_file)
    dispatch = strict_json(dispatch_raw)
    expected_dispatch = {'format': 'ohf-native-checker-dispatch/1',
                         'input_binding_sha256': pins[str(paths(path)[2])],
                         'request_sha256': meta['request_sha256'],
                         'configuration_sha256': meta['configuration_sha256'],
                         'output_name': Path(output_path).name,
                         'started_at': receipt.get('started_at') if isinstance(receipt, dict) else None}
    expected_keys = {'format', 'producer_contract', 'input_binding_sha256', 'request_sha256',
                     'configuration_sha256', 'result_sha256', 'started_at', 'returned_at', 'dispatch_sha256',
                     'result_manifest'}
    if (meta['checker'] != checker or meta['envelope'] != envelope
            or not isinstance(receipt, dict) or set(receipt) != expected_keys
            or receipt_raw != encoded(receipt) or dispatch_raw != encoded(dispatch)
            or receipt['format'] != RESULT_FORMAT or receipt['producer_contract'] != projection.PRODUCER_CONTRACT
            or receipt['input_binding_sha256'] != pins[str(paths(path)[2])]
            or receipt['request_sha256'] != meta['request_sha256']
            or receipt['configuration_sha256'] != meta['configuration_sha256']
            or receipt['dispatch_sha256'] != projection.sha(dispatch_raw) or dispatch != expected_dispatch
            or receipt['result_sha256'] != projection.sha(raw)):
        raise ValueError('returned result/envelope differs from frozen checker request; no old-verdict/new-input merge')
    if receipt['result_manifest'] != result_manifest(results):
        raise ValueError('result manifest differs from actual returned result bytes')
    pins.update({str(files[0]): projection.sha(raw), str(files[1]): projection.sha(receipt_raw)})
    pins[str(dispatch_file)] = projection.sha(dispatch_raw)
    return VerifiedPair(items, results, meta, receipt, dispatch, pins, projection.sha(receipt_raw), _token=_VERIFIED)
