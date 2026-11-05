"""Gate (2): the licence comes from the source bytes, not from an argument."""
import json

import pytest

import check_card
import ohfkit
from conftest import PARAS, PMCID, SCRIPTS, build_card, jats, load, put, run_pass
from conftest import invented_budget_counter

HTML_URL = 'https://example.org/article/1'


def html_workdir(tmp_path, statement):
    paras = [PARAS[0], statement, PARAS[1]] if statement else [PARAS[0], PARAS[1]]
    page = '<html><body><h2>Abstract</h2>' + ''.join(f'<p>{p}</p>' for p in paras) + '</body></html>'
    put(tmp_path, 'page.html', page.encode())
    (tmp_path / 'docs.json').write_text(json.dumps({HTML_URL: {'kind': 'html', 'file': 'page.html'}}))
    return ohfkit.HtmlDocument(HTML_URL, 'page.html', tmp_path)


def html_skeleton(doc, **kw):
    return ohfkit.skeleton(budget_counter=invented_budget_counter, ident='h_html', doc=doc, citation='c', doi='10.0000/h', topic=['t'],
                           sources={'p1': doc.src(1)}, author_names='A', **kw)


@pytest.mark.parametrize('text, lic', [
    ('This article is licensed under a Creative Commons Attribution 4.0 International License', 'CC-BY-4.0'),
    ('distributed under the terms of the Creative Commons Attribution License (http://creativecommons.org/'
     'licenses/by/4.0). The Creative Commons Public Domain Dedication waiver (http://creativecommons.org/'
     'publicdomain/zero/1.0/) applies to the data made available in this article', 'CC-BY-4.0'),
    ('This open access article is distributed under Creative Commons Attribution License 4.0 (CC BY).', 'CC-BY-4.0'),
    ('Attribution License (http://creativecommons.org/licenses/by/3.0), which permits', 'CC-BY-3.0'),
    ('This work is licensed under a CC BY 4.0 License', 'CC-BY-4.0'),
    ('This article is in the public domain.', 'public-domain'),
    # Every CC BY version permits republication with attribution, so a version named in the article's
    # own bytes is read (the owner's decision of 2026-10-23). The kit had refused two real sources on
    # the version alone: a CC BY 2.5 work that is a named lead on the rapamycin card, and a CC BY 2.0
    # showcase candidate.
    ('http://creativecommons.org/licenses/by/2.0/', 'CC-BY-2.0'),
    ('Creative Commons Attribution License ( http://creativecommons.org/licenses/by/2.0 ), which '
     'permits unrestricted use', 'CC-BY-2.0'),
    ('http://creativecommons.org/licenses/by/2.5/', 'CC-BY-2.5'),
    ('CC BY 1.0', 'CC-BY-1.0'),
    # The ordinary case the ambiguity rule must not break: the phrase and its version in one sentence,
    # with a CC0 waiver for the data in the next.
    ('distributed under the terms of the Creative Commons Attribution License '
     '(http://creativecommons.org/licenses/by/4.0). The Creative Commons Public Domain Dedication waiver '
     '(http://creativecommons.org/publicdomain/zero/1.0/) applies to the data made available in this '
     'article', 'CC-BY-4.0'),
    # The ordinary open-access statement keeps the phrase in one sentence and the URL in the next, and
    # that version **is** the article's. The ambiguity rule must not touch it.
    ('This is an open access article under the terms of the Creative Commons Attribution License, which '
     'permits use, distribution and reproduction in any medium, provided the original work is properly '
     'cited. http://creativecommons.org/licenses/by/4.0/', 'CC-BY-4.0'),
    # The same review's paired positive: a sentence that names the article **and** its data is about the
    # article too, so keying the refusal on the word "data" was wrong. The subject of each grant is
    # tracked instead.
    ('This article and its data are licensed under Creative Commons Attribution 4.0 (CC BY).', 'CC-BY-4.0'),
    ('The article, its figures and its data are released under Creative Commons Attribution 2.5 (CC BY).',
     'CC-BY-2.5'),
    # And the real statement of the article this came up on, which must keep working.
    ('\u00a9 2006 Wolf and Hager. 2006 https://creativecommons.org/licenses/by/4.0/ This is an open-access '
     'article distributed under the terms of the Creative Commons Attribution License, which permits '
     'unrestricted use, distribution, and reproduction in any medium, provided the original author and '
     'source are credited.', 'CC-BY-4.0'),
])
def test_allowed_statements(text, lic):
    assert ohfkit.licence_of(text) == lic


@pytest.mark.parametrize('text, why', [
    ('Creative Commons Attribution-NonCommercial-NoDerivatives 4.0 International (CC BY-NC-ND 4.0)', 'restriction'),
    ('https://creativecommons.org/licenses/by-nc-nd/4.0/', 'restriction'),
    ('CC BY-SA 4.0', 'restriction'),
    ('Creative Commons Attribution-ShareAlike 4.0', 'restriction'),
    # Exactly-Attribution statements with no version moved out of this list in 0.9.3: see
    # test_an_attribution_licence_with_no_version_in_the_record, which is version-aware. They were
    # refused here because a version from a publisher's policy page is not in the card's bytes - which
    # is still true, and is why no version is inferred; what changed is that the grant in the bytes is
    # recorded as the unversioned Attribution licence it is instead of being refused with it.
    # A restriction is a restriction at every version, including the ones just allowed.
    ('http://creativecommons.org/licenses/by-nc/2.0/', 'restriction'),
    ('CC BY-NC 2.5', 'restriction'),
    ('Creative Commons Attribution-NonCommercial 1.0', 'restriction'),
    ('http://creativecommons.org/licenses/by/5.0/', 'is not one of'),
    # An independent review of the widened rule, three findings, all of them only reachable **because**
    # the versions were widened. The two about a version scoped to the data moved to
    # `test_the_article_licence_element_decides_the_version`, which is where that question is now
    # answered: in flat text the caller asserts that the statement is the article's own, and this
    # function cannot second-guess that - two rounds of review broke every attempt to.
    # The second round of the same review: the version sits in a later sentence holding nothing but the
    # URL, so the sentence has no subject of its own and inherits the data from the sentence before it.
    # Reading that sentence alone made the data's version look like the article's licence.
    # A version this kit has not been told about must be refused, not truncated to one it knows.
    ('Creative Commons Attribution License 2.01', 'is not one of'),
    ('http://creativecommons.org/licenses/by/2.0.1/', 'is not one of'),
    # A restriction written with typographic dashes is still a restriction. Before this, NC went
    # undetected behind an en dash and a non-breaking hyphen, and the BY grant beside it was accepted.
    ('Attribution\u2013Non\u2011Commercial 2.0 (CC BY 2.0)', 'restriction'),
    ('CC BY\u2013NC 2.0 and http://creativecommons.org/licenses/by/2.0/', 'restriction'),
    ('CC BY\u2014SA 3.0', 'restriction'),
    ('http://creativecommons.org/licenses/by\u2011nd/4.0/', 'restriction'),
    ('CC BY 3.0 and http://creativecommons.org/licenses/by/4.0/', 'ambiguous'),
    ('All rights reserved.', 'no versioned CC BY'),
    ('', 'no licence statement'),
])
def test_refused_statements(text, why):
    with pytest.raises(ohfkit.LicenceError, match=why):
        ohfkit.licence_of(text)


def test_nc_nd_xml_fails(xml_workdir):
    put(xml_workdir, f'{PMCID}.xml', jats(PARAS, permissions='© 2026. This is an open access article under the CC '
                                                         'BY-NC-ND 4.0 license.'))
    with pytest.raises(ohfkit.LicenceError, match='restriction marker'):
        build_card(xml_workdir)
    with pytest.raises(ohfkit.LicenceError, match='restriction marker'):  # an argument does not override it
        build_card(xml_workdir, licence='CC-BY-4.0')


def test_xml_without_permissions_fails(xml_workdir):
    # The refusal now names what is missing - the article's own permissions element - because the
    # element is addressed rather than searched for anywhere in the document.
    put(xml_workdir, f'{PMCID}.xml', jats(PARAS, permissions=None))
    with pytest.raises(ohfkit.LicenceError, match='no article licence'):
        build_card(xml_workdir)


def test_licence_argument_that_disagrees_fails(xml_workdir):
    with pytest.raises(ohfkit.LicenceError, match="'CC-BY-3.0' disagrees with 'CC-BY-4.0'"):
        build_card(xml_workdir, licence='CC-BY-3.0')
    assert load(build_card(xml_workdir, licence='CC-BY-4.0'))['author']['source']['license'] == 'CC-BY-4.0'


def test_html_with_cc_by_statement_passes(tmp_path):
    doc = html_workdir(tmp_path, 'This work is licensed under a CC BY 4.0 License.')
    card = html_skeleton(doc, licence_statement=(2, 'This work is licensed under a CC BY 4.0 License'))
    assert card['author']['source']['license'] == 'CC-BY-4.0'
    rec = card['added']['sources'][ohfkit.RIGHTS_KEY]
    assert rec['locator'].startswith('HTML <p> 2 ') and 'licence statement: "This work is licensed' in rec['locator']
    assert ohfkit.source_licence(card, doc) == 'CC-BY-4.0'


def test_html_without_statement_fails(tmp_path):
    doc = html_workdir(tmp_path, None)
    with pytest.raises(ohfkit.LicenceError, match='give licence_statement'):
        html_skeleton(doc, licence='CC-BY-4.0')
    with pytest.raises(ValueError, match='does not contain'):  # a statement that is not on the page
        html_skeleton(doc, licence_statement=(2, 'This work is licensed under a CC BY 4.0 License'))


def test_html_statement_cut_out_of_a_restricted_licence_fails(tmp_path):
    doc = html_workdir(tmp_path, 'This work is licensed under a CC BY 4.0 License; CC BY-NC applies to figures.')
    with pytest.raises(ohfkit.LicenceError, match='restriction marker'):
        html_skeleton(doc, licence_statement=(2, 'This work is licensed under a CC BY 4.0 License'))


def test_check_card_rederives_the_licence(xml_workdir):
    card_path = build_card(xml_workdir)
    card = load(card_path)
    card['author']['source']['license'] = 'CC-BY-3.0'
    errors = check_card.conversion_errors(card, xml_workdir)
    assert any("author.source.license is 'CC-BY-3.0', but the source grants 'CC-BY-4.0'" in e for e in errors)


def test_check_card_fails_html_card_without_rights_record(tmp_path):
    doc = html_workdir(tmp_path, 'This work is licensed under a CC BY 4.0 License.')
    card = html_skeleton(doc, licence_statement=(2, 'This work is licensed under a CC BY 4.0 License'))
    assert ohfkit.source_licence(card, doc) == 'CC-BY-4.0'
    del card['added']['sources'][ohfkit.RIGHTS_KEY]
    with pytest.raises(ohfkit.LicenceError, match="no added.sources\\['rights'\\]"):
        ohfkit.source_licence(card, doc)


IMPRINT = 'London: John Murray, Albemarle Street. 1868.'


def old_work(**kw):
    return {'published': 1868, 'imprint': (2, IMPRINT), 'author_died': 1882,
            'death_source': 'https://example.org/author', **kw}


def book_skeleton(doc, **kw):
    kw.setdefault('url', 'https://example.org/scan')
    kw.setdefault('citation', 'c')
    return ohfkit.skeleton(budget_counter=invented_budget_counter, ident='h_book', doc=doc, topic=['t'], kind='book',
                           sources={'p1': doc.src(1)}, author_names='A', **kw)


def test_public_domain_by_term_passes(tmp_path):
    doc = html_workdir(tmp_path, IMPRINT)
    card = book_skeleton(doc, public_domain=old_work())
    source = card['author']['source']
    assert source['license'] == 'public-domain' and 'doi' not in source and source['url'] == 'https://example.org/scan'
    rec = card['added']['sources'][ohfkit.RIGHTS_KEY]
    assert rec['locator'].startswith('HTML <p> 2 ') and ohfkit.TERM_MARK in rec['locator']
    assert 'United Kingdom' in rec['tool'] and 'ended at the end of 1952' in rec['tool']
    assert 'United States' in rec['tool'] and 'ended at the end of 1963' in rec['tool']
    assert ohfkit.source_licence(json.loads(json.dumps(card)), doc) == 'public-domain'


@pytest.mark.parametrize('change, why', [
    ({'author_died': 2000}, 'United Kingdom: the term'),
    ({'published': 1950, 'imprint': (2, 'Published 1950.'), 'author_died': 1951}, 'does not contain'),
    ({'imprint': (2, 'London: John Murray, Albemarle Street.')}, 'does not name the year 1868'),
    ({'death_source': 'a book'}, 'https URL'),
    ({'author_died': True}, 'are not a publication and a later death'),
    ({'author_died': 1700}, 'are not a publication and a later death'),
])
def test_public_domain_refused(tmp_path, change, why):
    doc = html_workdir(tmp_path, IMPRINT)
    with pytest.raises((ohfkit.LicenceError, ValueError), match=why):
        book_skeleton(doc, public_domain=old_work(**change))


def test_public_domain_needs_every_key(tmp_path):
    doc = html_workdir(tmp_path, IMPRINT)
    terms = old_work()
    del terms['death_source']
    with pytest.raises(ohfkit.LicenceError, match='needs exactly'):
        book_skeleton(doc, public_domain=terms)


def test_public_domain_and_statement_together_fail(tmp_path):
    doc = html_workdir(tmp_path, IMPRINT)
    with pytest.raises(ohfkit.LicenceError, match='not both'):
        book_skeleton(doc, public_domain=old_work(), licence_statement=(2, IMPRINT))


def test_recorded_terms_are_checked_again(tmp_path):
    doc = html_workdir(tmp_path, IMPRINT)
    card = book_skeleton(doc, public_domain=old_work())
    rec = card['added']['sources'][ohfkit.RIGHTS_KEY]
    rec['locator'] = rec['locator'].replace('"author_died": 1882', '"author_died": 2000')
    with pytest.raises(ohfkit.LicenceError, match='United Kingdom: the term'):
        ohfkit.source_licence(card, doc)


def test_work_without_doi_or_url_fails(tmp_path):
    doc = html_workdir(tmp_path, IMPRINT)
    with pytest.raises(ValueError, match='without one the url'):
        book_skeleton(doc, public_domain=old_work(), url=None)


def test_verify_source_without_doi_uses_the_catalogue(tmp_path, monkeypatch):
    import io
    doc = html_workdir(tmp_path, IMPRINT)
    card = book_skeleton(doc, public_domain=old_work(), citation='Darwin C. The variation of animals. 1868.',
                         citation_title='The variation of animals')
    seen = []

    def urlopen(request):
        seen.append(request.full_url)
        if request.full_url == doc.url:
            return io.BytesIO((tmp_path / 'page.html').read_bytes())
        return io.BytesIO(json.dumps({'metadata': {'title': 'The variation of animals'}}).encode())
    monkeypatch.setattr(ohfkit.urllib.request, 'urlopen', urlopen)
    with pytest.raises(ValueError, match='give catalogue'):
        ohfkit.verify_source(card, doc)
    ohfkit.verify_source(card, doc, catalogue=('archive.org', 'item 2'))
    check = card['added']['source_verification']
    assert check['status'] == 'refetched_match' and seen[-1] == 'https://archive.org/metadata/item%202'
    assert check['metadata_check']['title_match'] is True and check['metadata_check']['retracted'] == 'unknown'
    assert 'doi_match' not in check['metadata_check']


def translation(**kw):
    return {'published': 1868, 'imprint': (2, IMPRINT), 'deaths': [
        {'person': 'A', 'role': 'author', 'died': 1882, 'death_source': 'https://example.org/a'},
        {'person': 'T', 'role': 'translator', 'died': 1900, 'death_source': 'https://example.org/t'}], **kw}


def test_term_runs_from_the_latest_death(tmp_path):
    doc = html_workdir(tmp_path, IMPRINT)
    card = book_skeleton(doc, public_domain=translation())
    assert 'ended at the end of 1970' in card['added']['sources'][ohfkit.RIGHTS_KEY]['tool']
    assert ohfkit.source_licence(json.loads(json.dumps(card)), doc) == 'public-domain'


@pytest.mark.parametrize('deaths, why', [
    ([{'person': 'T', 'role': 'translator', 'died': 1900, 'death_source': 'https://example.org/t'}], 'include the author'),
    ([{'person': 'A', 'role': 'author', 'died': 1882, 'death_source': 'https://example.org/a'},
      {'person': 'T', 'role': 'translator', 'died': 1990, 'death_source': 'https://example.org/t'}], 'United Kingdom: the term'),
    ([{'person': 'A', 'role': 'editor', 'died': 1882, 'death_source': 'https://example.org/a'}], 'a role in'),
    ([{'person': 'A', 'role': 'author', 'died': 1882}], 'deaths must be a list'),
    ([{'person': 'A', 'role': 'author', 'died': 1882, 'death_source': 'a book'}], 'https URL'),
])
def test_several_deaths_refused(tmp_path, deaths, why):
    doc = html_workdir(tmp_path, IMPRINT)
    with pytest.raises(ohfkit.LicenceError, match=why):
        book_skeleton(doc, public_domain=translation(deaths=deaths))


def test_recorded_translator_death_is_checked_again(tmp_path):
    doc = html_workdir(tmp_path, IMPRINT)
    card = book_skeleton(doc, public_domain=translation())
    rec = card['added']['sources'][ohfkit.RIGHTS_KEY]
    rec['locator'] = rec['locator'].replace('"died": 1900', '"died": 1990')
    with pytest.raises(ohfkit.LicenceError, match='United Kingdom: the term'):
        ohfkit.source_licence(card, doc)


def test_imprint_year_in_roman_numerals(tmp_path):
    imprint = 'London: Taylor and Francis, Red Lion Court, Fleet Street. MDCCCLXXI.'
    doc = html_workdir(tmp_path, imprint)
    terms = old_work(published=1871, imprint=(2, imprint))
    assert book_skeleton(doc, public_domain=terms)['author']['source']['license'] == 'public-domain'
    assert ohfkit.names_year('MDCCCLXXI.', 1871) and not ohfkit.names_year('MDCCCLXXII.', 1871)
    assert not ohfkit.names_year('XMDCCCLXXI', 1871)


# The version of a CC licence is often only in the link, as Wiley writes it. Read from the prose
# alone, such a block says "CC BY" with no version and the article is refused although its own
# permissions block states the licence plainly (found on PMC4717280, an Aging Cell paper quoted by
# an accepted card, 2026-10-21).
WILEY = ('This is an open access article under the terms of the <ext-link '
         'xlink:href="http://creativecommons.org/licenses/by/4.0/" ext-link-type="uri">Creative Commons '
         'Attribution</ext-link> License, which permits use, distribution and reproduction in any medium, '
         'provided the original work is properly cited.')


def xml_with(tmp_path, permissions):
    put(tmp_path, f'{PMCID}.xml',
        jats(PARAS, permissions).replace(b'<article>',
                                         b'<article xmlns:xlink="http://www.w3.org/1999/xlink">'))
    return ohfkit.Document(PMCID, tmp_path)


def test_a_licence_version_only_in_a_link_is_read(tmp_path):
    doc = xml_with(tmp_path, WILEY)
    assert 'creativecommons.org/licenses/by/4.0' in doc.permissions
    assert doc.licence() == 'CC-BY-4.0'


def test_a_restriction_only_in_a_link_still_stops_the_conversion(tmp_path):
    """Reading the hrefs cannot loosen the check: it is also where an NC URL would stand."""
    doc = xml_with(tmp_path, WILEY.replace('licenses/by/4.0', 'licenses/by-nc/4.0'))
    with pytest.raises(ohfkit.LicenceError, match='restriction marker'):
        doc.licence()


def test_the_prose_of_the_block_is_still_read(tmp_path):
    """A block with no link is unchanged by this: its prose decides, as before."""
    doc = xml_with(tmp_path, 'This article is licensed under a Creative Commons Attribution 4.0 '
                             'International License')
    assert doc.licence() == 'CC-BY-4.0'
    bare = xml_with(tmp_path, 'This is an open access article under the terms of the Creative Commons '
                              'Attribution License.')
    if ohfkit.standard_release() >= ohfkit.UNVERSIONED_SINCE:
        assert bare.licence() == ohfkit.UNVERSIONED_LICENCE
    else:
        with pytest.raises(ohfkit.LicenceError, match='CC BY with no version'):
            bare.licence()


JATS_PERMISSIONS = '<permissions xmlns:xlink="http://www.w3.org/1999/xlink">{}</permissions>'


def permissions(inner):
    import xml.etree.ElementTree as ET
    return ET.fromstring(JATS_PERMISSIONS.format(inner))


@pytest.mark.parametrize('inner, expected', [
    # The article's own licence element decides, and a grant to the data beside it is not read for the
    # article's version. Two rounds of review broke every attempt to do this by reading the prose of a
    # whole block: first a data version was read as the article's, then a sentence naming the article
    # *and* its data was refused for naming the data. The lead's rule ends the guessing.
    ('<license xlink:href="http://creativecommons.org/licenses/by/4.0/"><license-p>This article is '
     'distributed under the Creative Commons Attribution License.</license-p></license>'
     '<p>The data are released under CC BY 2.0.</p>', 'CC-BY-4.0'),
    ('<license><license-p>Creative Commons Attribution License '
     '(http://creativecommons.org/licenses/by/2.0)</license-p></license>', 'CC-BY-2.0'),
    ('<license><license-p>This article and its data are licensed under Creative Commons Attribution 4.0 '
     '(CC BY).</license-p></license>', 'CC-BY-4.0'),
])
def test_the_article_licence_element_decides_the_version(inner, expected):
    assert ohfkit.licence_of_jats(permissions(inner)) == expected


@pytest.mark.parametrize('inner, why', [
    # The review's own repros moved to test_the_data_version_is_never_borrowed_for_the_article, which
    # is version-aware: from 1.1.4 the article's own element is read as an unversioned Attribution
    # licence, and the version written beside it for the data is still not the article's.
    # two elements, two versions: which is the article's cannot be read, so it is refused, not guessed
    ('<license xlink:href="http://creativecommons.org/licenses/by/4.0/"><license-p>article</license-p>'
     '</license><license xlink:href="http://creativecommons.org/licenses/by/2.0/"><license-p>data'
     '</license-p></license>', 'which of them is the article'),
    # a restriction anywhere in the block stops it, deliberately wider than the element
    ('<license xlink:href="http://creativecommons.org/licenses/by/4.0/"><license-p>article</license-p>'
     '</license><p>Figures are CC BY-NC 4.0.</p>', 'restriction marker'),
    ('<p>Open access under CC BY 4.0.</p>', 'no <license> element'),
])
def test_a_permissions_block_the_article_licence_cannot_be_read_from_is_refused(inner, why):
    with pytest.raises(ohfkit.LicenceError, match=why):
        ohfkit.licence_of_jats(permissions(inner))


# ---------------------------------------------------------------- the article's own permissions only
# The hole the last round of review found: with `root.find('.//permissions')` the licence of a part of
# the document is read as the article's. These are the review's own mutants, at the level of the
# addressing rather than of the version rules, because the version rules were never the defect: a
# figure's CC BY 4.0 element would license an article that grants nothing, and the bug is invisible on
# every article that has a block of its own.
ARTICLE = ('<article xmlns:xlink="http://www.w3.org/1999/xlink"><front><article-meta>{meta}'
           '</article-meta></front><body>{body}</body>{tail}</article>')
GRANT = ('<permissions><license xlink:href="http://creativecommons.org/licenses/by/{v}/">'
         '<license-p>Open access under Creative Commons Attribution.</license-p></license></permissions>')


def article(meta='', body='', tail=''):
    import xml.etree.ElementTree as ET
    return ET.fromstring(ARTICLE.format(meta=meta, body=body, tail=tail))


def test_the_articles_own_permissions_is_read():
    root = article(meta=GRANT.format(v='4.0'))
    assert ohfkit.licence_of_jats(ohfkit.article_permissions(root)) == 'CC-BY-4.0'


def test_a_figures_permissions_is_not_the_articles():
    root = article(body=f'<fig id="f1"><label>Fig 1</label>{GRANT.format(v="4.0")}</fig>')
    with pytest.raises(ohfkit.LicenceError, match='no article licence'):
        ohfkit.article_permissions(root)


def test_a_sub_articles_permissions_is_not_the_articles():
    root = article(tail=f'<sub-article article-type="reviewer-report"><front-stub>'
                        f'{GRANT.format(v="4.0")}</front-stub></sub-article>')
    with pytest.raises(ohfkit.LicenceError, match='no article licence'):
        ohfkit.article_permissions(root)


def test_a_table_or_supplement_permissions_is_not_the_articles():
    root = article(body=f'<table-wrap>{GRANT.format(v="3.0")}</table-wrap>'
                        f'<supplementary-material>{GRANT.format(v="2.0")}</supplementary-material>')
    with pytest.raises(ohfkit.LicenceError, match='no article licence'):
        ohfkit.article_permissions(root)


def test_a_part_of_the_document_is_not_a_fallback_for_the_article():
    """Not even when the article's own block says nothing the kit can use: a refusal stands."""
    root = article(meta='<permissions><copyright-statement>All rights reserved.</copyright-statement>'
                        '</permissions>',
                   body=f'<fig>{GRANT.format(v="4.0")}</fig>')
    with pytest.raises(ohfkit.LicenceError, match='no <license> element'):
        ohfkit.licence_of_jats(ohfkit.article_permissions(root))


def test_the_articles_block_is_read_even_when_a_part_carries_another():
    root = article(meta=GRANT.format(v='4.0'), body=f'<fig>{GRANT.format(v="2.0")}</fig>')
    assert ohfkit.licence_of_jats(ohfkit.article_permissions(root)) == 'CC-BY-4.0'


def test_permissions_outside_article_meta_is_not_the_articles():
    """`article/front/permissions` is not the address either: the element is addressed, not searched."""
    import xml.etree.ElementTree as ET
    root = ET.fromstring('<article xmlns:xlink="http://www.w3.org/1999/xlink"><front>'
                         + GRANT.format(v='4.0') + '<article-meta/></front></article>')
    with pytest.raises(ohfkit.LicenceError, match='no article licence'):
        ohfkit.article_permissions(root)


def test_a_document_that_is_not_an_article_is_refused():
    import xml.etree.ElementTree as ET
    root = ET.fromstring('<pmc-articleset><article><front><article-meta/></front></article>'
                         '</pmc-articleset>')
    with pytest.raises(ohfkit.LicenceError, match='not an article'):
        ohfkit.article_permissions(root)


# -- an Attribution licence whose record states no version ------------------------------------------

UNVERSIONED = ('This is an open-access article distributed under the terms of the Creative Commons '
               'Attribution License, which permits unrestricted use, distribution, and reproduction in '
               'any medium, provided the original author and source are properly credited.')


def standard_is(version):
    """Whether the checkout under test is at least this release."""
    return ohfkit.standard_release() >= version


@pytest.mark.skipif(not standard_is((1, 1, 4)), reason='the value is defined by OHF 1.1.4')
@pytest.mark.parametrize('statement, expected', [
    # The owner's four mutants, and the fifth the standard asked for.
    (UNVERSIONED, ohfkit.UNVERSIONED_LICENCE),
    (UNVERSIONED.replace('Creative Commons Attribution License',
                         'Creative Commons Attribution-NonCommercial License'), None),
    (UNVERSIONED.replace('Creative Commons Attribution License',
                         'Creative Commons Attribution-ShareAlike License'), None),
    (UNVERSIONED.replace('Creative Commons Attribution License',
                         'Creative Commons Attribution-NoDerivatives License'), None),
    # Exactly Attribution in words, with an NC link beside it in the same block: the rule is about the
    # record, not about one element of it, so this is refused.
    (UNVERSIONED + ' See http://creativecommons.org/licenses/by-nc/3.0/.', None),
])
def test_the_five_mutants_of_an_unversioned_attribution_licence(statement, expected):
    if expected is None:
        with pytest.raises(ohfkit.LicenceError):
            ohfkit.licence_of(statement)
    else:
        assert ohfkit.licence_of(statement) == expected


def test_an_unversioned_attribution_licence_is_refused_before_the_release_that_defines_it():
    """The value is defined by OHF 1.1.4 and a card at 1.0 cannot carry what 1.0 does not define, so
    the rule is gated on the checkout rather than on the kit's own version. Against an older standard
    the statement is refused exactly as before, which is what keeps already accepted 1.0 cards from
    changing under a kit upgrade."""
    if standard_is((1, 1, 4)):
        assert ohfkit.licence_of(UNVERSIONED) == ohfkit.UNVERSIONED_LICENCE
    else:
        with pytest.raises(ohfkit.LicenceError) as e:
            ohfkit.licence_of(UNVERSIONED)
        assert 'no version' in str(e.value) and '1.1.4' in str(e.value)


def test_a_version_in_the_statement_still_wins_and_is_never_guessed():
    """1.1.4 did not make versions inferable. A statement that names a version keeps it; one that names
    none is recorded as naming none, which is a different value from any version."""
    assert ohfkit.licence_of(UNVERSIONED.replace('Attribution License',
                                                 'Attribution 4.0 International License')) == 'CC-BY-4.0'
    assert ohfkit.UNVERSIONED_LICENCE not in ('CC-BY-4.0', 'CC-BY-3.0', 'CC-BY-2.5', 'CC-BY-2.0',
                                              'CC-BY-1.0')
    assert ohfkit.UNVERSIONED_LICENCE in ohfkit.ALLOWED_LICENCES
@pytest.mark.parametrize('statement', [
    'distributed under the terms of the Creative Commons Attribution License, which permits',
    ('Copyright 2016 Conn and Nelson. This is an open-access article distributed under the terms of the '
     'Creative Commons Attribution License (CC BY). The use, distribution or reproduction in other '
     'forums is permitted'),
])
def test_an_attribution_licence_with_no_version_in_the_record(statement):
    """These were refused until 0.9.3, and the reason they were is still true: a version from a
    publisher's policy page is not in the card's own bytes, so no version is inferred. What the owner's
    rule changed is the answer - the grant that IS in the bytes is recorded as the unversioned
    Attribution licence it is, rather than refused along with the missing version. Frontiers articles
    say exactly this and nothing more, and there are five such records among the 37 the showcase has
    measured."""
    if ohfkit.standard_release() >= ohfkit.UNVERSIONED_SINCE:
        assert ohfkit.licence_of(statement) == ohfkit.UNVERSIONED_LICENCE
    else:
        with pytest.raises(ohfkit.LicenceError, match='no version'):
            ohfkit.licence_of(statement)


@pytest.mark.parametrize('inner, data_version', [
    ('<license><license-p>This article is distributed under CC BY.</license-p></license>'
     '<p>The data are released under the following licence. http://creativecommons.org/licenses/by/2.0/</p>',
     'CC-BY-2.0'),
    ('<license><license-p>Licensed under CC BY.</license-p></license>'
     '<p>Supplementary material is covered by https://creativecommons.org/licenses/by/1.0/</p>',
     'CC-BY-1.0'),
])
def test_the_data_version_is_never_borrowed_for_the_article(inner, data_version):
    """Two repros from the review that produced the element rule: the article's own licence element
    says CC BY with no version, and a version sits beside it in the block for the data or the
    supplement. Reading the block as prose made that version look like the article's.

    From 1.1.4 the article's element is read as an unversioned Attribution licence, which is the honest
    answer: the grant is stated, the version is not, and the version that IS stated belongs to
    something else. Before 1.1.4 the same block was refused. Either way the data's version is never
    the answer, which is the whole point of these cases."""
    if ohfkit.standard_release() >= ohfkit.UNVERSIONED_SINCE:
        got = ohfkit.licence_of_jats(permissions(inner))
        assert got == ohfkit.UNVERSIONED_LICENCE
        assert got != data_version
    else:
        with pytest.raises(ohfkit.LicenceError, match='CC BY with no version'):
            ohfkit.licence_of_jats(permissions(inner))


def test_a_card_declares_the_release_line_of_the_checkout_it_was_built_against(xml_workdir):
    """`standard_version` was the constant '1.0' while the standard went to 1.1, so the kit could emit
    only a 1.0 card whatever checkout it was given, and a conversion that needed the fields 1.1 added
    had no way to declare them. The checkout is the single source of truth: the same OHF_REPO
    validates the card. Patch releases are not card versions - 1.1.3 and 1.1.4 both emit `1.1`."""
    card = load(build_card(xml_workdir))
    assert card['standard_version'] == ohfkit.standard_line()
    assert card['standard_version'] == '.'.join(str(n) for n in ohfkit.standard_release()[:2])
    assert ohfkit.standard_line((1, 1, 3)) == ohfkit.standard_line((1, 1, 4)) == '1.1'
    assert ohfkit.standard_line((1, 0, 1)) == '1.0'


def test_a_card_declares_the_vocabularies_its_release_line_requires(xml_workdir):
    """The vocabularies used to be copied from `examples/cards/muller-sheltering.json`, which is a 1.0
    card even in a 1.1 checkout. So a card emitted as 1.1 came out without `terms`, and the schema
    refused it - which is the first thing the first real 1.1 card met, after the emission itself had
    been reviewed and released. A card declares the vocabularies of the checkout it was built
    against, so they are read from that checkout's own files and not from one of its examples."""
    card = load(build_card(xml_workdir))
    vocab = card['vocabularies']
    assert set(vocab) >= {'heuristics', 'profiles'}
    if ohfkit.standard_release()[:2] >= (1, 1):
        assert 'terms' in vocab, 'a 1.1 card declares the terms vocabulary'
        assert vocab['terms']['id'] == 'ohf:terms@1'
        import hashlib
        import os
        from pathlib import Path
        raw = (Path(os.environ['OHF_REPO']) / 'vocabularies' / 'terms-1.json').read_bytes()
        assert vocab['terms']['sha256'] == 'sha256:' + hashlib.sha256(raw).hexdigest(), \
            'the hash is of the checkout\'s own file, not of a string carried in the kit'
    else:
        assert 'terms' not in vocab, 'a 1.0 card declares no terms vocabulary'


def test_the_card_the_kit_emits_passes_the_standards_own_checkers(xml_workdir):
    """End to end, because the unit tests are what the vocabularies defect walked past: a card the
    kit builds is handed to the standard's own tools and must come back valid.

    The emission of 1.1 cards had unit tests and a release before anything built a 1.1 card and fed it
    to the schema; the first one that was fed to the schema was refused, for a vocabulary the kit had
    copied from a 1.0 example. A test that asserts the pieces cannot catch that. This one asserts the
    answer.

    The card goes through the kit's own order - build, finalise, merge - and nothing is edited after
    the hash is taken. The first version of this test wrote the members a build fills (the profile's
    domain, the source verification) into the finished JSON by hand, which left `content_hash` and the
    ledger pointing at bytes that no longer existed; the standard's `content_hash.py --check` says so,
    and a review found it. A card is not a dict that happens to validate: editing one after it is
    finished is the same mistake as feeding a skeleton to a checker, which this test already existed
    to catch."""
    import subprocess
    import sys as _sys
    from pathlib import Path as _Path

    card_path = _Path(xml_workdir) / 'card.json'
    doc = ohfkit.Document(PMCID, xml_workdir)
    card = ohfkit.skeleton(budget_counter=invented_budget_counter, ident='h_e2e', doc=doc, citation='Test A. A test. 2026', doi='10.0000/e2e',
                           topic=['test'], sources={'p1': doc.src(1), 'p2': doc.src(2)},
                           author_names='A Test')
    card['author']['layers']['core']['statement'] = doc.author(
        1, 'We propose that X causes Y when recombination stops.')
    card['added']['layers']['core']['scope'] = {'value': 'In mice, X may cause Y.', 'src': 'p2',
                                                'paraphrase': True, 'basis_quote': 'X may cause Y'}
    # The members a build fills, filled before the card is finished rather than after.
    card['added']['layers']['profile'] = {
        'domain': ['none'] if card['standard_version'] == '1.4' else 'none'}
    card['added']['source_verification'] = {
        'status': 'refetched_match',
        'fetched_from': card['author']['source'].get('url') or 'https://example.org/article',
        'fetched_at': '2026-10-24T07:00:00Z',
        'sha256': card['author']['source']['source_text_sha256'],
        'metadata_check': {'registry': 'none', 'record_url': 'https://example.org/record',
                           'checked_at': '2026-10-24T07:00:00Z', 'title_match': True,
                           'retracted': 'unknown'}}
    ohfkit.finish(card, card_path)
    # The merge rewrites the card and its ledger together, so the hash stays the hash of what is there.
    assert run_pass(card_path, xml_workdir).returncode == 0
    card = load(card_path)

    for tool in ('validate.py', 'check_gaps.py', 'check_refs.py'):
        r = subprocess.run([_sys.executable, str(_Path(ohfkit.REPO) / 'tools' / tool), str(card_path)],
                           capture_output=True, text=True, cwd=str(ohfkit.REPO))
        assert r.returncode == 0, (f'{tool} refused a card this kit emitted at '
                                   f'standard_version {card["standard_version"]}:\n'
                                   f'{r.stdout[-1200:]}\n{r.stderr[-600:]}')
    # And the hash is the hash of these bytes: the standard checks that itself.
    r = subprocess.run([_sys.executable, str(_Path(ohfkit.REPO) / 'tools' / 'content_hash.py'),
                        '--check', str(card_path)], capture_output=True, text=True, cwd=str(ohfkit.REPO))
    assert r.returncode == 0, f'content_hash --check refused it:\n{r.stdout[-600:]}\n{r.stderr[-400:]}'
    assert card['content_hash'] == ohfkit.content_hash(card)
    assert card['added']['integrity']['entailment'], 'the merge left the card with its records'
    assert card['standard_version'] == ohfkit.standard_line(), \
        'the card declares the release line of the checkout it was built against'

    # And the invariant between the two sides, which neither side can check alone: no path this kit
    # demands a gap for may be a path the standard refuses a gap for. A fixture card is not a finished
    # conversion, so the kit demands plenty of gaps here and that is right - what must never happen is
    # that it demands one the standard would reject.
    #
    # Found exactly here: `gap_coverage` demanded `profile.aging_hallmarks[]`, a path of a profile the
    # card does not select, which the standard's `check_gaps` refuses as GAP_PROFILE_FIELD. The kit
    # was asking for what the standard forbids, because it read `profiles-1.json` while the standard
    # reads `profiles-2.json`, where the aging profile lives. Only a card with a profile could show
    # it, and the first one was a real conversion rather than any fixture.
    # The oracle is the standard's answer about the gaps themselves, not a file either side picked.
    # Every gap this kit demands must pass the standard's own `check_gaps.check` - called the way the
    # standard calls it - without GAP_PROFILE_FIELD. A kit that demands a gap the standard refuses
    # leaves a card that can satisfy neither, which is what happened on the first conversion to
    # declare a profile.
    #
    # Two earlier versions of this check were worthless, and in the same way: the first took both
    # sides from the kit, so it compared the kit with itself; the second read the standard's default
    # by regex out of `check_gaps.py`, which a decoy file and a comment naming it would satisfy. Both
    # passed against heads that had the defect. The question has to be put to the standard's code.
    import gap_coverage
    check_gaps, policy = gap_coverage._tools()
    demanded = [row['path'] for row in gap_coverage.unrecorded(card)]
    probe = json.loads(json.dumps(card))
    probe['added']['gaps'] = [{'path': path, 'disposition': 'not_supplied',
                               'reason': 'Probe: does the standard admit a gap here.'}
                              for path in demanded]
    answer = check_gaps.check(probe, policy,
                              check_gaps.load(_Path(ohfkit.REPO) / 'spec/field-catalogue.json'),
                              check_gaps.load(_Path(ohfkit.REPO) / 'spec/mapping.json'))
    refused = sorted({e.get('path') for e in answer.get('errors', [])
                      if e.get('code') == 'GAP_PROFILE_FIELD'})
    assert not refused, (f'the kit demands a gap on {refused}, which the standard refuses as '
                        f'GAP_PROFILE_FIELD: paths of a profile the card does not select')


def test_a_decoy_profiles_file_cannot_make_the_profile_check_pass(xml_workdir, tmp_path):
    """The regression a review asked for, from its own decoy. Both earlier versions of the profile
    check chose a file: the kit took `max(profiles-*.json)` and the test read the standard's default
    by regex out of `check_gaps.py`. An extra `profiles-99.json` in the checkout - with a comment
    naming it, to satisfy the regex - would then have been chosen by the kit and ignored by the
    standard, and both the kit and the test would have been green with the defect live.

    So: a checkout with such a decoy, and the kit must still agree with the standard. It can only do
    that by not choosing a file at all, which is what it now does - it asks `check_gaps.check` about
    the gaps themselves."""
    import shutil
    from pathlib import Path
    import gap_coverage
    real = Path(ohfkit.REPO)
    if not (real / 'vocabularies' / 'profiles-2.json').exists():
        pytest.skip(f'the decoy needs a checkout with more than one profiles vocabulary; '
                    f'OHF_REPO names {(real / "VERSION").read_text().strip()}')
    decoyed = tmp_path / 'standard-with-a-decoy'
    shutil.copytree(real, decoyed, symlinks=True)
    # A vocabulary the standard will never read, numbered so that `max()` would prefer it, holding a
    # profile that claims a path the card does not select.
    (decoyed / 'vocabularies' / 'profiles-99.json').write_text(json.dumps(
        {'schema': 'ohf:profiles@99',
         'profiles': [{'id': 'ohf:decoy@1', 'paths': ['core.scope']}, {'id': 'none', 'paths': []}]}))
    gaps = decoyed / 'tools' / 'check_gaps.py'
    gaps.write_text('# a comment naming vocabularies/profiles-99.json, to satisfy a regex\n'
                    + gaps.read_text())

    card_path = build_card(xml_workdir)
    card = load(card_path)
    before = {row['path'] for row in gap_coverage.unrecorded(card)}
    old_repo = ohfkit.REPO
    try:
        ohfkit.REPO = decoyed
        gap_coverage._tools.cache_clear() if hasattr(gap_coverage._tools, 'cache_clear') else None
        after = {row['path'] for row in gap_coverage.unrecorded(card)}
    finally:
        ohfkit.REPO = old_repo
    assert after == before, (
        'a decoy profiles vocabulary changed what the kit demands, so the kit is choosing the file '
        f'rather than asking the standard: {sorted(after ^ before)}')
    assert 'core.scope' not in after, 'the decoy profile was read as if it were the standard\'s'
