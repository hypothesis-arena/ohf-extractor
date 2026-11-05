#!/usr/bin/env python3
"""Time sanity for an OHF card: run with python3 -I time_check.py CARD [COMMIT_ISO].

Fails on: added.at earlier than any assessed_at in the added zone; any assessment.assessed_at later than the entailment checked_at of the
same pointer (or its parent value); round placeholder times (HH:00:00 / HH:MM:00);
any time later than the commit; added.at later than the commit.
"""
import json
import re
import sys
from datetime import datetime


def ts(s):
    return datetime.fromisoformat(s.replace('Z', '+00:00'))


def walk(o, p=''):
    """(JSON pointer, scalar) for every leaf; keys are escaped as RFC 6901 says (~0, ~1)."""
    if isinstance(o, dict):
        for k, v in o.items():
            yield from walk(v, f"{p}/{k.replace('~', '~0').replace('/', '~1')}")
    elif isinstance(o, list):
        for i, v in enumerate(o):
            yield from walk(v, f'{p}/{i}')
    else:
        yield p, o


card = json.load(open(sys.argv[1]))
commit = ts(sys.argv[2]) if len(sys.argv) > 2 else None
checked = {e['pointer']: e.get('checked_at') for e in card['added']['integrity']['entailment']}
errors = []
for path, value in walk(card):
    if not (isinstance(value, str) and re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?(Z|[+-]\d\d:\d\d)', value)):
        continue
    if re.search(r'T\d\d:\d\d:00(Z|\+00:00)$', value):
        errors.append(f'round time {path} = {value}')
    if commit and ts(value) > commit:
        errors.append(f'after commit {path} = {value}')
    if path.endswith('/assessment/assessed_at'):
        target = path[:-len('/assessment/assessed_at')]
        pointer = target
        while pointer and pointer not in checked:
            pointer = pointer.rsplit('/', 1)[0]
        if not pointer:
            errors.append(f'no entailment for {target}')
        elif checked[pointer] and ts(value) > ts(checked[pointer]):
            errors.append(f'assessed after check {target}: {value} > {checked[pointer]} ({pointer})')
# added.at is when the converter wrote the added zone: no value or assessment in it is later.
added_at = card['added'].get('at')
if added_at:
    for path, value in walk(card['added']):
        if path.endswith('/assessed_at') and isinstance(value, str) and ts(value) > ts(added_at):
            errors.append(f'added.at {added_at} earlier than {path} = {value}')
for e in errors:
    print(e)
print('TIME CHECK', 'FAIL' if errors else 'PASS', len(errors))
sys.exit(1 if errors else 0)
