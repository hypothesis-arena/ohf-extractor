"""RecordDocument: a structured API record read field by field."""
import json

import pytest

import entailment
import ohfkit
from conftest import put
from conftest import invented_budget_counter

URL = 'https://example.org/api/records/r1'
LICENCE = {'name': 'CC BY 4.0', 'url': 'https://creativecommons.org/licenses/by/4.0/', 'attribution': 'Example'}


def record(**kw):
    rec = {'title': 'A title', 'one_liner': 'Cells may do X. Then Y follows.', 'gap': {'delta': 'Z is unknown.'},
           'notes': ['first', 'second'], 'odd/key~': 'escaped', 'assessment': {'summary': 'self-scored'},
           'generated_at': '2026-01-01T00:00:01Z', 'license': LICENCE, 'count': 3}
    rec.update(kw)
    return rec


def record_doc(tmp_path, rec=None):
    tmp_path.mkdir(parents=True, exist_ok=True)
    put(tmp_path, 'r1.json', json.dumps(rec or record()).encode())
    (tmp_path / 'docs.json').write_text(json.dumps({URL: {'kind': 'record', 'file': 'r1.json'}}))
    return ohfkit.RecordDocument(URL, 'r1.json', tmp_path)


def test_fields_are_string_leaves_in_key_order_with_pointers(tmp_path):
    doc = record_doc(tmp_path)
    assert [p for p, _ in doc.fields] == ['/gap/delta', '/license/attribution', '/license/name', '/license/url', '/notes/0',
                                         '/notes/1', '/odd~1key~0', '/one_liner', '/title']
    n = doc.field('/one_liner')
    assert doc.locator(n).startswith(f'API record field {n} /one_liner ')
    assert ohfkit.para_number(doc.locator(n)) == n


def test_excluded_members_cannot_be_cited(tmp_path):
    doc = record_doc(tmp_path)
    for pointer in ('/assessment/summary', '/generated_at'):
        with pytest.raises(ValueError, match='no string field'):
            doc.field(pointer)
    assert 'self-scored' not in doc.paragraphs


def test_author_value_is_the_whole_field(tmp_path):
    doc = record_doc(tmp_path)
    assert doc.author('/one_liner', 'Cells may do X. Then Y follows.')['value'] == 'Cells may do X. Then Y follows.'
    with pytest.raises(ValueError, match='whole field'):
        doc.author('/one_liner', 'Cells may do X.')
    with pytest.raises(ValueError, match='quoted whole'):
        doc.author_part('/one_liner', 'Cells may do X.', 'a cut')


def test_licence_is_the_records_own_member(tmp_path):
    assert record_doc(tmp_path).licence() == 'CC-BY-4.0'
    rec = record()
    del rec['license']
    with pytest.raises(ohfkit.LicenceError, match='no licence statement'):
        record_doc(tmp_path / 'none', rec).licence()
    with pytest.raises(ohfkit.LicenceError, match='restriction'):
        record_doc(tmp_path / 'nc', record(license={'name': 'CC BY-NC 4.0', 'url': ''})).licence()


def test_skeleton_takes_the_licence_from_the_record(tmp_path):
    doc = record_doc(tmp_path)
    card = ohfkit.skeleton(budget_counter=invented_budget_counter, ident='h_r1', doc=doc, citation='A title. Record r1.', url=URL, kind='database_record',
                           topic=['t'], sources={'s': doc.src('/one_liner')}, author_names='A')
    assert card['author']['source']['license'] == 'CC-BY-4.0' and 'doi' not in card['author']['source']
    assert ohfkit.source_licence(card, doc) == 'CC-BY-4.0'
    with pytest.raises(ohfkit.LicenceError, match='permissions block decides'):
        ohfkit.skeleton(budget_counter=invented_budget_counter, ident='h_r1', doc=doc, citation='c', url=URL, topic=['t'], sources={}, author_names='A',
                        licence_statement=('/title', 'A title'))


def test_hash_is_of_the_canonical_record_without_the_volatile_time(tmp_path):
    import rfc8785
    doc = record_doc(tmp_path)
    rec = record()
    del rec['generated_at']
    assert doc.sha == ohfkit.sha256(rfc8785.dumps(rec))
    assert ohfkit.sha256((tmp_path / doc.artifact).read_bytes()) == doc.sha == doc.item('/title')['sha256']
    again = json.dumps(record(generated_at='2026-02-02T00:00:02Z'), indent=2).encode()
    assert ohfkit.sha256(ohfkit.RecordDocument.canonical(again)) == doc.sha
    assert ohfkit.sha256(ohfkit.RecordDocument.canonical(json.dumps(record(title='B')).encode())) != doc.sha


def test_licence_member_is_a_source_but_not_an_author_value(tmp_path):
    doc = record_doc(tmp_path)
    assert doc.src('/license/name')['locator'].startswith('API record field ')
    with pytest.raises(ValueError, match='metadata member'):
        doc.author('/license/name', 'CC BY 4.0')


def test_verify_source_matches_a_record_whose_time_changed(tmp_path, monkeypatch):
    import io
    doc = record_doc(tmp_path)
    responses = {URL: json.dumps(record(generated_at='2026-03-03T00:00:03Z')).encode(),
                 'https://example.org/catalogue/r1': json.dumps({'title': 'A title'}).encode()}
    monkeypatch.setitem(ohfkit.CATALOGUES, 'test', ('Test catalogue', 'https://example.org/catalogue/{}',
                                                    lambda m: m['title']))
    monkeypatch.setattr(ohfkit.urllib.request, 'urlopen', lambda req: io.BytesIO(responses[req.full_url]))
    card = {'author': {'source': {'citation': 'A title. Record r1.', 'source_text_sha256': doc.sha}}, 'added': {}}
    ohfkit.verify_source(card, doc, catalogue=('test', 'r1'))
    v = card['added']['source_verification']
    assert v['status'] == 'refetched_match' and v['sha256'] == doc.sha
    responses[URL] = json.dumps(record(title='Changed')).encode()
    ohfkit.verify_source(card, doc, catalogue=('test', 'r1'))
    assert card['added']['source_verification']['status'] == 'refetched_mismatch'


def test_entailment_reads_the_passage_of_a_record_field(tmp_path):
    doc = record_doc(tmp_path)
    card = {'added': {'sources': {'s': doc.src('/one_liner')}}}
    assert entailment.passage(card, {URL: doc}, 's') == 'Cells may do X. Then Y follows.'


def test_docs_json_opens_a_record(tmp_path):
    doc = record_doc(tmp_path)
    card = {'added': {'sources': {'s': doc.src('/title')}}}
    [opened] = entailment.docs_for(card, tmp_path).values()
    assert isinstance(opened, ohfkit.RecordDocument) and opened.sha == doc.sha
