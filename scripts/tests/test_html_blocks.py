"""The HTML block reader (references/rules.md, "HTML blocks") keeps the text outside <p>, and its
numbers are the ones the rule gives.

The defect it guards against: the <p> reader read the case-8 blog post as 8 argument paragraphs and
lost the 20 written in <div>s (61% of the text, the introduction that states the hypothesis) without
an error. The fixture `fixtures/html/brembs-blocks.html` is cut line by line from that page
(bjoern.brembs.blog, CC BY 3.0, the Internet Archive capture of 2024-11-12): the page title, the
related-posts menu, the start of the post with its <div> paragraphs, three section headings, Box 1
in a table cell split by <br>, the first three references split by <br>, and the footer that holds
the licence statement.
"""
import hashlib
import json
import os
import re
from pathlib import Path

import pytest

import ohfkit
import read_cards
from conftest import put
from test_accepted_cards import ACCEPTED, accepted_dir

FIXTURE = Path(__file__).resolve().parent / 'fixtures' / 'html' / 'brembs-blocks.html'
URL = 'https://bjoern.brembs.net/2013/07/brains-as-outputinput-systems/'
WORK = 'div.entry'

# Every block of the fixture by number: (start of its text, section, work or framing). The numbers
# are the rule's, counted by hand from the fixture; a reader that loses, adds or reorders a block
# fails here, not only one that loses text.
EXPECTED = [
    ('bjoern.brembs.blog » Brains as', '(none)', 'framing'),
    ('Off to Paris for #FENS2022', 'Related posts', 'framing'),
    ('What is a decision?', 'Related posts', 'framing'),
    ('The speed (or lack thereof) of science', 'Related posts', 'framing'),
    ('In the process of migrating content', 'Related posts', 'work'),
    ('Neuroscience is predominantly interested', 'Related posts', 'work'),
    ('The concept of causality is so central', 'Related posts', 'work'),
    ('Early, often overlooked psychological conjecture', 'Related posts', 'work'),
    ('We all feel the very basic notion', 'Behavioral Variability: the output', 'work'),
    ('Thus, competitive success', 'Controlling external events: the input', 'work'),
    ('The first experiments into the mechanistic basis', 'The main function of brains', 'work'),
    ('Box 1: Predictive learning', 'The main function of brains', 'work'),
    ('Classical (Pavlovian) conditioning is the process', 'The main function of brains', 'work'),
    ('Operant (instrumental) conditioning is the process', 'The main function of brains', 'work'),
    ('Both operant and classical conditioning serve', 'The main function of brains', 'work'),
    ('This shift is signified by a steady decrease', 'The main function of brains', 'work'),
    ('References:', 'The main function of brains', 'work'),
    ('1. Kant I (1781) Critique of Pure Reason', 'The main function of brains', 'work'),
    ('2. Voltaire (1752/1924)', 'The main function of brains', 'work'),
    ('3. Shahan TA, Chase PN (2002)', 'The main function of brains', 'work'),
    ('bjoern.brembs.blog by Björn Brembs is licensed', 'The main function of brains', 'framing'),
]
LICENCE = 'bjoern.brembs.blog by Björn Brembs is licensed under a Creative Commons Attribution 3.0 Unported License.'


def numbering_errors(doc):
    """The blocks whose number, text, section or side differ from EXPECTED."""
    got = [(p, s, 'work' if w else 'framing') for p, s, w in zip(doc.paragraphs, doc.sections, doc.in_work)]
    errors = [] if len(got) == len(EXPECTED) else [f'{len(got)} blocks, expected {len(EXPECTED)}']
    for n, (want, have) in enumerate(zip(EXPECTED, got), 1):
        if not (have[0].startswith(want[0]) and have[1:] == want[1:]):
            errors.append(f'block {n}: {have[0][:40]!r} {have[1:]} != {want}')
    return errors


def blocks_doc(tmp_path, html=None, work=WORK):
    put(tmp_path, 'page.html', html.encode() if html is not None else FIXTURE.read_bytes())
    return ohfkit.HtmlBlocksDocument(URL, 'page.html', tmp_path, work)


def test_div_paragraphs_are_read(tmp_path):
    """Mutant: a <div> paragraph is lost (drop 'div' from HTML_BLOCK_BOUNDARIES, or read only <p>)."""
    doc = blocks_doc(tmp_path)
    assert doc.para(6).startswith('Neuroscience is predominantly interested')
    assert doc.para(7).startswith('The concept of causality is so central')
    # the defect: the <p> reader has neither
    old = ohfkit._Paragraphs().read(FIXTURE.read_text())
    assert not any(p.startswith(('Neuroscience is', 'The concept of causality')) for p in old.paragraphs)


def test_every_block_has_the_rule_number(tmp_path):
    assert numbering_errors(blocks_doc(tmp_path)) == []


def test_a_block_inserted_at_the_top_is_caught(tmp_path):
    """Mutant: the numbering shifted. One block more before the work moves every number after it,
    and numbering_errors sees it even though no text is lost."""
    html = FIXTURE.read_text().replace('</head>', '</head><div>Inserted.</div>', 1)
    doc = blocks_doc(tmp_path, html)
    assert doc.para(1) == 'bjoern.brembs.blog » Brains as output/input systems'
    assert doc.para(2) == 'Inserted.'
    errors = numbering_errors(doc)
    assert errors[0] == '22 blocks, expected 21' and len(errors) == 21  # every block from 2 on is off by one


def test_locator_names_the_block_and_its_side(tmp_path):
    doc = blocks_doc(tmp_path)
    assert doc.locator(9) == ('HTML block 9 (1-based order of the non-empty text runs between block boundaries; '
                              'section: Behavioral Variability: the output; work: inside div.entry)')
    assert doc.locator(21).endswith('; framing: outside div.entry)')
    assert ohfkit.para_number(doc.locator(9)) == 9
    assert doc.report() == [(1, 4, 'framing'), (5, 20, 'work'), (21, 21, 'framing')]
    assert 'work = the element div.entry' in doc.src(9)['tool']


def test_licence_statement_in_the_framing_is_quoted_by_its_block(tmp_path):
    doc = blocks_doc(tmp_path)
    licence, record = ohfkit.rights_record(doc, 21, LICENCE)
    assert licence == 'CC-BY-3.0'
    assert record['locator'].startswith('HTML block 21 ')


def test_work_must_name_an_element_on_the_page(tmp_path):
    with pytest.raises(ValueError, match='no block inside the work element'):
        blocks_doc(tmp_path, work='article#post-1')
    with pytest.raises(ValueError, match='work selector'):
        blocks_doc(tmp_path, work='div .entry')


@pytest.mark.parametrize('html, blocks', [
    ('<div>A<p>B</p>C</div>', ['A', 'B', 'C']),            # a nested block cuts the own text in two
    ('<div>A <em>b</em> <a href=x>c</a> d</div>', ['A b c d']),  # inline tags split nothing
    ('<p>A<br>B<br/>C</p>', ['A', 'B', 'C']),               # <br> is a boundary
    ('<ul><li>A</li><li>B</li></ul>', ['A', 'B']),
    ('<table><tr><td>A</td><td>B</td></tr></table>', ['A', 'B']),
    ('<div>A<script>x</script>B<!-- c --></div>', ['AB']),   # skipped text and comments are not text
    ('<div>A<span>B</div>C</span>D', ['AB', 'CD']),        # misnesting moves no number
    ('<div>A</p>B</div>', ['A', 'B']),                       # nor does a stray end tag
    ('text at body level<div>A</div>', ['text at body level', 'A']),
    ('<div> &amp; </div><div>  </div>', ['&']),             # an empty piece is not a block
])
def test_rule_cases(html, blocks):
    assert ohfkit._Blocks().read(html).blocks == blocks


def test_headings_are_sections_not_blocks():
    r = ohfkit._Blocks().read('<div>A</div><h2>Two</h2><div>B</div><h5>Five</h5><h3>T<br>C</h3>')
    assert r.blocks == ['A', 'B', 'Five', 'C']
    assert r.sections == ['(none)', 'Two', 'Two', 'T']


def test_rules_list_the_same_boundaries_as_the_code():
    """The rule a reader follows and the set the reader uses are one closed list."""
    rules = (ohfkit.SKILL / 'references' / 'rules.md').read_text()
    section = rules.split('### HTML blocks', 1)[1].split('\n## ', 1)[0]
    listed = re.search(r'only these \(a closed list; the tag name is matched in lower case\): `([^`]+)`', section)
    assert listed and set(listed.group(1).split()) == ohfkit.HTML_BLOCK_BOUNDARIES


def test_the_p_reader_is_unchanged():
    """HtmlDocument still reads the fixture as the same six <p> paragraphs: the block reader is a
    second numbering, not a change of the first."""
    r = ohfkit._Paragraphs().read(FIXTURE.read_text())
    starts = ['We all feel the very basic notion', 'Thus, competitive success', 'The first experiments',
              'This shift is signified', 'References: 1. Kant I', 'bjoern.brembs.blog by Björn Brembs']
    assert len(r.paragraphs) == 6 and all(p.startswith(s) for p, s in zip(r.paragraphs, starts))
    assert r.sections[0] == 'Behavioral Variability: the output'


def locators(node, author=False):
    """(locator, author value or None) of every record under node."""
    if isinstance(node, dict):
        loc = node.get('locator')
        if isinstance(loc, str):
            yield loc, node.get('value') if author and isinstance(node.get('value'), str) else None
        for k, v in node.items():
            yield from locators(v, author)
    elif isinstance(node, list):
        for v in node:
            yield from locators(v, author)


HTML_P = re.compile(r'HTML <p> (\d+) \(1-based order of the non-empty <p> elements; section: (\(none\)|[^)]*)\)')
# The one accepted card read from an HTML page (by <p>), and that page: the bytes its
# author.source.source_text_sha256 names, Research Square rs-10439106 v1, CC BY 4.0.
HTML_CARD, HTML_PAGE = 'alpha-gal-metformin-oit', 'rs-10439106-v1.html'


def test_no_accepted_locator_moves(tmp_path):
    """No accepted card changes a locator by this release, asserted from the bytes. One accepted
    card (alpha-gal) was read from an HTML page by <p>: its page is re-read here and every one of its
    HTML <p> locators must come out the same, with every author value still in its paragraph. No
    card has an HTML block locator. Counted over every locator of every card, so an empty set cannot
    pass. OHF_ACCEPTED_CARDS=<dir> runs the HTML-block part on another tree of cards."""
    root = accepted_dir()
    cards = {c.stem: json.loads(c.read_text()) for c, _ in read_cards.cards_and_ledgers(root)}
    assert set(cards) >= set(ACCEPTED) or os.environ.get('OHF_ACCEPTED_CARDS')
    found = [loc for card in cards.values() for loc, _ in locators(card)]
    assert len(found) > 100
    assert [loc for loc in found if 'HTML block' in loc] == []
    html = {name: [loc for loc, _ in locators(card) if 'HTML <p>' in loc] for name, card in cards.items()}
    assert {name for name, locs in html.items() if locs} <= {HTML_CARD}
    if HTML_CARD not in cards:
        return
    card = cards[HTML_CARD]
    page = (FIXTURE.parent / HTML_PAGE).read_bytes()
    original_source = card['author']['source']['source_text_sha256']
    actual_page = ohfkit.sha256(page)
    assert actual_page == 'sha256:' + hashlib.sha256(page).hexdigest()
    if actual_page != original_source:
        # An export derivative keeps the original source identity in its manifest.
        manifest = json.loads((Path(__file__).resolve().parents[2] /
                               'DATA-FIXTURE-MANIFEST.json').read_text())
        page_path = 'scripts/tests/fixtures/html/' + HTML_PAGE
        matches = [row for row in manifest['rows']
                   if row['original_path'] == page_path and row['export_path'] == page_path]
        assert len(matches) == 1
        recorded = matches[0]
        assert recorded['origin'] == 'ARTICLE_WEBPAGE_FRAGMENT'
        assert 'sha256:' + recorded['original_sha256'] == original_source
        assert 'sha256:' + recorded['output_sha256'] == actual_page
        assert recorded['public_export_changes'] == [
            'Contact/host privacy redaction under public export dispositions; '
            'source/custodian identity retained separately.']
    else:
        assert actual_page == original_source
    put(tmp_path, HTML_PAGE, page)
    doc = ohfkit.HtmlDocument(card['author']['source'].get('url', URL), HTML_PAGE, tmp_path)
    checked = 0
    for loc, _ in locators(card):
        for m in HTML_P.finditer(loc):
            assert m.group(0) == doc.locator(int(m.group(1))), loc
            checked += 1
    quoted = 0
    for loc, value in locators(card['author'], author=True):
        m = HTML_P.match(loc)
        if m and value is not None:
            assert value in doc.para(int(m.group(1))), loc
            quoted += 1
    assert checked == 22 and quoted > 0
