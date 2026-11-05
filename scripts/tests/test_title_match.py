"""The title comparison, measured on a labelled set in both directions.

Three of the four finished cards that carry a `metadata_check` reported `title_match: false` beside
`doi_match: true`, and in each measured case the titles were the same title: Crossref answers in
typeset prose (U+2018, U+2013, U+2010, an EM SPACE before a colon, inline JATS markup with the line
breaks of a pretty-printed document) while the card's citation is typed in ASCII. The old comparison
also truncated the title to sixty characters and asked whether it appeared anywhere in the citation,
which hid the opposite error: a longer title of a neighbouring work, or a citation missing the
subtitle, matched on its first sixty characters.

The positives are the forms actually found - the two cards' own titles, and three forms taken from
registry answers kept in the conversions' logs. The negatives are the cases that must stay false, and
they are the reason the comparison is equality against a separate title rather than a search
inside the citation. Both halves live here together so that a later change is measured against judgements made
before it.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import ohfkit  # noqa: E402
from conftest import invented_budget_counter

AMOEBAE = ("Casadevall A, Fu MS, Guimaraes AJ, Albuquerque P. The 'Amoeboid Predator-Fungal Animal "
           "Virulence' Hypothesis. J Fungi (Basel). 2019;5(1):10")
IMPRINTING = ('Wolf JB, Hager R. A maternal-offspring coadaptation theory for the evolution of '
              'genomic imprinting. PLoS Biol. 2006;4(12):e380')

POSITIVES = [
    ('a registry title with U+2018 and U+2019 where the citation has apostrophes',
     "The ‘Amoeboid Predator-Fungal Animal Virulence’ Hypothesis",
     "The 'Amoeboid Predator-Fungal Animal Virulence' Hypothesis", AMOEBAE),
    ('an EN DASH where the citation has a hyphen',
     'A Maternal–Offspring Coadaptation Theory for the Evolution of Genomic Imprinting',
     'A maternal-offspring coadaptation theory for the evolution of genomic imprinting', IMPRINTING),
    ('U+2010, the non-breaking hyphen, three times in one title',
     'Rapamycin‐mediated mouse lifespan extension: Late‐life dosage regimes with '
     'sex‐specific effects',
     'Rapamycin-mediated mouse lifespan extension: Late-life dosage regimes with sex-specific effects',
     'Anonymous A. Rapamycin-mediated mouse lifespan extension: Late-life dosage regimes with '
     'sex-specific effects. Aging Cell. 2025;24:e1'),
    ('an EM SPACE before a colon',
     'Genomic Imprinting of Grb10 : Coadaptation or Conflict?',
     'Genomic imprinting of Grb10: coadaptation or conflict?',
     'Anonymous A. Genomic imprinting of Grb10: coadaptation or conflict? PLoS Biol. 2014;12:e1'),
    ('inline markup with the line breaks of a pretty-printed document',
     'm\n                    <scp>TORC</scp>\n                    2‐\n'
     '                    <scp>SGK</scp>\n                    ‐1 acts',
     'mTORC2-SGK-1 acts',
     'Anonymous A. mTORC2-SGK-1 acts. Aging Cell. 2020;19:e1'),
    ('a title that ends in a question mark, with the journal after it',
     'Bench to bedside: is rapamycin headed for the docTOR?',
     'Bench to bedside: is rapamycin headed for the docTOR?',
     'Anonymous A. Bench to bedside: is rapamycin headed for the docTOR? GeroScience. 2026;48:1'),
]

NEGATIVES = [
    ('a neighbouring work whose title has three more words',
     'A Maternal–Offspring Coadaptation Theory for the Evolution of Genomic Imprinting in '
     'Mammals', 'A maternal-offspring coadaptation theory for the evolution of genomic imprinting', IMPRINTING),
    ('the citation is missing the subtitle',
     'Bench to bedside: is rapamycin headed for the docTOR?',
     'Bench to bedside',
     'Anonymous A. Bench to bedside. GeroScience. 2026;48:1'),
    ('a different number',
     'Effects of 2 mg rapamycin on glucose metabolism',
     'Effects of 5 mg rapamycin on glucose metabolism',
     'Anonymous A. Effects of 5 mg rapamycin on glucose metabolism. J Test. 2025;1:1'),
    ('a different unit',
     'Effects of 2 mg rapamycin on glucose metabolism',
     'Effects of 2 mg/kg rapamycin on glucose metabolism',
     'Anonymous A. Effects of 2 mg/kg rapamycin on glucose metabolism. J Test. 2025;1:1'),
    ('a citation of another work entirely',
     "The ‘Amoeboid Predator-Fungal Animal Virulence’ Hypothesis",
     'A maternal-offspring coadaptation theory for the evolution of genomic imprinting', IMPRINTING),
    ('a registry that holds no title at all',
     '', 'Anything at all', 'Anonymous A. Anything at all. J Test. 2025;1:1'),
    # The space before a mark is closed up; the words around it are not. Searched for a real pair of
    # titles that this fold would merge: of the 47 registry titles kept in the conversions' logs,
    # exactly one has a space before a mark - the EM SPACE above - and the fold makes no two distinct
    # titles identical. So there is no measured case, and this constructed one holds the bound.
    ('the space before the colon is closed, the words after it are not',
     'Genomic Imprinting of Grb10\u2003: Coadaptation or Conflict?',
     'Genomic imprinting of Grb10: coadaptation and conflict?',
     'Anonymous A. Genomic imprinting of Grb10: coadaptation and conflict? PLoS Biol. 2014;12:e1'),
]


@pytest.mark.parametrize('case,registry,title,citation', POSITIVES, ids=[c[0][:40] for c in POSITIVES])
def test_a_registry_title_typeset_differently_is_the_same_title(case, registry, title, citation):
    assert ohfkit.title_match(registry, title) == (True, None), case


@pytest.mark.parametrize('case,registry,title,citation', NEGATIVES, ids=[c[0][:40] for c in NEGATIVES])
def test_a_title_that_differs_in_what_it_says_stays_false(case, registry, title, citation):
    matched, why = ohfkit.title_match(registry, title)
    assert matched is False and why == 'title_differs', case


def test_the_old_comparison_fails_this_set_in_the_direction_it_was_built_to_hide():
    """What moves and what does not. The old rule got one of the six positives and all of the
    negatives: on this set its error was one-sided, and the fix adds five positives without losing a
    negative. The one it passed is the case whose typesetting happened to fall outside the first sixty
    characters it compared - which is the measure of how little that truncation was protecting."""
    def old(title, ours):
        return bool(title) and title.lower()[:60] in ours.lower()

    assert sum(old(r, c) for _, r, _, c in POSITIVES) == 1
    assert sum(ohfkit.title_match(r, t)[0] for _, r, t, _ in POSITIVES) == len(POSITIVES)
    assert sum(not old(r, c) for _, r, _, c in NEGATIVES) == len(NEGATIVES)
    assert sum(not ohfkit.title_match(r, t)[0] for _, r, t, _ in NEGATIVES) == len(NEGATIVES)


def test_whitespace_is_dropped_only_where_it_touches_a_tag():
    """The lead's bound on removing markup, in both directions. A line break beside a removed tag
    goes with the tag, because it is the document's formatting; a line break between two ordinary
    words is a space, and a space an author wrote beside a tag stays a space."""
    assert ohfkit.compare_form('Rapamycin\n                mediated') == 'rapamycin mediated'
    assert ohfkit.compare_form('<i>Drosophila</i> melanogaster') == 'drosophila melanogaster'
    assert ohfkit.compare_form('m\n  <scp>TORC</scp>\n  2‐1') == 'mtorc2-1'


def test_nothing_stored_is_normalised():
    """The comparison form exists for the length of a comparison. `norm`, which is what a card's
    stored values go through, is untouched by it: it collapses whitespace and nothing else, so a
    citation keeps its apostrophes, its dashes and its case."""
    typeset = "The ‘Amoeboid’ Hypothesis : A–B"
    assert ohfkit.norm(typeset) == typeset.replace(' ', ' ')
    assert '‘' in ohfkit.norm(typeset) and '–' in ohfkit.norm(typeset)


# -- the bounds a review drew, each as a case -------------------------------------------------------

def test_only_the_title_field_is_compared():
    """The review's R1, and the worst of the three. Comparing the registry's title with every field
    of the citation, and with every run of consecutive fields, is a substring search with extra
    steps: the journal name alone matched a registry title of `Nature`, so a record about one article
    would have verified a card about another.

    One separate title, never any part of a citation."""
    title = "The 'Amoeboid Predator-Fungal Animal Virulence' Hypothesis"
    assert ohfkit.title_match('J Fungi (Basel)', title) == (False, 'title_differs')
    assert ohfkit.title_match('Nature', 'A theory of imprinting') \
        == (False, 'title_differs')
    assert ohfkit.title_match('Casadevall A, Fu MS, Guimaraes AJ, Albuquerque P', title) \
        == (False, 'title_differs')
    assert ohfkit.title_match('2019;5(1):10', title) == (False, 'title_differs')


def test_a_title_can_contain_sentence_breaks_without_becoming_several_fields():
    title = 'Ageing is not a disease. A reply'
    assert ohfkit.title_match(title, title) == (True, None)
    assert ohfkit.title_match('Ageing is not a disease', title) == (False, 'title_differs')
    assert ohfkit.title_match('A real title.', 'A real title') == (False, 'title_differs')


def test_an_inequality_is_not_markup():
    """The review's R3: `<[^>]+>` stripped `< 5 and y >` out of a title about `x < 5 and y > 2`, so
    the comparison compared two strings neither of which was written anywhere. A tag is one of the
    names JATS and HTML use, in proper form; angle brackets around arithmetic stay text."""
    inequality = 'Effects when x < 5 and y > 2'
    assert 'x < 5 and y > 2' in ohfkit.compare_form(inequality)
    assert ohfkit.title_match(inequality, inequality) == (True, None)
    # and a real tag still goes, with the pretty-printer's line breaks beside it
    assert ohfkit.compare_form('m\n  <scp>TORC</scp>\n  2') == 'mtorc2'
    assert ohfkit.compare_form('<unknown-thing>kept</unknown-thing>') == \
        '<unknown-thing>kept</unknown-thing>', 'an unknown name is not treated as markup'


SCRIPT_CASES = [
    ('a superscript two against a plain two', 'Effects of x²', 'Effects of x2'),
    ('a subscript two against a plain two', 'CO₂ and growth', 'CO2 and growth'),
    ('a negative exponent', 'A shift of 10⁻³', 'A shift of 10-3'),
]


@pytest.mark.parametrize('case,registry,ours', SCRIPT_CASES, ids=[c[0][:40] for c in SCRIPT_CASES])
def test_a_difference_only_in_scripts_is_false_and_says_so(case, registry, ours):
    """The owner's decision of 2026-10-24, and it goes against the grain of the rest of this form:
    NFKC folds x² into x2, and here that is wrong - a squared term is not a term followed by a two,
    so the titles **do** differ. But a reader must be able to see that the difference is a typesetting
    of exponents rather than a different work, so it is reported as `title_differs_in_script`."""
    matched, why = ohfkit.title_match(registry, ours)
    assert matched is False and why == 'title_differs_in_script', case


@pytest.mark.parametrize('registry,ours', [
    ('Role of α-tubulin', 'Role of β-tubulin'),
    ('A shift of ±2 units', 'A shift of +2 units'),
    ('Effects of x²', 'Effects of x³'),
])
def test_letters_and_signs_are_still_different_titles(registry, ours):
    """And the guard on that exception: a Greek letter is not another Greek letter, a plus-minus is
    not a plus, and one exponent is not another. None of these is a matter of typesetting, so none of
    them gets the script code - they are simply different titles."""
    assert ohfkit.title_match(registry, ours) == (False, 'title_differs')


def test_the_comparison_runs_on_a_production_record(tmp_path, monkeypatch):
    """The review's R2, and the sharpest of its findings about my own evidence. `verify_source`
    called `norm` on the registry's title **before** comparing, so the line breaks of a
    pretty-printed title were gone by the time the markup rule could see them: the rule fired in a
    direct call to the comparison and never on a real record, where `title_match` stayed false.

    So the registry's title is compared as it arrived, and this test drives the whole production path
    - a Crossref answer with the title Crossref actually sends - instead of calling the comparison
    itself."""
    import io as _io
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from conftest import PARAS, jats, put  # noqa: E402

    put(tmp_path, 'PMC0000001.xml', jats(PARAS))
    doc = ohfkit.Document('PMC0000001', workdir=str(tmp_path))
    card = {'author': {'source': {
        'doi': '10.1111/evl3.1', 'url': 'https://doi.org/10.1111/evl3.1',
        'citation': 'Anonymous A. mTORC2-SGK-1 acts in two pathways. Aging Cell. 2020;19:e1'}},
        'added': {}, 'citation_title': 'mTORC2-SGK-1 acts in two pathways'}
    crossref = {'message': {'DOI': '10.1111/evl3.1', 'title': [
        'm\n                    <scp>TORC</scp>\n                    2-\n'
        '                    <scp>SGK</scp>\n                    -1 acts in two pathways']}}

    def urlopen(request, timeout=None):
        if request.full_url == doc.url:
            return _io.BytesIO((tmp_path / 'PMC0000001.xml').read_bytes())
        return _io.BytesIO(json.dumps(crossref).encode())

    monkeypatch.setattr(ohfkit.urllib.request, 'urlopen', urlopen)
    out = ohfkit.verify_source(card, doc)
    check = card['added']['source_verification']['metadata_check']
    assert check['doi_match'] is True
    assert check['title_match'] is True, 'the production path still saw a mismatch'
    assert out['title_difference'] is None
    # And the reason, where it has to live: `metadata_check` is closed at 1.1.4 and 1.2.0, so the
    # card carries the verdict and the run carries why.
    assert 'title_difference' not in check


# Reissue controls drive both production registry paths, using only synthetic records. The card
# is made by skeleton too: accepting a free-form citation there does not make it parseable here.
@pytest.fixture
def verify_title(tmp_path, monkeypatch):
    import io
    from conftest import PARAS, jats, put

    raw = jats(PARAS)
    put(tmp_path, 'PMC0000001.xml', raw)
    doc = ohfkit.Document('PMC0000001', workdir=str(tmp_path))

    def verify(registry_title, citation, doi, title=None, details=False):
        card = ohfkit.skeleton(budget_counter=invented_budget_counter, ident='h_title', doc=doc, citation=citation,
                               doi='10.0000/title' if doi else None, url=doc.url,
                               topic=['test'], sources={}, author_names='Smith A')
        # Direct callers can provide a card without going through the new skeleton API. Exercise
        # that route too; the separate API validation and export boundary are tested below.
        if title is not None:
            card['citation_title'] = title

        def urlopen(request, timeout=None):
            if request.full_url == doc.url:
                return io.BytesIO(raw)
            titles = registry_title if isinstance(registry_title, list) else [registry_title]
            payload = ({'message': {'DOI': '10.0000/title', 'title': titles}} if doi else
                       {'metadata': {'title': registry_title}})
            return io.BytesIO(json.dumps(payload).encode())

        monkeypatch.setattr(ohfkit.urllib.request, 'urlopen', urlopen)
        out = ohfkit.verify_source(card, doc, catalogue=None if doi else ('archive.org', 'test'))
        assert card['author']['source']['citation'] == citation
        check = card['added']['source_verification']['metadata_check']
        assert check['title_match'] == out['metadata_check']['title_match']
        assert 'title_difference' not in check
        if details:
            return out, card
        return check['title_match'], out['title_difference']

    return verify


@pytest.mark.parametrize('doi', [True, False], ids=['crossref', 'catalogue'])
@pytest.mark.parametrize('registry,citation', [
    ('Nature', 'Different article. Nature. 2024;1:1'),
    ('Smith', 'A. Smith. Different article. Nature. 2024;1:1'),
    ('Nature', 'Different article. Nature. Journal. 2024;1:1'),
    ('Record r1', 'A title. Record r1.'),
    ('Nature', 'Smith A. A title. J. Nature. 2024;1:1'),
])
def test_ambiguous_citations_do_not_verify_other_fields(verify_title, doi, registry, citation):
    # Missing is a mismatch, even if the tempting field appears in the citation. An explicit title
    # likewise cannot be overridden by a journal or author fragment elsewhere in that string.
    assert verify_title(registry, citation, doi) == (False, 'title_differs')
    assert verify_title(registry, citation, doi, title='A different title') == (False, 'title_differs')


SCRIPT_REISSUE = [
    ('Effects xₙ', 'Effects xn', False, 'title_differs_in_script'),
    ('Effects xᵃ', 'Effects xa', False, 'title_differs_in_script'),
    ('Effects x<sup>2</sup>', 'Effects x2', False, 'title_differs_in_script'),
    ('Effects x<sub>2</sub>', 'Effects x2', False, 'title_differs_in_script'),
    ('Effects x<sup>n</sup>', 'Effects xn', False, 'title_differs_in_script'),
    ('Effects x<sub>n</sub>', 'Effects xn', False, 'title_differs_in_script'),
    ('Effects <mml:msup><mml:mi>x</mml:mi><mml:mn>2</mml:mn></mml:msup>',
     'Effects x2', False, 'title_differs_in_script'),
    ('Effects <mml:msub><mml:mi>x</mml:mi><mml:mn>2</mml:mn></mml:msub>',
     'Effects x2', False, 'title_differs_in_script'),
    ('Effects x<SUP class="power">2</SUP>', 'Effects x2', False, 'title_differs_in_script'),
    ('Effects x²', 'Effects x<sup>2</sup>', True, None),
    ('Effects xₙ', 'Effects x<sub>n</sub>', True, None),
    ('Shift 10⁻³', 'Shift 10<sup>−3</sup>', True, None),
    ('Effects x<sup>2</sup>', 'Effects x<sup>3</sup>', False, 'title_differs'),
    ('Effects x<sup>2</sup>', 'Effects x₃', False, 'title_differs'),
    ('Effects x<sup>α</sup>', 'Effects x<sup>β</sup>', False, 'title_differs'),
    ('Effects x<sup>±2</sup>', 'Effects x<sup>+2</sup>', False, 'title_differs'),
    # A literal private-use character must not impersonate an internal script placeholder.
    ('Effects x²', 'Effects x\ue000', False, 'title_differs'),
]


@pytest.mark.parametrize('doi', [True, False], ids=['crossref', 'catalogue'])
@pytest.mark.parametrize('registry,title,matched,reason', SCRIPT_REISSUE)
def test_script_styles_survive_the_production_paths(verify_title, doi, registry, title, matched, reason):
    assert verify_title(registry, f'Smith A. {title}. Journal. 2024;1:1', doi, title=title) == (matched, reason)


@pytest.mark.parametrize('doi', [True, False], ids=['crossref', 'catalogue'])
@pytest.mark.parametrize('citation', ['Title first. Record r1.', 'A. Smith. A real title. Journal.',
                                    'An opaque citation without any known layout'])
def test_citation_layout_does_not_decide_the_title(verify_title, doi, citation):
    assert verify_title('A real title', citation, doi, title='A real title') == (True, None)


@pytest.mark.parametrize('doi', [True, False], ids=['crossref', 'catalogue'])
@pytest.mark.parametrize('title', ['', '  ', ['A real title'], {'title': 'A real title'}, 12])
def test_malformed_direct_card_title_is_a_mismatch(verify_title, doi, title):
    assert verify_title('A real title', 'A real title', doi, title=title) == (False, 'title_differs')


@pytest.mark.parametrize('doi', [True, False], ids=['crossref', 'catalogue'])
def test_registry_title_fields_are_not_joined(verify_title, doi):
    assert verify_title(['A real', ' title'], 'Unused citation', doi, title='A real title') == (False, 'title_differs')


@pytest.mark.parametrize('doi', [True, False], ids=['crossref', 'catalogue'])
@pytest.mark.parametrize('registry,title,expected', [
    ('The ‘real’ title', "The 'real' title", (True, None)),
    ('Effects x<sup>2</sup>', 'Effects x2', (False, 'title_differs_in_script')),
    ('A different work', 'The article title', (False, 'title_differs')),
    ('The article title', None, (False, 'title_differs')),
])
def test_saved_run_record_replays_after_the_finished_card_loses_its_build_title(
        verify_title, tmp_path, doi, registry, title, expected):
    out, card = verify_title(registry, 'An opaque citation', doi, title=title, details=True)
    record_path, card_path = tmp_path / 'source-check.json', tmp_path / 'finished.json'
    record_path.write_text(json.dumps(out, ensure_ascii=False))
    ohfkit.finish(card, card_path)
    saved_card = json.loads(card_path.read_text())
    saved_record = json.loads(record_path.read_text())
    assert 'citation_title' not in saved_card
    assert 'citation_title' not in saved_card['added']['source_verification']['metadata_check']
    assert saved_record['citation_title'] == title
    assert saved_record['registry_title'] == registry
    assert saved_record['source_text_sha256'] == saved_card['author']['source']['source_text_sha256']
    assert saved_record['converter_hash'] == saved_card['added']['by']['converter_hash']
    replay = ohfkit.title_match(saved_record['registry_title'], saved_record['citation_title'])
    assert replay == expected
    assert replay == (saved_record['metadata_check']['title_match'], saved_record['title_difference'])
    assert replay[0] == saved_card['added']['source_verification']['metadata_check']['title_match']


@pytest.mark.parametrize('doi', [True, False], ids=['crossref', 'catalogue'])
def test_registry_response_cannot_replace_the_title_read_from_the_article(verify_title, doi):
    article_title, registry_title = 'Title read from the article itself', 'Registry-only title'
    out, card = verify_title(registry_title, f'{article_title}. Journal.', doi,
                             title=article_title, details=True)
    assert card['citation_title'] == article_title
    assert out['citation_title'] == article_title
    assert out['registry_title'] == registry_title
    assert out['metadata_check']['title_match'] is False
    assert out['title_difference'] == 'title_differs'


def skeleton_with_title(workdir, **kw):
    doc = ohfkit.Document('PMC0000001', workdir=str(workdir))
    return ohfkit.skeleton(budget_counter=invented_budget_counter, ident='h_title', doc=doc, citation='A. Smith. Different article. Nature.',
                           doi='10.0000/title', topic=['test'], sources={}, author_names='Smith A', **kw)


def test_skeleton_records_the_explicit_title_and_finish_removes_the_build_field(xml_workdir):
    title = 'A title. Its subtitle — with punctuation'
    card = skeleton_with_title(xml_workdir, citation_title=title)
    assert card['citation_title'] == title
    assert card['author']['source']['citation'] == 'A. Smith. Different article. Nature.'
    path = xml_workdir / 'finished.json'
    ohfkit.finish(card, path)
    saved = json.loads(path.read_text())
    assert 'citation_title' not in saved
    assert saved['content_hash'] == ohfkit.content_hash(saved)


@pytest.mark.parametrize('title', ['', ' \n ', ['A title'], ('A', 'title'), {'title': 'A title'}, 12])
def test_skeleton_refuses_empty_titles_or_joining_fields(xml_workdir, title):
    with pytest.raises(ValueError, match='citation_title'):
        skeleton_with_title(xml_workdir, citation_title=title)


def test_every_unicode_super_or_sub_decomposition_keeps_its_script():
    import unicodedata

    checked = 0
    for codepoint in range(sys.maxunicode + 1):
        char = chr(codepoint)
        decomposition = unicodedata.decomposition(char)
        if not decomposition.startswith(('<super>', '<sub>')):
            continue
        checked += 1
        plain = unicodedata.normalize('NFKC', char)
        styled, flat = f'Index {char} value', f'Index {plain} value'
        assert ohfkit.title_match(styled, flat) == (False, 'title_differs_in_script'), hex(codepoint)
        assert ohfkit.title_match(flat, styled) == (False, 'title_differs_in_script'), hex(codepoint)
    assert checked > 200, 'the full Unicode traversal did not cover the script classes'
