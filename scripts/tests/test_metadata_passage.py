"""Explicit article-meta passages remain model-check inputs, never resolution verdicts."""
import copy
from types import SimpleNamespace
import xml.etree.ElementTree as ET

import pytest

import entailment
import ohfkit


LOCATOR = 'XML ./front/article-meta (title-group, contrib-group, article-id, pub-date, permissions)'
SOURCE = 'https://example.invalid/invented.xml'
XML = ('<article><front><article-meta>'
       '<article-id>invented-1</article-id>'
       '<title-group><article-title>  Invented <italic>test</italic> name.\n</article-title></title-group>'
       '<contrib-group>Author A</contrib-group><pub-date>2026</pub-date>'
       '<permissions>Invented permission text.</permissions><abstract>Not selected.</abstract>'
       '</article-meta></front><body><p>Not metadata.</p></body></article>')
EXPECTED = 'invented-1\n  Invented test name.\n\nAuthor A\n2026\nInvented permission text.'


def inputs(xml=XML, locator=LOCATOR):
    card = {'standard_version': ohfkit.standard_line(), 'added': {
        'layers': {'core': {'names': [{'value': 'Invented test name.', 'src': 'meta'}]}},
        'sources': {'meta': {'source': SOURCE, 'locator': locator}}}}
    return card, {SOURCE: SimpleNamespace(root=ET.fromstring(xml))}


def test_complete_metadata_text_stays_in_checker_with_source_binding():
    card, docs = inputs()
    before = copy.deepcopy(card)
    items = entailment.build(card, docs)
    assert items == [{'id': 'r1', 'pointer': '/added/layers/core/names/0', 'basis': 'src',
                      'value': 'Invented test name.', 'source_passage': EXPECTED}]
    assert entailment.checker_items(items) == items
    assert not entailment.is_resolved(items[0])
    assert card == before


@pytest.mark.parametrize('name', ['title-group', 'contrib-group', 'article-id', 'pub-date', 'permissions'])
def test_each_named_element_is_required_even_if_same_tag_exists_elsewhere(name):
    card, docs = inputs()
    root = docs[SOURCE].root
    meta = root.find('./front/article-meta')
    element = meta.find(name)
    meta.remove(element)
    root.find('./body').append(element)
    with pytest.raises(ValueError, match='^META_ELEMENT_MISSING:'):
        entailment.build(card, docs)


@pytest.mark.parametrize('locator', [
    'XML ./front/article-meta (title-group, ../body)',
    'XML ./front/article-meta (../../body/.//p[1])',
    'XML ./front/article-meta (title-group/article-title)',
    'XML ./front/article-meta (/article/body)',
    'XML ./front/article-meta (title-group,)',
    'XML ./front/article-meta ()',
    'XML ./front/article-meta (title-group, title-group)',
    'XML ./front/article-meta/../../body',
    'XML ./front/article-meta (title-group) trailing',
])
def test_locator_cannot_escape_or_silently_select_other_parts(locator):
    card, docs = inputs(locator=locator)
    with pytest.raises(ValueError, match='^META_LOCATOR:'):
        entailment.build(card, docs)


@pytest.mark.parametrize('xml', [
    '<article><front/></article>',
    '<article><front><article-meta/><article-meta/></front></article>',
    '<article><body><article-meta><title-group>Wrong part</title-group></article-meta></body></article>',
])
def test_missing_or_ambiguous_front_metadata_refuses(xml):
    card, docs = inputs(xml=xml)
    with pytest.raises(ValueError, match='^META_ROOT:'):
        entailment.build(card, docs)


def test_non_xml_document_refuses_without_attribute_error():
    card, docs = inputs()
    docs[SOURCE] = SimpleNamespace()
    with pytest.raises(ValueError, match='^META_ROOT:'):
        entailment.build(card, docs)


def test_empty_named_element_refuses():
    card, docs = inputs(xml=XML.replace('Author A', ' \n '))
    with pytest.raises(ValueError, match='^META_ELEMENT_EMPTY:'):
        entailment.build(card, docs)


def test_all_repeated_named_elements_and_inline_text_are_kept_in_document_order():
    xml = ('<article><front><article-meta><article-id>One</article-id><pub-date>First</pub-date>'
           '<article-id>Two</article-id><pub-date>Second</pub-date></article-meta></front></article>')
    card, docs = inputs(xml=xml, locator='XML ./front/article-meta (pub-date, article-id)')
    assert entailment.passage(card, docs, 'meta') == 'One\nFirst\nTwo\nSecond'


def test_existing_paragraph_passage_is_unchanged():
    card, docs = inputs(locator='XML .//p[1]')
    docs[SOURCE].para = lambda number: ('Original paragraph' if number == 1 else 'Wrong paragraph')
    assert entailment.build(card, docs)[0]['source_passage'] == 'Original paragraph'


@pytest.mark.parametrize('release', ['1.0.1', '1.1.4'])
def test_explicit_1_4_card_refuses_an_active_legacy_primary(tmp_path, monkeypatch, release):
    # A minimal invented active-primary directory, deliberately without the pinned
    # 1.4 projection module. The ordinary route must not fall back to local rules.
    primary = tmp_path / 'legacy-primary'
    primary.mkdir()
    (primary / 'VERSION').write_text(release + '\n')
    monkeypatch.setenv('OHF_REPO', str(primary))
    monkeypatch.setattr(ohfkit, 'REPO', primary)
    assert ohfkit.standard_line() == '.'.join(release.split('.')[:2])
    card, docs = inputs()
    card['standard_version'] = '1.4'
    before = copy.deepcopy(card)
    with pytest.raises(ValueError, match='^pinned projection source unavailable$'):
        entailment.build(card, docs)
    assert card == before


@pytest.fixture
def metadata_ledger(monkeypatch):
    import hashlib
    import os
    from pathlib import Path
    import check_ledger
    import projection_binding
    from conftest import SCRIPTS

    primary = (ohfkit.REPO if ohfkit.standard_line() == '1.4' else
               Path(os.environ.get('OHF_TEST_PRIMARY_14', SCRIPTS.parents[0] / 'standard-primary-1.4')))
    assert 'sha256:' + hashlib.sha256((primary / 'tools/check_ledger.py').read_bytes()).hexdigest() == (
        projection_binding.STANDARD_MODULE_SHA256)
    monkeypatch.setenv('OHF_REPO', str(primary))
    monkeypatch.setattr(ohfkit, 'REPO', primary)
    card, docs = inputs()
    # An invented ledger component, not a whole-card schema certificate.
    card.update(schema='ohf:hypothesis@1', id='h_invented_metadata', version=1,
                identity={'proposition_id': 'h_invented_metadata', 'version': 1})
    card['added']['integrity'] = {'entailment': []}
    card['content_hash'] = check_ledger._content_hash()(card)
    ledger = check_ledger.new_ledger(card)
    items = entailment.build(card, docs)
    entailment.merge(card, items, [{'id': item['id'], 'verdict': 'entails'} for item in items],
                     docs, ledger)
    card['content_hash'] = check_ledger._content_hash()(card)
    ledger['content_hash'] = card['content_hash']
    reader = check_ledger._projection_module().reference()
    return card, ledger, items, check_ledger, reader


def test_metadata_name_requires_its_record_like_the_pinned_reader(metadata_ledger):
    card, ledger, items, producer, reader = metadata_ledger
    assert len(items) == 1 and not entailment.is_resolved(items[0])
    assert items[0]['pointer'] == '/added/layers/core/names/0'
    passages = {producer.key_of(item): item['source_passage'] for item in items}
    assert producer.check(card, ledger, passages=passages) == reader.check(card, ledger, passages=passages) == []
    card['added']['integrity']['entailment'] = []
    card['content_hash'] = producer._content_hash()(card)
    ledger['content_hash'] = card['content_hash']
    expected = ['/added/layers/core/names/0 (src): no entailment record (run the entailment pass on it)']
    assert producer.check(card, ledger, passages=passages) == expected
    assert reader.check(card, ledger, passages=passages) == expected


@pytest.mark.parametrize('changed', ['value', 'passage'])
def test_metadata_record_keeps_value_and_passage_binding(metadata_ledger, changed):
    card, ledger, items, producer, reader = metadata_ledger
    passages = {producer.key_of(item): item['source_passage'] for item in items}
    if changed == 'value':
        card['added']['layers']['core']['names'][0]['value'] = 'Another invented name.'
        card['content_hash'] = producer._content_hash()(card)
        ledger['content_hash'] = card['content_hash']
    else:
        passages[producer.key_of(items[0])] = 'Another invented metadata passage.'
    for check in (producer.check, reader.check):
        errors = check(card, ledger, passages=passages)
        assert errors and all('/added/layers/core/names/0' in error for error in errors)


@pytest.mark.parametrize('locator,expected', [
    (LOCATOR, True),
    ('XML .//p[1]', True),
    ('XML ./front/', False),
    ('XML ./front/title-group (article-title)', False),
    ('XML ./front/article-meta-other (title-group)', False),
    ('NCBI Taxonomy: invented database record', False),
])
def test_readable_metadata_prefix_does_not_admit_other_front_paths(locator, expected):
    import check_ledger
    card, _ = inputs(locator=locator)
    assert check_ledger.reads_a_passage(card, 'meta') is expected


@pytest.fixture
def xml_permissions_ledger(xml_workdir):
    import check_ledger
    from conftest import CC_BY, PMCID

    # The existing JATS fixture has a real permissions element; test_callstore
    # already uses this locator. No article/exemplar card or model is read.
    doc = ohfkit.Document(PMCID, xml_workdir)
    passage = ''.join(doc.root.find('.//permissions').itertext())
    assert passage == CC_BY
    card = {'schema': 'ohf:hypothesis@1', 'id': 'h_invented_permissions', 'version': 1,
            'identity': {'proposition_id': 'h_invented_permissions', 'version': 1},
            'standard_version': ohfkit.standard_line(),
            'added': {'sources': {'permissions': {
                'source': doc.url, 'locator': 'XML .//permissions',
                'accessed_at': doc.retrieved, 'tool': 'reading of the fixture XML'}},
                'layers': {'core': {'scope': {
                    'value': 'X causes Y in every population.', 'src': 'permissions'}}},
                'integrity': {'entailment': []}}}
    card['content_hash'] = check_ledger._content_hash()(card)
    ledger = check_ledger.new_ledger(card)
    [value] = check_ledger.value_items(card)
    item = {**value, 'source_passage': passage}
    assert not entailment.is_resolved(item)
    # An injected negative checker answer, not a model or semantic oracle:
    # the fixture licence says nothing about this invented causal claim.
    record = {'pointer': item['pointer'], 'basis': 'src', 'verdict': 'no',
              'checked_at': '2026-11-03T00:00:00Z', 'checker': entailment.CHECKER,
              'note': 'Invented negative check: the licence does not state a causal result.'}
    check_ledger.add_entry(ledger, check_ledger.key_of(item),
                           check_ledger.entry(item, record), record['note'])
    card['added']['integrity']['entailment'] = [record]
    card['content_hash'] = check_ledger._content_hash()(card)
    ledger['content_hash'] = card['content_hash']
    return card, ledger, item, check_ledger


def test_fixture_xml_permissions_uses_only_general_xml_passage_arm(xml_permissions_ledger):
    card, _, _, producer = xml_permissions_ledger
    locator = card['added']['sources']['permissions']['locator']
    assert locator == 'XML .//permissions'
    assert ohfkit.para_number(locator) is None  # No .//p[N] or numbered page/API form.
    assert 'table-wrap' not in locator
    assert not locator.startswith('XML ./front/article-meta (')
    assert producer.reads_a_passage(card, 'permissions') is True


def test_fixture_xml_permissions_cannot_drop_a_negative_passage_check(xml_permissions_ledger):
    card, ledger, item, producer = xml_permissions_ledger
    key = producer.key_of(item)
    passages = {key: item['source_passage']}
    # A faithfully rendered "no" is valid ledger integrity, not scientific acceptance.
    assert producer.check(card, ledger, passages=passages) == []
    assert ledger['entries'][key][0]['verdict'] == 'no'
    assert 'resolver' not in ledger['entries'][key][0]
    before = copy.deepcopy(ledger['entries'])
    card['added']['integrity']['entailment'] = []
    card['content_hash'] = producer._content_hash()(card)
    ledger['content_hash'] = card['content_hash']
    assert producer.check(card, ledger, passages=passages) == [
        '/added/layers/core/scope (src): no entailment record (run the entailment pass on it)']
    assert ledger['entries'] == before
