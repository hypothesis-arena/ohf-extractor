"""The converter hash reproduces from a copy of the kit alone, as the OHF repository recomputes it."""
import hashlib
import json
import re
import shutil
import subprocess
import sys

import ohfkit
from conftest import SCRIPTS

KIT = SCRIPTS.parent


def sha(data):
    return 'sha256:' + hashlib.sha256(data).hexdigest()


def ohf_pin(directory):
    """tools/converter_hash.converter_hash of the OHF repository: every file, by POSIX relative path."""
    files = sorted((f for f in directory.rglob('*') if f.is_file()), key=lambda f: f.relative_to(directory).as_posix())
    return sha(''.join(f'{f.relative_to(directory).as_posix()} {sha(f.read_bytes())}\n' for f in files).encode())


def test_rules_hash_is_the_pin_of_a_copy_of_the_rules(tmp_path):
    copy = tmp_path / 'converters' / 'ohf-extractor-x'
    (copy / 'references').mkdir(parents=True)
    (copy / 'scripts').mkdir()
    shutil.copy(KIT / 'SKILL.md', copy / 'SKILL.md')
    # Every file, not only the prose: a permission kept in a subdirectory and a table the kit reads
    # are both rules, and the hash covers them (K9).
    for f in (KIT / 'references').rglob('*'):
        if not f.is_file():
            continue
        target = copy / 'references' / f.relative_to(KIT / 'references')
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(f, target)
    for f in SCRIPTS.glob('*.py'):
        shutil.copy(f, copy / 'scripts' / f.name)
    assert ohf_pin(copy) == ohfkit.rules_hash()


def test_rules_hash_names_no_file_outside_the_kit():
    assert ohfkit.TIME_CHECK.parent == SCRIPTS
    assert str(KIT) not in ''.join(p.read_text() for p in SCRIPTS.glob('*.py') if p.name != 'ohfkit.py')


def time_check(tmp_path, card):
    path = tmp_path / 'card.json'
    path.write_text(json.dumps(card))
    return subprocess.run([sys.executable, '-I', str(ohfkit.TIME_CHECK), str(path)], capture_output=True, text=True)


def test_time_check_escapes_keys(tmp_path):
    """An assessment under a key with '/' is compared with the record of its escaped pointer."""
    card = {'added': {'at': '2026-10-20T10:11:19Z',
                      'layers': {'x': {'a/b': {'value': 'v', 'assessment': {'assessed_at': '2026-10-20T10:11:17Z'}}}},
                      'integrity': {'entailment': [{'pointer': '/added/layers/x/a~1b', 'checked_at': '2026-10-20T10:11:13Z'}]}}}
    r = time_check(tmp_path, card)
    assert r.returncode == 1 and 'assessed after check /added/layers/x/a~1b' in r.stdout, r.stdout
    card['added']['integrity']['entailment'][0]['checked_at'] = '2026-10-20T10:11:18Z'
    r = time_check(tmp_path, card)
    assert r.returncode == 0 and 'TIME CHECK PASS' in r.stdout, r.stdout


def test_a_released_version_never_names_two_sets_of_rules(tmp_path):
    """One version string must determine the rules it was built under. It did not: cards were built
    under `0.8.17` both at the release commit and after three later commits had changed the rules
    files, so two flagship cards carry the same `converter_version` and different
    `converter_hash` — `458ce6a7…` and `7b4c48ce…`. The acceptor found it and required that no
    release name two rules hashes.

    The guard that is checkable from the published tree alone: while the CHANGELOG has unreleased
    entries, the kit's version is a development version (`-dev`), so every card built in between says
    so; and a version without `-dev` means its pending sections are empty. Both `Unreleased`
    and a numbered `(not released)` heading identify pending entries.
    """
    changelog = (KIT / 'CHANGELOG.md').read_text()
    pending = re.findall(
        r'(?ms)^## (?:Unreleased|[0-9]+\.[0-9]+\.[0-9]+ \(not released\))\n(.*?)(?=^## |\Z)',
        changelog)
    has_unreleased = any(line.startswith('- ') for section in pending for line in section.splitlines())
    version = ohfkit.CONVERTER['version']
    if has_unreleased:
        assert version.endswith('-dev'), (
            f'the CHANGELOG has unreleased entries, so the rules have moved since {version} was '
            f'released: the version must be a development version until the next release')
    else:
        assert not version.endswith('-dev'), (
            'nothing is unreleased, so the version must be the released one')
