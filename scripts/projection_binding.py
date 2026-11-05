"""Pinned pure standard projection; native conditioning and producer lineage stay native.

No fallback to an ambient module, old checkout, network or abbreviated target.
"""
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import types

STANDARD_COMMIT = 'bf1f582f977c2ac65e5537ebd9f1b1b19ae328d3'
STANDARD_MODULE_SHA256 = 'sha256:add24440e8c0782ec22e23b5f89c590e0c0208f9964ee45a3069cf6e4dc11720'
STANDARD_SCHEMA_SHA256 = 'sha256:ae1769a44c19bb575d2e4c7c903e756386b1831945b3bd788028c71f36c5c951'
TARGET_PROJECTION = 'ohf-target-projection/1'
PRODUCER_CONTRACT = 'ohf-native-checker-binding/1'
RELATIONAL = re.compile(r'^/added/layers/evidence/lines/(\d+)/(direction|indirectness)$')
_modules = {}


def sha(raw):
    return 'sha256:' + hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def value_sha256(value):
    return sha(canonical(value))


def reference():
    root = os.environ.get('OHF_REPO')
    if not root:
        raise ValueError('projection contract requires explicit OHF_REPO')
    root = Path(root).resolve()
    path = root / 'tools/check_ledger.py'
    schema_path = root / 'schema/hypothesis-1.schema.json'
    try:
        raw = path.read_bytes()
    except OSError as error:
        raise ValueError('pinned projection source unavailable') from error
    if sha(raw) != STANDARD_MODULE_SHA256:
        raise ValueError('projection API pin differs: use the accepted standard candidate, never fallback')
    try:
        schema_raw = schema_path.read_bytes()
    except OSError as error:
        raise ValueError('pinned projection schema unavailable') from error
    if sha(schema_raw) != STANDARD_SCHEMA_SHA256:
        raise ValueError('projection schema pin differs: use the pinned source-mode schema')
    key = str(path)
    if key not in _modules:
        module = types.ModuleType('ohf_native_pinned_projection_reference')
        module.__file__ = str(path)
        exec(compile(raw, str(path), 'exec'), module.__dict__)
        class SchemaPath(type(path)):
            def read_bytes(self):
                if self.absolute() == schema_path.absolute():
                    return schema_raw
                return super().read_bytes()

            def read_text(self, encoding=None, errors=None):
                return self.read_bytes().decode(encoding or 'utf-8', errors or 'strict')
        # The new source-mode gate reads this exact verified snapshot. Existing
        # non-schema data readers keep their source-root path semantics.
        module.Path = SchemaPath
        if module.TARGET_PROJECTION != TARGET_PROJECTION:
            raise ValueError('projection API version differs')
        _modules[key] = module
    return _modules[key]


def target_statement(card, line):
    if card.get('standard_version') != '1.4':
        raise ValueError('UNSUPPORTED_VERSION: full target projection requires OHF 1.4')
    return reference().target_statement(card, line)


def require_resolved(target):
    if reference()._unresolved_scientific_target(target):
        raise ValueError('unresolved external scientific target: no checker input or active support')


def checked_relation(card, pointer, node):
    if card.get('standard_version') != '1.4':
        raise ValueError('UNSUPPORTED_VERSION: full relational projection requires OHF 1.4')
    match = RELATIONAL.fullmatch(pointer)
    if match is None:
        raise ValueError('not a native relational field')
    index, field = int(match[1]), match[2]
    line = card['added']['layers']['evidence']['lines'][index]
    api = reference()
    direction_pointer = f'/added/layers/evidence/lines/{index}/direction'
    result = api.checked_value(card, direction_pointer, node)
    require_resolved(result['target_statement'])
    if field == 'indirectness':
        # Same full target and semantic line conditions. The judged field is kept
        # once, at its native position, and the other relational field is context.
        result['indirectness'] = result.pop('direction')
        result['evidence_conditions'].pop('indirectness', None)
        if 'direction' in line:
            direction = line['direction']
            result['evidence_conditions']['direction'] = copy.deepcopy(
                direction.get('value') if isinstance(direction, dict) else direction)
    if isinstance(line.get('quote'), str):
        result['line_quote'] = line['quote']
    return result


def is_projected(item):
    return RELATIONAL.fullmatch(item.get('pointer', '')) is not None


def target_of(item):
    value = item.get('value')
    target = value.get('target_statement') if isinstance(value, dict) else None
    if not isinstance(target, dict) or target.get('format') != TARGET_PROJECTION:
        raise ValueError('missing full scientific target projection')
    require_resolved(target)
    return target


def item_identity(item, passage_sha256):
    # rN is transport order, not scientific identity. Retain it in frozen IO, but
    # permit an explicit carry when unrelated input items renumber it.
    return value_sha256({'pointer': item['pointer'], 'basis': item['basis'],
                         'value_sha256': value_sha256(item['value']),
                         'passage_sha256': passage_sha256})


def valid_binding(item, entry):
    """Structural IO provenance, not authentication of a checker or its judgement."""
    binding = entry.get('checker_binding')
    if not isinstance(binding, dict) or binding.get('contract') != PRODUCER_CONTRACT:
        return False
    passage = entry.get('passage_sha256')
    try:
        if binding.get('item_identity') != item_identity(item, passage):
            return False
        if binding.get('result') != {'verdict': entry.get('verdict'), 'note_sha256': entry.get('note_sha256')}:
            return False
        times = (binding.get('started_at'), binding.get('returned_at'), entry.get('checked_at'))
        if (any(not isinstance(t, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z', t) for t in times)
                or not times[0] <= times[1] <= times[2]):
            return False
        if any(not isinstance(binding.get(k), str) or not re.fullmatch(r'sha256:[0-9a-f]{64}', binding[k])
               for k in ('input_sha256', 'request_sha256', 'input_binding_sha256',
                         'result_sha256', 'result_binding_sha256', 'result_item_sha256', 'dispatch_sha256')):
            return False
        return binding.get('standard_module_sha256') == STANDARD_MODULE_SHA256
    except (KeyError, TypeError, ValueError):
        return False


def eligible(item, entry, proofs=None):
    if not is_projected(item):
        return True
    target = target_of(item)
    from checker_io import binding_proven
    return (entry.get('target_projection') == TARGET_PROJECTION
            and entry.get('target_sha256') == value_sha256(target)
            and valid_binding(item, entry) and binding_proven(item, entry, proofs or {}))
