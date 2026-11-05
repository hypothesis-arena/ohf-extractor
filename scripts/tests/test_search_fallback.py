# Export fixture provenance: inputs named in SYNTHETIC-FIXTURES.json are
# constructed test data; their identifiers and dates are regression tokens.
# Recorded-response descriptions below identify the replaced source snapshots,
# not live-service provenance for those synthetic replacement inputs.
"""Offline bounded retrieval: 91 hits are not 91 relevant papers.

The broad page is recorded; primary zero and other control responses are synthetic.
No article sentence is retained: only metadata and hash provenance, never an efficacy oracle.
"""
import hashlib
import json
import socket
import urllib.parse
import urllib.request
from pathlib import Path
from types import SimpleNamespace

import pytest

import search

FIX = Path(__file__).parent / 'fixtures/search/fallback-skin'
PRIMARY = 'ELOVL1 AND CERS3 AND barrier AND longevity'
BROAD = 'ELOVL1 AND CERS3'
EMPTY = b'{"hitCount":0,"resultList":{"result":[]}}'


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def denied(*args, **kwargs):
        pytest.fail('real network is forbidden in fallback tests')
    for name in ('socket', 'socketpair', 'fromfd', 'create_connection', 'getaddrinfo'):
        monkeypatch.setattr(socket, name, denied)
    monkeypatch.setattr(urllib.request, 'urlopen', denied)


class Recorded:
    def __init__(self, *, primary=EMPTY, fallback=None, error=False):
        self.primary = primary
        self.fallback = fallback if fallback is not None else (FIX/'epmc-broad.json').read_bytes()
        self.error = error
        self.urls = []

    def __call__(self, url):
        self.urls.append(url)
        params = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
        assert url.startswith(search.EPMC+'search?')
        query = params['query'][0]
        if self.error:
            return 400, b'{"error":"invented collection failure"}', {}
        if query == BROAD:
            return 200, self.fallback, {}
        assert query in (PRIMARY, f'({PRIMARY}) NOT PUB_TYPE:review',
                         f'({BROAD}) NOT PUB_TYPE:review', 'another broad query',
                         '(another broad query) NOT PUB_TYPE:review') or 'FIRST_IDATE' in query
        return 200, self.primary if query == PRIMARY else EMPTY, {}


def make(tmp_path, **kwargs):
    transport = Recorded(**kwargs)
    return search.Searcher(tmp_path, get=transport, sleep=lambda _: None, clock=lambda: 0.0), transport


def test_primary_zero_fallback_retains_recorded_source_and_discloses_91_not_91_relevant(tmp_path):
    s, net = make(tmp_path)
    out = s.literature_fallback(PRIMARY, [BROAD], limit=3, sources=('europepmc',))
    assert out['outcome'] == 'ok' and out['fallback']['used'] is True
    assert out['fallback']['trigger'] == 'empty'
    assert out['searches'][0]['calls'][0]['hit_count'] == 0
    assert out['searches'][0]['calls'][0]['found'] == 0
    assert 'PMC13243600' in [w['pmcid'] for w in out['works']]
    assert out['searches'][1]['calls'][0]['hit_count'] == 91
    assert '91 hits are not 91 relevant papers' in json.dumps(out)
    assert out['hit_count'] is None  # Never sum duplicate/cross-query service counts.
    assert out['coverage']['relevance'] == 'not_assessed'
    assert out['fallback']['queries_run'] == 2 and len(net.urls) == 4
    expected_queries = [PRIMARY, f'({PRIMARY}) NOT PUB_TYPE:review', BROAD,
                        f'({BROAD}) NOT PUB_TYPE:review']
    assert [urllib.parse.parse_qs(urllib.parse.urlsplit(u).query)['query'][0] for u in net.urls] == expected_queries
    rows = search.read_log(tmp_path)
    assert [r['tool'] for r in rows] == ['literature']*4 + ['literature_fallback']
    assert rows[-1] == out
    assert [c['call_id'] for q in out['searches'] for c in q['calls']] == [r['call_id'] for r in rows[:-1]]
    assert all(r['responses'][0]['sha256'] for r in rows[:-1])
    # Runtime retention contains only recorded/synthetic bibliographic JSON.
    assert all(p.read_bytes() in ((FIX/'epmc-broad.json').read_bytes(), EMPTY)
               for p in (tmp_path/search.RESPONSES).iterdir())


def test_fixture_retains_licence_attribution_and_unretained_excerpt_provenance():
    info = json.loads((FIX/'LICENCE-AND-PROVENANCE.json').read_text())
    assert info['licence']['id'] == 'CC-BY-NC-ND-4.0'
    assert info['licence']['url'].endswith('/by-nc-nd/4.0/')
    assert 'no author-zone conversion' in info['licence']['kit_conversion']
    assert info['article']['doi'] == '10.1038/s41598-026-48648-3'
    assert hashlib.sha256((FIX/'epmc-broad.json').read_bytes()).hexdigest() == info['provenance']['response_sha256']
    assert info['excerpt']['retained'] is False and info['excerpt']['characters'] == 120
    assert len(info['excerpt']['sha256']) == len(info['excerpt']['sentence_utf8_sha256']) == 64
    assert not list(FIX.glob('PMC*.txt')) and not list(FIX.glob('*.xml'))
    rights = (FIX/'LICENSE-THIRD-PARTY').read_text()
    assert 'CC BY-NC-ND 4.0' in rights and 'does not relicense' in rights
    assert 'DOI: 10.1038/s41598-026-48648-3' in rights
    assert '91 hits are not 91 relevant papers' in info['provenance']['notice']
    assert 'Synthetic empty response' in info['provenance']['primary_zero']


def test_adequate_primary_keeps_existing_calls_and_records_exact(tmp_path, monkeypatch):
    # Same clock/UUID sequence lets the complete native call records be compared.
    monkeypatch.setattr(search, 'now', lambda: '2026-10-27T05:30:00Z')
    counter = iter(range(100))
    monkeypatch.setattr(search.uuid, 'uuid4', lambda: SimpleNamespace(hex=f'{next(counter):032x}'))
    adequate = (FIX/'epmc-broad.json').read_bytes()
    ordinary, net1 = make(tmp_path/'ordinary', primary=adequate)
    expected = ordinary.literature(PRIMARY, 3, ('europepmc',))
    counter = iter(range(100))
    selected, net2 = make(tmp_path/'selected', primary=adequate)
    out = selected.literature_fallback(PRIMARY, [BROAD], limit=3, sources=('europepmc',))
    assert net1.urls == net2.urls and len(net2.urls) == 2
    assert search.read_log(tmp_path/'selected')[:-1] == expected
    assert out['fallback']['used'] is False
    assert out['fallback']['trigger'] is None
    assert out['fallback']['queries_not_run'] == [BROAD]
    assert out['fallback']['stop'] == 'candidate_threshold_met'


def test_poor_candidate_count_uses_fallback_but_does_not_assert_relevance(tmp_path):
    raw = json.loads((FIX/'epmc-broad.json').read_text())
    raw['resultList']['result'] = raw['resultList']['result'][:1]
    raw.pop('nextCursorMark', None)
    s, _ = make(tmp_path, primary=json.dumps(raw).encode())
    out = s.literature_fallback(PRIMARY, [BROAD], limit=3, sources=('europepmc',))
    assert out['fallback']['trigger'] == 'below_candidate_threshold'
    assert out['found'] == 3
    assert out['coverage']['measure'] == 'unique source IDs, not relevance or scientific completeness'


@pytest.mark.parametrize('kwargs', [
    {'fallback_queries': [BROAD, 'x', 'y']}, {'fallback_queries': []}, {'fallback_queries': BROAD},
    {'fallback_queries': [PRIMARY]}, {'fallback_queries': [BROAD, BROAD]}, {'fallback_queries': [' ']},
    {'limit': 0}, {'limit': 21}, {'limit': True}, {'max_works': 61}, {'max_works': False},
    {'min_works': 0}, {'min_works': 61}, {'min_works': True}, {'sources': ()},
    {'sources': ('foreign',)}, {'sources': ({},)}, {'sort': []}, {'sources': ('europepmc', 'europepmc')},
    {'sort': 'unknown'}, {'query': 'x'*2001}, {'as_of': 'not-a-date'}])
def test_caps_and_invalid_plans_refuse_before_any_request_or_log(tmp_path, kwargs):
    s, net = make(tmp_path)
    args = {'query': PRIMARY, 'fallback_queries': [BROAD], **kwargs}
    with pytest.raises(search.SearchError):
        s.literature_fallback(**args)
    assert net.urls == [] and not (tmp_path/search.LOG).exists()


def test_result_cap_is_explicit_and_primary_wins_stable_order(tmp_path):
    s, net = make(tmp_path, primary=(FIX/'epmc-broad.json').read_bytes())
    out = s.literature_fallback(PRIMARY, [BROAD], limit=3, max_works=2, min_works=2,
                                sources=('europepmc',))
    assert out['found'] == len(out['works']) == 2
    assert [w['pmcid'] for w in out['works']] == ['PMC13664863', 'PMC13243600']
    assert out['fallback']['results_truncated'] is True
    assert out['fallback']['unique_candidates_seen'] == 3
    assert out['fallback']['caps']['selected_results'] == 2
    assert out['fallback']['used'] is False and len(net.urls) == 2


def test_queries_stop_at_plan_cap_without_silent_successful_coverage(tmp_path):
    s, net = make(tmp_path, fallback=EMPTY)
    out = s.literature_fallback(PRIMARY, [BROAD, 'another broad query'], limit=3,
                                sources=('europepmc',))
    assert out['fallback']['queries_run'] == out['fallback']['caps']['logical_queries'] == 3
    assert len(net.urls) == out['fallback']['caps']['service_variant_calls'] == 6
    assert out['fallback']['stop'] == 'queries_exhausted'
    assert out['coverage']['status'] == 'queries_exhausted'
    assert out['coverage']['relevance'] == 'not_assessed'


def test_collection_failure_is_unknown_not_zero_and_never_triggers_an_empty_fallback(tmp_path):
    s, net = make(tmp_path, error=True)
    out = s.literature_fallback(PRIMARY, [BROAD], limit=3, sources=('europepmc',))
    assert out['outcome'] == 'incomplete'
    assert out['fallback']['used'] is False and len(net.urls) == 2
    assert out['fallback']['trigger'] == 'collection_incomplete'
    assert out['coverage']['status'] == 'unknown_collection_incomplete'
    assert all(c['hit_count'] is None for c in out['searches'][0]['calls'])
    assert out['hit_count'] is None
    assert 'collection failure is not zero' in json.dumps(out)


def test_cutoff_and_sort_stay_in_each_existing_call(tmp_path):
    s, net = make(tmp_path)
    out = s.literature_fallback(PRIMARY, [BROAD], limit=3, sources=('europepmc',),
                                sort='cited', as_of='2026-01-01')
    assert len(net.urls) == 4
    assert all('FIRST_IDATE' in urllib.parse.parse_qs(urllib.parse.urlsplit(u).query)['query'][0] for u in net.urls)
    assert all(urllib.parse.parse_qs(urllib.parse.urlsplit(u).query)['sort'] == ['CITED desc'] for u in net.urls)
    assert out['ask']['as_of'] == '2026-01-01'


def test_cli_discloses_fallback_and_candidate_notice(tmp_path, monkeypatch, capsys):
    s, net = make(tmp_path)
    monkeypatch.setattr(search, 'Searcher', lambda *_: s)
    assert search.main(['literature', PRIMARY, '--fallback-query', BROAD, '--sources', 'europepmc',
                        '--limit', '3', '--workdir', str(tmp_path)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert 'PMC13243600' in [w['pmcid'] for w in out['works']]
    assert '91 hits are not 91 relevant papers' in json.dumps(out)
    assert out['fallback']['used'] is True


def test_cli_collection_failure_returns_nonzero_with_unknown_coverage(tmp_path, monkeypatch, capsys):
    s, net = make(tmp_path, error=True)
    monkeypatch.setattr(search, 'Searcher', lambda *_: s)
    status = search.main(['literature', PRIMARY, '--fallback-query', BROAD, '--sources', 'europepmc',
                          '--limit', '3', '--workdir', str(tmp_path)])
    out = json.loads(capsys.readouterr().out)
    assert status == 1
    assert out['outcome'] == 'incomplete'
    assert out['coverage']['status'] == 'unknown_collection_incomplete'
    assert out['hit_count'] is None and out['fallback']['used'] is False
    assert len(net.urls) == 2


@pytest.mark.parametrize('args', [['known-search', 'queries.json', '--fallback-query', BROAD],
                                ['literature', PRIMARY, '--min-works', '2']])
def test_cli_refuses_misplaced_fallback_options_before_search(tmp_path, monkeypatch, args):
    monkeypatch.setattr(search, 'Searcher', lambda *_: pytest.fail('invalid CLI must not instantiate a searcher'))
    with pytest.raises(SystemExit) as e:
        search.main(args)
    assert e.value.code == 2
