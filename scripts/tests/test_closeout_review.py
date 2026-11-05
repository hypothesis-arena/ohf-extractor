"""Production-path controls for the separate closeout form; synthetic metadata, no network."""
import json

import pytest

import search
from test_search import answering_log, bare_card, COMMENT, ERRATUM_WORK, PARTIAL_WORK, Routed


def production_status(workdir, *, types=('Partial Retraction',), links=(), updates=(), retracted=None,
                      ident=None, as_of=None):
    s = search.Searcher(workdir, sleep=lambda *_: None, clock=lambda: 0.0)
    target = {'source': 'MED', 'id': '8888', 'pmid': '8888', 'doi': PARTIAL_WORK['doi'],
              'title': 'Synthetic partial work', 'pubTypeList': {'pubType': list(types)},
              'commentCorrectionList': {'commentCorrection': list(links)}, 'retracted': retracted}
    s.get = Routed([
        ('search?query=', json.dumps({'hitCount': 1, 'resultList': {'result': [target]}}).encode(), 200),
        ('api.crossref.org/works/', json.dumps({'message': {'updated-by': list(updates)}}).encode(), 200),
    ])
    return s, s.status(ident or PARTIAL_WORK['doi'], as_of=as_of)


def carried_partial(workdir):
    answering_log(workdir, [PARTIAL_WORK])
    card = bare_card()
    card['added']['sources'] = {'p': {'source': 'https://doi.org/' + PARTIAL_WORK['doi']}}
    return card


LINK = {'type': 'Partial retraction in', 'source': 'MED', 'id': '9999'}
READ_HASH = search.sha256(b'A synthetic notice that the test reader read, with no retained body.')


@pytest.mark.parametrize('types,links,updates,retracted', [
    (('Partial Retraction',), (), (), None),
    (('Partial Retraction of Publication',), (), (), True),
    (('Journal Article',), (LINK,), (), None),
    (('Journal Article',), (), ({'type': 'partial_retraction', 'DOI': '10.1111/notice'},), None),
    (('Journal Article',), (), ({'type': 'partial-retraction', 'DOI': '10.1111/notice'},), None),
])
def test_production_partial_status_is_never_none_found_or_corrected(tmp_path, types, links, updates, retracted):
    _, status = production_status(tmp_path, types=types, links=links, updates=updates, retracted=retracted)
    assert status['outcome'] == 'ok'
    assert status['status'] == 'partial'
    assert any(n['status'] == 'partial' for n in status['notices'])


@pytest.mark.parametrize('links', [(), (LINK,), ({'type': 'Erratum in', 'source': 'MED', 'id': '9999'},)])
def test_production_metadata_discovery_is_not_a_notice_reading(tmp_path, links):
    card = carried_partial(tmp_path)
    s, status = production_status(tmp_path, links=links)
    assert status['outcome'] == 'ok' and status['notices']
    out = search.closeout(card, tmp_path)
    assert out['closed'] is False
    assert out['without_verdict'][0]['notice_read'] is False
    assert all('search?query=' in url or 'api.crossref.org/works/' in url for url in s.get.urls)


def test_a_separate_bound_reading_closes_the_specific_partial_work_without_keeping_text(tmp_path):
    card = carried_partial(tmp_path)
    s, status = production_status(tmp_path, links=(LINK,))
    requests = list(s.get.urls)
    reading = s.notice_read(PARTIAL_WORK['doi'], 'MED:9999', status['call_id'], 'paragraph 2', READ_HASH, 'test-reader')
    assert s.get.urls == requests, 'an attestation must not secretly fetch a notice body'
    out = search.closeout(card, tmp_path)
    assert out['closed'] is True
    row = out['answering_works'][0]
    assert row['notice_read'] is True and row['verdict'] == 'carried'
    assert row['partial_notices_required'] == ['pmid:9999']
    assert row['notice_readings'][0]['call_id'] == reading['call_id']
    assert reading['status_record']['sha256'] == search.record_hash(status)
    assert 'A synthetic notice that' not in (tmp_path / search.LOG).read_text()


@pytest.mark.parametrize('field,value', [
    ('id', '10.1111/a-different-work'), ('notice', 'MED:9998'), ('status_call', 'not-a-call'),
    ('locator', ''), ('reader', ' '), ('notice_sha256', 'not-a-hash'),
])
def test_an_unbound_or_incomplete_reading_is_refused_without_writing_it(tmp_path, field, value):
    carried_partial(tmp_path)
    s, status = production_status(tmp_path, links=(LINK,))
    args = {'ident': PARTIAL_WORK['doi'], 'notice': 'MED:9999', 'status_call': status['call_id'],
            'locator': 'paragraph 2', 'notice_sha256': READ_HASH, 'reader': 'test-reader'}
    args['ident' if field == 'id' else field] = value
    before = (tmp_path / search.LOG).read_bytes()
    with pytest.raises(search.SearchError):
        s.notice_read(**args)
    assert (tmp_path / search.LOG).read_bytes() == before


def test_an_ordinary_correction_cannot_bind_a_partial_notice_reading(tmp_path):
    card = carried_partial(tmp_path)
    s, status = production_status(tmp_path, types=('Published Erratum',),
                                  links=({'type': 'Erratum in', 'source': 'MED', 'id': '9999'},))
    with pytest.raises(search.SearchError):
        s.notice_read(PARTIAL_WORK['doi'], 'MED:9999', status['call_id'], 'paragraph 2', READ_HASH, 'reader')
    assert search.closeout(card, tmp_path)['closed'] is False


def test_changing_the_bound_status_record_invalidates_the_reading(tmp_path):
    card = carried_partial(tmp_path)
    s, status = production_status(tmp_path, links=(LINK,))
    s.notice_read(PARTIAL_WORK['doi'], 'MED:9999', status['call_id'], 'paragraph 2', READ_HASH, 'reader')
    calls = search.read_log(tmp_path)
    next(r for r in calls if r['call_id'] == status['call_id'])['notices'][0]['kind'] = 'Ordinary correction'
    (tmp_path / search.LOG).write_text(''.join(json.dumps(r) + '\n' for r in calls))
    assert search.closeout(card, tmp_path)['closed'] is False


def test_two_known_partial_notices_need_two_bound_readings(tmp_path):
    card = carried_partial(tmp_path)
    s, status = production_status(tmp_path, links=(LINK, {**LINK, 'id': '9998'}))
    s.notice_read(PARTIAL_WORK['doi'], 'MED:9999', status['call_id'], 'paragraph 2', READ_HASH, 'reader')
    assert search.closeout(card, tmp_path)['closed'] is False
    s.notice_read(PARTIAL_WORK['doi'], 'MED:9998', status['call_id'], 'paragraph 3', READ_HASH, 'reader')
    assert search.closeout(card, tmp_path)['closed'] is True


def test_reading_the_notice_does_not_supply_a_missing_work_verdict(tmp_path):
    carried_partial(tmp_path)
    s, status = production_status(tmp_path, links=(LINK,))
    s.notice_read(PARTIAL_WORK['doi'], 'MED:9999', status['call_id'], 'paragraph 2', READ_HASH, 'reader')
    out = search.closeout(bare_card(), tmp_path)
    assert out['closed'] is False
    assert out['without_verdict'][0]['notice_read'] is True
    assert out['without_verdict'][0]['verdict'] is None


def test_a_valid_reading_attestation_survives_production_metadata_failure(tmp_path, monkeypatch):
    s = answering_log(tmp_path, [COMMENT])
    def unavailable(*args, **kwargs):
        raise search.SearchError('synthetic metadata unavailable')
    monkeypatch.setattr(s, 'epmc_search', unavailable)
    record = s.not_cited(COMMENT['doi'], 'other_endpoint', 'Results table 2')
    assert record['outcome'] == 'failed'
    assert search.valid_not_cited(record)
    assert search.closeout(bare_card(), tmp_path)['answering_works'][0]['verdict'] == 'set_aside'
    assert search.closeout(bare_card(), tmp_path)['closed'] is True
    assert not search.screen(bare_card(), tmp_path)['unscreened']


@pytest.mark.parametrize('reason,locator', [('retracted', 'Results'), ('invented', 'Results'), ('off_topic', '')])
def test_a_failed_record_is_not_automatically_a_valid_attestation(tmp_path, reason, locator):
    s = answering_log(tmp_path, [COMMENT])
    record = {'call_id': 'invalid', 'tool': 'not_cited', 'outcome': 'failed', 'works': [],
              'ask': {'id': COMMENT['doi'], 'reason': reason, 'locator': locator}}
    s.log(record)
    assert not search.valid_not_cited(record)
    assert search.closeout(bare_card(), tmp_path)['closed'] is False
    assert search.screen(bare_card(), tmp_path)['unscreened']


def test_production_semantic_refusal_does_not_close_a_corrected_work(tmp_path):
    work = {'source_id': 'MED:6666', 'pmid': '6666', 'doi': '10.1111/evl3.6666',
            'title': 'A corrected work', 'type': 'Published Erratum'}
    s = answering_log(tmp_path, [work])
    s.get = Routed([('search?query=', json.dumps({'hitCount': 1, 'resultList': {'result': [ERRATUM_WORK]}}).encode(), 200)])
    s.sleep = lambda *_: None
    record = s.not_cited(work['doi'], 'retracted', 'the correction notice')
    assert record['outcome'] == 'failed'
    assert not search.valid_not_cited(record)
    assert search.closeout(bare_card(), tmp_path)['closed'] is False
    assert search.screen(bare_card(), tmp_path)['unscreened']


def discovered_work(workdir, disposition, initial_type='Comment; Journal Article'):
    """The answering search did not say partial; its existing disposition is already closed."""
    work = {**PARTIAL_WORK, 'type': initial_type}
    s = answering_log(workdir, [work])
    card = bare_card()
    if disposition == 'carried':
        card['added']['sources'] = {'p': {'source': 'https://doi.org/' + work['doi']}}
    elif disposition == 'set_aside':
        # The attestation is independent of this synthetic failed metadata lookup.
        def unavailable(*args, **kwargs):
            raise search.SearchError('synthetic metadata unavailable')
        s.epmc_search = unavailable
        record = s.not_cited(work['doi'], 'other_endpoint', 'Results table 2')
        assert record['outcome'] == 'failed' and search.valid_not_cited(record)
    else:
        assert disposition == 'unavailable'
        s.log({'call_id': 'unavailable', 'tool': 'not_read', 'outcome': 'ok',
               'ask': {'id': work['doi']}, 'readable': False, 'works': []})
    assert search.closeout(card, workdir)['closed'] is True
    return card


@pytest.mark.parametrize('disposition', ['carried', 'set_aside'])
@pytest.mark.parametrize('initial_type', ['Comment; Journal Article', 'Journal Article'])
@pytest.mark.parametrize('route', ['epmc', 'crossref'])
def test_production_status_discovery_reopens_a_previously_accounted_work(
        tmp_path, disposition, initial_type, route):
    card = discovered_work(tmp_path, disposition, initial_type)
    links = (LINK,) if route == 'epmc' else ()
    updates = ({'type': 'partial_retraction', 'DOI': '10.1111/notice'},) if route == 'crossref' else ()
    _, status = production_status(tmp_path, types=('Journal Article',), links=links, updates=updates)
    assert status['outcome'] == 'ok' and status['status'] == 'partial'
    out = search.closeout(card, tmp_path)
    assert out['closed'] is False
    row, = out['without_verdict']
    assert row['verdict'] is None and row['notice'] == ['partial']
    assert 'partial retraction' in row['classes'] and row['notice_read'] is False
    assert row['partial_notices_required'] == (['pmid:9999'] if route == 'epmc' else ['10.1111/notice'])
    assert row['returned_by'] == 1, 'status discovery is not another search return'
    assert row['tools'] == ['responses']
    assert not any(r['tool'] == 'notice_read' for r in search.read_log(tmp_path))
    assert out['declared_only'], 'direct tests remain a declared-only boundary'


def test_discovered_partial_needs_all_bound_readings_before_the_prior_disposition_stands(tmp_path):
    card = discovered_work(tmp_path, 'carried')
    s, status = production_status(tmp_path, types=('Comment',), links=(LINK, {**LINK, 'id': '9998'}))
    assert search.closeout(card, tmp_path)['closed'] is False
    s.notice_read(PARTIAL_WORK['doi'], 'MED:9999', status['call_id'], 'paragraph 2', READ_HASH, 'reader')
    assert search.closeout(card, tmp_path)['closed'] is False
    s.notice_read(PARTIAL_WORK['doi'], 'MED:9998', status['call_id'], 'paragraph 3', READ_HASH, 'reader')
    out = search.closeout(card, tmp_path)
    assert out['closed'] is True
    row, = out['answering_works']
    assert row['verdict'] == 'carried' and row['notice_read'] is True
    assert row['partial_notices_required'] == ['pmid:9998', 'pmid:9999']


def test_a_discovered_partial_does_not_require_a_reading_when_the_work_is_unavailable(tmp_path):
    card = discovered_work(tmp_path, 'unavailable')
    production_status(tmp_path, links=(LINK,))
    out = search.closeout(card, tmp_path)
    row, = out['answering_works']
    assert out['closed'] is True and row['verdict'] == 'unavailable'
    assert row['notice'] == ['partial'] and not row['notice_readings']


def test_status_discovery_binds_through_a_different_identifier_of_the_same_work(tmp_path):
    card = discovered_work(tmp_path, 'set_aside')
    production_status(tmp_path, links=(LINK,), ident='8888')
    out = search.closeout(card, tmp_path)
    assert out['closed'] is False
    row, = out['without_verdict']
    assert 'pmid:8888' in row['ids'] and PARTIAL_WORK['doi'] in row['ids']
    assert row['notice'] == ['partial']


def test_discovery_for_another_work_does_not_reopen_the_carried_work(tmp_path):
    work = {**PARTIAL_WORK, 'doi': '10.1111/a-different-comment', 'pmid': '4444', 'source_id': 'MED:4444',
            'type': 'Comment; Journal Article'}
    answering_log(tmp_path, [work])
    card = bare_card()
    card['added']['sources'] = {'p': {'source': 'https://doi.org/' + work['doi']}}
    production_status(tmp_path, links=(LINK,))
    out = search.closeout(card, tmp_path)
    row, = out['answering_works']
    assert out['closed'] is True and row['verdict'] == 'carried' and not row['notice']


def test_a_failed_status_record_cannot_reclassify_the_work(tmp_path):
    card = discovered_work(tmp_path, 'carried')
    search.Searcher(tmp_path).log({'call_id': 'failed-status', 'tool': 'status', 'outcome': 'failed',
        'ask': {'id': PARTIAL_WORK['doi']}, 'status': 'partial', 'notices': [],
        'target': {**PARTIAL_WORK, 'type': 'Partial Retraction'}, 'works': []})
    out = search.closeout(card, tmp_path)
    row, = out['answering_works']
    assert out['closed'] is True and not row['notice']


def test_a_later_clean_status_does_not_erase_a_previous_partial_discovery(tmp_path):
    card = discovered_work(tmp_path, 'carried')
    production_status(tmp_path, links=(LINK,))
    production_status(tmp_path, types=('Journal Article',))
    out = search.closeout(card, tmp_path)
    assert out['closed'] is False and out['without_verdict'][0]['notice'] == ['partial']


def test_as_of_excluded_partial_notice_is_not_promoted_to_a_current_requirement(tmp_path):
    card = discovered_work(tmp_path, 'carried')
    _, status = production_status(tmp_path, types=('Journal Article',), as_of='2026-01-01',
        updates=({'type': 'partial_retraction', 'DOI': '10.1111/notice',
                  'updated': {'date-parts': [[2027, 1, 1]]}},))
    assert status['outcome'] == 'ok' and status['status'] == 'none_found' and status['left_out']
    out = search.closeout(card, tmp_path)
    row, = out['answering_works']
    assert out['closed'] is True and not row['notice']


@pytest.mark.parametrize('publication_type,kind,expected', [
    ('Partial Retraction', 'partial_retraction', 'partial'),
    ('Published Erratum', 'correction', 'corrected'),
    ('Expression of Concern', 'expression_of_concern', 'concern'),
    ('Retracted Publication', 'retraction', 'retracted'),
])
@pytest.mark.parametrize('notice_date', [None, [2027, 1, 1], [2025, 1, 1]],
                         ids=['undated', 'after-cutoff', 'before-cutoff'])
def test_historical_status_promotes_only_qualified_notice_classes_for_an_unaccounted_work(
        tmp_path, publication_type, kind, expected, notice_date):
    answering_log(tmp_path, [{**PARTIAL_WORK, 'type': 'Journal Article'}])
    card = bare_card()
    before = search.closeout(card, tmp_path)
    assert before['closed'] is True and before['answering_works'] == [] and before['declared_only']
    notice = {'type': kind, 'DOI': '10.1111/dated-notice'}
    if notice_date:
        notice['updated'] = {'date-parts': [notice_date]}
    _, status = production_status(tmp_path, types=('Journal Article', publication_type),
                                  updates=(notice,), as_of='2026-01-01')
    assert status['outcome'] == 'ok' and status['undetermined'], 'current pubType has no date'
    out = search.closeout(card, tmp_path)
    if notice_date == [2025, 1, 1]:
        assert status['status'] == expected and status['notices']
        assert out['closed'] is False
        row, = out['without_verdict']
        assert row['notice'] == [expected] and row['verdict'] is None
    else:
        assert status['status'] == 'none_found' and status['notices'] == []
        if notice_date:
            assert status['left_out']
        assert out['closed'] is True and out['answering_works'] == []
    assert out['declared_only'], 'temporal notice classification does not cover direct scientific tests'


def test_a_qualified_correction_does_not_import_an_excluded_current_partial_class(tmp_path):
    card = discovered_work(tmp_path, 'carried', 'Journal Article')
    _, status = production_status(tmp_path, types=('Journal Article', 'Partial Retraction'),
        as_of='2026-01-01', updates=(
            {'type': 'partial_retraction', 'DOI': '10.1111/future-notice',
             'updated': {'date-parts': [[2027, 1, 1]]}},
            {'type': 'correction', 'DOI': '10.1111/past-notice',
             'updated': {'date-parts': [[2025, 1, 1]]}},
        ))
    assert status['status'] == 'corrected' and status['left_out'] and status['undetermined']
    out = search.closeout(card, tmp_path)
    row, = out['answering_works']
    assert out['closed'] is True and row['verdict'] == 'carried'
    assert row['notice'] == ['corrected'] and row['classes'] == ['published erratum']
    assert row['partial_notices_required'] == []
