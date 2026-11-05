# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Hypothesis Arena contributors
# Adapted from Hypothesis Arena tools/check_language.py; modified for standalone
# exact-count line allowances. See third_party/language_gate/{LICENSE,NOTICE}.
"""Check tracked source text against exact, count-bound Cyrillic line allowances.

This checks source language only. It does not approve translation quality,
scientific content, rights or publication. There are no whole-file exemptions.
"""
import argparse
from collections import Counter
import hashlib
import html
import json
from pathlib import Path, PurePosixPath
import re
import subprocess

RANGES = ((0x400, 0x52f), (0x1c80, 0x1c8f), (0x2de0, 0x2dff),
          (0xa640, 0xa69f), (0x1e030, 0x1e08f))
STRING = re.compile(r'"(?:[^"\\\x00-\x1f]|\\(?:["\\/bfnrt]|u[0-9a-fA-F]{4}))*"')
TEXT_SUFFIXES = {'.py', '.md', '.txt', '.json', '.jsonl', '.xml', '.html', '.htm',
                 '.svg', '.yml', '.yaml', '.js', '.ts', '.css', '.sh', '.toml', '.csv'}
CLASSES = {'synthetic-fixture', 'runtime-source-language-matching'}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def cyrillic(text):
    return any(lo <= ord(char) <= hi for char in text for lo, hi in RANGES)


def decoded_cyrillic(text):
    """Inspect JSON-escaped strings, including nested payloads and object keys."""
    def probe(value, depth=0):
        if depth > 48:
            raise ValueError('JSON decoding depth budget')
        if isinstance(value, dict):
            return any(probe(key, depth + 1) or probe(child, depth + 1)
                       for key, child in value.items())
        if isinstance(value, list):
            return any(probe(child, depth + 1) for child in value)
        if not isinstance(value, str):
            return False
        if cyrillic(value):
            return True
        try:
            decoded = json.loads(value)
        except (ValueError, RecursionError):
            return False
        return decoded != value and probe(decoded, depth + 1)
    if probe(text):
        return True
    return any(probe(json.loads(match[0])) for match in STRING.finditer(text))


def unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON key')
        result[key] = value
    return result


def relative_path(name):
    if (not isinstance(name, str) or not name or '\x00' in name or '\\' in name
            or PurePosixPath(name).is_absolute() or '..' in PurePosixPath(name).parts
            or PurePosixPath(name).as_posix() != name or any(c in name for c in '*?[')):
        raise ValueError('paths must be exact and repository-relative')
    return name


def line_units(raw, name):
    """Fingerprint complete lines; decoding never grants a file-wide exemption."""
    try:
        encoding = ('utf-32' if raw.startswith((b'\xff\xfe\x00\x00', b'\x00\x00\xfe\xff'))
                    else 'utf-16' if raw.startswith((b'\xff\xfe', b'\xfe\xff')) else 'utf-8-sig')
        text = raw.decode(encoding)
        if '\x00' in text:
            raise UnicodeError('NUL in text')
    except UnicodeError:
        if Path(name).suffix.lower() in TEXT_SUFFIXES:
            raise ValueError('tracked text is not supported Unicode text')
        return []  # Non-text bytes are outside this source-text gate.
    markup = Path(name).suffix.lower() in {'.html', '.htm', '.xml', '.svg'}
    return [sha(line.encode()) for line in text.splitlines()
            if decoded_cyrillic(line) or (markup and decoded_cyrillic(html.unescape(line)))]


def load_policy(path):
    data = json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=unique_pairs)
    if (not isinstance(data, dict)
            or set(data) != {'schema', 'inventory', 'classification_plan_sha256', 'entries'}
            or data['schema'] != 'ohf-extractor-language-allowlist/1'):
        raise ValueError('unknown language policy schema')
    inventory = data['inventory']
    if (not isinstance(inventory, dict) or set(inventory) != {'sha256', 'base_commit', 'rows'}
            or not isinstance(inventory['rows'], list)
            or any(type(row) is not int for row in inventory['rows'])
            or inventory['rows'] != list(range(166, 173))
            or not isinstance(inventory['base_commit'], str)
            or not re.fullmatch('[0-9a-f]{40}', inventory['base_commit'])):
        raise ValueError('invalid inventory binding')
    for digest in (inventory.get('sha256'), data['classification_plan_sha256']):
        if not isinstance(digest, str) or not re.fullmatch('[0-9a-f]{64}', digest):
            raise ValueError('invalid provenance digest')
    if not isinstance(data['entries'], list) or len(data['entries']) != 7:
        raise ValueError('expected seven inventory-bound paths')
    seen_paths, seen_rows = set(), set()
    for entry in data['entries']:
        if (not isinstance(entry, dict)
                or set(entry) != {'path', 'class', 'inventory_row_id', 'source_sha256', 'units'}):
            raise ValueError('invalid allowance entry')
        name = relative_path(entry['path'])
        row = entry['inventory_row_id']
        if (not isinstance(row, str) or name in seen_paths or row in seen_rows
                or row not in {f'rows/{i}' for i in inventory['rows']}):
            raise ValueError('duplicate or foreign allowance')
        seen_paths.add(name)
        seen_rows.add(row)
        if (not isinstance(entry['class'], str) or entry['class'] not in CLASSES
                or not isinstance(entry['source_sha256'], str)
                or not re.fullmatch('[0-9a-f]{64}', entry['source_sha256'])
                or not isinstance(entry['units'], list) or not entry['units']):
            raise ValueError('invalid classification or literal binding')
        seen_units = set()
        for item in entry['units']:
            if (not isinstance(item, dict) or set(item) != {'sha256', 'count'}
                    or not isinstance(item['sha256'], str)
                    or not re.fullmatch('[0-9a-f]{64}', item['sha256'])
                    or type(item['count']) is not int or item['count'] < 1):
                raise ValueError('invalid literal count or digest')
            if item['sha256'] in seen_units:
                raise ValueError('duplicate literal allowance')
            seen_units.add(item['sha256'])
    return data


def audit(raw, name, entries):
    entry = next((e for e in entries if e['path'] == name), None)
    allowed = Counter({u['sha256']: u['count'] for u in entry['units']}) if entry else Counter()
    actual = Counter(line_units(raw, name))
    errors = []
    if actual - allowed:
        errors.append(name + ': Cyrillic outside exact line/count allowance')
    if allowed - actual:
        errors.append(name + ': allowance count mismatch (missing or changed literal)')
    return errors


def check(root, policy):
    root = root.resolve()
    raw = subprocess.check_output(['git', '-C', str(root), 'ls-files', '-z', '--cached'])
    names = raw.decode('utf-8').rstrip('\x00').split('\x00') if raw else []
    if len(names) != len(set(names)):
        raise ValueError('duplicate tracked paths or unmerged index')
    names = [relative_path(name) for name in names]
    errors = [entry['path'] + ': allowed path is not tracked'
              for entry in policy['entries'] if entry['path'] not in names]
    for name in names:
        path = root / name
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            errors.append(name + ': symlink requires explicit source review')
        elif not path.is_file():
            errors.append(name + ': tracked source missing')
        else:
            try:
                errors.extend(audit(path.read_bytes(), name, policy['entries']))
            except (ValueError, OSError, RecursionError) as error:
                errors.append(name + ': unreadable tracked text: ' + str(error))
    return errors


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--policy', type=Path)
    args = parser.parse_args(argv)
    try:
        policy = load_policy(args.policy or args.root / 'data/policy/language-allowlist.json')
        errors = check(args.root, policy)
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        errors = ['language gate refused: ' + str(error)]
    print(json.dumps({'status': 'FAIL' if errors else 'PASS', 'findings': errors}, indent=2))
    return int(bool(errors))


if __name__ == '__main__':
    raise SystemExit(main())
