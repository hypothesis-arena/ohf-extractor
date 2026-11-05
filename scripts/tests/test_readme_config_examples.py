"""The public examples use the existing POSIX environment interface, without credentials."""
import os
from pathlib import Path
import subprocess

import pytest

import ohfkit


ROOT = Path(__file__).resolve().parents[2]


def load_example(example, tmp_path):
    checkout = tmp_path / 'checkout with spaces'
    checkout.mkdir()
    # Only shell builtins run. The child gets no ambient credentials or shell startup hooks.
    result = subprocess.run(
        ['/bin/sh', '-c', 'set -eu; . "$1"; '
         'printf "%s\\0" "$OHF_REPO" "$OHF_MODEL" "$OHF_CONTACT" '
         '"${PYTEST_DISABLE_PLUGIN_AUTOLOAD-}"',
         'readme-example', str(ROOT / 'examples/config' / example)],
        cwd=checkout, env={'PATH': os.defpath}, capture_output=True, check=True, timeout=5)
    values = result.stdout.decode().split('\0')
    assert values.pop() == '' and len(values) == 4
    assert result.stderr == b''
    return checkout, dict(zip(
        ['OHF_REPO', 'OHF_MODEL', 'OHF_CONTACT', 'PYTEST_DISABLE_PLUGIN_AUTOLOAD'], values))


@pytest.mark.parametrize('example,autoload', [
    ('offline.env.example', '1'), ('article.env.example', ''),
])
def test_readme_environment_examples_load(example, autoload, tmp_path):
    checkout, env = load_example(example, tmp_path)
    assert env == {'OHF_REPO': str(checkout / 'open-hypothesis-format'),
                   'OHF_MODEL': '', 'OHF_CONTACT': '',
                   'PYTEST_DISABLE_PLUGIN_AUTOLOAD': autoload}


@pytest.mark.parametrize('example', ['offline.env.example', 'article.env.example'])
def test_example_requires_a_real_model_identifier_for_a_builder(example, tmp_path, monkeypatch):
    _, env = load_example(example, tmp_path)
    monkeypatch.setattr(ohfkit, 'MODEL', env['OHF_MODEL'] or None)
    with pytest.raises(ValueError, match='^set OHF_MODEL to the model that reads the article'):
        ohfkit.model()
