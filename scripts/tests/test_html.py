"""Gate (4): the HTML reader keeps every <p> or fails with a position."""
import pytest

import ohfkit


def read(html):
    return ohfkit._Paragraphs().read(html)


# The three synthetic inputs of the review, §4.2, each of which used to lose or pollute a paragraph.
def test_review_void_source_element():
    r = read('<p>Alpha <source src=x> one.</p><p>Beta two.</p><p>Gamma.</p>')
    assert r.paragraphs == ['Alpha one.', 'Beta two.', 'Gamma.']
    assert r.counts['opened'] == r.counts['closed_by_end_tag'] == 3


def test_review_unclosed_p_closed_by_next_p():
    r = read('<p>Alpha one.<p>Beta two.</p><p>Gamma.</p>')
    assert r.paragraphs == ['Alpha one.', 'Beta two.', 'Gamma.']
    assert r.counts == {'opened': 3, 'closed_by_end_tag': 2, 'closed_by_next_block': 1,
                        'closed_by_parent_end': 0, 'empty_from_stray_end_tag': 0}


def test_review_script_inside_p():
    assert read('<p>Alpha <script>ignore me now</script> one.</p>').paragraphs == ['Alpha one.']


@pytest.mark.parametrize('tag', ['style', 'template', 'noscript'])
def test_skipped_elements(tag):
    r = read(f'<p>Alpha <{tag}><p>not text</p> hidden</{tag}> one.</p><{tag}><p>x</p></{tag}><p>Beta.</p>')
    assert r.paragraphs == ['Alpha one.', 'Beta.']


@pytest.mark.parametrize('void', sorted(ohfkit.HTML_VOID - {'hr'}))
def test_every_void_element(void):
    assert read(f'<p>Alpha <{void}> one.</p><p>Beta.</p>').paragraphs == ['Alpha one.', 'Beta.']


def test_hr_closes_p():
    # HTML: <hr> ends the <p>; " one." is then outside it, and the </p> makes an empty <p>.
    r = read('<p>Alpha <hr> one.</p><p>Beta.</p>')
    assert r.paragraphs == ['Alpha', 'Beta.']
    assert r.counts['closed_by_next_block'] == 1 and r.counts['empty_from_stray_end_tag'] == 1


def test_block_element_closes_p():
    r = read('<div><p>Alpha<div>Table</div>tail</div><p>Beta.</p>')
    assert r.paragraphs == ['Alpha', 'Beta.'] and r.counts['closed_by_next_block'] == 1


def test_parent_end_closes_p():
    r = read('<div><p>Alpha</div><p>Beta.</p>')
    assert r.paragraphs == ['Alpha', 'Beta.'] and r.counts['closed_by_parent_end'] == 1


def test_stray_end_tag_is_an_empty_p():
    r = read('<p>Alpha</p></p><p>Beta.</p>')
    assert r.paragraphs == ['Alpha', 'Beta.'] and r.counts['empty_from_stray_end_tag'] == 1


def test_p_inside_heading_is_a_paragraph():
    r = read('<h2>Results</h2><h1><p>Title</p></h1><p>Body.</p>')
    assert r.paragraphs == ['Title', 'Body.'] and r.sections == ['Results', 'Results']


def test_headings_name_sections():
    r = read('<h2>Abstract</h2><p>One.</p><h3>Methods</h3><p>Two.</p>')
    assert r.sections == ['Abstract', 'Methods']


@pytest.mark.parametrize('html, msg', [
    ('<p>Alpha one.', 'line 1, column 1: <p> opened at line 1, column 1 is never closed'),
    ('<p>One.</p>\n<p>Alpha <b>bold <i>both</b> one.</p>', 'line 2, column 25: </b> inside <p> opened at line 2, column 1 while <i> is open'),
    ('<p>One <script>x', '<script> is never closed'),
    ('<p/>Alpha', 'self-closing <p/>'),
    ('<a><p>Alpha</a>', '</a> cannot close <p>'),
    ('<h2>Alpha <div>x</div></h2>', '<div> inside <h2>'),
    ('<h2>Alpha', '<h2> opened at line 1, column 1 is never closed'),
])
def test_unclean_paragraphs_fail_with_position(html, msg):
    with pytest.raises(ohfkit.HtmlParseError, match='HTML line') as e:
        read(html)
    assert msg in str(e.value)
