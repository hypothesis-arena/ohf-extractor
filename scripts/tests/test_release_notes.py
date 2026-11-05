"""The CHANGELOG's section headings are derived from the tags, and the suite says so.

Eight sections at once had gone stale - every release from 0.9.2 to 0.9.9 was tagged while its own
section still called itself unreleased - which is the ordinary fate of a fact kept in prose beside a
fact kept in git. The headings are generated now, and this test is what keeps the next release from
leaving them stale: a tagged version whose section says `(not released)` fails here.
"""
import subprocess
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import release_notes  # noqa: E402

@pytest.fixture
def owned_tag_repo(tmp_path, monkeypatch):
    """Measure lightweight and annotated tags in an owned Git repository."""
    repo = tmp_path / 'owned-release-tags'
    repo.mkdir()
    def git(*args):
        return subprocess.run(['git', '-c', 'core.hooksPath=/dev/null',
                               '-c', 'commit.gpgsign=false', '-c', 'tag.gpgsign=false',
                               '-c', 'user.name=Fixture',
                               '-c', 'user.email=fixture@example.invalid',
                               '-C', str(repo), *args],
                              capture_output=True, text=True, check=True)
    git('init', '--initial-branch=main')
    expected = {}
    for version, commit_date, tag_date in [
            ('0.9.2', '2026-01-02', None),
            ('0.9.8', '2026-02-03', None),
            ('0.9.9', '2026-03-04', '2026-04-05')]:
        monkeypatch.setenv('GIT_AUTHOR_DATE', commit_date + 'T03:04:05+00:00')
        monkeypatch.setenv('GIT_COMMITTER_DATE', commit_date + 'T03:04:05+00:00')
        git('commit', '--allow-empty', '-m', 'Owned release-check fixture ' + version)
        commit = git('rev-parse', '--short', 'HEAD').stdout.strip()
        if tag_date is None:
            git('tag', 'v' + version)
        else:
            monkeypatch.setenv('GIT_COMMITTER_DATE', tag_date + 'T03:04:05+00:00')
            git('tag', '-a', 'v' + version, '-m', 'Owned annotated tag')
        expected[version] = (tag_date or commit_date, commit)
    monkeypatch.setattr(release_notes, 'REPO', repo)
    return repo, expected



def test_every_tagged_version_says_so_in_the_changelog():
    """The check the maintenance script performs, as a test. It is the whole point of deriving the
    headings: the claim "released" now comes from the tag that released it."""
    wrong = release_notes.check(release_notes.CHANGELOG.read_text(), release_notes.tags())
    assert wrong == [], '\n'.join(f'{v}: {now!r} should be {want!r}' for v, now, want in wrong)


def test_a_version_with_no_tag_is_marked_unreleased():
    """And the other direction, so that the check cannot be satisfied by calling everything released:
    the version being prepared has no tag, and its heading must say so."""
    released = release_notes.tags()
    text = '## 9.9.9 - released 2026-10-24, tag v9.9.9 on abc1234\n'
    wrong = release_notes.check(text, released)
    assert wrong and wrong[0][2] == '## 9.9.9 (not released)'


def test_the_documented_check_alias_and_write_are_exclusive():
    assert release_notes.main(['--check']) == 0
    with pytest.raises(SystemExit) as error:
        release_notes.main(['--check', '--write'])
    assert error.value.code == 2


def test_a_range_heading_is_left_alone():
    """The early history is written as `## 0.3.0 - 0.3.3`, and such a heading is not a claim about
    one release. The first form of this rewrote those into "(not released)" - deleting real
    information to tidy a format - so a range is refused by the pattern, and this is the case that
    says so."""
    text = '## 0.3.0 – 0.3.3\nsomething\n## 0.1.0 – 0.2.2\n'
    assert release_notes.check(text, release_notes.tags()) == []
    assert release_notes.write(text, release_notes.tags()) == text


def test_the_script_reports_and_exits_non_zero_on_a_stale_heading(tmp_path, monkeypatch, owned_tag_repo):
    """The script is what a person runs, so its exit code is part of the behaviour: zero when the
    headings agree with the tags, non-zero when they do not."""
    assert release_notes.main([]) == 0
    stale = tmp_path / 'CHANGELOG.md'
    stale.write_text('## 0.9.9 (not released)\n')
    monkeypatch.setattr(release_notes, 'CHANGELOG', stale)
    assert release_notes.main([]) == 1
    assert release_notes.main(['--write']) == 0
    assert 'released' in stale.read_text() and 'not released' not in stale.read_text()


def test_the_dates_come_from_git_and_not_from_the_text(owned_tag_repo):
    """Both kinds of tag are read: a lightweight tag has no date of its own and the date shown is its
    commit's, an annotated tag has one. What a reader needs is the day and the commit; which kind of
    tag carries it is in git, and this test is here to notice if one kind stops being read at all."""
    repo, expected = owned_tag_repo
    found = release_notes.tags()
    assert list(found) == list(expected)
    assert found == expected
    assert {'0.9.2', '0.9.8', '0.9.9'} <= set(found), sorted(found)
    for version, (date, commit) in found.items():
        assert len(date) == 10 and date.startswith('2026-'), (version, date)
        assert subprocess.run(['git', '-C', str(repo), 'cat-file', '-t', commit], capture_output=True,
                              text=True).stdout.strip() == 'commit'
