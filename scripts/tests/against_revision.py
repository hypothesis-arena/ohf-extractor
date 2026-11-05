"""Run tests of this working tree against an **older revision of the kit**, and report each result.

Why this is in the repository. A review of 0.9.9 asked where the ten mutants were: they were tests in
`test_search.py`, but the claim beside them - "all ten fail on 7150ae4" - had been measured in a
scratch directory with a copied test file and a hand-edited constant, so the run that justified the
claim could not be repeated by anyone else. A mutant whose discrimination is not reproducible is a
test with a story attached. This script is that run.

What it does: checks the given revision out into a temporary worktree **outside** the repository,
copies the chosen test files of the working tree into it, and runs them there with pytest. The code
under test is the old revision; the tests are the new ones. A mutant that passes against the old
revision does not discriminate, and the summary says so per test.

    python scripts/tests/against_revision.py 7150ae4 -k "bioc or unreadable"

Two honest limits, both reported rather than hidden. A test that calls a function the old revision
does not have errors on the attribute, which is not a behavioural difference - the summary marks it
`no-api`, and a behavioural claim must not rest on those. And a test file that imports a name added
later cannot be collected at all against that revision, which the summary reports as `no-collect`
for the whole file; the route names in `test_search.py` are written out as literals for exactly this
reason, with one test binding them to the kit's constants.
"""
import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
# pytest's `-rA` short summary writes "PASSED path::test" and "FAILED path::test - reason". A node id
# of a parametrised case contains spaces - `test_x[payload0-an empty answer]` - so it runs to the end
# of the line, or to the " - " before a failure's reason. The first form of this stopped at the first
# space, which split one case into several names and counted 160 of 164; a review found it by running
# the script on the whole file and comparing with pytest's own total. Hence `totals`, below: the
# script now checks its own arithmetic against pytest and says so when they differ.
RESULT = re.compile(r'^(?P<outcome>PASSED|FAILED|ERROR|SKIPPED|XFAIL|XPASS)\s+'
                    r'(?P<file>\S+\.py)::(?P<test>.+?)(?: - .*)?$')
# A name the old revision does not have, or a signature it does not have: both mean the old code
# could not be asked to behave differently, so neither is evidence of a behavioural difference.
#
# Deliberately narrow. `has no attribute` on its own also matches the crash a mutant is *testing* -
# "'NoneType' object has no attribute 'get'" is the defect, not a missing API - so only an attribute
# of a module counts here. Marking that one as `no-api` would have hidden a real discrimination
# behind the classifier, which is the mistake this script exists to avoid making.
NO_API = re.compile(r"module '[\w.]+' has no attribute|cannot import name|is not defined"
                    r"|missing \d+ required positional argument|unexpected keyword argument")
HEADER = re.compile(r'^_+ (?P<test>.+?) _+$')
TOTALS = re.compile(r'(\d+) (passed|failed|error|errors|skipped|xfailed|xpassed)')


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('revision', help='the kit revision to run the tests against')
    ap.add_argument('-k', dest='select', default=None, help="pytest's -k expression")
    ap.add_argument('--tests', nargs='*', default=['scripts/tests/test_search.py'],
                    help='test files of this working tree to copy into the old revision')
    args = ap.parse_args(argv)

    work = Path(tempfile.mkdtemp(prefix='ohf-against-'))
    tree = work / 'tree'
    subprocess.run(['git', '-C', str(REPO), 'worktree', 'add', '--quiet', '--detach',
                    str(tree), args.revision], check=True)
    try:
        for name in args.tests:
            shutil.copy(REPO / name, tree / name)
        cmd = [sys.executable, '-m', 'pytest', *args.tests, '-rA', '--tb=short', '-q']
        if args.select:
            cmd += ['-k', args.select]
        run = subprocess.run(cmd, cwd=tree, capture_output=True, text=True)
        out = run.stdout + run.stderr
        lines = out.splitlines()
        if 'during collection' in out:
            print(f'no-collect: the tests do not import against {args.revision}')
            print('\n'.join(lines[-15:]))
            return 2
        verdict = {}
        for line in lines:
            hit = RESULT.match(line)
            if hit:
                verdict[hit.group('test')] = hit.group('outcome')
        # A failure whose reason is a missing attribute is not a behavioural difference: the old
        # revision has no such function to behave differently. `--tb=short` prints each
        # failure under its own header, so each reason is read beside the test it belongs to.
        current = None
        for line in lines:
            header = HEADER.match(line)
            if header:
                current = header.group('test')
            elif current and NO_API.search(line):
                verdict[current] = 'no-api'
                current = None
        for test, mark in verdict.items():
            print(f'{mark:9s} {test}')
        kinds = {m: sum(1 for v in verdict.values() if v == m) for m in sorted(set(verdict.values()))}
        print(f'\nagainst {args.revision}: ' + ', '.join(f'{n} {m}' for m, n in kinds.items()))
        counted = sum(int(n) for n, _ in TOTALS.findall(lines[-1] if lines else ''))
        if counted and counted != len(verdict):
            print(f'MISCOUNT: pytest reports {counted} cases and this script named {len(verdict)}. '
                  f'The summary above is not a count of the run; read pytest\'s own line:\n'
                  f'  {lines[-1]}')
        print('a mutant that discriminates by behaviour is FAILED here; no-api proves nothing')
        return 0 if verdict else 1
    finally:
        subprocess.run(['git', '-C', str(REPO), 'worktree', 'remove', '--force', str(tree)],
                       check=False)
        shutil.rmtree(work, ignore_errors=True)


if __name__ == '__main__':
    raise SystemExit(main())
