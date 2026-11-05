"""Fixtures: a work directory with a small Europe PMC-style XML or an HTML page, and a card
built on it with the kit, as a builder would."""
import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

import entailment  # noqa: E402
import ohfkit  # noqa: E402

# A card records the model that read the article, from OHF_MODEL (ohfkit.model). These fixtures are
# not a reading, so they name a test model rather than depend on the environment.
ohfkit.MODEL = ohfkit.MODEL or 'test-model'


def pytest_terminal_summary(terminalreporter):
    """Keep the optional export feature's skip visible even with pytest -q."""
    receipt = 'evidence-export: SKIPPED (scrubber not supplied)'
    if any(receipt in str(report.longrepr)
           for report in terminalreporter.stats.get('skipped', ())):
        terminalreporter.write_line(receipt)


PMCID = 'PMC0000001'
CC_BY = ('© The Author(s) 2026. This article is licensed under a Creative Commons Attribution 4.0 International '
         'License. To view a copy of this licence, visit http://creativecommons.org/licenses/by/4.0/.')
PARAS = [
    'We propose that X causes Y when recombination stops. This would explain Z, e.g. in mice.',
    'In mice, X may cause Y. The effect was 3.5 times larger in males (Fig. 2).',
    'A third paragraph says nothing about X.',
]
RETRIEVED = '2026-10-20T10:11:12Z'


def jats(paras, permissions=CC_BY):
    perm = f'<permissions><license><license-p>{permissions}</license-p></license></permissions>' if permissions else ''
    body = ''.join(f'<p>{p}</p>' for p in paras)
    return (f'<article><front><article-meta>{perm}</article-meta></front><body><sec>{body}</sec></body>'
            '</article>').encode()


def put(workdir, name, data):
    (workdir / name).write_bytes(data)
    (workdir / f'{name}.retrieved').write_text(RETRIEVED)


@pytest.fixture
def xml_workdir(tmp_path):
    put(tmp_path, f'{PMCID}.xml', jats(PARAS))
    return tmp_path


def invented_budget_counter():
    """Injected fake complete zero for invented fixtures, never a real conversion measurement."""
    return {'model_calls': 0, 'http_requests': 0, 'coverage': 'complete',
            'scope': 'invented-fixture-only; injected fake checker and transport'}


def build_card(workdir, scope='In mice, X may cause Y.', src='p2', out=None, **skel):
    """A card with one paraphrased added value (two checker items) on the XML of `workdir`."""
    doc = ohfkit.Document(PMCID, workdir)
    sources = {'p1': doc.src(1), 'p2': doc.src(2), 'p3': doc.src(3)}
    card = ohfkit.skeleton(budget_counter=invented_budget_counter, ident='h_test', doc=doc, citation='Test A. A test. 2026', doi='10.0000/test',
                           topic=['test'], sources=sources, author_names='A Test', **skel)
    card['author']['layers']['core']['statement'] = doc.author(1, 'We propose that X causes Y when recombination stops.')
    card['added']['layers']['core']['scope'] = {'value': scope, 'src': src, 'paraphrase': True,
                                                'basis_quote': 'X may cause Y'}
    out = out or workdir / 'card.json'
    ohfkit.finish(card, out)
    return out


def load(path):
    return json.loads(Path(path).read_text())


def run_pass(card_path, workdir, verdict='entails', note=None):
    """The entailment pass: input from the card, a checker output, then merge through the CLI."""
    import subprocess
    card = load(card_path)
    items = entailment.build(card, entailment.docs_for(card, workdir))
    inp = workdir / 'in.json'
    inp.write_text(json.dumps(items))
    out = workdir / 'out.json'
    out.write_text(json.dumps([{'id': x['id'], 'verdict': verdict, **({'note': note} if note else {})} for x in items]))
    return subprocess.run([sys.executable, '-I', str(SCRIPTS / 'entailment.py'), 'merge', str(card_path),
                           str(workdir), str(inp), str(out)], capture_output=True, text=True)
