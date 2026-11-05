"""Keep the CHANGELOG's section headings honest about what is released.

Every section of a version that has a tag says so, with the tag's date and the commit it points at,
and only the version being prepared says `(not released)`. Those words had gone stale on eight
sections at once - every release from 0.9.2 to 0.9.9 was tagged while its section still called itself
unreleased - which is the ordinary fate of a fact kept in prose beside a fact kept in git.

So the headings are derived from the tags rather than typed: `--write` rewrites them, `--check`
reports what disagrees and exits non-zero, and a test runs the check, so the next release cannot
leave them stale without the suite saying so.

A lightweight tag (`v0.9.2` through `v0.9.8`) has no date of its own, so the date shown is that of the
commit it names; an annotated tag (`v0.9.0`, `v0.9.1`, `v0.9.9`) has its own. The heading does not
distinguish them, because what a reader needs is the day the release was cut and the commit to check
it against; which kind of tag carries that is in git.
"""
import argparse
import re
import subprocess
import sys
from pathlib import Path

# The repository is this file's own, never the CHANGELOG's directory: a caller may point the module
# at another file to check it, and the tags still come from here.
REPO = Path(__file__).resolve().parents[1]
CHANGELOG = REPO / 'CHANGELOG.md'
# One version and its release line, never a range: the early history is written as `## 0.3.0 - 0.3.3`
# and such a heading is not a claim about one release. The first form of this rewrote those into
# "(not released)", which would have deleted real information to tidy a format - so the pattern
# refuses a range, and a heading is only touched when its version has a tag or when it calls itself
# unreleased.
HEADING = re.compile(r'^## (?P<version>\d+\.\d+\.\d+)(?P<rest>(?: \(not released[^)]*\)'
                     r'| - released [^\n]*)?)$', re.M)
UNRELEASED = '(not released)'


def tags(repo=None):
    """{version: (date, commit)} for every v* tag of this repository."""
    out = subprocess.run(['git', '-C', str(repo or REPO), 'tag', '-l', 'v*',
                          '--format=%(refname:short)\t%(creatordate:short)'],
                         capture_output=True, text=True, check=True).stdout
    found = {}
    for line in out.strip().splitlines():
        if not line.strip():
            continue
        name, date = line.split('\t')
        commit = subprocess.run(['git', '-C', str(repo or REPO), 'rev-parse', '--short',
                                 f'{name}^{{commit}}'], capture_output=True, text=True,
                                check=True).stdout.strip()
        found[name.lstrip('v')] = (date, commit)
    return found


def claimed(version, rest, released):
    """Whether this heading makes a claim about a release, and so must agree with the tags: the
    version has a tag, or the heading calls itself unreleased, or it says it was released.

    A heading that says "released" for a version with **no** tag is the false claim in the other
    direction, and the first form of this skipped it - it looked only for a tag or for the words
    `(not released)`, so a wrong "released" line would have stood.
    """
    return version in released or UNRELEASED in rest or '- released' in rest


def heading_for(version, released):
    if released is None:
        return f'## {version} {UNRELEASED}'
    date, commit = released
    return f'## {version} - released {date}, tag v{version} on {commit}'


def check(text, released):
    """The headings that disagree with the tags: [(version, heading as it is, heading as it should be)]."""
    wrong = []
    for hit in HEADING.finditer(text):
        version = hit.group('version')
        if not claimed(version, hit.group('rest'), released):
            continue
        want = heading_for(version, released.get(version))
        if hit.group(0).strip() != want:
            wrong.append((version, hit.group(0).strip(), want))
    return wrong


def write(text, released):
    def one(m):
        version = m.group('version')
        if not claimed(version, m.group('rest'), released):
            return m.group(0)
        return heading_for(version, released.get(version))

    return HEADING.sub(one, text)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument('--write', action='store_true', help='rewrite the headings from the tags')
    mode.add_argument('--check', action='store_true', help='check the headings (also the default)')
    args = ap.parse_args(argv)
    text = CHANGELOG.read_text()
    released = tags()
    wrong = check(text, released)
    if args.write:
        CHANGELOG.write_text(write(text, released))
        print(f'{len(wrong)} heading(s) rewritten from the tags')
        return 0
    for version, now, want in wrong:
        print(f'{version}: {now!r}\n{" " * len(version)}  should be {want!r}')
    print(f'{len(wrong)} heading(s) disagree with the tags')
    return 1 if wrong else 0


if __name__ == '__main__':
    raise SystemExit(main())
