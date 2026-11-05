"""The README smoke uses the existing invented JATS fixture, never a real article."""
import json
import sys
from types import SimpleNamespace

import pytest

import entailment
import ohfkit
from conftest import PMCID, load, pytest_terminal_summary
from conftest import invented_budget_counter


def test_offline_conversion_and_validation(xml_workdir, monkeypatch):
    """Schema and hash smoke only; the source verification below is invented data."""
    attempts = {'network': 0, 'process': 0}
    active = [True]

    def deny(event, args):
        if not active[0]:
            return
        if event.startswith('socket.') and event not in ('socket.__new__', 'socket.gethostname'):
            attempts['network'] += 1
            raise AssertionError('quickstart smoke forbids network and DNS')
        if event in ('subprocess.Popen', 'os.system', 'os.posix_spawn', 'os.exec', 'os.fork'):
            attempts['process'] += 1
            raise AssertionError('quickstart smoke forbids external processes, including models')

    sys.addaudithook(deny)
    try:
        doc = ohfkit.Document(PMCID, xml_workdir)
        card = ohfkit.skeleton(budget_counter=invented_budget_counter,
            ident='h_quickstart', doc=doc, citation='Test A. A test. 2026', doi='10.0000/test',
            topic=['test'], sources={'p1': doc.src(1), 'p2': doc.src(2)}, author_names='A Test')
        card['author']['layers']['core']['statement'] = doc.author(
            1, 'We propose that X causes Y when recombination stops.')
        card['added']['layers']['core']['scope'] = {
            'value': 'In mice, X may cause Y.', 'src': 'p2',
            'paraphrase': True, 'basis_quote': 'X may cause Y'}
        card['added']['layers']['profile'] = {
            'domain': ['none'] if card['standard_version'] == '1.4' else 'none'}
        # Same synthetic verification shape as test_licence's emission fixture.
        # No source fetch or entailment checker is performed by this smoke.
        card['added']['source_verification'] = {
            'status': 'refetched_match', 'fetched_from': 'https://example.org/article',
            'fetched_at': '2026-10-24T07:00:00Z',
            'sha256': card['author']['source']['source_text_sha256'],
            'metadata_check': {'registry': 'none', 'record_url': 'https://example.org/record',
                               'checked_at': '2026-10-24T07:00:00Z', 'title_match': True,
                               'retracted': 'unknown'}}
        path = xml_workdir / 'card.json'
        ohfkit.finish(card, path)
        # Explicitly fake checker results populate the schema-required integrity list.
        monkeypatch.setattr(entailment, 'CHECKER', {
            **entailment.CHECKER, 'name': 'synthetic-quickstart-not-a-model'})
        docs = entailment.docs_for(card, xml_workdir)
        items = entailment.build(card, docs)
        assert items
        entailment.merge(card, items, [{'id': item['id'], 'verdict': 'entails'} for item in items],
                         docs, entailment.read_ledger(card, xml_workdir))
        ohfkit.finish(card, path)
        emitted = load(path)
        from tools import validate
        schema = json.loads((ohfkit.REPO / 'schema/hypothesis-1.schema.json').read_bytes())
        assert not validate.validation_errors(schema, emitted)
        assert emitted['content_hash'] == ohfkit.content_hash(emitted)
        # A genuine schema oracle, not only a successful writer/import.
        broken = dict(emitted)
        del broken['id']
        assert validate.validation_errors(schema, broken)
        assert attempts == {'network': 0, 'process': 0}
        print('quickstart: schema/hash PASS; network_attempts=0; model_calls=0; '
              'process_attempts=0; invented source verification and fake checker results')
    finally:
        active[0] = False


@pytest.mark.parametrize('skipped,expected', [(True, True), (False, False)])
def test_optional_feature_receipt(skipped, expected):
    receipt = 'evidence-export: SKIPPED (scrubber not supplied)'
    lines = []
    reporter = SimpleNamespace(
        stats={'skipped': [SimpleNamespace(longrepr=('test_evidence.py', 1, receipt))]
               if skipped else []}, write_line=lines.append)
    pytest_terminal_summary(reporter)
    assert lines == ([receipt] if expected else [])
