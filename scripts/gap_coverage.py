#!/usr/bin/env python3
"""Every empty applicable field has a gap: gap_coverage.py CARD [CARD ...]

The standard's `tools/check_gaps.py` checks the gaps a card lists, and says so in its own first
paragraph: it "does not show that every missing applicable field is listed". So a field left empty
with no gap beside it is invisible — invisible to the card, which says nothing about it, and
invisible to every check, because the kit demands a gap only where one was written. That is the
worst kind of absence: not a question answered "unknown", but a question nobody asked.

This is the other half. The candidate fields are the standard's own gap paths
(`spec/gap-path-policy.json`, 180 of them: the paths for which a gap may be recorded at all), and
the path is resolved with the standard's own resolver, so this check adds no field list of its own
and cannot drift from the specification. For each candidate:

- a filled value anywhere it can appear is an answer, and needs no gap;
- an empty one whose parent exists is applicable, so it needs a gap at that path — missing, it is
  reported as UNRECORDED;
- an empty one whose parent does not exist belongs to a layer or profile the card does not use. It
  is absent, not empty, and needs nothing (the rule `check_gaps.py` states for a profile a card
  does not select).

A card may be read with `--known N`, which passes when the count is exactly N: a card accepted
before this check existed has its number of unrecorded fields recorded rather than rewritten, and
the number cannot drift unnoticed. Exit 0 when nothing is unrecorded, or when the count matches
`--known`.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ohfkit  # noqa: E402


def _tools():
    """The standard's gap checker and its gap-path policy, from OHF_REPO.

    No domain-profile vocabulary is read here, and that is the point. This kit used to pick the file
    itself - first a fixed `profiles-1.json`, then the newest `profiles-*.json` - and either way it
    was guessing at something the standard decides. The first guess left the kit demanding a gap on
    `profile.aging_hallmarks[]`, a path of a profile the card does not select, which the standard's
    checker refuses as `GAP_PROFILE_FIELD`: no card could satisfy both halves. The second guess was
    no better in kind, and a review showed it with a decoy - an extra `profiles-99.json` in the
    checkout, which `max()` would have chosen and the standard would have ignored.

    So the question is put to the standard instead, about the gaps themselves: `refuses_a_gap_on`
    asks `check_gaps.check` with `profiles=None`, which is how the standard names its own default."""
    repo = ohfkit.REPO
    sys.path.insert(0, str(repo / 'tools'))
    import check_gaps  # noqa: PLC0415
    policy = json.loads((repo / 'spec/gap-path-policy.json').read_text())
    return check_gaps, policy


def refuses_a_gap_on(card, paths):
    """Of `paths`, those where the standard refuses a gap because the card selects no such profile.

    The card is copied with a gap written at each path and handed to the standard's own checker with
    `profiles=None`, so the vocabulary is the one the standard chooses and not one this kit picked.
    Only `GAP_PROFILE_FIELD` is read off the answer: every other code is this kit's business or the
    card's, and a path refused for another reason is still a path the kit may ask about."""
    check_gaps, _policy = _tools()
    paths = list(paths)
    if not paths:
        return set()
    probe = json.loads(json.dumps(card))
    probe['added']['gaps'] = [{'path': path, 'disposition': 'not_supplied',
                               'reason': 'Probe: does the standard admit a gap here.'}
                              for path in paths]
    repo = ohfkit.REPO
    answer = check_gaps.check(probe, json.loads((repo / 'spec/gap-path-policy.json').read_text()),
                              check_gaps.load(repo / 'spec/field-catalogue.json'),
                              check_gaps.load(repo / 'spec/mapping.json'))
    return {e.get('path') for e in answer.get('errors', [])
            if e.get('code') == 'GAP_PROFILE_FIELD'}


def _since():
    """{path: the version the field was added in} from the standard's field catalogue.

    The gap-path policy carries no version, so a 1.0 card checked against a 1.1 checkout was told to
    record gaps for fields its own version does not have - thirteen of them, measured on the first card
    where this happened - while the standard's own `check_gaps` refused every one of those gaps as
    GAP_PATH_UNKNOWN. The two halves of the check contradicted each other.

    The version is in `spec/field-catalogue.json`, in the `since` member (36 fields carry `1.1`), which
    is where the standard keeps it and where its own checker reads it; the owners asked the kit to join
    the policy to the catalogue on the path rather than keep a second copy that could drift. So this is
    the join, and the blunt refusal it replaces is gone.
    """
    catalogue = json.loads((ohfkit.REPO / 'spec/field-catalogue.json').read_text())
    return {row['path']: row.get('since') for row in catalogue['fields'] if row.get('path')}


def _after(since, declared):
    """Whether a field added in `since` is newer than the version the card declares."""
    if not since or not declared:
        return False
    part = lambda v: [int(n) for n in str(v).split('.')[:2]]  # noqa: E731
    return part(since) > part(declared)


def unrecorded(card):
    """The applicable paths of the policy that are empty and have no gap, in policy order.

    A path of a domain profile the card does not select is not demanded, because the standard's
    own checker refuses a gap there (GAP_PROFILE_FIELD). Demanding one would have made the two
    halves of the check contradict each other: no card could satisfy both at once. Found on the
    first card built to reach zero unrecorded fields, whose profile.domain is `none`, so that
    every path of every profile is unselected.
    """
    check_gaps, policy = _tools()
    # A field the card's own version does not have is not demanded: the standard's checker refuses a gap
    # for it, so demanding one would make the two halves contradict each other.
    newer = {path for path, since in _since().items() if _after(since, card.get('standard_version'))}
    # Every path of the policy is probed, not the ones whose names begin with `profile.`: a domain
    # profile owns paths across the layers - `predictions[].intercurrent_events[]` is one - and
    # filtering by the name was the same guess in smaller clothes, which cost one more round.
    unselected = refuses_a_gap_on(card, [row['path'] for row in policy['fields']])
    recorded = {g.get('path') for g in card.get('added', {}).get('gaps', []) if isinstance(g, dict)}
    out = []
    for row in policy['fields']:
        path = row['path']
        if path in newer:
            continue
        if path in recorded or path in unselected:
            continue
        found, parent_exists = check_gaps.values(card, path)
        if any(check_gaps.filled(v) for v in found):
            continue
        if not parent_exists:
            continue  # a layer or profile the card does not use: absent, not empty
        out.append({'path': path, 'na_allowed': row.get('na_allowed')})
    return out


def empty_lists(card):
    """Empty lists whose items the catalogue knows but whose own path it does not.

    `core.assumptions` is the case: the policy and the catalogue carry
    `core.assumptions[].id`, `.text`, `.fundamental` and `.assessment`, and no path for the list
    itself. So when a card holds no assumption at all, there is nothing for `unrecorded` to find —
    the component paths resolve to nothing because their parent list is absent — and a gap at
    `core.assumptions` is refused by the standard's own checker with `GAP_PATH_UNKNOWN` (tested,
    2026-10-21, against a card of the accepted set).

    These are therefore reported, never demanded: the kit cannot ask for a gap the standard will
    not accept, and it will not invent a path of its own. Until the standard has one, an empty list
    of this kind is carried by the report and by the map of missing answers.
    """
    check_gaps, policy = _tools()
    lists, out = {}, []
    for row in policy['fields']:
        head, sep, _ = row['path'].partition('[]')
        if sep and head:
            lists[head] = True
    for path in sorted(lists):
        found, _ = check_gaps.values(card, path)
        if any(check_gaps.filled(v) for v in found):
            continue
        parent = path.rpartition('.')[0]
        if parent:
            up, parent_exists = check_gaps.values(card, parent)
            if not (parent_exists and any(check_gaps.filled(v) for v in up)):
                continue  # the layer itself is not in the card
        out.append(path)
    return out


def uncited_sources(card):
    """Source records the card declares and no value cites, in declaration order.

    A source record asserts a retrieval: a document, a locator and the time it was read. One that no
    value names asserts a retrieval nothing rests on, and the report counts sources, so it inflates
    the breadth the card appears to have. It is also a useful marker. On the two flagship cards every
    uncited source that pointed at the article under conversion sat in a paragraph where a blind
    second reader had found something the card did not answer — eight for eight: the leftover key is
    the fingerprint of a value the converter meant to write and did not.
    """
    declared = card.get('added', {}).get('sources', {})
    used = set()

    def walk(node):
        if isinstance(node, dict):
            if isinstance(node.get('src'), str):
                used.add(node['src'])
            if isinstance(node.get('component_sources'), dict):
                used.update(v for v in node['component_sources'].values() if isinstance(v, str))
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(card)
    return [k for k in declared if k not in used]


def report(card, known=None):
    """(text, ok) for one card."""
    rows = unrecorded(card)
    lines = [f"UNRECORDED {r['path']}: the field is empty and no gap records it "
             f"(fill it, or add a gap at this path with its disposition)" for r in rows]
    for path in empty_lists(card):
        lines.append(f'NOTE {path}: the list is empty and the standard has no gap path for it, so none '
                     'is demanded here; carry it in the report and in the map of missing answers')
    for key in uncited_sources(card):
        rec = card.get('added', {}).get('sources', {}).get(key) or {}
        lines.append(f'NOTE source {key} ({rec.get("locator", "no locator")}) is declared and no value '
                     'cites it: either a value belongs there and was never written, or the record '
                     'should go')
    if known is None:
        ok = not rows
    else:
        ok = len(rows) == known
        if not ok:
            lines.append(f'KNOWN COUNT {known} expected, {len(rows)} found: a card accepted before this '
                         'check may keep its number, but the number may not change unnoticed')
    lines.append(f'GAP COVERAGE {"PASS" if ok else "FAIL"} {len(rows)} unrecorded'
                 + (f' (known {known})' if known is not None else ''))
    return '\n'.join(lines), ok


def main():
    ap = argparse.ArgumentParser(description='Every empty applicable field has a gap.')
    ap.add_argument('cards', nargs='+')
    ap.add_argument('--known', type=int, help='pass when the count is exactly this (a card accepted earlier)')
    a = ap.parse_args()
    ok = True
    for path in a.cards:
        card = json.loads(Path(path).read_text())
        text, good = report(card, a.known)
        print(f'--- {Path(path).name}')
        print(text)
        ok &= good
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
