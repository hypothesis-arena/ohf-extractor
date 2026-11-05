#!/usr/bin/env python3
"""What an OHF 1.1 evidence line's quote states in numbers, against what the line records.

Usage: line_figures.py CARD --standard DIR

For each evidence line of a 1.1 card: the spans of its quote that the standard's patterns take for a
result in numbers, a dose and an age (`RESULT_NUMBER`, `DOSE_NUMBER`, `AGE_NUMBER` of
`tools/check_refs.py` in the checkout DIR, OHF 1.1 or later), what the line records for them (a
`result_estimate`, `intervention.dose`, `system.age_at_start`, or a gap), the sentences of the quote
that hold the result spans (from which `result_estimate.reported` is cut: it must be words of the
quote), and the standard's own codes for the line (`REF_ESTIMATE_IN_QUOTE`, `REF_ESTIMATE_NOT_QUOTED`,
`REF_CONDITION_IN_QUOTE`). The patterns and the codes are the standard's: this script keeps no copy of
them. It writes nothing; the estimate is the converter's reading of the quote.

Exit 0 when the standard reports none of those codes, 1 otherwise.
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import biodb  # noqa: E402

FIGURES = """
import json, sys
sys.path.insert(0, sys.argv[1] + '/tools')
import check_refs
card = json.load(sys.stdin)
def spans(pattern, text):
    return [{'text': m.group(), 'at': m.start()} for m in pattern.finditer(text)]
out = []
for line in check_refs.layers(card, 'added').get('evidence', {}).get('lines', []):
    quote = check_refs.unwrap(line.get('quote'))
    quote = quote if isinstance(quote, str) else ''
    out.append({'result': spans(check_refs.RESULT_NUMBER, quote), 'dose': spans(check_refs.DOSE_NUMBER, quote),
                'age': spans(check_refs.AGE_NUMBER, quote)})
found = check_refs.check(card)
codes = [x for x in found['errors'] + found['warnings']
         if x['code'] in ('REF_ESTIMATE_IN_QUOTE', 'REF_ESTIMATE_NOT_QUOTED', 'REF_CONDITION_IN_QUOTE')]
print(json.dumps({'lines': out, 'codes': codes}))
"""
CODES = ('REF_ESTIMATE_IN_QUOTE', 'REF_ESTIMATE_NOT_QUOTED', 'REF_CONDITION_IN_QUOTE')
SENTENCE_END = re.compile(r'(?<=[.!?])\s+(?=[A-Z(])')


def sentences(quote):
    """(start, sentence) of each sentence of the quote, as exact substrings."""
    out, at = [], 0
    for part in SENTENCE_END.split(quote):
        start = quote.index(part, at)
        out.append((start, part))
        at = start + len(part)
    return out


def gaps_for(card, index, member):
    paths = {f'evidence.lines[].{member}', f'evidence.lines[{index}].{member}'}
    return [{'disposition': g.get('disposition'), 'reason': g.get('reason')}
            for g in card['added'].get('gaps', []) if g.get('path') in paths]


def recorded(holder, member, line):
    node = line.get(holder)
    return isinstance(node, dict) and node.get(member) is not None


def figures(card, standard):
    """The worklist of each line: spans, what is recorded, the sentences, the standard's codes."""
    if card.get('standard_version') != '1.1':
        raise SystemExit('result_estimate and line conditions are OHF 1.1 members; this card is '
                         + str(card.get('standard_version')))
    got = json.loads(biodb.standard_run(standard, FIGURES, stdin=json.dumps(card)))
    lines = card['added']['layers'].get('evidence', {}).get('lines', [])
    out = []
    for i, (line, found) in enumerate(zip(lines, got['lines'])):
        quote = biodb._val(line.get('quote')) or ''
        codes = [x for x in got['codes'] if x['path'].startswith(f'evidence.lines[{i}].')]
        v = {'pointer': f'/added/layers/evidence/lines/{i}', 'line': line.get('id'), 'codes': codes}
        if found['result']:
            hit = sorted({s for start, s in sentences(quote)
                          for x in found['result'] if start <= x['at'] < start + len(s)}, key=quote.index)
            v['result'] = {'spans': [x['text'] for x in found['result']], 'sentences': hit,
                           'estimate': biodb._val(line.get('result_estimate')),
                           'gaps': gaps_for(card, i, 'result_estimate')}
        for kind, holder, member in (('dose', 'intervention', 'dose'), ('age', 'system', 'age_at_start')):
            if found[kind]:
                v[kind] = {'spans': [x['text'] for x in found[kind]], 'recorded': recorded(holder, member, line),
                           'gaps': gaps_for(card, i, f'{holder}.{member}')}
        out.append(v)
    return out


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    p.add_argument('card')
    p.add_argument('--standard', required=True, metavar='DIR', help='a checkout of OHF 1.1 or later')
    a = p.parse_args(argv)
    version = biodb.standard_version(a.standard)
    lines = figures(json.loads(Path(a.card).read_text()), a.standard)
    worklist = [v for v in lines if v['codes'] or 'result' in v or 'dose' in v or 'age' in v]
    print(json.dumps({'standard': version, 'lines': worklist}, ensure_ascii=False, indent=1))
    return 1 if any(v['codes'] for v in lines) else 0


if __name__ == '__main__':
    sys.exit(main())
