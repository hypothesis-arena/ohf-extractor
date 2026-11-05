"""Helpers for converting a published article into an OHF 1.0 card.

A card builder imports this module, registers its source documents, and writes
values through these helpers. They fail rather than let a value drift from its
source: an author-zone value must be whole sentences of the paragraph it names, an
evidence quotation must be an exact substring of its own source document, and the
licence is read from the source, not given.
Every timestamp comes from the clock at the moment of the step it records.
"""
import datetime
import gzip
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
import zlib
import xml.etree.ElementTree as ET
from pathlib import Path

# A checkout of the open-hypothesis-format repository at the release the cards are written for.
if not os.environ.get('OHF_REPO'):
    sys.exit('set OHF_REPO to a checkout of the open-hypothesis-format repository')
REPO = Path(os.environ['OHF_REPO']).resolve()
sys.path.insert(0, str(REPO))
from tools.content_hash import content_hash  # noqa: E402

SKILL = Path(__file__).resolve().parents[1]
# The version is written once, in the SKILL.md front matter.
CONVERTER = {'name': 'ohf-extractor',
             'version': re.search(r'^version: (\S+)$', (SKILL / 'SKILL.md').read_text(), re.M).group(1)}
# The model that reads the article, recorded in added.by.model. The kit assumes no model: it is
# given by the OHF_MODEL environment variable, and a build without it fails rather than record a
# model that did not do the reading.
MODEL = os.environ.get('OHF_MODEL') or None
# Appended to the User-Agent of a catalogue request when OHF_CONTACT is set, as Crossref asks of
# a client. The kit carries no address of its own.
CONTACT = os.environ.get('OHF_CONTACT') or None
EPMC = 'https://www.ebi.ac.uk/europepmc/webservices/rest/{}/fullTextXML'
LOCATOR = 'XML .//p[{}] (1-based document order)'
# The time-check script that check_card.py runs; its bytes are part of rules_hash().
TIME_CHECK = Path(__file__).resolve().parent / 'time_check.py'
# Appended to an author-zone locator by Document.author_part: the value is part of a sentence.
PART_MARK = '; part of a sentence, cut by the converter: '
# The added.sources record that holds the licence statement of a PDF or HTML main source.
RIGHTS_KEY = 'rights'
RIGHTS_MARK = '; licence statement: '
# The added.sources record of what a submission manifest states about the generation of the text.
GENERATION_KEY = 'generation'
# The added.sources record of the converter's sentence decisions on a submitted text: own or third_party.
OWNERSHIP_KEY = 'ownership'
OWNERSHIP_MARK = '; sentence decisions: '
DECISIONS = ('own', 'third_party')
# Marks the rights record of a main source in the public domain because its copyright terms ended.
TERM_MARK = '; copyright terms ended: '
REFERENCE_ONLY_MARK = '; cited by src only, not quoted: '
# The copyright terms a public-domain work by age must be past: (where, primary source, rule,
# the year the term counts from, years). A term of N years from year Y ends at the end of Y + N.
COPYRIGHT_TERMS = (
    ('United Kingdom', 'https://www.legislation.gov.uk/ukpga/1988/48/section/12',
     'Copyright, Designs and Patents Act 1988, s. 12(2): 70 years from the end of the calendar year '
     'in which the author dies', 'author_died', 70),
    ('United States', 'https://www.law.cornell.edu/uscode/text/17/304',
     '17 U.S.C. 304(b): a work published before 1978 has at most 95 years from the date its copyright '
     'was first secured', 'published', 95),
)


def model():
    """The model recorded in added.by.model, from OHF_MODEL. A card states which model read the
    article; the kit will not guess one, so a build without OHF_MODEL stops here."""
    if not MODEL:
        raise ValueError('set OHF_MODEL to the model that reads the article (added.by.model)')
    return MODEL


def user_agent():
    """The User-Agent of a catalogue request. Crossref asks a client to identify itself and may
    give a contact address better service; the address is the caller's, from OHF_CONTACT, and the
    kit has none of its own."""
    name = f"{CONVERTER['name']}/{CONVERTER['version']}"
    return f'{name} (mailto:{CONTACT})' if CONTACT else name


def now():
    """The current UTC time, to the second, as OHF writes it.

    The time check refuses a time with :00 seconds as a likely placeholder, so a real
    reading that falls on :00 waits one second and reads the clock again."""
    t = datetime.datetime.now(datetime.timezone.utc)
    if t.second == 0:
        time.sleep(1.05 - t.microsecond / 1e6)
        t = datetime.datetime.now(datetime.timezone.utc)
    return t.strftime('%Y-%m-%dT%H:%M:%SZ')


def norm(text):
    return re.sub(r'\s+', ' ', text).strip()


# -- comparing a registry's title with a card's citation -------------------------------------------
#
# A registry answers in typeset prose and a card's citation is typed: Crossref holds "The 'Amoeboid
# Predator-Fungal Animal Virulence' Hypothesis" with U+2018 and U+2019 where the citation has ASCII
# apostrophes, "A Maternal-Offspring Coadaptation Theory..." with an EN DASH where the citation has a
# hyphen, "Rapamycin-mediated..." with U+2010, an EM SPACE before a colon, and inline JATS markup
# with the line breaks of a pretty-printed document inside the string. A comparison that does not
# undo those answers "the titles differ" about identical titles, which is how three of the four
# finished cards came to carry `title_match: false` beside `doi_match: true`.
#
# Only the comparison is normalised. Nothing stored moves: the citation a card carries and the title
# a record holds are left exactly as they are, and this form exists for the length of one comparison.
# Real markup only, by name and by form. A review found `<[^>]+>` stripping `< 5 and y >` out of a
# title that says "x < 5 and y > 2": the angle brackets of an inequality are not a tag, and a
# comparison that eats them compares two titles neither of which was written. So a tag is one of the
# names JATS and HTML actually use, in proper form, and anything else stays text.
TAG_NAMES = ('scp', 'sup', 'sub', 'i', 'b', 'em', 'strong', 'italic', 'bold', 'roman', 'sc',
             'monospace', 'underline', 'overline', 'strike', 'br', 'p', 'span', 'div', 'a', 'xref',
             'ext-link', 'uri', 'inline-formula', 'disp-formula', 'tex-math', 'named-content',
             'styled-content', 'alternatives', 'small', 'big', 'tt', 'code',
             'mml:math', 'mml:mi', 'mml:mn', 'mml:mo', 'mml:msup', 'mml:msub', 'mml:mrow',
             'mml:mfrac', 'mml:msqrt')
MARKUP = re.compile(r'(?:\s*\n\s*)?<(?P<closing>/)?(?P<tag>' + '|'.join(re.escape(n) for n in TAG_NAMES) +
                    r')(?:\s+[^<>]*?)?\s*/?>(?:\s*\n\s*)?', re.I)
# What NFKC leaves alone: the quotation marks and the dash family. Nothing beyond these is folded -
# in particular no punctuation is stripped, because a missing subtitle or a changed unit must still
# tell two titles apart.
QUOTES = {0x2018: "'", 0x2019: "'", 0x201a: "'", 0x201b: "'", 0x2032: "'", 0x2039: "'", 0x203a: "'",
          0x201c: '"', 0x201d: '"', 0x201e: '"', 0x201f: '"', 0x2033: '"', 0x00ab: '"', 0x00bb: '"'}
DASHES = {0x2010: '-', 0x2011: '-', 0x2012: '-', 0x2013: '-', 0x2014: '-', 0x2015: '-', 0x2043: '-',
          0x2212: '-', 0xfe58: '-', 0xfe63: '-', 0xff0d: '-'}
COMPARE_FOLD = {**QUOTES, **DASHES}
SPACE_BEFORE_MARK = re.compile(r'\s+(?=[:;,.?!])')
# **Superscripts and subscripts are not folded**: NFKC turns x² into x2 and
# 10⁻³ into 10-3, and those are different titles - a squared term is not a term followed by a two.
# Unicode's <super>/<sub> decomposition identifies the characters, including letters. Registry
# sup/sub tags carry the same distinction. Keep it as a style on text runs before removing markup;
# a hand list misses letters, and private-use placeholders can collide with literal source text.


def title_runs(text):
    """Text runs with their nested sup/sub styles; other known markup and its formatting go."""
    runs, styles = [], []

    def append(value):
        for char in value:
            decomposition = unicodedata.decomposition(char)
            script = ('sup' if decomposition.startswith('<super>') else
                      'sub' if decomposition.startswith('<sub>') else None)
            style = tuple(styles) + ((script,) if script else ())
            value = unicodedata.normalize('NFKC', char) if script else char
            if runs and runs[-1][0] == style:
                runs[-1] = (style, runs[-1][1] + value)
            else:
                runs.append((style, value))

    end = 0
    for tag in MARKUP.finditer(text or ''):
        append(text[end:tag.start()])
        name = tag.group('tag').lower()
        if name in ('sup', 'sub', 'mml:msup', 'mml:msub'):
            if tag.group('closing'):
                if styles and styles[-1] == name:
                    styles.pop()
                else:
                    append(tag.group())  # unmatched closing tag is text, not a licence to erase it
            else:
                styles.append(name)
        end = tag.end()
    append((text or '')[end:])
    return runs


def compare_form(text, *, fold_scripts=False):
    """`text` as a title comparison sees it, and nowhere else: markup removed, NFKC (except the
    super- and subscripts, which are not folded), quotation marks
    and dashes folded to ASCII, a space before a punctuation mark closed up, whitespace collapsed,
    casefolded.

    Markup goes with the whitespace of a pretty-printed document, but only where that whitespace
    touches a tag and only when it holds a line break: `m\\n<scp>TORC</scp>\\n2-...` is the one title
    `mTORC2-...`, while `<i>Drosophila</i> melanogaster` keeps the space its author wrote, and a line
    break between two ordinary words becomes a space rather than nothing.
    """
    runs = title_runs(text)
    if fold_scripts:
        text = ''.join(value for _, value in runs)
        text = unicodedata.normalize('NFKC', text).translate(COMPARE_FOLD)
    else:
        text = ''.join(''.join(f'<{s}>' for s in style) +
                       unicodedata.normalize('NFKC', value).translate(COMPARE_FOLD) +
                       ''.join(f'</{s}>' for s in reversed(style)) for style, value in runs)
    return ' '.join(SPACE_BEFORE_MARK.sub('', text).split()).casefold()


def script_form(text):
    """`compare_form`'s output with the super- and subscripts folded as well: the form in which `x²`
    and `x2` are one string. Used only to say *why* two titles differ, never to decide they match.

    The dash fold runs again afterwards, because NFKC turns a superscript minus into a MINUS SIGN and
    not into a hyphen: without it `10⁻³` and `10-3` would still differ after folding, and the
    difference between them would be reported as a different title rather than as a typesetting.
    """
    return compare_form(text, fold_scripts=True)


def title_value(value):
    """One nonempty title string, without coercing or joining fields."""
    return value if isinstance(value, str) and value.strip() else None


def title_match(registry_title, citation_title):
    """`(matches, why)` for a registry title against the builder's separate title field.

    Citation text is never parsed. The builder records citation_title before verification; missing
    or malformed titles give a mismatch, never a fallback to a journal, author or other field.

    `why` is `None` when the titles match, `title_differs_in_script` when they differ **only** in
    super- or subscripts (`x²` against `x2`, `10⁻³` against `10-3`), and `title_differs`
    otherwise. The script case is reported rather than folded away: a squared
    term is not a term followed by a two, so the titles do differ - but a reader must be able to see
    that the difference is a typesetting of exponents and not a different work.
    """
    registry_title, citation_title = title_value(registry_title), title_value(citation_title)
    if registry_title is None or citation_title is None:
        return False, 'title_differs'
    want = compare_form(registry_title)
    have = compare_form(citation_title)
    if not want or not have:
        return False, 'title_differs'
    if have == want:
        return True, None
    if script_form(have) == script_form(want):
        return False, 'title_differs_in_script'
    return False, 'title_differs'


def sha256(data):
    return 'sha256:' + hashlib.sha256(data).hexdigest()


def decoded(body, headers):
    """The body as the bytes a reader reads: gunzipped when the server said it is gzip.

    A server may compress a response that was not asked to be compressed — the Internet Archive's
    `id_` form does, returning the original bytes with `Content-Encoding: gzip` though no
    `Accept-Encoding` was sent. Stored as received, such a file parses to nothing: no paragraphs, no
    licence, no error. So the encoding is undone here, and what is written to disk, hashed and quoted
    is one thing: the text. A body that claims an encoding this kit cannot undo is an error, never a
    file that silently holds nothing.
    """
    encoding = (headers.get('Content-Encoding') or headers.get('content-encoding') or '').strip().lower()
    if not encoding or encoding == 'identity':
        return body
    if encoding == 'gzip':
        return gzip.decompress(body)
    if encoding == 'deflate':
        # RFC 9110 says HTTP deflate is the zlib wrapper; servers send the raw stream too. Try the
        # wrapper first and fall back, so a correct body is never refused for being correct.
        try:
            return zlib.decompress(body)
        except zlib.error:
            return zlib.decompress(body, -zlib.MAX_WBITS)
    raise ValueError(f'the response is {encoding!r}-encoded and this kit cannot undo that: '
                     f'fetch it another way rather than storing bytes nothing can read')


def fetch(url, path):
    """Download url to path unless it is already there; return (bytes, retrieved_at).

    The bytes on disk are the decoded ones (see `decoded`), so the sha256 a card records is of the
    text that was read and not of a transport encoding.
    """
    path = Path(path)
    stamp = path.with_suffix(path.suffix + '.retrieved')
    if not path.exists():
        with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': user_agent()})) as r:
            path.write_bytes(decoded(r.read(), dict(r.headers)))
        stamp.write_text(now())
    return path.read_bytes(), stamp.read_text().strip()


# The restriction markers the kit searches for, as the kit names them: a code may carry which of
# these matched, because the word then comes from this list and not from the document.
_MARKERS = ('noncommercial', 'noderiv', 'sharealike', 'nc', 'nd', 'sa')


def _marker(found):
    """Which of the kit's own markers a match is, or 'other'."""
    flat = re.sub(r'[^a-z]', '', (found or '').lower())
    # Longest first, because "noncommercial" also contains "nc".
    return next((m for m in _MARKERS if flat and m in flat), 'other')


class LicenceError(ValueError):
    """The source does not show a licence that allows author-zone text.

    `code` names the reason from a closed set, and `facts` carries the few values a report may need
    beside it, each from the kit's own vocabulary rather than from the document: which restriction
    marker matched, how many licence elements the block had, which licence id was read.

    Why the code exists at all. A review of the licence command found that every attempt to reflect
    *this message* safely failed in a new way - a repr in double quotes when the statement held an
    apostrophe, a `str(e)` one call further out - and the conclusion was that free text from a
    document cannot be filtered, only not quoted. So a caller that must write a refusal into a record
    builds it from `code` and `facts`, and the statement itself travels in one field with its own
    length rule. The message stays as it is for a person reading a traceback.
    """

    def __init__(self, message, code=None, **facts):
        super().__init__(message)
        self.code = code
        self.facts = facts


# A rights statement is read after the dashes in it are made ordinary. A review found NC undetected
# behind an en dash and a non-breaking hyphen - "Attribution-Non-Commercial 2.0 (CC BY-NC 2.0)" with
# typographic characters - which let an NC work through once the allowed versions were widened. A
# licence check that can be defeated by a character set is not a licence check.
_DASHES = {ord(c): '-' for c in '\u2010\u2011\u2012\u2013\u2014\u2015\u2212\u00ad\u2043\ufe63\uff0d'}


def _dashed(text):
    return (text or '').translate(_DASHES)


# A restriction marker anywhere in the rights text stops the conversion.
_RESTRICTED = re.compile(r'licen[cs]es/by-(?:nc|nd|sa)|\bcc[ -]?by[ -]?(?:nc|nd|sa)\b|\bby-(?:nc|nd|sa)\b'
                         r'|non-?\s?commercial|no-?\s?deriv|share-?\s?alike', re.I)
# A version is captured whole, dots and all, so that an unknown one is refused rather than truncated:
# "2.0.1" used to read as 2.0 and "/by/2.0.1/" as CC BY 2.0.
_GRANTS = [  # (pattern, licence); group 1 is the CC BY version where the pattern has one
    (re.compile(r'creativecommons\.org/licen[cs]es/by/(\d+(?:\.\d+)*)', re.I), 'CC-BY-{}'),
    (re.compile(r'creative commons attribution(?: international)?(?: licen[cs]e)?,? (?:version )?'
                r'(\d+(?:\.\d+)*)', re.I), 'CC-BY-{}'),
    (re.compile(r'\bcc[ -]by[ -](\d+(?:\.\d+)*)\b', re.I), 'CC-BY-{}'),
    (re.compile(r'creativecommons\.org/publicdomain/zero/1\.0|\bcc0\b', re.I), 'CC0-1.0'),
    (re.compile(r'\bpublic domain\b', re.I), 'public-domain'),
]
# An unversioned mention of CC BY, which is what the publisher usually writes about the article itself.
_UNVERSIONED = re.compile(r'creative commons attribution(?! ?(?:international )?(?:licen[cs]e)?,? ?'
                          r'(?:version )?\d)|\bcc[ -]by\b(?![ -]?\d)', re.I)
# A licence that is exactly Attribution and states no version. The owner's rule of 2026-10-24: such a
# statement is accepted when the permissions element of the article names Attribution and no NC, ND or
# SA anywhere in the block, and it is written as what it is - an Attribution licence whose version the
# record does not state - never as a guessed 4.0. The form is SPDX's for a licence with no standard
# id, because SPDX has no identifier for CC BY without a version.
#
# It is gated on the checkout of the standard, and that is the point of the gate rather than caution:
# the value is defined by OHF 1.1.4, a card at 1.0 cannot carry a value 1.0 does not define, and 1.0
# is frozen. Against an older checkout the statement is refused exactly as before, so no card built on
# 1.0 or 1.1.3 changes.
UNVERSIONED_LICENCE = 'LicenseRef-CC-BY-version-not-stated'
UNVERSIONED_SINCE = (1, 1, 4)
ALLOWED_LICENCES = (UNVERSIONED_LICENCE, 'CC-BY-4.0', 'CC-BY-3.0', 'CC-BY-2.5', 'CC-BY-2.0', 'CC-BY-1.0',
                    'CC0-1.0', 'public-domain')


def standard_release():
    """The release of the standard checkout OHF_REPO names, as a tuple, for a rule that one version
    defines and an earlier one does not. A VERSION that cannot be read as a release reads as (0, 0, 0),
    so a rule gated on a release stays off rather than guessing."""
    try:
        parts = (REPO / 'VERSION').read_text().strip().split('.')
        return tuple(int(n) for n in parts[:3])
    except (OSError, ValueError):
        return (0, 0, 0)


# The vocabulary files a card declares, by the release line it declares. Read from the checkout's own
# files rather than copied from an example card: the example this used to copy from is a 1.0 card, so
# a card emitted as 1.1 came out without `terms`, which 1.1 requires - and the schema's refusal was
# the first thing the first real 1.1 card met. A card declares the vocabularies of the checkout it was
# built against, so the checkout is where they are read.
VOCABULARIES = {'heuristics': 'heuristics-1.json', 'profiles': 'profiles-1.json'}
VOCABULARIES_SINCE = {(1, 1): {'terms': 'terms-1.json'}}


def vocabularies_of(line):
    """{name: {id, sha256}} for the release line a card declares."""
    wanted = dict(VOCABULARIES)
    for since, more in VOCABULARIES_SINCE.items():
        if tuple(int(n) for n in line.split('.')[:2]) >= since:
            wanted.update(more)
    out = {}
    for name, filename in wanted.items():
        raw = (REPO / 'vocabularies' / filename).read_bytes()
        out[name] = {'id': f'ohf:{name}@{filename.split("-")[1].split(".")[0]}',
                     'sha256': sha256(raw)}
    return out


def standard_line(release=None):
    """The release line a card declares as its standard_version: major.minor of the checkout."""
    return '.'.join(str(n) for n in (release or standard_release())[:2])


def licence_of(text):
    """The licence a rights statement grants: a CC BY version in ALLOWED_LICENCES, CC0-1.0 or
    public-domain.

    Raises LicenceError for an empty statement, any NC, ND or SA marker, a CC BY version outside
    ALLOWED_LICENCES, or two different CC BY versions. A statement that is exactly Attribution with no
    version returns `LicenseRef-CC-BY-version-not-stated` against a checkout of OHF 1.1.4 or later,
    which defines that value, and is refused against an earlier one. A public-domain or
    CC0 mention counts only when no CC BY licence is named: publishers add a CC0 waiver for the data
    to a CC BY article licence.

    A version taken from a publisher's policy page is still refused, however well known the policy:
    what the card may rest on is what its own bytes show. What changed in 1.1.4 is not that a version
    may be inferred - it may not - but that an Attribution licence whose record states no version is
    recorded as exactly that, instead of being refused as if the grant itself were in doubt.

    **What `text` must be: the licence statement of the article itself and nothing else.** A permissions
    block often licenses the article in one place and its data, figures or supplement in another, and
    the version of the second is not the licence of the first. Two rounds of review broke every attempt
    to tell them apart by reading prose - a version scoped to the data was read as the article's, and
    then a sentence naming the article *and* its data was refused for naming the data. There is no
    reliable way to do it in flat text, so this function does not try: for JATS the kit reads the
    `<license>` element alone (`licence_of_jats`), which is where the article's own grant is, and a
    caller with a PDF or a web page passes that article's licence statement, as step 1 of the skill
    requires.
    """
    text = norm(_dashed(text))
    if not text:
        raise LicenceError('no licence statement (no permissions block, or an empty one): stop and report',
                           code='no_statement')
    bad = _RESTRICTED.search(text)
    if bad:
        raise LicenceError(f'the licence has a restriction marker {bad.group(0)!r}: NC, ND and SA works are not '
                           f'converted. Statement: {text[:300]!r}',
                           code='restriction_marker', marker=_marker(bad.group(0)))
    found = set()
    for pattern, grant in _GRANTS:
        for m in pattern.finditer(text):
            found.add(grant.format(m.group(1)) if pattern.groups else grant)
    by = {f for f in found if f.startswith('CC-BY-')}
    if len(by) > 1:
        raise LicenceError(f'ambiguous licence: the statement names {sorted(by)}. Statement: {text[:300]!r}',
                           code='several_versions', count=len(set(by)))
    if by:
        lic = by.pop()
        if lic not in ALLOWED_LICENCES:
            raise LicenceError(f'{lic} is not one of {", ".join(l for l in ALLOWED_LICENCES if l.startswith("CC-BY"))}. '
                               f'Statement: {text[:300]!r}', code='version_not_allowed', licence=lic)
        return lic
    if re.search(r'creative commons attribution|\bcc[ -]by\b', text, re.I):
        # Exactly Attribution with no version. Accepted from OHF 1.1.4, which defines the value; the
        # restriction markers were refused above, so what reaches here carries none.
        if standard_release() >= UNVERSIONED_SINCE:
            return UNVERSIONED_LICENCE
        raise LicenceError(f'ambiguous licence: CC BY with no version, and the standard at {REPO} is '
                           f'{".".join(str(n) for n in standard_release())}, before the 1.1.4 that '
                           f'defines {UNVERSIONED_LICENCE}. Statement: {text[:300]!r}',
                           code='no_version_before_1_1_4')
    if found:
        return 'CC0-1.0' if 'CC0-1.0' in found else 'public-domain'
    raise LicenceError(f'no versioned CC BY, CC0 or public-domain licence in the statement: {text[:300]!r}',
                       code='no_licence_named')


# A "." after one of these tokens does not end a sentence (compared in lower case, with the dot).
ABBREVIATIONS = frozenset(
    'e.g. i.e. et al. fig. figs. vs. cf. eq. eqs. ref. refs. no. nos. approx. ca. resp. viz. etc. al. '
    'dr. mr. mrs. ms. prof. st. suppl. sect. ch. vol. pp. p. ed. eds. tab. ext. sp. spp. var.'.split())
_CLOSERS = '"\'”’)]}»'
# A submitted text is often Markdown: "**A heading.** Then a sentence." ends a sentence after the
# emphasis marks. Only SubmittedText reads them as closers; articles keep _CLOSERS.
MARKDOWN_CLOSERS = _CLOSERS + '*_'
_OPENERS = '(["\'“‘'


def _token_before(text, i):
    """The token that ends with the dot text[i], lower case, without opening brackets."""
    j = i
    while j > 0 and not text[j - 1].isspace():
        j -= 1
    return text[j:i + 1].lower().lstrip(_OPENERS)


def sentence_ends(text, closers=_CLOSERS):
    """Offsets just after each sentence end in `text`: a ".", "?" or "!", with any closing
    quotes or brackets after it, followed by a space or the end of the text. A "." that ends
    a token in ABBREVIATIONS, or that stands between digits, is not an end."""
    ends = set()
    for i, c in enumerate(text):
        if c not in '.?!':
            continue
        if c == '.' and (_token_before(text, i) in ABBREVIATIONS or (i + 1 < len(text) and text[i + 1].isdigit())):
            continue
        k = i + 1
        while k < len(text) and text[k] in closers:
            k += 1
        if k == len(text) or text[k] == ' ':
            ends.add(k)
    return ends


def whole_sentences(para, value, closers=_CLOSERS):
    """True when `value` occurs in `para` beginning at the paragraph start or after a sentence
    end and its space, and ending at a sentence end or the paragraph end."""
    ends = sentence_ends(para, closers) | {len(para)}
    starts = {0} | {e + 1 for e in ends if e < len(para)}
    i = para.find(value)
    while i != -1:
        if i in starts and i + len(value) in ends:
            return True
        i = para.find(value, i + 1)
    return False


def _local(el):
    return el.tag.rsplit('}', 1)[-1] if isinstance(el.tag, str) else ''


def _children(el, name):
    return [child for child in el if _local(child) == name]


def article_permissions(root):
    """The permissions element of **the article itself**: `article/front/article-meta/permissions`.

    Nothing else counts, and there is no fallback. `root.find('.//permissions')` descends into
    whatever carries one - a figure, a table, a supplement, an embedded `sub-article` such as a
    reviewer report or a correction - and returns the first in document order. For an article that
    states no licence of its own that is the licence of something else read as the article's, which is
    how a CC BY 4.0 figure in an all-rights-reserved paper would license the paper. For an article that
    does state one it is usually the right element, which is why the hole stayed open through two
    reviews of the version rules: the bug is invisible on every article that has its own block.

    So the element is addressed, not searched: the article's front matter, its article-meta, its
    permissions. Absent, the answer is a refusal and never the permissions of a part of the document.
    """
    if root is None:
        raise LicenceError('no article element: stop and report', code='no_article_element')
    if _local(root) != 'article':
        raise LicenceError(f'the document root is {_local(root)!r} and not an article, so it has no '
                           f'article licence to read: stop and report', code='root_not_article')
    for front in _children(root, 'front'):
        for meta in _children(front, 'article-meta'):
            for perm in _children(meta, 'permissions'):
                return perm
    raise LicenceError('no article licence: the article has no permissions element of its own '
                       '(article/front/article-meta/permissions). A permissions element elsewhere in '
                       'the document - a figure, a table, a supplement, an embedded sub-article - is '
                       'not the article\'s licence and is not read as one: stop and report',
                       code='no_article_permissions')


def licence_of_jats(perm):
    """The licence of the **article**, from the `<license>` element of a JATS permissions block.

    The lead's rule of 2026-10-23, after two rounds of review broke every attempt to read a whole
    permissions block: the version is taken from the article's own licence element - its attributes and
    links, and the text inside that same element - and from nothing else. A grant to the data, the
    figures or a supplement, which publishers write as a separate `<license>` or as prose beside it, is
    not read for the article's version.

    Refusals: no permissions block or no licence element; a restriction marker anywhere in the block
    (that part is deliberately wider than the element, because an NC URL beside the grant is a reason to
    stop and look); more than one CC BY version inside the element; a version the kit does not know.
    """
    if perm is None:
        raise LicenceError('no permissions block: stop and report', code='no_permissions_block')
    restriction = _RESTRICTED.search(norm(_dashed(permissions_text(perm))))
    if restriction:
        raise LicenceError(f'the licence has a restriction marker {restriction.group(0)!r} somewhere in the '
                           f'permissions block: NC, ND and SA works are not converted',
                           code='restriction_marker', marker=_marker(restriction.group(0)))
    elements = [el for el in perm.iter() if el.tag.rsplit('}', 1)[-1] == 'license']
    if not elements:
        raise LicenceError(f'the permissions block has no <license> element, so the article\'s own licence '
                           f'is not stated in it: {norm(permissions_text(perm))[:200]!r}',
                           code='no_license_element')
    # Every <license> element of the block is the article's licence only if there is one. Where a
    # publisher writes a second element for the data, the two disagree and the block is ambiguous: the
    # kit will not guess which one is the article's.
    grants = [licence_of(permissions_text(el)) for el in elements]
    if len(set(grants)) > 1:
        raise LicenceError(f'the permissions block has {len(elements)} <license> elements granting '
                           f'{", ".join(sorted(set(grants)))}: which of them is the article\'s cannot be '
                           f'read from the block, so it is refused rather than guessed',
                           code='several_license_elements', count=len(elements))
    return grants[0]


def permissions_text(perm):
    """The rights statement of a JATS permissions block: its text and the licence URLs in it.

    The version of a Creative Commons licence is often only in a link, not in the prose. Wiley
    writes "the terms of the <ext-link xlink:href='http://creativecommons.org/licenses/by/4.0/'>
    Creative Commons Attribution</ext-link> License", so a reader of the text alone sees "CC BY"
    with no version and the licence is refused as ambiguous, although the block states it plainly.
    JATS also allows the URL on the license element itself (`license/@xlink:href`).

    So every href inside the block is read with the prose. This cannot loosen the check: the
    restriction markers are searched first, and an href is where a by-nc, by-nd or by-sa URL would
    stand too, which until now the kit could not see either.
    """
    if perm is None:
        return ''
    parts = list(perm.itertext())
    for el in perm.iter():
        for name, value in el.attrib.items():
            if name.rsplit('}', 1)[-1].lower() == 'href':
                parts.append(' ' + value)
    return norm(''.join(parts))


class Document:
    """One source document read as Europe PMC JATS XML, split into paragraphs."""
    # What may close a sentence after its full stop (sentence_ends).
    closers = _CLOSERS

    def __init__(self, pmcid, workdir):
        self.pmcid = pmcid
        self.url = EPMC.format(pmcid)
        self.file = f'{pmcid}.xml'
        data, self.retrieved = fetch(self.url, Path(workdir) / self.file)
        self.sha = sha256(data)
        self.root = ET.fromstring(data)
        self.paragraphs = [norm(''.join(p.itertext())) for p in self.root.iter('p')]
        self.permissions = permissions_text(article_permissions(self.root))

    def para(self, n):
        if not 1 <= n <= len(self.paragraphs):
            raise ValueError(f'{self.pmcid}: no paragraph {n} (has {len(self.paragraphs)})')
        return self.paragraphs[n - 1]

    def check(self, n, text):
        if text not in self.para(n):
            raise ValueError(f'{self.pmcid} p[{n}] does not contain: {text!r}')
        return text

    def locator(self, n):
        self.para(n)
        return LOCATOR.format(n)

    def check_sentences(self, n, text):
        """An exact passage of paragraph n that starts and ends on a sentence boundary."""
        self.check(n, text)
        if not whole_sentences(self.para(n), text, self.closers):
            raise ValueError(f'{self.pmcid} p[{n}]: {text!r} does not start and end on a sentence boundary of the '
                             'paragraph (quote whole sentences, or use author_part(n, text, reason))')
        return text

    def author(self, n, text):
        """An author-zone value: whole sentences of paragraph n, and its locator."""
        return {'value': self.check_sentences(n, text), 'locator': self.locator(n)}

    def author_part(self, n, text, reason):
        """An author-zone value that is part of a sentence, cut on purpose. The locator records
        the cut and its reason, so that a reader and check_card.py see it."""
        if not norm(reason or ''):
            raise ValueError('author_part needs a reason for the cut')
        self.check(n, text)
        if whole_sentences(self.para(n), text, self.closers):
            raise ValueError(f'{self.pmcid} p[{n}]: {text!r} is whole sentences: use author()')
        return {'value': text, 'locator': self.locator(n) + PART_MARK + norm(reason)}

    def licence(self):
        """The licence of this article, from the `<license>` element of its permissions block."""
        return licence_of_jats(article_permissions(self.root))

    def src(self, n):
        """An added.sources record for paragraph n."""
        return {'source': self.url, 'locator': LOCATOR.format(n), 'accessed_at': self.retrieved,
                'tool': 'reading of the Europe PMC full-text XML'}

    def src_table(self, table_id, label):
        if self.root.find(f".//table-wrap[@id='{table_id}']") is None:
            raise ValueError(f'{self.pmcid}: no table-wrap {table_id}')
        return {'source': self.url, 'locator': f"XML .//table-wrap[@id='{table_id}'] ({label})",
                'accessed_at': self.retrieved, 'tool': 'reading of the Europe PMC full-text XML'}

    def item(self, n):
        """An evidence item pointing at paragraph n of this document."""
        return {'artifact': self.file, 'sha256': self.sha, 'locator': LOCATOR.format(n)}


PDF_LOCATOR = 'PDF page {} (text extracted with pypdf {})'


class PdfDocument(Document):
    """A PDF source read page by page. A page plays the part of a paragraph.

    Text comes from pypdf extraction with whitespace collapsed. Extraction can split words
    at line ends; quote passages that extract cleanly rather than repairing the text.
    """

    def __init__(self, url, file, workdir):
        import pypdf
        self.pmcid = Path(file).stem
        self.url, self.file = url, file
        data, self.retrieved = fetch(url, Path(workdir) / file)
        self.sha = sha256(data)
        self.version = pypdf.__version__
        reader = pypdf.PdfReader(str(Path(workdir) / file))
        self.paragraphs = [norm(page.extract_text() or '') for page in reader.pages]
        self.root = None
        self.permissions = ''

    def locator(self, n):
        self.para(n)
        return PDF_LOCATOR.format(n, self.version)

    def licence(self):
        raise LicenceError('a PDF has no permissions block: give skeleton() the licence statement as '
                           'licence_statement=(page, exact text)')

    def src(self, n):
        return {'source': self.url, 'locator': PDF_LOCATOR.format(n, self.version), 'accessed_at': self.retrieved,
                'tool': f'reading of the PDF, text extracted with pypdf {self.version}'}

    def src_table(self, table_id, label):
        raise ValueError('tables in a PDF are cited by page: use src(page)')

    def item(self, n):
        return {'artifact': self.file, 'sha256': self.sha, 'locator': PDF_LOCATOR.format(n, self.version)}


HTML_LOCATOR = 'HTML <p> {} (1-based order of the non-empty <p> elements; section: {})'


# The HTML void elements (no end tag), with the obsolete ones browsers still treat as void.
HTML_VOID = frozenset('area base br col embed hr img input link meta source track wbr '
                      'param keygen frame basefont bgsound command image isindex nextid'.split())
# Elements whose text is not paragraph text, however they are nested.
HTML_SKIP = frozenset(('script', 'style', 'template', 'noscript'))
# A start tag of one of these closes an open <p> (HTML: the p end tag may be omitted before them).
HTML_P_CLOSERS = frozenset('address article aside blockquote details dialog div dl fieldset figcaption figure '
                           'footer form h1 h2 h3 h4 h5 h6 header hgroup hr main menu nav ol p pre search section '
                           'table ul li dd dt'.split())
# A <p> may end with its parent's end tag, except inside these.
HTML_P_NO_PARENT_CLOSE = frozenset('a audio del ins map noscript video'.split())
HTML_HEADINGS = ('h1', 'h2', 'h3', 'h4')


class HtmlParseError(ValueError):
    """A <p> or heading the reader cannot close cleanly; the message gives its line and column."""


class _Paragraphs:
    """Collect the text of every <p> element, and the heading h1-h4 above it, or fail.

    A <p> ends with </p>, with the start tag of an element that closes it under the HTML
    rule (HTML_P_CLOSERS), or with the end tag of its parent. A <p> directly inside a heading
    is a paragraph, and that heading is not a section title. Anything else is an
    HtmlParseError with its position: misnested tags inside a <p>, a <p>
    or heading open at the end of the page, a self-closing <p/>. Text inside script, style,
    template and noscript is skipped. As in HTML, closing a <p> ends the elements still open
    inside it, and a </p> with no open <p> makes an empty <p>. `counts` holds the <p> start tags read and how each
    was closed; they must add up.
    """

    def __init__(self):
        from html.parser import HTMLParser
        out = self

        class P(HTMLParser):
            def handle_starttag(self, tag, attrs):
                out.start(tag, self.getpos())

            def handle_startendtag(self, tag, attrs):
                if out.skip or tag in HTML_VOID:
                    return
                if tag == 'p' or tag in HTML_HEADINGS:
                    out.fail(self.getpos(), f'self-closing <{tag}/> (browsers read it as an open <{tag}>)')
                # any other <x/> is an empty element (foreign content such as SVG)

            def handle_endtag(self, tag):
                out.end(tag, self.getpos())

            def handle_data(self, data):
                if out.cur and not out.skip:
                    out.cur['buf'].append(data)

        self.cur, self.outer, self.skip, self.section, self.orphans = None, None, None, '(none)', {}
        self.paragraphs, self.sections = [], []
        self.counts = {'opened': 0, 'closed_by_end_tag': 0, 'closed_by_next_block': 0, 'closed_by_parent_end': 0,
                       'empty_from_stray_end_tag': 0}
        self.parser = P(convert_charrefs=True)

    @staticmethod
    def fail(pos, msg):
        raise HtmlParseError(f'HTML line {pos[0]}, column {pos[1] + 1}: {msg}')

    def where(self):
        line, col = self.cur['pos']
        return f'<{self.cur["tag"]}> opened at line {line}, column {col + 1}'

    def start(self, tag, pos):
        if self.skip:
            if tag == self.skip[0]:
                self.skip[1] += 1
            return
        if tag in HTML_SKIP:
            self.skip = [tag, 1, pos]
            return
        if self.cur:
            if tag == 'p' and self.cur['tag'] != 'p' and not self.cur['stack'] and not self.outer:
                # <h1><p>Title</p></h1>: HTML parses the <p> as a child of the heading. It is read
                # as a paragraph, and the heading does not become a section title.
                self.cur['nosection'], self.outer = True, self.cur
                self.counts['opened'] += 1
                self.cur = {'tag': 'p', 'stack': [], 'buf': [], 'pos': pos}
                return
            if tag in HTML_P_CLOSERS:
                if self.cur['tag'] != 'p':
                    self.fail(pos, f'<{tag}> inside {self.where()}')
                self.close('closed_by_next_block')
            elif tag not in HTML_VOID:
                self.cur['stack'].append(tag)
                return
            else:
                return
        if tag == 'p' or tag in HTML_HEADINGS:
            self.counts['opened'] += tag == 'p'
            self.cur = {'tag': tag, 'stack': [], 'buf': [], 'pos': pos}

    def end(self, tag, pos):
        if self.skip:
            if tag == self.skip[0]:
                self.skip[1] -= 1
                if not self.skip[1]:
                    self.skip = None
            return
        if tag in HTML_VOID:
            return
        if not self.cur:
            if tag != 'p' and self.orphans.get(tag):
                self.orphans[tag] -= 1
            elif tag == 'p':
                # HTML: a </p> with no open <p> makes an empty <p> element. It has no text, so
                # it gets no number; it is counted so that the count shows it.
                self.counts['opened'] += 1
                self.counts['empty_from_stray_end_tag'] += 1
            return
        stack = self.cur['stack']
        if stack and tag == stack[-1]:
            stack.pop()
        elif tag == self.cur['tag'] and (tag == 'p' or not stack):
            self.close('closed_by_end_tag')
        elif tag not in stack and self.orphans.get(tag):
            self.orphans[tag] -= 1  # the end tag of an element that an earlier close of a <p> ended
        elif tag in stack:
            self.fail(pos, f'</{tag}> inside {self.where()} while <{stack[-1]}> is open (misnested tags)')
        elif self.cur['tag'] != 'p':
            self.fail(pos, f'</{tag}> before the end of {self.where()}')
        elif stack:
            self.fail(pos, f'</{tag}> ends the parent of {self.where()} while <{stack[-1]}> is still open')
        elif tag in HTML_P_NO_PARENT_CLOSE:
            self.fail(pos, f'</{tag}> cannot close {self.where()} (HTML keeps the <p> open)')
        else:
            outer = self.outer
            self.close('closed_by_parent_end')
            if outer:  # </h1> ends both the <p> and the heading around it
                self.end(tag, pos)

    def close(self, how):
        text = norm(''.join(self.cur['buf']))
        for t in self.cur['stack']:  # HTML: closing a <p> ends the elements open inside it
            self.orphans[t] = self.orphans.get(t, 0) + 1
        if self.cur['tag'] == 'p':
            self.counts[how] += 1
            if text:
                self.paragraphs.append(text)
                self.sections.append(self.section)
            self.cur, self.outer = self.outer, None
            return
        if not self.cur.get('nosection'):
            self.section = text
        self.cur = None

    def read(self, html):
        self.parser.feed(html)
        self.parser.close()
        if self.skip:
            self.fail(self.skip[2], f'<{self.skip[0]}> is never closed')
        if self.cur:
            self.fail(self.cur['pos'], f'{self.where()} is never closed')
        c = self.counts
        if c['opened'] != (c['closed_by_end_tag'] + c['closed_by_next_block'] + c['closed_by_parent_end']
                           + c['empty_from_stray_end_tag']):
            raise HtmlParseError(f'<p> count mismatch: {c}')
        return self


class HtmlDocument(Document):
    """An HTML article page read by <p> element, for a source with no XML full text.

    A paragraph is the text of one <p> element with entities decoded and whitespace
    collapsed. The locator gives its document order and the nearest heading above it.
    Text outside <p> elements (page scripts, metadata) is not a paragraph and cannot be quoted.
    """

    def __init__(self, url, file, workdir):
        self.pmcid = Path(file).stem
        self.url, self.file = url, file
        data, self.retrieved = fetch(url, Path(workdir) / file)
        self.sha = sha256(data)
        reader = _Paragraphs().read(data.decode('utf-8'))
        self.paragraphs, self.sections, self.p_counts = reader.paragraphs, reader.sections, reader.counts
        self.root = None
        self.permissions = ''

    def locator(self, n):
        self.para(n)
        return HTML_LOCATOR.format(n, self.sections[n - 1])

    def licence(self):
        raise LicenceError('an HTML page has no permissions block: give skeleton() the licence statement as '
                           'licence_statement=(paragraph, exact text)')

    def src(self, n):
        return {'source': self.url, 'locator': self.locator(n), 'accessed_at': self.retrieved,
                'tool': f'reading of the HTML article page; paragraphs numbered by {CONVERTER["name"]} '
                        f'{CONVERTER["version"]} HtmlDocument: the non-empty <p> elements of the whole page in document order '
                        '(header, abstract and table cells included), '
                        'entities decoded and whitespace collapsed, text of script, style, template and noscript '
                        'skipped, headings h1-h4 as sections'}

    def src_table(self, table_id, label):
        raise ValueError('tables in an HTML page are not read: cite the paragraph that reports the value')

    def item(self, n):
        return {'artifact': self.file, 'sha256': self.sha, 'locator': self.locator(n)}


HTML_BLOCK_LOCATOR = ('HTML block {} (1-based order of the non-empty text runs between block boundaries; '
                      'section: {}; {})')
# A start or end tag of one of these ends a block (references/rules.md, "HTML blocks"). A closed
# list: an element not named here is inline, and its tags do not split a block.
HTML_BLOCK_BOUNDARIES = frozenset('address article aside blockquote body br caption dd details dialog div dl dt '
                                  'fieldset figcaption figure footer form h1 h2 h3 h4 h5 h6 head header hgroup hr '
                                  'html legend li main menu nav ol p pre search section summary table tbody td '
                                  'tfoot th thead title tr ul'.split())


class _Blocks:
    """Split a page into blocks: the text between two consecutive block boundaries.

    A boundary is a start or end tag of an element in HTML_BLOCK_BOUNDARIES (the void <br> and
    <hr> included). The text between two boundaries, with entities decoded and whitespace
    collapsed, is a block if it is not empty; inline tags inside it (a, em, span, ...) do not
    split it. Text inside script, style, template and noscript is skipped. The text of a heading
    h1-h4 is not a block: it is the section of the blocks after it. No tag nesting is needed to
    number blocks, so misnested or unclosed tags cannot move a number.

    Each block also records the elements open around it (tag, id, classes), read leniently: an end
    tag closes the innermost open element of its name and everything opened inside it, and an end
    tag with no open element of its name is ignored. This names the work and the framing
    (HtmlBlocksDocument), and does not affect the numbering.
    """

    def __init__(self):
        from html.parser import HTMLParser
        out = self

        class P(HTMLParser):
            def handle_starttag(self, tag, attrs):
                out.tag(tag, dict(attrs), start=True, void=tag in HTML_VOID)

            def handle_startendtag(self, tag, attrs):
                out.tag(tag, dict(attrs), start=True, void=True)

            def handle_endtag(self, tag):
                out.tag(tag, {}, start=False, void=False)

            def handle_data(self, data):
                if not out.skip:
                    out.buf.append(data)

        self.buf, self.skip, self.open, self.section, self.heading = [], None, [], '(none)', None
        self.blocks, self.sections, self.ancestors = [], [], []
        self.parser = P(convert_charrefs=True)

    def flush(self):
        text = norm(''.join(self.buf))
        self.buf = []
        if not text:
            return
        if self.heading:
            self.section = text
            return
        self.blocks.append(text)
        self.sections.append(self.section)
        self.ancestors.append(tuple(self.open))

    def tag(self, tag, attrs, start, void):
        if self.skip:
            if tag == self.skip[0]:
                self.skip[1] += 1 if start else -1
                if not self.skip[1]:
                    self.skip = None
            return
        if start and tag in HTML_SKIP and not void:
            self.skip = [tag, 1]
            return
        if tag in HTML_BLOCK_BOUNDARIES:
            self.flush()
            self.heading = start and tag in HTML_HEADINGS
        if void:
            return
        if start:
            self.open.append((tag, attrs.get('id') or '', tuple((attrs.get('class') or '').split())))
        else:
            for i in range(len(self.open) - 1, -1, -1):
                if self.open[i][0] == tag:
                    del self.open[i:]
                    break

    def read(self, html):
        self.parser.feed(html)
        self.parser.close()
        self.flush()
        return self


def html_selector(selector):
    """'tag', 'tag#id' or 'tag.class1.class2' as (tag, id, classes)."""
    m = re.fullmatch(r'([a-z][a-z0-9]*)(?:#([^.#\s]+))?((?:\.[^.#\s]+)*)', selector or '')
    if not m:
        raise ValueError(f'work selector {selector!r}: give tag, tag#id or tag.class (one element)')
    return m.group(1), m.group(2) or '', tuple(c for c in m.group(3).split('.') if c)


def _matches(element, selector):
    tag, ident, classes = selector
    return element[0] == tag and (not ident or element[1] == ident) and set(classes) <= set(element[2])


class HtmlBlocksDocument(HtmlDocument):
    """An HTML page read by block, for a page whose text is not all in <p> elements (a blog post
    written in <div>s, a reference list split by <br>).

    A paragraph is a block (_Blocks; references/rules.md, "HTML blocks"). Every block of the page
    is numbered, menus, sidebars and footers included; `work` names the one element that holds the
    work ('div.entry', 'article#post-1'), and each locator and report() say whether a block is
    inside it (work) or not (framing). HtmlDocument and its <p> locators are not changed by this
    reader: a page is read by one of the two, and the locator names which.
    """

    def __init__(self, url, file, workdir, work):
        self.pmcid = Path(file).stem
        self.url, self.file = url, file
        self.work = work
        selector = html_selector(work)
        data, self.retrieved = fetch(url, Path(workdir) / file)
        self.sha = sha256(data)
        reader = _Blocks().read(data.decode('utf-8'))
        self.paragraphs, self.sections = reader.blocks, reader.sections
        self.in_work = [any(_matches(e, selector) for e in a) for a in reader.ancestors]
        if not any(self.in_work):
            raise ValueError(f'{file}: no block inside the work element {work!r}')
        self.p_counts = None
        self.root = None
        self.permissions = ''

    def locator(self, n):
        self.para(n)
        return HTML_BLOCK_LOCATOR.format(n, self.sections[n - 1],
                                         f'work: inside {self.work}' if self.in_work[n - 1] else
                                         f'framing: outside {self.work}')

    def report(self):
        """The block numbers as runs of work and framing: [(first, last, 'work'|'framing'), ...]."""
        runs = []
        for n, inside in enumerate(self.in_work, 1):
            kind = 'work' if inside else 'framing'
            if runs and runs[-1][2] == kind:
                runs[-1][1] = n
            else:
                runs.append([n, n, kind])
        return [tuple(r) for r in runs]

    def src(self, n):
        return {'source': self.url, 'locator': self.locator(n), 'accessed_at': self.retrieved,
                'tool': f'reading of the HTML page by block; numbered by {CONVERTER["name"]} {CONVERTER["version"]} '
                        'HtmlBlocksDocument: the non-empty text runs between block boundaries of the whole page in '
                        'document order (references/rules.md, "HTML blocks"), entities decoded and whitespace '
                        'collapsed, text of script, style, template and noscript skipped, headings h1-h4 as '
                        f'sections; work = the element {self.work}'}


RECORD_LOCATOR = 'API record field {} {} (1-based order of the string fields of the record, keys in RFC 8785 order)'
# Members of an API record that are never read: the publisher's own assessment and model-made
# labels without attribution (see references/rules.md §1), and the response's volatile time.
RECORD_EXCLUDED = frozenset(('assessment', 'assessment_markdown', 'assessment_status', 'classification',
                             'summary_cards', 'generated_at'))
# Members that change between two requests for the same record. The record's hash is taken
# without them, so a new download of an unchanged record has the same hash.
RECORD_VOLATILE = ('generated_at',)
# Members about the record, not of its content: citable as the source of an added value (the
# licence), never an author-zone value.
RECORD_METADATA = frozenset(('license',))


def json_pointer(parts):
    """The RFC 6901 JSON Pointer of a path of keys and indices."""
    return ''.join('/' + str(p).replace('~', '~0').replace('/', '~1') for p in parts)


class RecordDocument(Document):
    """One record of a structured API, read field by field. A string field plays the part of a
    paragraph: field n is the n-th string leaf in RFC 8785 key order, and its locator names
    both n and its JSON Pointer. An author-zone value is a whole field, byte for byte. The
    members in RECORD_EXCLUDED are not fields and cannot be cited.

    The licence is the record's own `license` member, read by licence_of.

    The source is the record in RFC 8785 canonical form without the RECORD_VOLATILE members:
    the kit writes it next to the download as `<name>.canonical.json`, and its SHA-256 is the
    document hash. Anyone can reproduce it from a new download."""

    def __init__(self, url, file, workdir):
        self.pmcid = Path(file).stem
        self.url, self.file = url, file
        data, self.retrieved = fetch(url, Path(workdir) / file)
        self.record = json.loads(data)
        if not isinstance(self.record, dict):
            raise ValueError(f'{file}: an API record is a JSON object')
        canonical = self.canonical(data)
        self.artifact = f'{self.pmcid}.canonical.json'
        (Path(workdir) / self.artifact).write_bytes(canonical)
        self.sha = sha256(canonical)
        self.fields = []

        def leaves(o, parts):
            if isinstance(o, dict):
                for k in sorted(o, key=lambda k: k.encode('utf-16-be')):
                    if parts or k not in RECORD_EXCLUDED:
                        leaves(o[k], parts + [k])
            elif isinstance(o, list):
                for i, v in enumerate(o):
                    leaves(v, parts + [i])
            elif isinstance(o, str) and o.strip():
                self.fields.append((json_pointer(parts), o))
        leaves(self.record, [])
        self.paragraphs = [text for _, text in self.fields]
        self.pointers = {pointer: n for n, (pointer, _) in enumerate(self.fields, 1)}
        self.root = None
        lic = self.record.get('license')
        self.permissions = norm(f"{lic.get('name', '')} {lic.get('url', '')}") if isinstance(lic, dict) else ''

    def field(self, pointer):
        """The field number of a JSON Pointer."""
        if pointer not in self.pointers:
            raise ValueError(f'{self.pmcid}: no string field {pointer!r} (excluded members cannot be cited: '
                             f'{sorted(RECORD_EXCLUDED)})')
        return self.pointers[pointer]

    def _n(self, n):
        return self.field(n) if isinstance(n, str) else n

    def para(self, n):
        return super().para(self._n(n))

    def check(self, n, text):
        return super().check(self._n(n), text)

    def locator(self, n):
        n = self._n(n)
        self.para(n)
        return RECORD_LOCATOR.format(n, self.fields[n - 1][0])

    def author(self, n, text):
        """An author-zone value: the whole field, byte for byte."""
        n = self._n(n)
        if self.fields[n - 1][0].split('/')[1] in RECORD_METADATA:
            raise ValueError(f'{self.pmcid} {self.fields[n - 1][0]}: a metadata member is not an author value')
        if text != self.para(n):
            raise ValueError(f'{self.pmcid} {self.fields[n - 1][0]}: an author value is the whole field, byte for byte')
        return {'value': text, 'locator': self.locator(n)}

    def author_part(self, n, text, reason):
        raise ValueError('an API record field is quoted whole: use author()')

    def licence(self):
        """The licence the record's own `license` member grants (licence_of)."""
        return licence_of(self.permissions)

    def src(self, n):
        return {'source': self.url, 'locator': self.locator(n), 'accessed_at': self.retrieved,
                'tool': f'reading of the API record, field by JSON Pointer (ohf-extractor {CONVERTER["version"]} '
                        'RecordDocument)'}

    def src_table(self, table_id, label):
        raise ValueError('an API record has no tables: cite the field with src(pointer)')

    def item(self, n):
        return {'artifact': self.artifact, 'sha256': self.sha, 'locator': self.locator(n)}

    @staticmethod
    def canonical(data):
        """The hashed form of downloaded record bytes: RFC 8785, without RECORD_VOLATILE members."""
        import rfc8785
        record = json.loads(data)
        return rfc8785.dumps({k: v for k, v in record.items() if k not in RECORD_VOLATILE})


SUBMITTED_LOCATOR = 'Submitted text paragraph {} (1-based, paragraphs split on blank lines)'
# The rights basis of a submitted text: what the submitter states, recorded as their statement. It is
# not a licence the kit read in a published work.
SUBMITTED_BASIS = 'submitter_statement'
# The members of a submission manifest. Anything else is refused, so that a misspelt member is not
# silently lost and the card says "unknown" for it.
MANIFEST_REQUIRED = ('submitter', 'basis', 'card_licence', 'author_kind')
MANIFEST_OPTIONAL = ('author_name', 'system', 'system_version', 'model', 'model_basis', 'reasoning_effort',
                     'reasoning_effort_basis', 'prompt_file', 'run_id', 'generated_at', 'submitted_at', 'url', 'language', 'note')
AUTHOR_KINDS = ('human', 'ai_system', 'hybrid', 'unknown')
# What marks a paragraph of a submitted text as resting on another work: a link, a DOI, a PMID or PMCID,
# or an author-year citation. The submitter gives the card only their own text; such a paragraph quotes
# or retells the cited work, and its words are that work's, under that work's licence.
THIRD_PARTY_REFS = (
    ('link', re.compile(r'\[[^\]]*\]\((https?://[^)\s]+)\)')),
    ('url', re.compile(r'(?<![(\w])https?://[^\s)\]>]+')),
    ('doi', re.compile(r'\b10\.\d{4,9}/[^\s)\]>"]+')),
    ('pmid', re.compile(r'\bPMID:?\s*\d{4,9}\b', re.I)),
    ('pmcid', re.compile(r'\bPMC\d{4,9}\b')),
    ('author_year', re.compile(r'\b[A-Z][\w\'-]+(?: et al\.?| and [A-Z][\w\'-]+| и соавт\.?|,)[^.;\n]{0,80}?\b(?:19|20)\d{2}\b')),
)
# Words frequent enough in a language to tell it from a few sentences, for a text whose manifest does not
# name its language. A text that is not clearly one of these is "und" (undetermined, BCP 47).
LANGUAGE_WORDS = {'en': {'the', 'and', 'of', 'to', 'in', 'is', 'that', 'for', 'with', 'this'},
                  'ru': {'и', 'в', 'не', 'на', 'что', 'с', 'это', 'по', 'как', 'для'}}
# How the submitter knows the model. The model is named in author.generator.model however it is known,
# because the card is about the model, not the interface it ran in (that is author.generator.system); the
# basis, for example "declared in the CLI configuration, not seen in the output", is kept beside it in
# added.sources["generation"], so a reader can tell a declared model from one the output shows.
MODEL_OBSERVED = 'observed_in_output'
# Members that a manifest may give only with the basis on which the submitter knows them.
MANIFEST_BASES = (('model', 'model_basis'), ('reasoning_effort', 'reasoning_effort_basis'))


def language_of(text):
    """(BCP 47 tag, basis) of a text from its frequent words, for a manifest that names no language."""
    words = re.findall(r'\w+', text.lower())
    counts = {lang: sum(w in common for w in words) for lang, common in LANGUAGE_WORDS.items()}
    best = max(counts, key=counts.get)
    if counts[best] >= 5 and counts[best] >= 3 * max([c for lang, c in counts.items() if lang != best] or [0]):
        return best, f'frequent words ({counts[best]} of {len(words)})'
    return 'und', f'undetermined: frequent words {counts}'


# A "sentence" that is only a list marker ("1.", "2)", "-", "*") states nothing: it needs no ownership
# decision, and a value that touches it is judged by the sentences around it.
LIST_MARKER = re.compile(r'(?:\d{1,3}[.)]|[-*•])')


def sentences_of(para, closers=_CLOSERS):
    """The sentences of a paragraph, cut where sentence_ends cuts."""
    ends = sorted(sentence_ends(para, closers) | {len(para)})
    out, start = [], 0
    for e in ends:
        if para[start:e].strip():
            out.append(para[start:e].strip())
        start = e + 1
    return out


def decisions_in(card):
    """The sentence decisions recorded in a card (OWNERSHIP_KEY), or []."""
    rec = card.get('added', {}).get('sources', {}).get(OWNERSHIP_KEY)
    if not rec or OWNERSHIP_MARK not in rec.get('locator', ''):
        return []
    return json.loads(rec['locator'].split(OWNERSHIP_MARK, 1)[1])


def owned(doc, decisions, n, value):
    """Fail unless every sentence of paragraph n that `value` touches may enter the author zone on the
    submitter's statement: none judged third_party, and, in a paragraph marked third_party_candidate,
    each judged own with a reason and a time."""
    para = doc.para(n)
    i = para.find(value)
    if i == -1:
        raise ValueError(f'{doc.file} paragraph {n} does not contain: {value!r}')
    decided = {(d['paragraph'], d['sentence']): d for d in decisions}
    pos = 0
    for s in sentences_of(para, doc.closers):
        start = para.find(s, pos)
        pos = start + len(s)
        if start >= i + len(value) or pos <= i or LIST_MARKER.fullmatch(s):
            continue
        d = decided.get((n, s))
        if d and d['decision'] == 'third_party':
            raise LicenceError(f'{doc.file} paragraph {n}: {s!r} is judged third_party ({d["reason"]}): '
                               'the submitter\'s statement does not cover it; quote the cited work under its own '
                               'licence, or cite it by reference')
        if n in doc.third_party and not (d and d['decision'] == 'own' and norm(d.get('reason') or '')
                                         and d.get('assessed_at')):
            refs = ', '.join(f'{k} {v!r}' for k, v in doc.third_party[n])
            raise LicenceError(f'{doc.file} paragraph {n} is a third_party_candidate (it carries {refs}) and the '
                               f'sentence {s!r} is not judged own: decide it with doc.decide(n, sentence, '
                               '"own" | "third_party", reason) before quoting it')
    return value


class SubmittedText(Document):
    """A text submitted as it is: an answer of a model, a note or a text by a person, with no
    publication behind it. Paragraphs are split on blank lines; the exact bytes are the source and
    their SHA-256 is the document hash.

    What the kit knows about the text comes from the submission manifest beside it,
    `<file>.manifest.json`, written by the submitter: who submits, on what basis, under which terms
    the card is given, and, if they are known, the generator, model, prompt and times. What the
    manifest does not give is unknown in the card, never guessed. The rights are the submitter's
    statement (`SUBMITTED_BASIS`), recorded as such: no licence is read from the text or invented.

    `url` names the submission: the address the manifest gives, or `urn:sha256:<hash>` of the bytes."""
    closers = MARKDOWN_CLOSERS

    def __init__(self, url, file, workdir):
        workdir = Path(workdir)
        self.pmcid = Path(file).stem
        self.file = file
        path = workdir / file
        data = path.read_bytes()
        self.sha = sha256(data)
        # The time the kit first read the submission; kept, so a rebuild does not move it.
        stamp = path.with_suffix(path.suffix + '.received')
        if not stamp.exists():
            stamp.write_text(now())
        self.retrieved = stamp.read_text().strip()
        self.manifest_file = file + '.manifest.json'
        raw = (workdir / self.manifest_file).read_bytes()
        self.manifest_sha = sha256(raw)
        self.manifest = self.read_manifest(json.loads(raw))
        self.url = url or self.manifest.get('url') or 'urn:sha256:' + self.sha.split(':')[1]
        if self.manifest.get('url') and url and url != self.manifest['url']:
            raise ValueError(f'{file}: url {url!r} differs from the manifest url {self.manifest["url"]!r}')
        try:
            text = data.decode('utf-8')
        except UnicodeDecodeError as e:
            raise ValueError(f'{file}: a submitted text is UTF-8 ({e})') from None
        self.paragraphs = [norm(p) for p in re.split(r'\n[ \t]*\n', text.replace('\r\n', '\n')) if norm(p)]
        self.third_party, self.decisions = {}, []
        for n, para in enumerate(self.paragraphs, 1):
            refs = [(kind, m.group(0)) for kind, rx in THIRD_PARTY_REFS for m in rx.finditer(para)]
            if refs:
                self.third_party[n] = refs
        self.language, self.language_basis = ((self.manifest['language'], 'stated in the manifest')
                                              if self.manifest.get('language') else language_of(text))
        self.prompt_sha = None
        if self.manifest.get('prompt_file'):
            self.prompt_sha = sha256((workdir / self.manifest['prompt_file']).read_bytes())
        self.root = None
        self.permissions = ''

    @staticmethod
    def read_manifest(m):
        if not isinstance(m, dict):
            raise ValueError('a submission manifest is a JSON object')
        unknown = sorted(set(m) - set(MANIFEST_REQUIRED) - set(MANIFEST_OPTIONAL))
        if unknown:
            raise ValueError(f'submission manifest: unknown members {unknown}; '
                             f'allowed {sorted(MANIFEST_REQUIRED + MANIFEST_OPTIONAL)}')
        for k in MANIFEST_REQUIRED:
            if not (isinstance(m.get(k), str) and m[k].strip()):
                raise ValueError(f'submission manifest: {k} is required (a statement; "unknown" if it is not known)')
        if m['author_kind'] not in AUTHOR_KINDS:
            raise ValueError(f'submission manifest: author_kind is one of {AUTHOR_KINDS}')
        for k, basis in MANIFEST_BASES:
            if m.get(k) and not m.get(basis):
                raise ValueError(f'submission manifest: {k} needs {basis} ({MODEL_OBSERVED!r}, or how else it is '
                                 'known, for example "declared in the CLI configuration, not seen in the output")')
        return m

    def locator(self, n):
        self.para(n)
        return SUBMITTED_LOCATOR.format(n)

    def sentences(self, n):
        """The sentences of paragraph n, as sentence_ends cuts them."""
        return sentences_of(self.para(n), self.closers)

    def decide(self, n, sentence, decision, reason):
        """Record the converter's judgement on one sentence of paragraph n: `own` (the submitter's own
        words) or `third_party` (a quotation or retelling of another work), with the reason. A
        paragraph marked third_party_candidate is a hint to judge it, not a verdict; any paragraph may be
        judged, and a sentence judged third_party never enters the author zone on the submitter's
        statement. Returns the decision record, also kept for ownership()."""
        if decision not in DECISIONS:
            raise ValueError(f'decision is one of {DECISIONS}')
        if not norm(reason or ''):
            raise ValueError('a decision needs its reason')
        if sentence not in self.sentences(n):
            raise ValueError(f'{self.file} paragraph {n}: {sentence!r} is not one of its sentences')
        record = {'paragraph': n, 'sentence': sentence, 'decision': decision, 'reason': norm(reason),
                  'assessor': f"{CONVERTER['name']} {CONVERTER['version']}", 'model': model(), 'assessed_at': now()}
        self.decisions = [d for d in self.decisions if (d['paragraph'], d['sentence']) != (n, sentence)]
        self.decisions.append(record)
        return record

    def ownership(self):
        """The added.sources record of every sentence decision, for the card (OWNERSHIP_KEY)."""
        decisions = sorted(self.decisions, key=lambda d: (d['paragraph'], self.sentences(
            d['paragraph']).index(d['sentence'])))
        return {'source': self.url, 'locator': 'submitted text' + OWNERSHIP_MARK
                + json.dumps(decisions, ensure_ascii=False, sort_keys=True),
                'accessed_at': self.retrieved, 'tool': 'judgement of the converter, sentence by sentence'}

    def author(self, n, text):
        owned(self, self.decisions, n, text)
        return super().author(n, text)

    def author_part(self, n, text, reason):
        owned(self, self.decisions, n, text)
        return super().author_part(n, text, reason)

    def third_party_candidates(self):
        """For the report: each paragraph that carries a reference, with what it carries, and each of its
        sentences with the decision on it (None: not judged)."""
        decided = {(d['paragraph'], d['sentence']): d for d in self.decisions}
        return [{'paragraph': n, 'locator': self.locator(n), 'refs': [{'kind': k, 'text': v} for k, v in refs],
                 'sentences': [{'sentence': s, 'decision': (decided.get((n, s)) or {}).get('decision'),
                                'reason': (decided.get((n, s)) or {}).get('reason')} for s in self.sentences(n)]}
                for n, refs in sorted(self.third_party.items())]

    def licence(self):
        """The terms under which the submitter gives the card, as the manifest states them."""
        return self.manifest['card_licence'].strip()

    def rights(self):
        """The added.sources record of the submitter's statement: the manifest, by its hash."""
        statement = {k: self.manifest[k] for k in ('submitter', 'basis', 'card_licence')}
        return {'source': self.url, 'locator': f'submission manifest {self.manifest_file} ({self.manifest_sha})'
                + RIGHTS_MARK + json.dumps(statement, ensure_ascii=False, sort_keys=True),
                'accessed_at': self.retrieved, 'tool': 'the submitter\'s statement in the submission manifest'}

    def generation(self):
        """(author.generator, author.generation, added.sources record of what the manifest claims).
        A field the manifest does not give is None. The model is the generator's model however it is known;
        its basis, and a reasoning effort, which the generator has no member for, are kept in the record."""
        m = self.manifest
        generator = {'kind': m['author_kind'], 'system': m.get('system'), 'system_version': m.get('system_version'),
                     'model': m.get('model')}
        generation = {'run_id': m.get('run_id'), 'generated': None, 'submitted': None, 'submits_all': None}
        claims = {k: m[k] for k in MANIFEST_OPTIONAL if k in m and k not in ('url', 'note')}
        if self.prompt_sha:
            claims['prompt_sha256'] = self.prompt_sha
        claims['language'] = {'tag': self.language, 'basis': self.language_basis}
        record = {'source': self.url, 'locator': f'submission manifest {self.manifest_file} ({self.manifest_sha}); '
                  'as stated: ' + json.dumps(claims, ensure_ascii=False, sort_keys=True),
                  'accessed_at': self.retrieved, 'tool': 'the submitter\'s statement in the submission manifest'}
        return generator, generation, record

    def src(self, n):
        return {'source': self.url, 'locator': self.locator(n), 'accessed_at': self.retrieved,
                'tool': 'reading of the submitted text, paragraphs split on blank lines'}

    def src_table(self, table_id, label):
        raise ValueError('a submitted text has no tables: cite the paragraph with src(n)')

    def item(self, n):
        return {'artifact': self.file, 'sha256': self.sha, 'locator': self.locator(n)}


def assessment(doc, at):
    """Attribution for a converter judgement made at time `at` from document `doc`."""
    return {'assessor': f"{CONVERTER['name']} {CONVERTER['version']}", 'assessed_at': at,
            'evidence_ref': {'kind': 'artifact', 'sha256': doc.sha}}


def rules_hash():
    """SHA-256 over the rules and the code a card was converted and checked under: SKILL.md,
    **every file** under references/ at any depth, and scripts/*.py, each listed by its path
    relative to the kit. Nothing outside the kit is hashed, so the hash reproduces from a copy of
    the kit anywhere. A reference in a subdirectory is hashed too: a card may rest on a permission
    kept in references/permissions/, and a licence the card leans on must move the pin when it
    changes.

    Every file, not only the .md ones: a table the kit reads is as much a rule as the prose that
    describes it. While this hashed only *.md, a data file under references/ — the hallmark map is
    the first — could change what the kit decides without changing any card's converter_hash, and
    the only guard was a sha256 pinned by hand in the script that read it. A hash that does not move
    when the rules move is not an identifier of the rules.
    """
    files = ([SKILL / 'SKILL.md']
             + sorted(f for f in (SKILL / 'references').rglob('*') if f.is_file())
             + sorted((SKILL / 'scripts').glob('*.py')))
    listing = ''.join(f'{f.relative_to(SKILL).as_posix()} {sha256(f.read_bytes())}\n' for f in files)
    return sha256(listing.encode())


def para_number(locator):
    """The paragraph or page number a locator names, or None."""
    m = (re.search(r'\.//p\[(\d+)\]', locator)
         or re.match(r'(?:PDF page|HTML <p>|HTML block|API record field|Submitted text paragraph) (\d+) ', locator))
    return int(m.group(1)) if m else None


def rights_record(doc, n, text):
    """(licence, added.sources record) for the licence statement `text` in paragraph or page n
    of a PDF or HTML main source. The statement must be an exact passage of n, the whole of n
    must carry no NC, ND or SA marker, and the statement must grant an allowed licence."""
    doc.check(n, text)
    bad = _RESTRICTED.search(doc.para(n))
    if bad:
        raise LicenceError(f'{doc.pmcid} {n}: the passage around the licence statement has a restriction marker '
                           f'{bad.group(0)!r}')
    lic = licence_of(text)
    return lic, {**doc.src(n), 'locator': doc.locator(n) + RIGHTS_MARK + json.dumps(text, ensure_ascii=False)}


def reference_only(record, reason):
    """An added.sources record of another work that may not be quoted, with the reason in the
    card: its tool ends with REFERENCE_ONLY_MARK and the reason (for example the licence that
    forbids quoting, or the copyright check that could not be made). check_card.py fails on a
    quote or basis_quote whose src names such a record."""
    if not (isinstance(reason, str) and reason.strip()):
        raise ValueError('reference_only needs the reason the work is not quoted')
    if REFERENCE_ONLY_MARK in record['tool']:
        raise ValueError('the record is already marked reference only')
    return {**record, 'tool': record['tool'] + REFERENCE_ONLY_MARK + reason.strip()}


ROLES = ('author', 'translator')


def roman(n):
    """The year n in Roman numerals, as an imprint may print it (1871 -> MDCCCLXXI)."""
    out = ''
    for value, sym in ((1000, 'M'), (900, 'CM'), (500, 'D'), (400, 'CD'), (100, 'C'), (90, 'XC'),
                       (50, 'L'), (40, 'XL'), (10, 'X'), (9, 'IX'), (5, 'V'), (4, 'IV'), (1, 'I')):
        while n >= value:
            out, n = out + sym, n - value
    return out


def names_year(text, year):
    """Whether an imprint names the year, in digits or in Roman numerals (as a whole word)."""
    return str(year) in text or re.search(rf'(?<![A-Z]){roman(year)}(?![A-Z])', text) is not None


def _year(y):
    return isinstance(y, int) and not isinstance(y, bool)


def term_record(doc, public_domain):
    """(licence, added.sources record) for a PDF or HTML main source in the public domain because
    every term in COPYRIGHT_TERMS has ended. `public_domain` gives `published` (year), `imprint`
    (page or paragraph n, exact text of n that names that year in digits or Roman numerals, such
    as the title page), and either `author_died` (year) with `death_source` (where that year is
    recorded), or `deaths`: one entry per person whose work is in the text read, the author and,
    for a translation, the translator: {"person", "role" ("author" or "translator"), "died",
    "death_source"}. A term that runs from a death runs from the latest of them."""
    one, several = {'published', 'imprint', 'author_died', 'death_source'}, {'published', 'imprint', 'deaths'}
    if not isinstance(public_domain, dict) or set(public_domain) not in (one, several):
        raise LicenceError(f'public_domain needs exactly {sorted(one)} or {sorted(several)}')
    published = public_domain['published']
    if 'deaths' in public_domain:
        deaths = public_domain['deaths']
        if not (isinstance(deaths, list) and deaths and all(
                isinstance(d, dict) and set(d) == {'person', 'role', 'died', 'death_source'} for d in deaths)):
            raise LicenceError('public_domain: deaths must be a list of {"person", "role", "died", "death_source"}')
        if any(d['role'] not in ROLES or not (isinstance(d['person'], str) and d['person'].strip()) for d in deaths):
            raise LicenceError(f'public_domain: every death needs a person and a role in {ROLES}')
        if not any(d['role'] == 'author' for d in deaths):
            raise LicenceError('public_domain: deaths must include the author')
    else:
        deaths = [{'person': 'the author', 'role': 'author', 'died': public_domain['author_died'],
                   'death_source': public_domain['death_source']}]
    if not _year(published) or not all(_year(d['died']) and d['died'] >= published - 1 for d in deaths):
        raise LicenceError(f'public_domain: years {published!r}, {[d["died"] for d in deaths]!r} are not a '
                           'publication and a later death')
    n, text = public_domain['imprint']
    doc.check(n, text)
    if not names_year(text, published):
        raise LicenceError(f'{doc.pmcid} {n}: the imprint {text!r} does not name the year {published}')
    if not all(isinstance(d['death_source'], str) and d['death_source'].startswith('https://') for d in deaths):
        raise LicenceError('public_domain: death_source must be an https URL')
    bases = {'published': published, 'author_died': max(d['died'] for d in deaths)}
    year = int(now()[:4])
    ended = []
    for where, url, rule, base, years in COPYRIGHT_TERMS:
        end = bases[base] + years
        if year <= end:
            raise LicenceError(f'{where}: the term ({rule}) runs to the end of {end}; the work is not in the public domain')
        ended.append(f'{where}, {rule} ({url}): ended at the end of {end}')
    record = {'source': doc.url,
              'locator': doc.locator(n) + RIGHTS_MARK + json.dumps(text, ensure_ascii=False)
              + TERM_MARK + json.dumps(public_domain, ensure_ascii=False, sort_keys=True),
              'accessed_at': doc.retrieved,
              'tool': 'copyright terms checked by the converter kit: ' + '; '.join(ended)}
    return 'public-domain', record


def source_licence(card, doc):
    """The licence of the main source, derived again from its bytes: the permissions block of
    an XML, or the statement recorded in added.sources['rights'] for a PDF or HTML page."""
    if isinstance(doc, SubmittedText):
        rec = card['added']['sources'].get(RIGHTS_KEY)
        if rec != doc.rights():
            raise LicenceError(f'added.sources[{RIGHTS_KEY!r}] is not the statement of the submission manifest '
                               f'{doc.manifest_file} (rebuild: skeleton() records it)')
        if card['author']['source'].get('rights_basis') != SUBMITTED_BASIS:
            raise LicenceError(f'a submitted text has rights_basis {SUBMITTED_BASIS!r}: the submitter\'s statement, '
                               'not a licence of a published work')
        return doc.licence()
    if not isinstance(doc, (PdfDocument, HtmlDocument)):
        return doc.licence()
    rec = card['added']['sources'].get(RIGHTS_KEY)
    if rec is None or RIGHTS_MARK not in rec.get('locator', ''):
        raise LicenceError(f'no added.sources[{RIGHTS_KEY!r}] with the licence statement of the {type(doc).__name__} '
                           'main source (give skeleton() licence_statement=(n, text))')
    if rec['source'] != doc.url:
        raise LicenceError(f'added.sources[{RIGHTS_KEY!r}] is for {rec["source"]}, not the main source {doc.url}')
    where, statement = rec['locator'].split(RIGHTS_MARK, 1)
    n = para_number(where)
    if n is None:
        raise LicenceError(f'added.sources[{RIGHTS_KEY!r}]: no page or paragraph in locator {where!r}')
    if TERM_MARK in statement:
        terms = json.loads(statement.split(TERM_MARK, 1)[1])
        terms['imprint'] = tuple(terms['imprint'])
        return term_record(doc, terms)[0]
    return rights_record(doc, n, json.loads(statement))[0]


def observed_budget(counter):
    """Read complete conversion totals from the caller's counter, without defaults.

    The callback returns model_calls, http_requests, coverage='complete' and a
    nonempty scope naming the observed run. The caller retains the measurement
    and must include every operation attributed to that run. A partial log or a
    runtime event count cannot establish either total. This validates the supplied
    measurement shape; it does not independently certify its provenance.
    """
    if not callable(counter):
        raise ValueError('BUDGET_COUNTER_REQUIRED: complete model/HTTP totals were not observed')
    snapshot = counter()
    keys = {'model_calls', 'http_requests', 'coverage', 'scope'}
    if (type(snapshot) is not dict or snapshot.keys() != keys
            or snapshot['coverage'] != 'complete'
            or type(snapshot['scope']) is not str or not snapshot['scope'].strip()):
        raise ValueError('BUDGET_COUNTER_INCOMPLETE: complete totals and their scope are required')
    counts = {}
    for name in ('model_calls', 'http_requests'):
        value = snapshot[name]
        if type(value) is not int or value < 0:
            raise ValueError('BUDGET_COUNTER_INVALID: ' + name + ' must be an observed nonnegative integer')
        counts[name] = value
    return counts


def skeleton(*, ident, doc, citation, doi=None, topic, sources, author_names, licence=None, licence_statement=None,
             public_domain=None, url=None, kind='paper', submitted_at=None, citation_title=None,
             budget_counter=None):
    """The fixed parts of a card. Layers start empty; the builder fills them.

    The licence is derived from the main source, not taken on trust: from the permissions
    block of an XML, or, for a PDF or HTML page, from `licence_statement=(n, exact text)`,
    or from `public_domain` (term_record) for an old work with no licence statement; either
    becomes added.sources['rights']. A `licence` argument that disagrees with the derived
    licence is an error; LicenceError stops the conversion. A work with no DOI gives `url`,
    the address of the copy read.

    citation_title is an explicit builder argument read from the article itself (for JATS, its own
    article-title), never from Crossref or Europe PMC metadata. Supply it separately from citation
    and before registry verification, as one nonempty string rather than a list of fields. Missing
    titles remain missing. finish removes this build-only field from the card; verify_source returns
    both raw titles in its separate run record so the check can be repeated after export.

    budget_counter supplies complete observed model/HTTP totals via observed_budget.
    Missing or partial counters refuse construction; no number is inferred or defaulted.
    Token accounting is supplied separately and is unchanged by this counter contract."""
    budget_counts = observed_budget(budget_counter)
    if citation_title is not None and title_value(citation_title) is None:
        raise ValueError('citation_title must be one nonempty title string, not joined fields')
    sources = dict(sources)
    submitted = isinstance(doc, SubmittedText)
    if submitted:
        url = url or doc.url
    if doi is None and url is None:
        raise ValueError('give the DOI, or for a work without one the url of the copy read')
    if submitted:
        if licence_statement is not None or public_domain is not None:
            raise LicenceError('a submitted text: the submitter\'s statement in its manifest decides; do not pass '
                               'licence_statement or public_domain')
        derived = doc.licence()
        generator, generation, claims = doc.generation()
        for key, record in ((RIGHTS_KEY, doc.rights()), (GENERATION_KEY, claims)):
            if key in sources and sources[key] != record:
                raise ValueError(f'sources[{key!r}] is reserved for the submission manifest')
            sources[key] = record
    elif isinstance(doc, (PdfDocument, HtmlDocument)):
        if (licence_statement is None) == (public_domain is None):
            raise LicenceError(f'{type(doc).__name__} main source: give licence_statement=(n, exact text) '
                               'or public_domain, not both')
        if public_domain is not None:
            derived, record = term_record(doc, public_domain)
        else:
            derived, record = rights_record(doc, *licence_statement)
        if RIGHTS_KEY in sources and sources[RIGHTS_KEY] != record:
            raise ValueError(f'sources[{RIGHTS_KEY!r}] is reserved for the licence statement')
        sources[RIGHTS_KEY] = record
    else:
        if licence_statement is not None or public_domain is not None:
            raise LicenceError('an XML main source: its permissions block decides; do not pass licence_statement '
                               'or public_domain')
        derived = doc.licence()
    if licence is not None and licence != derived:
        raise LicenceError(f'licence argument {licence!r} disagrees with {derived!r} derived from the source')
    licence = derived
    vocab = vocabularies_of(standard_line())
    layer = lambda: {'core': {}, 'mechanism': {}, 'predictions': [], 'evidence': {},  # noqa: E731
                     'provenance': {}, 'profile': {}, 'appendix': {}}
    return {
        'schema': 'ohf:hypothesis@1', 'id': ident, 'version': 1,
        # The release line of the checkout the card is built and checked against, not a constant. It
        # was '1.0' here while the standard went to 1.1, so the kit could only ever emit a 1.0 card
        # whatever checkout it was given - and a conversion that wanted the newer fields had no way to
        # say so. The checkout is the one source of truth: the same OHF_REPO validates the card, and a
        # card whose declared version disagrees with it is refused elsewhere in the kit. Patch
        # releases are not card versions: a checkout of 1.1.3 or 1.1.4 both emit `1.1`.
        'standard_version': standard_line(),
        'vocabularies': vocab,
        'identity': {'proposition_id': ident, 'version': 1, 'supersedes': [], 'retractions': [],
                     'duplicate_cluster_ref': None, 'representative_ref': None, 'lifecycle': 'example'},
        'author': {
            'source': {'kind': 'submitted_text' if submitted else kind, 'citation': citation,
                       **({'doi': doi} if doi else {}), 'url': url or f'https://doi.org/{doi}',
                       'license': licence, 'rights_basis': SUBMITTED_BASIS if submitted else 'license',
                       'retrieved_at': doc.retrieved, 'source_text_sha256': doc.sha,
                       'language': doc.language if submitted else 'en'},
            'generator': generator if submitted else {'kind': 'human', 'system': None, 'system_version': None,
                                                      'model': None},
            'generation': generation if submitted else {'run_id': None, 'generated': None, 'submitted': None,
                                                        'submits_all': None},
            'submitted_at': submitted_at or (doc.manifest.get('submitted_at') if submitted else None) or doc.retrieved,
            'layers': layer()},
        'added': {
            'by': {'converter': CONVERTER['name'], 'converter_version': CONVERTER['version'],
                   'converter_hash': rules_hash(), 'model': model()},
            'at': None, 'cutoff_date': None, 'layers': layer(), 'gaps': [],
            'completeness': {'level': 'accepted', 'layers_present': [], 'missing_for_next': []},
            'sources': sources,
            'budget': {**budget_counts, 'input_tokens': None, 'output_tokens': None},
            'produced_by': {'kind': 'example_converter', 'pipeline': dict(CONVERTER)},
            'source_verification': None,
            'integrity': {'entailment': []}},
        'facets': {'topic': topic, 'source_class': 'submitted' if submitted else 'external_published'},
        '_author_names': author_names,
        **({'citation_title': citation_title} if citation_title is not None else {}),
    }


def latest_time(card):
    """The latest assessed_at in the added zone."""
    times = []

    def walk(o):
        if isinstance(o, dict):
            if isinstance(o.get('assessed_at'), str):
                times.append(o['assessed_at'])
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(card['added']['layers'])
    return max(times) if times else None


# Catalogue records a work without a DOI can be looked up in: registry name, record URL template
# and the title in the parsed JSON record.
CATALOGUES = {
    'archive.org': ('Internet Archive item metadata', 'https://archive.org/metadata/{}',
                    lambda msg: msg.get('metadata', {}).get('title', '')),
    'eternalsearch': ('Eternal Search API record', 'https://eternalsearch.net/api/v1/content/hypotheses/{}',
                      lambda msg: msg.get('title', '')),
}


def verify_source(card, doc, catalogue=None):
    """Download the source again, compare its hash, and look the work up: the DOI in Crossref,
    or, for a work without a DOI, its record in a catalogue, `catalogue=(name, item id)` with
    the name a key of CATALOGUES. A catalogue records no retractions: `retracted` is "unknown".

    Save the returned run record separately from the OHF card. It retains citation_title and the
    registry_title as compared, the verdict and reason, the source hash and the converter rules hash.
    Repeating title_match(record['registry_title'], record['citation_title']) needs no registry call
    and no reconstruction from citation text. The registry response never supplies citation_title."""
    fetched_at = now()
    with urllib.request.urlopen(urllib.request.Request(doc.url, headers={'User-Agent': user_agent()})) as r:
        data = r.read()
    # A record is hashed in canonical form, so a response time that changed does not count.
    again = sha256(RecordDocument.canonical(data) if isinstance(doc, RecordDocument) else data)
    same = again == doc.sha
    doi = card['author']['source'].get('doi')
    ours = card.get('citation_title')
    if doi:
        if catalogue is not None:
            raise ValueError('a work with a DOI is looked up in Crossref; do not pass catalogue')
        record = f'https://api.crossref.org/works/{doi}'
        checked_at = now()
        with urllib.request.urlopen(urllib.request.Request(record, headers={'User-Agent': user_agent()})) as r:
            msg = json.load(r)['message']
        # The registry's title is compared **as it arrived**. `norm` collapsed its whitespace here,
        # before the comparison could see it - so the line breaks of a pretty-printed title were gone
        # by then, the markup rule never fired on a real record, and production records still came
        # back `title_match: false` while a direct call to the comparison passed. Normalisation
        # belongs inside the comparison and nowhere else.
        titles = msg.get('title')
        title = titles[0] if isinstance(titles, list) and len(titles) == 1 else None
        retracted = any(u.get('type') in ('retraction', 'withdrawal') for u in msg.get('update-to', []) + msg.get('updated-by', []))
        matched, why = title_match(title, ours)
        check = {'registry': 'Crossref REST API', 'record_url': record, 'checked_at': checked_at,
                 'doi_match': msg.get('DOI', '').lower() == doi.lower(),
                 'title_match': matched, 'retracted': retracted}
    else:
        if catalogue is None or catalogue[0] not in CATALOGUES:
            raise ValueError(f'a work without a DOI: give catalogue=(name, item id), name one of {sorted(CATALOGUES)}')
        registry, template, title_of = CATALOGUES[catalogue[0]]
        record = template.format(urllib.parse.quote(catalogue[1], safe=''))
        checked_at = now()
        with urllib.request.urlopen(urllib.request.Request(record, headers={'User-Agent': user_agent()})) as r:
            msg = json.load(r)
        title = title_of(msg)
        matched, why = title_match(title, ours)
        check = {'registry': registry, 'record_url': record, 'checked_at': checked_at,
                 'title_match': matched, 'retracted': 'unknown'}
    card['added']['source_verification'] = {
        'status': 'refetched_match' if same else 'refetched_mismatch',
        'fetched_from': doc.url, 'fetched_at': fetched_at, 'sha256': again, 'metadata_check': check}
    # Why a title differs cannot go in the card: `metadata_check` is closed at 1.1.4 and 1.2.0
    # (registry, record_url, checked_at, doi_match, title_match, retracted). So the reason is
    # returned with the comparison's raw inputs in the separate run record. The card carries the
    # verdict alone; finish can remove its temporary title without losing the replay inputs.
    return {'metadata_check': dict(check), 'title_difference': why,
            'citation_title': ours, 'registry_title': title,
            'source_text_sha256': doc.sha, 'converter_hash': rules_hash()}


def id_lists(card, path=''):
    """Every list of objects with an `id`, as {json pointer: [ids]}."""
    out = {}

    def walk(node, p):
        if isinstance(node, dict):
            for k, v in node.items():
                walk(v, f'{p}/{k}')
        elif isinstance(node, list):
            ids = [x.get('id') for x in node if isinstance(x, dict) and isinstance(x.get('id'), str)]
            if len(ids) == len(node) and ids:
                out[p] = ids
            for i, v in enumerate(node):
                walk(v, f'{p}/{i}')

    walk(card, path)
    return out


def inserted_mid_list(old_card, card):
    """Lists where a new element was put before an old one, with the ids that moved.

    A ledger is keyed by JSON pointer, so inserting an element renumbers every later element and
    invalidates its records: the same text has to be checked again under a new pointer. Appending
    costs nothing. Measured on the second flagship: inserting four evidence lines mid-list turned 59
    needed re-checks into 171, and the same mistake repeated twice more in one night, each time
    because grouping a new line beside its kin reads better.
    """
    was, now_ = id_lists(old_card), id_lists(card)
    moved = []
    for pointer, before in was.items():
        after = now_.get(pointer)
        if not after or before == after:
            continue
        kept = [i for i in after if i in before]
        if kept != before:          # an old element was removed or reordered: not this check
            continue
        new_ids = [i for i in after if i not in before]
        first_new = min(after.index(i) for i in new_ids) if new_ids else len(after)
        renumbered = [i for i in before if after.index(i) > first_new]
        if renumbered:
            moved.append((pointer, new_ids, renumbered))
    return moved


def warn_insertions(card, out):
    """Print a loud warning when this build inserts a value into the middle of a list.

    Called by finish() when a card already exists at `out`. It warns and does not refuse: a
    renumbering is sometimes the right thing, and the converter is the one who decides. What it may
    not be is silent, because the cost lands later, on the entailment ledger.
    """
    path = Path(out)
    if not path.exists():
        return []
    try:
        old_card = json.loads(path.read_text())
    except (OSError, ValueError):
        return []
    moved = inserted_mid_list(old_card, card)
    for pointer, new_ids, renumbered in moved:
        print(f'WARNING {pointer}: {", ".join(new_ids)} inserted before {", ".join(renumbered)}. '
              f'Every later pointer is renumbered, so the ledger records of {len(renumbered)} '
              f'element(s) no longer name their own text and have to be checked again. Append '
              f'instead, unless the order itself is the point.', file=sys.stderr)
    return moved


def finish(card, out):
    """Stamp added.at, fill layers_present, hash, and write the card."""
    card.pop('_author_names', None)
    card.pop('citation_title', None)
    warn_insertions(card, out)
    present = [n for n in ('core', 'mechanism', 'predictions', 'evidence', 'provenance', 'profile', 'appendix')
               if card['author']['layers'][n] or card['added']['layers'][n]]
    card['added']['completeness']['layers_present'] = present
    card['added']['at'] = max(filter(None, [latest_time(card), card['added']['at'], now()]))
    card['content_hash'] = content_hash(card)
    Path(out).write_text(json.dumps(card, ensure_ascii=False, indent=2) + '\n')
    return card


def rehash(card, out):
    card['content_hash'] = content_hash(card)
    Path(out).write_text(json.dumps(card, ensure_ascii=False, indent=2) + '\n')


def run_checks(path):
    """Run the repository checkers on one card; return (ok, output)."""
    path = Path(path).resolve()  # the checkers run in REPO, so a relative path would point there
    py = str(REPO / '.venv/bin/python') if (REPO / '.venv/bin/python').exists() else sys.executable
    out, ok = [], True
    for tool in ('validate.py', 'check_gaps.py', 'check_refs.py'):
        r = subprocess.run([py, str(REPO / 'tools' / tool), str(path)], capture_output=True, text=True, cwd=REPO)
        out.append(f'{tool}: rc={r.returncode} {r.stdout.strip()[-1500:]} {r.stderr.strip()[-800:]}')
        ok &= r.returncode == 0
    return ok, '\n'.join(out)
