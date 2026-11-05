#!/usr/bin/env python3
"""Read-only literature search for a conversion: find the works that answer an article, and its status.

The extractor reads an article and cites works it has been given; it does not find them. This module
finds them, through key-free open APIs (Europe PMC, NCBI E-utilities, Crossref), and records every
search, so that "nothing was found against it" is a claim with its searches behind it.

Each call returns a record: what was asked, of which service, when, the exact URLs, the SHA-256 of
every response, how many hits the service reported and the works found, each with its identifiers
(PMID, PMCID, DOI) and the licence the source itself states, or none. A search log (JSON lines) keeps
the records in the work directory, and the raw responses are kept beside it by hash.

The records hold identifiers, titles, types and dates. They hold no abstract or other article text:
access through an API is not a licence to republish it.

Usage:
  search.py literature QUERY [--limit N] [--sources europepmc,pubmed] [--sort default|cited]
                                   (each query is sent twice: as given, and without reviews)
                                   [--fallback-query QUERY ...] [--min-works N] [--max-works N]
                                   (opt-in candidate-count fallback; service hits are not relevance)
  search.py cited-by ID            (PMID, PMCID or DOI)
  search.py responses ID           (comments, replies and notices attached to the work)
  search.py status ID              (retracted, corrected, expression of concern)
  search.py similar ID [--limit N] (PubMed's related articles, cited or not, by its ranking)
  search.py terms ID               (the article's MeSH headings and keywords, to widen a query)
  search.py trial NCT              (a ClinicalTrials.gov study: status, phases, dates, primary outcomes)
  search.py text ID                (where the full text can be read openly, with each place's licence)
  search.py not-read ID [--atom KEY]  (a work found and not readable: every place tried, with what it
                                    answered; exit 1 if any place answers, because then it is readable)
  search.py trials QUERY [--limit N] (ClinicalTrials.gov studies matching the query)
  search.py check-refs FILE        (each reference inside a submitted text: does the work exist, does
                                    the reference match it; relevance is left to a reader)
  search.py not-cited ID --reason R --locator WHERE [--atom KEY]
                                   (a work read and not cited, with the reason from a closed list)
  search.py relevance-input TEXT OUT.json     (the verified references of a checked text, for a separate
                                               checker to judge what each work says; references/relevance.md)
  search.py relevance-merge TEXT IN.json VERDICTS.json --extractor NAME   (log the checker's verdicts)
  search.py similar-cards TEXT --cards DIR [--limit N]  (accepted cards that may state the same
                                               hypothesis, with why: candidates, not a filter)
  search.py known-input TEXT OUT.json --cards DIR [--cards DIR ...] [--exclude ID@VERSION]
                                   (after the literature searches for TEXT: the works they found and the cards
                                    that may state it, for a separate checker; references/known-result.md)
  search.py known-search QUERIES.json [--limit 20]
                                   (each query of the query writer as given, narrowed to trials and to null
                                    results, in Europe PMC and PubMed, run before known-input)
  search.py known-check IN.json VERDICTS.json
                                   (the reader's passages known-merge would not verify, to rewrite once
                                    before handing in; exit 1 when any is listed)
  search.py known-merge TEXT IN.json VERDICTS.json --query-writer NAME [--second VERDICTS2.json]
                                   (the checker's verdicts logged, and the result known_result, duplicate,
                                    tested_unresolved, new or incomplete, with its evidence, in VERDICTS-result.json)
  search.py notice-read ID --notice NOTICE --status-call CALL --notice-sha256 HASH --locator WHERE --reader NAME
                                   (a separate reading attestation for the identified partial notice)
  search.py report                 (the search section of the conversion report)
  search.py attribute CARD         (which logged call found each work the card cites)
  search.py screen CARD            (works a call returned that no record says anyone looked at)
  search.py licence ID             (the licence from the work's own permissions element, as a record)
  search.py locate ID --find WORDS [--limit N] (passage addresses without retaining the JATS body;
                                               default 5 addresses, positive integer limit)
  search.py purge [--remove]       (retained bodies a measured licence forbids keeping)
  search.py close-step             (fix the written log, counts and publication types; no verdicts)
with --workdir DIR (default: the current directory) for the log and the responses, and --as-of
YYYY-MM-DD for only what was known on that day.
"""
import argparse
import contextlib
import calendar
import datetime
import fcntl
import difflib
import gzip
import hashlib
import json
import math
import os
import re
import stat
import sys
import threading
import time
import unicodedata
import urllib.error
import xml.etree.ElementTree as ET
import uuid
import urllib.parse
import urllib.request
import zlib
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]
VERSION = re.search(r'^version: (\S+)$', (SKILL / 'SKILL.md').read_text(), re.M).group(1)
# As in ohfkit: the kit has no contact address; a caller may give one, which Crossref and NCBI ask for.
CONTACT = os.environ.get('OHF_CONTACT') or None

EPMC = 'https://www.ebi.ac.uk/europepmc/webservices/rest/'
EUTILS = 'https://eutils.ncbi.nlm.nih.gov/entrez/eutils/'
CROSSREF = 'https://api.crossref.org/works/'
CTGOV = 'https://clinicaltrials.gov/api/v2/'
OPENALEX = 'https://api.openalex.org/'
BIORXIV = 'https://api.biorxiv.org/details/'
ARXIV_OAI = 'https://oaipmh.arxiv.org/oai'
UNPAYWALL = 'https://api.unpaywall.org/v2/'
BIOC = 'https://www.ncbi.nlm.nih.gov/research/bionlp/RESTful/pmcoa.cgi/BioC_json/{}/unicode'
# The two routes a licence may be measured by, and the only strings `measured_from` carries. Both are
# the article's own record: the JATS permissions element of the article itself, and the `license` infon
# of the same article's front passage in PMC BioC, which the owner's rule of 2026-10-24 accepts as the
# record of the article with the same checks applied to it. The constants exist because the routes are
# now compared with each other, and a comparison between two spellings of one route is not a comparison.
JATS_ROUTE = 'article permissions (measured)'
BIOC_ROUTE = 'PMC BioC front passage, license infon (measured)'
# DOI prefixes of bioRxiv and medRxiv (10.64898 since 2025).
PREPRINT_PREFIXES = ('10.1101/', '10.64898/')
ARXIV_DOI = re.compile(r'^(?:10\.48550/arxiv\.|arxiv:)(.+)$', re.I)
# OpenAlex without a key: one free daily budget per network address (a list page costs $0.0001 of
# $0.10), and plain page paging only; the kit asks 200 works a page.
OPENALEX_PAGE = 200
OPENALEX_FIELDS = 'id,doi,ids,title,publication_year,publication_date,type,primary_location'
# The order a literature search asks for, as each service names it. With none, both services return
# the most recent works first (checked 2026-10-21); "cited" asks for the established works: Europe PMC
# by citations, PubMed, which has no such order, by its Best Match.
SORTS = {'default': {'europepmc': None, 'pubmed': None},
         'cited': {'europepmc': 'CITED desc', 'pubmed': 'relevance'}}
# Each literature query is also sent with reviews excluded: reviews push the primary works off the first
# page, and a primary work against the claim is what a search must not miss. Both answers are logged.
VARIANTS = {'as_given': {'europepmc': '{}', 'pubmed': '{}'},
            'no_reviews': {'europepmc': '({}) NOT PUB_TYPE:review', 'pubmed': '({}) NOT review[pt]'}}
NO_REVIEWS = {'europepmc': 'NOT PUB_TYPE:review', 'pubmed': 'NOT review[pt]'}
# Opt-in fallback caps: one primary + at most two caller-supplied broader queries.
# Each uses the existing two variants per service; their per-call and selected
# result caps are separate. These are retrieval bounds, not relevance thresholds.
FALLBACK_QUERIES = 3
FALLBACK_PER_CALL = 20
FALLBACK_WORKS = 60
# The known-result search runs each query four ways, so that a test is found whichever way it came out:
# as given, narrowed to trials and experiments, narrowed to null results, and restricted to trials by
# publication type, most cited first. Held-out run 3: the landmark trials were in no service's first page
# by the default order (PubMed's is the most recent first), and came back at ranks 0-6 restricted by
# type and sorted by citations. Each probe gives its query per service and the order (a key of SORTS).
PROBES = {
    'as_given': {'europepmc': '{}', 'pubmed': '{}', 'sort': 'default'},
    'trial': {'europepmc': '({}) AND (randomized OR randomised OR trial OR "controlled study" OR experiment)',
              'pubmed': '({}) AND (randomized OR randomised OR trial OR "controlled study" OR experiment)',
              'sort': 'default'},
    'null': {'europepmc': '({}) AND ("no effect" OR "no significant" OR "did not" OR "no difference" OR "failed to" OR null)',
             'pubmed': '({}) AND ("no effect" OR "no significant" OR "did not" OR "no difference" OR "failed to" OR null)',
             'sort': 'default'},
    'rct': {'europepmc': '({}) AND (PUB_TYPE:"randomized controlled trial" OR PUB_TYPE:"clinical trial")',
            'pubmed': '({}) AND (randomized controlled trial[pt] OR clinical trial[pt])', 'sort': 'cited'}}
# known-input takes the works of the publication-type trial probe first, to this depth, before the
# others in turn: a decisive trial the probe found is not cut by the limit on works.
RCT_FIRST = 5
# Publication types (Europe PMC pubTypeList, lower case, '-' read as ' ') of a work that reports no test
# of its own: it can be context for a claim, never evidence that the claim was tested.
SECONDARY = {'review', 'review article', 'systematic review', 'meta analysis', 'network meta analysis',
             'scoping review', 'evidence synthesis', 'editorial', 'comment', 'article commentary', 'letter',
             'practice guideline', 'guideline', 'consensus statement', 'product review', 'clinical trial protocol',
             'study guide', 'news'}
# Why a work that was read is not cited, from a closed list: a search that read a work against the claim
# and dropped it must leave the reason in the log, where the critic sees it.
NOT_CITED = {'other_species': 'about another organism than the atom',
             'other_endpoint': 'measures another outcome than the atom',
             'other_intervention': 'tests another intervention or compound',
             'subgroup_only': 'the result holds only in a subgroup',
             'background_or_review': 'background or review, no result of its own',
             # A work can bear on the atom exactly and still not be citable here: a line of a card
             # quotes its passage, and a work whose own bytes state no licence this kit may republish
             # under cannot supply one. Without this reason such a work has to be logged under a false
             # one or left out of the log, and the second is worse: the works that bear on a claim most
             # directly are the ones a reader of the card most needs to know were read. Found on the
             # imprinting conversion, where the formal published Comment on the converted article, the
             # authors' reply to it, and the one work that ran the card's own cheapest test all state
             # "CC BY" with no version in their bytes.
             'licence_refuses_quotation': 'read, and its own bytes state no licence under which this '
                                          'kit may quote it',
             # A retracted work the search returned and the card does not use still needs a record
             # with its reason, not silence. Found on the amoebae conversion: a retracted publication
             # came back from seven literature calls and nothing in the log mentioned it. The card
             # does not rest on it, which is why the reason is `retracted` and not a notice request -
             # the work was returned, read far enough to see the retraction, and not used.
             # Only a RETRACTED work, never a corrected one: a correction changes a result and the
             # work is read with it, so "not read as a result" would be false of it. `not_cited`
             # refuses this reason for a work whose types say corrected or concern.
             'retracted': 'retracted by the publisher, so not read as a result',
             'off_topic': 'not about the atom'}
# Whether a work a submitted text cites says what the text attaches it to: decided by a separate
# checker, never by the converter that extracted the card, and never by this code (references/relevance.md).
# A field tag names a syntax, not a service: `[tiab]` is PubMed's and `ABSTRACT:` is Europe PMC's.
# Asked in the other service's syntax, each answers HTTP 200 with no results and no error, so a question
# that was never understood comes back looking like a question answered "nothing is published". That is
# the one zero a conversion must never read as absence - a card says "a dispute was searched for and not
# found" on the strength of it - so a query is refused by its fields before it is sent, whichever
# service was going to receive it, and the refusal is logged as a call with outcome `malformed_query`.
PUBMED_TAGS = frozenset("""ad ab ai all au aid crdt dp ds ec edat filter grant ir isbn jid jour la lid
majr mesh mh nm pa pmid pt rn sb si so subh subs ti tiab tw vi""".split())
EPMC_FIELDS = frozenset("""ABSTRACT ACK_FUND AFF AUTH AUTHORID CHEM CITED CONCEPT DISCUSS DOI FIRST_AUTH
FIRST_IDATE FIRST_PDATE HAS_FT INTRO ISSN JOURNAL KW LANG LICENSE MESH METHODS OPEN_ACCESS PMCID PMID
PUB_TYPE PUB_YEAR RESULTS REVIEW SRC SUPPL TITLE TITLE_ABS""".split())
FIELD_TAG = re.compile(r'\[([A-Za-z/ ]{2,24})\]')
FIELD_PREFIX = re.compile(r'\b([A-Z_]{2,24}):')
SYNTAX_FIELDS = {'pubmed': PUBMED_TAGS, 'europepmc': EPMC_FIELDS}


def query_fields(query):
    """The field tags in query, by the syntax each belongs to: {'pubmed': {...}, 'europepmc': {...}}."""
    return {'pubmed': {t.strip().lower() for t in FIELD_TAG.findall(query)
                       if t.strip().lower() in PUBMED_TAGS},
            'europepmc': {f for f in FIELD_PREFIX.findall(query) if f in EPMC_FIELDS}}


def refuse_foreign_syntax(query, source):
    """Raise MalformedQuery when query carries field tags of a syntax `source` does not implement.

    The test is on the fields, not on the service: a tag is foreign when it belongs to a vocabulary
    other than the one the service being asked implements, and a query carrying no field tag at all is
    free text, which both services read."""
    found = query_fields(query)
    foreign = sorted(f for syntax, fields in found.items() if syntax != source for f in fields)
    if foreign:
        other = next(syntax for syntax in found if syntax != source and found[syntax])
        raise MalformedQuery(
            f'{source} does not implement the {other} field syntax: {", ".join(foreign)}. '
            f'The service would answer with no results and no error, and a zero from a query the '
            f'service never understood is not evidence that nothing is published. Rewrite the query '
            f'in {source} syntax, or send it to {other}.')


RELEVANCE = {'supports_claim': 'the work states what the paragraph attaches it to',
             'related_not_claim': 'the work is on the topic but does not state that',
             'unrelated': 'the work is not about it',
             'not_retrievable': 'the checker could not read the work: no abstract or open text'}
RELEVANCE_PROMPT = SKILL / 'references' / 'relevance.md'
# Seconds between two requests to one host. NCBI allows 3 requests/s without a key; Europe PMC and
# Crossref ask for moderate use and give no number, so the kit keeps two a second. ClinicalTrials.gov
# allows about 50 a minute.
MIN_INTERVAL = {'www.ebi.ac.uk': 0.5, 'eutils.ncbi.nlm.nih.gov': 0.34, 'api.crossref.org': 0.5,
                'clinicaltrials.gov': 1.2, 'api.openalex.org': 0.2, 'api.biorxiv.org': 1.0,
                'oaipmh.arxiv.org': 3.0, 'api.unpaywall.org': 0.5}
# The fields of a ClinicalTrials.gov study that change as the trial goes on. The API gives the current
# version of a record only, so for a cutoff they are known only when the record was last updated by then.
TRIAL_CHANGING = ('status', 'status_verified', 'phases', 'enrollment', 'start', 'primary_completion',
                  'completion', 'conditions', 'interventions', 'primary_outcomes')
TRIAL_FIELDS = 'NCTId,BriefTitle,OverallStatus,Phase,StudyFirstPostDate,LastUpdatePostDate,ResultsFirstPostDate,HasResults'
# Retries of a 429 or 5xx answer, and the longest wait the kit accepts from Retry-After.
RETRIES = 3
MAX_WAIT = 60
# Ids per Europe PMC lookup query; the service caps a query's length.
BATCH = 50
LOG = 'search-log.jsonl'
STEP_ONE = 'step-1.json'
RESPONSES = 'search-responses'
# Every command of this kit that writes to a work directory takes this lock, and so does `purge`, so
# that a removal and a write cannot interleave. It is re-entrant for the same thread and workdir
# (a command that locks and then logs does not deadlock on itself) and exclusive between processes. What it does not
# cover is said plainly in the README: an adversary who already holds an open descriptor on a body is
# outside the threat model, and purge is not run beside writers that do not take this lock.
LOCK = '.ohf-store.lock'
_LOCKS = {}
_LOCKS_GUARD = threading.Lock()


@contextlib.contextmanager
def store_lock(workdir):
    """Hold the work directory's lock for the duration of the block."""
    path = Path(workdir).resolve()
    path.mkdir(parents=True, exist_ok=True)
    with _LOCKS_GUARD:
        state = _LOCKS.setdefault(path, {'owner': threading.RLock(), 'depth': 0, 'fd': None})
    # Only this thread holding this workdir's RLock can reuse the descriptor. A competing thread
    # must wait for the outer operation to log; another workdir gets its own descriptor and owner.
    with state['owner']:
        if state['depth'] == 0:
            state['fd'] = os.open(path / LOCK, os.O_RDWR | os.O_CREAT, 0o600)
            try:
                fcntl.flock(state['fd'], fcntl.LOCK_EX)
            except BaseException:
                os.close(state['fd'])
                state['fd'] = None
                raise
        state['depth'] += 1
        try:
            yield
        finally:
            state['depth'] -= 1
            if state['depth'] == 0:
                fcntl.flock(state['fd'], fcntl.LOCK_UN)
                os.close(state['fd'])
                state['fd'] = None

# Europe PMC comment/correction links on a work, by what the linked work does to it.
RESPONSE_LINKS = {'Comment in', 'Erratum in', 'Retraction in', 'Expression of concern in',
                  'Republished in', 'Update in', 'Corrected and republished in', 'Partial retraction in'}
# A citing work of one of these types answers the article rather than only cites it.
RESPONSE_TYPES = ('comment', 'reply', 'letter', 'correspondence', 'article-commentary', 'editorial',
                  'retraction', 'erratum', 'correction', 'expression of concern')
# What a notice does to the article, from a Crossref update type or a Europe PMC link or type.
STATUS_OF = {'retraction': 'retracted', 'withdrawal': 'retracted', 'removal': 'retracted',
             'correction': 'corrected', 'erratum': 'corrected',
             'corrigendum': 'corrected', 'addendum': 'corrected', 'clarification': 'corrected',
             'expression_of_concern': 'concern',
             'Retraction in': 'retracted', 'Erratum in': 'corrected',
             'Corrected and republished in': 'corrected', 'Expression of concern in': 'concern',
             'Retracted Publication': 'retracted'}
# The worst status wins: a retracted work that was also corrected is retracted.
SEVERITY = ('none_found', 'corrected', 'concern', 'partial', 'retracted')
# The names above are compared **normalised**, and the publication type is what the screen keys on.
# Measured on the amoebae conversion: Europe PMC's structural `retracted` field was null for a work
# whose `type` said "Retracted Publication", so a screen resting on the field would have passed it -
# and the kit's own records carry that type lowercased in the log, where an exact-string table misses
# it too. The field remains a signal and is reported when it is set; it is not the key.
#
# Four classes, and the distinction is not bookkeeping. **A retraction withdraws the result:
# the work is not read as a result at all.** A correction changes it: the work is still a result and
# is read together with its correction. An expression of concern is neither - it reports a doubt that
# has not been resolved. The first form of this listed all of them together, which would have let a
# corrected work be set aside with the reason `retracted` ("not read as a result"), and that is false
# about a work a card may perfectly well use.
RETRACTION_TYPES = ('retracted publication', 'retraction of publication', 'retraction',
                    'retracted article', 'withdrawn publication', 'withdrawal', 'removal')
CORRECTION_TYPES = ('published erratum', 'erratum', 'correction', 'corrigendum', 'addendum',
                    'clarification', 'corrected and republished article',
                    'corrected and republished in', 'erratum in')
CONCERN_TYPES = ('expression of concern', 'expression_of_concern', 'expression of concern in')
# A **partial** retraction is not a
# correction. Part of the results is withdrawn, and which part is in the notice and nowhere else - so
# a work read "with its correction" but without its notice can be rested on exactly where it was
# withdrawn. Such a work may be used only when the notice has been read and the line does not stand
# on the withdrawn part; the second half of that is a reading, not a check, and this code says so.
PARTIAL_TYPES = ('partial retraction', 'partial retraction in', 'partial retraction of publication')
STATUS_NORMAL = {re.sub(r'[^a-z]', '', k.lower()): v for k, v in STATUS_OF.items()}
for _names, _status in ((RETRACTION_TYPES, 'retracted'), (CORRECTION_TYPES, 'corrected'),
                        (CONCERN_TYPES, 'concern'), (PARTIAL_TYPES, 'partial')):
    STATUS_NORMAL.update({re.sub(r'[^a-z]', '', n): _status for n in _names})


def status_of(name):
    """What a notice or publication type does to the article, whatever case or spacing it arrives in."""
    return STATUS_NORMAL.get(re.sub(r'[^a-z]', '', str(name or '').lower()))


def retraction_classes(work):
    """The statuses a work's **publication types** state, in either shape - `pubTypeList` from a
    service, `type` as this kit logs it - with the structural field as a signal only.

    Each is one of `retracted`, `corrected`, `concern` or `partial`, and they are four different
    things: a retraction withdraws the result, a correction changes it, a concern reports an
    unresolved doubt, and a partial retraction withdraws **part** of the result - which part being in
    the notice and nowhere else.
    """
    stated = set(pub_types(work)) | {p for p in str(work.get('type') or '').split(';')}
    found = {status_of(t) for t in stated if t}
    return sorted(f for f in found if f in ('retracted', 'corrected', 'concern', 'partial'))


def withdrawn(work):
    """Whether a work's own publication types say it was **retracted** - not corrected, not doubted.

    This is the only question that may put the reason `retracted` on a work, and the reason the kit
    checks it rather than trusting the caller: `retracted` says "not read as a result", which is false
    of a corrected work, and a conversion setting it aside that way would be recording something
    untrue about a work a card could use with its correction.
    """
    return 'retracted' in retraction_classes(work)


def valid_not_cited(record):
    """A reading attestation is independent of its metadata lookup; a semantic refusal is not one.

    Other reasons are validated, with the locator, before lookup. `retracted` additionally needs a
    successful lookup establishing full withdrawal; it never stands after a failed lookup or for a
    corrected/partially withdrawn work.
    """
    ask = record.get('ask') or {}
    reason = ask.get('reason')
    if (record.get('tool') != 'not_cited' or record.get('outcome') not in ('ok', 'failed') or
            reason not in NOT_CITED or not isinstance(ask.get('locator'), str) or not ask['locator'].strip()):
        return False
    return reason != 'retracted' or (record['outcome'] == 'ok' and withdrawn(record.get('work') or {}))


def notice_key(value):
    """One notice/work identifier, without treating an unrelated URL as an identity."""
    value = str(value or '').strip()
    value = re.sub(r'^https?://(?:dx\.)?doi\.org/', '', value, flags=re.I)
    if re.fullmatch(r'(?:MED:|PMID:)?\d+', value, re.I):
        return 'pmid:' + value.rsplit(':', 1)[-1]
    value = re.sub(r'^PMC:(?=PMC)', '', value, flags=re.I)
    if re.fullmatch(r'PMC\d+', value, re.I) or is_doi(value):
        return value.lower()
    return None


def record_hash(record):
    return sha256(json.dumps(record, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode())


def bound_notice_reading(record, calls):
    """The work ids a separately declared partial-notice reading is bound to, or an empty set.

    The notice hash/locator/reader are an attestation, not fetched text or a scientific judgement.
    Metadata discovery alone has no such attestation and can never count as a reading.
    """
    if record.get('tool') != 'notice_read' or record.get('outcome') != 'ok':
        return set()
    proof, binding = record.get('reading') or {}, record.get('status_record') or {}
    if (proof.get('kind') != 'attestation' or
            not re.fullmatch(r'sha256:[0-9a-f]{64}', str(proof.get('notice_sha256') or '')) or
            not all(isinstance(proof.get(k), str) and proof[k].strip() for k in ('reader', 'locator'))):
        return set()
    candidates = [r for r in calls if r.get('call_id') == binding.get('call_id')]
    if len(candidates) != 1:
        return set()
    status = candidates[0]
    if status.get('tool') != 'status' or status.get('outcome') != 'ok' or record_hash(status) != binding.get('sha256'):
        return set()
    work = work_ids(status.get('target') or status.get('work') or {})
    given = notice_key((status.get('ask') or {}).get('id'))
    if given:
        work.add(given)
    aliases = alias_map(calls)
    work = set().union(work, *(aliases.get(i, set()) for i in work))
    ask = record.get('ask') or {}
    if notice_key(ask.get('id')) not in work:
        return set()
    notice = notice_key(ask.get('notice'))
    if not notice or not any(n.get('status') == 'partial' and status_of(n.get('kind')) == 'partial' and
                             notice_key(n.get('notice')) == notice for n in status.get('notices', [])):
        return set()
    return work


class SearchError(RuntimeError):
    pass


class StepClosedError(RuntimeError):
    """A frozen search step cannot make another call or change its log."""


def search_open(workdir):
    if (Path(workdir) / STEP_ONE).exists():
        raise StepClosedError('search step is fixed by step-1.json; use a new work directory for a new search')


class MalformedQuery(SearchError):
    """A query written in a syntax the service being asked does not implement."""


class RouteUnavailable(SearchError):
    """A route answered, and what it answered cannot be used as the work's own record.

    Three ways that happens, and none of them is a transport failure or a licence refusal: the
    payload holds no document at all, the document it holds is not the work that was asked for, or
    its identity is missing or self-contradictory, so that reading a licence out of it would be a
    claim about the requested work resting on another document's bytes. The call is recorded with
    `outcome: 'unavailable'` - a route that answered and gave nothing usable - which is neither
    `failed` (nothing answered) nor `ok` with a refusal (the work's own record was read and refused).
    """


def now():
    return datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def sha256(data):
    return 'sha256:' + hashlib.sha256(data).hexdigest()


def user_agent():
    name = f'ohf-extractor/{VERSION}'
    return f'{name} (mailto:{CONTACT})' if CONTACT else name


def http_get(url, body=None):
    """The network transport: (status, bytes, headers). Tests replace it with recorded responses.
    With body (bytes), a POST of JSON, for a service that takes its query only that way (GraphQL)."""
    headers = {'User-Agent': user_agent()}
    if body is not None:
        headers['Content-Type'] = 'application/json'
    req = urllib.request.Request(url, data=body, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, r.read(), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read(), dict(e.headers or {})


def decoded(data, headers):
    """(the body as a reader reads it, the content encoding undone or None).

    A server may compress a response that was not asked to be: the Internet Archive's `id_` form
    returns the original bytes with `Content-Encoding: gzip` though no `Accept-Encoding` is sent. Kept
    as received, such a body parses to nothing, with no error. So gzip and deflate are undone here,
    and what is kept, hashed and read is one thing. An encoding the kit cannot undo is an error, never
    a kept body that nothing can read."""
    encoding = next((v for k, v in headers.items() if k.lower() == 'content-encoding'), '').strip().lower()
    if encoding in ('', 'identity'):
        return data, None
    try:
        if encoding in ('gzip', 'x-gzip'):
            return gzip.decompress(data), encoding
        if encoding == 'deflate':  # zlib-wrapped as RFC 9110 says; some servers send it raw
            try:
                return zlib.decompress(data), encoding
            except zlib.error:
                return zlib.decompress(data, -zlib.MAX_WBITS), encoding
    except (OSError, EOFError, zlib.error) as e:
        # Not `{e}`: a response that claims gzip and is not carries its first bytes in the
        # decompressor's message ("Not a gzipped file (b'<?xml'...)"), and this wrapper used to put
        # them in the record of the call. The encoding is named because it matched the kit's own
        # vocabulary above; the failure is named by its class.
        raise SearchError(f'the response says {encoding} and does not decode '
                          f'({type(e).__name__})') from e
    # The encoding is a header value, so it is named only if it has the shape of one; a header that
    # carries something else is reported by its length. Not the body's problem, but the same rule.
    named = encoding if re.fullmatch(r'[a-z0-9*-]{1,20}', encoding) else f'{len(encoding)} characters'
    raise SearchError(f'the response names a content encoding the kit cannot undo: {named}')


class Searcher:
    """Runs searches, waits between requests to a host, and logs each call in workdir."""

    def __init__(self, workdir='.', get=http_get, sleep=time.sleep, clock=time.monotonic):
        self.workdir = Path(workdir)
        self.get, self.sleep, self.clock = get, sleep, clock
        self.last = {}

    # -- transport -------------------------------------------------------------------------------

    def fetch(self, url, responses, body=None, keep_body=True):
        """GET url politely, or POST body to it; append {url, at, status, sha256} to responses (and
        request_sha256 of a body, kept like a response, so the request repeats) and return the bytes.
        A compressed body is decoded first (`decoded`): sha256 is of the decoded bytes, and the record
        names the encoding undone as decoded_from, so the hash is not compared with the server's bytes.

        With `keep_body=False` the answer is recorded by hash and status and **not written to disk**:
        the record carries `kept: false`, and `search-responses/` gets no file. That is for a probe of
        a full text - a request made to find out whether a place answers at all, not to read the work -
        where retaining the payload would keep a copy of a work this kit may have no licence to
        reproduce, and would make a claim of "no bytes kept" false. Every metadata fetch keeps its
        answer as before, so a call can still be repeated from the responses it hashed."""
        search_open(self.workdir)
        host = urllib.parse.urlsplit(url).hostname
        asked = {'request_sha256': self.keep(body)} if body is not None else {}
        for attempt in range(RETRIES + 1):
            wait = self.last.get(host, -1e9) + MIN_INTERVAL.get(host, 1.0) - self.clock()
            if wait > 0:
                self.sleep(wait)
            at = now()
            status, data, headers = self.get(url) if body is None else self.get(url, body)
            self.last[host] = self.clock()
            if status == 200:
                break
            if status != 429 and status < 500 or attempt == RETRIES:
                responses.append({'url': url, **asked, 'at': at, 'status': status, 'sha256': sha256(data)})
                raise SearchError(f'{url}: HTTP {status}')
            after = headers.get('Retry-After', '')
            self.sleep(min(int(after) if after.isdigit() else 2 ** attempt, MAX_WAIT))
        try:
            data, encoding = decoded(data, headers)
        except SearchError:
            responses.append({'url': url, **asked, 'at': at, 'status': status, 'content_encoding': next(
                v for k, v in headers.items() if k.lower() == 'content-encoding'), 'kept': False})
            raise
        kept = {'sha256': self.keep(data)} if keep_body else {'sha256': sha256(data), 'kept': False}
        responses.append({'url': url, **asked, 'at': at, 'status': status, **kept}
                         | ({'decoded_from': encoding} if encoding else {}))
        return data

    def keep(self, data):
        """Keep bytes in the work directory by their hash; return the hash."""
        keep = self.workdir / RESPONSES
        with store_lock(self.workdir):
            keep.mkdir(parents=True, exist_ok=True)
            (keep / (sha256(data).split(':')[1] + '.body')).write_bytes(data)
        return sha256(data)

    def json(self, url, responses, body=None):
        """The JSON at url; with body (a dict), the JSON a POST of it returns."""
        data = None if body is None else json.dumps(body, sort_keys=True, separators=(',', ':')).encode()
        return json.loads(self.fetch(url, responses, data))

    def log(self, record):
        with store_lock(self.workdir):
            search_open(self.workdir)
            self.workdir.mkdir(parents=True, exist_ok=True)
            with open(self.workdir / LOG, 'a') as f:
                f.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + '\n')
        return record

    def call(self, tool, ask, run):
        # Keep a close-step from cutting between the network call and its log record. The existing
        # store lock is re-entrant for the nested response/log writes made by the same call.
        with store_lock(self.workdir):
            search_open(self.workdir)
            return self._call(tool, ask, run)

    def _call(self, tool, ask, run):
        """Run one search: run(responses) returns (hit_count, works, extra). The record is logged
        whether the search succeeds or fails; a failed search is a search that found nothing known."""
        record = {'call_id': uuid.uuid4().hex[:12], 'tool': tool, 'ask': ask, 'started_at': now(),
                  'kit': f'ohf-extractor/{VERSION}', 'responses': []}
        try:
            hits, works, extra = run(record['responses'])
            record.update(extra, hit_count=hits, found=len(works), works=works, outcome='ok')
        # Before `failed`: a malformed query is not a search that found nothing known, it is a search
        # that was never made, and the two must not read alike in the log.
        except MalformedQuery as e:
            record.update(outcome='malformed_query', error=str(e), hit_count=None, found=0, works=[])
        # Also before `failed`, and for the same reason: a route that answered 200 with something the
        # kit cannot bind to the work asked for has not failed to reach the service, and a reader of
        # the log must be able to tell those apart. The responses already carry that answer's status
        # and hash, so the evidence of what arrived stays in the record without its body.
        except RouteUnavailable as e:
            record.update(outcome='unavailable', error=str(e), hit_count=None, found=0, works=[])
        except (SearchError, OSError, ValueError, KeyError) as e:
            record.update(outcome='failed', error=str(e), hit_count=None, found=0, works=[])
        record['finished_at'] = now()
        return self.log(record)

    # -- Europe PMC ------------------------------------------------------------------------------

    def epmc_search(self, query, limit, responses, core=True, sort=None):
        """Results of a Europe PMC query, following the cursor until limit; (hit_count, results)."""
        results, cursor, hits = [], '*', 0
        while len(results) < limit:
            params = {'query': query, 'format': 'json', 'pageSize': min(1000, limit - len(results)),
                      'cursorMark': cursor, 'resultType': 'core' if core else 'lite'}
            if sort:
                params['sort'] = sort
            page = self.json(EPMC + 'search?' + urllib.parse.urlencode(params), responses)
            hits = page.get('hitCount', 0)
            batch = page.get('resultList', {}).get('result', [])
            results += batch
            if not batch or page.get('nextCursorMark') in (None, cursor):
                break
            cursor = page['nextCursorMark']
        return hits, results[:limit]

    def epmc_record(self, ident, responses):
        """The Europe PMC core record of one work, or None."""
        _, found = self.epmc_search(id_query(ident), 1, responses)
        return found[0] if found else None

    def epmc_lookup(self, ids, responses):
        """Core records of works given as (source, id) pairs, keyed by (source, id)."""
        out = {}
        ids = list(dict.fromkeys(ids))
        for i in range(0, len(ids), BATCH):
            part = ids[i:i + BATCH]
            q = ' OR '.join(f'(EXT_ID:{x} AND SRC:{s})' for s, x in part)
            for r in self.epmc_search(q, len(part), responses)[1]:
                out[(r.get('source'), r.get('id'))] = r
        return out

    # -- searches --------------------------------------------------------------------------------

    def literature(self, query, limit=100, sources=('europepmc', 'pubmed'), sort='default', as_of=None, probe=None):
        """Search Europe PMC and/or PubMed for query, as given and without reviews (VARIANTS); one logged
        record per source and variant. sort is a key of SORTS; the record's ask holds the order sent to
        that service (None: the service's own), and each work its rank in the answer. With as_of (a
        cutoff day), each service is asked only for works it indexed or published by then, and each work
        is then judged by its own dates (`cut`). probe (a key of PROBES) is recorded in the ask: the query
        was made by known_search from a query writer's query."""
        out = []
        if sort not in SORTS:
            raise SearchError(f'sort: one of {sorted(SORTS)}')
        window = {} if as_of is None else {'as_of': cutoff_day(as_of)}
        for source in ('europepmc', 'pubmed'):
            if source not in sources:
                continue
            order = SORTS[sort][source]
            for variant, form in VARIANTS.items():
                sent = form[source].format(query)
                if as_of is not None:
                    sent = (epmc_until if source == 'europepmc' else pubmed_until)(sent, as_of)
                ask = {'query': query, 'limit': limit, 'source': source, 'sort': order, 'variant': variant,
                       **window, **({'sent': sent} if sent != query else {}), **({'probe': probe} if probe else {})}
                out.append(self.call('literature', ask,
                                     self.literature_run(source, sent, limit, order, as_of, query)))
        return out

    def known_search(self, queries, limit=20):
        """The literature search of a known-result check: each query of the query writer run each way of
        PROBES, in each service, each through literature() in the probe's order."""
        if not queries or not all((q or '').strip() for q in queries):
            raise SearchError('known-search: at least one non-empty query')
        return [r for q in queries for probe, form in PROBES.items() for source in ('europepmc', 'pubmed')
                for r in self.literature(form[source].format(q.strip()), limit, (source,), form['sort'], probe=probe)]

    def literature_fallback(self, query, fallback_queries, limit=20, sources=('europepmc', 'pubmed'),
                            sort='default', as_of=None, min_works=3, max_works=60):
        """Explicit, bounded query plan; ordinary literature callers are unchanged.

        Try broader queries in caller order only while successful retrieval has
        fewer than min_works unique source IDs. This count cannot judge relevance
        or scientific coverage. Collection failure stops the plan as incomplete,
        never as an empty search. Existing source/variant order, cutoff, response
        provenance, retries and rate limits remain in literature(). The query cap
        is logical queries, not a promise about physical HTTP attempts.
        """
        if (type(query) is not str or not query.strip() or type(fallback_queries) is not list
                or not fallback_queries or len(fallback_queries) >= FALLBACK_QUERIES
                or any(type(q) is not str or not q.strip() for q in fallback_queries)):
            raise SearchError('fallback: one primary and 1..2 non-empty fallback queries required (cap 3 total)')
        queries = [query.strip(), *(q.strip() for q in fallback_queries)]
        if len(set(queries)) != len(queries) or any(len(q) > 2000 for q in queries):
            raise SearchError('fallback: distinct queries of at most 2000 characters required')
        if (type(limit) is not int or not 1 <= limit <= FALLBACK_PER_CALL
                or type(max_works) is not int or not 1 <= max_works <= FALLBACK_WORKS
                or type(min_works) is not int or not 1 <= min_works <= max_works):
            raise SearchError('fallback: limit 1..20, max_works 1..60, min_works 1..max_works required')
        if (type(sources) not in (tuple, list) or not sources
                or any(type(s) is not str or s not in ('europepmc', 'pubmed') for s in sources)
                or len(set(sources)) != len(sources) or type(sort) is not str or sort not in SORTS):
            raise SearchError('fallback: explicit supported sources and sort required')
        if as_of is not None:
            as_of = cutoff_day(as_of)
        with store_lock(self.workdir):
            search_open(self.workdir)
            started, searches, candidates, seen = now(), [], [], set()
            trigger, stop, incomplete = None, 'queries_exhausted', False
            for index, q in enumerate(queries):
                records = self.literature(q, limit, sources, sort, as_of)
                searches.append({'query': q, 'phase': 'primary' if index == 0 else 'fallback',
                                 'calls': [{'call_id': r['call_id'], 'source': r['ask']['source'],
                                            'variant': r['ask']['variant'], 'outcome': r['outcome'],
                                            'hit_count': r['hit_count'], 'found': r['found'],
                                            'hit_count_notice': (f"{r['hit_count']} hits are not "
                                                f"{r['hit_count']} relevant papers; relevance is not assessed."
                                                if r['hit_count'] is not None else
                                                'Hit count unavailable; collection failure is not zero.')}
                                           for r in records]})
                for r in records:
                    for w in r['works']:
                        key = w['source_id']
                        if key not in seen:
                            seen.add(key)
                            candidates.append(w)
                if not records or any(r['outcome'] != 'ok' for r in records):
                    incomplete, stop = True, 'collection_incomplete'
                    if index == 0:
                        trigger = 'collection_incomplete'
                    break
                if len(candidates) >= min_works:
                    stop = 'candidate_threshold_met'
                    break
                if index == 0:
                    trigger = 'empty' if not candidates else 'below_candidate_threshold'
            # The original literature calls retain their own response hashes and
            # capped metadata in the log. This summary references them, not copies
            # of the bodies or uncapped work lists in its public output.
            return self.log({'call_id': uuid.uuid4().hex[:12], 'tool': 'literature_fallback',
                'kit': f'ohf-extractor/{VERSION}', 'started_at': started, 'finished_at': now(),
                'ask': {'query': query, 'fallback_queries': fallback_queries, 'limit': limit,
                        'sources': list(sources), 'sort': sort, 'as_of': as_of,
                        'min_works': min_works, 'max_works': max_works},
                'outcome': 'incomplete' if incomplete else 'ok', 'hit_count': None,
                'found': min(len(candidates), max_works), 'works': candidates[:max_works], 'responses': [],
                'searches': searches,
                'fallback': {'selected': True, 'used': len(searches) > 1, 'trigger': trigger,
                             'stop': stop, 'queries_run': len(searches),
                             'queries_not_run': queries[len(searches):],
                             'caps': {'logical_queries': FALLBACK_QUERIES, 'per_call_results': limit,
                                      'selected_results': max_works,
                                      'service_variant_calls': FALLBACK_QUERIES * len(sources) * len(VARIANTS)},
                             'unique_candidates_seen': len(candidates),
                             'results_truncated': len(candidates) > max_works},
                'coverage': {'status': 'unknown_collection_incomplete' if incomplete else stop,
                             'measure': 'unique source IDs, not relevance or scientific completeness',
                             'relevance': 'not_assessed'},
                'notice': 'Service hit counts are candidate matches, not relevant-paper counts. '
                          'Counts from separate queries are not added; inspect the referenced literature calls.'})

    def literature_run(self, source, sent, limit, order, as_of, query=None):
        """The search of one literature record, as call() runs it.

        The syntax check is inside the returned run, so that a refused query is logged as a call like
        any other; it tests the query as given, since the variant wrappers the kit adds are written in
        each service's own syntax."""
        inner = self.literature_inner(source, sent, limit, order, as_of)

        def run(responses):
            refuse_foreign_syntax(query if query is not None else sent, source)
            return inner(responses)
        return run

    def literature_inner(self, source, sent, limit, order, as_of):
        """The search itself, without the syntax check."""
        if source == 'europepmc':
            def run(responses):
                hits, results = self.epmc_search(sent, limit, responses, sort=order)
                return (hits, *bounded(ranked([work_epmc(r) for r in results]),
                                       {'service': 'Europe PMC REST search'}, as_of))
        else:
            def run(responses):
                hits, pmids = self.esearch(sent, limit, responses, sort=order)
                return (hits, *bounded(ranked(self.pubmed_works(pmids, responses)),
                                       {'service': 'NCBI E-utilities esearch+esummary'}, as_of))
        return run

    def not_cited(self, ident, reason, locator, atom=None):
        """Log a work that was read and is not cited: the reason, a key of NOT_CITED, and where in the
        work it shows (a section, table or figure; no text of the work). A reason outside the list or a
        blank locator is refused and nothing is logged. The work is looked up in Europe PMC for its
        identifiers; if the lookup fails, the record keeps the reading with the failure."""
        if reason not in NOT_CITED:
            raise SearchError(f'reason: one of {sorted(NOT_CITED)}')
        if not (locator or '').strip():
            raise SearchError('locator: where in the work the reason shows')
        query = id_query(ident)
        ask = {'id': ident, 'reason': reason, 'locator': locator.strip(), **({'atom': atom} if atom else {})}

        def run(responses):
            found = self.epmc_search(query, 1, responses)[1]
            work = work_epmc(found[0]) if found else None
            # `retracted` says "not read as a result", and that is false of a **corrected** work: a
            # correction changes a result, and the work is read together with it. So the reason is
            # checked against the work's own publication types rather than taken on the caller's
            # word - the kit listed retractions and corrections together for an hour, and an hour was
            # enough for the reason to become available for a work a card may use.
            if reason == 'retracted' and not withdrawn(work or {}):
                classes = retraction_classes(work or {}) or ['no notice']
                raise SearchError(
                    f'{ident}: the reason `retracted` is for a work the publisher withdrew, and this '
                    f"work's own publication types say {', '.join(classes)}. A corrected work is "
                    f'still a result and is read with its correction; record the reason that is true '
                    f'of it, and the notice beside it.')
            return len(found), [], {'work': work, 'notice': retraction_classes(work or {})}
        return self.call('not_cited', ask, run)

    def cited_by(self, ident, limit=2000, as_of=None):
        """Works that cite ident: Europe PMC citations, PubMed 'cited in' and OpenAlex, merged by
        identifier.

        Europe PMC lists citing works without DOI or licence, so the citing works are looked up
        again in batches; PubMed 'cited in' covers only citations PMC has seen. OpenAlex reads the
        reference lists publishers deposit, so it lists citing works the other two do not see (books,
        and journals without full text in PMC); a work it gives with a PMID is read from Europe PMC like
        the rest, and one without is recorded from OpenAlex. If OpenAlex fails (its keyless daily budget
        is shared), the call still stands on the other two and records the failure. A work Europe PMC
        has no record of is read from its PubMed summary. With as_of, only works known by then are kept."""
        window = {} if as_of is None else {'as_of': cutoff_day(as_of)}

        def run(responses):
            target = self.epmc_record(ident, responses)
            if target is None:
                raise SearchError(f'{ident}: not in Europe PMC')
            src, tid = target['source'], target['id']
            listed, page = [], 1
            while len(listed) < limit:
                url = EPMC + f'{src}/{tid}/citations?' + urllib.parse.urlencode(
                    {'format': 'json', 'pageSize': 1000, 'page': page})
                data = self.json(url, responses)
                batch = data.get('citationList', {}).get('citation', [])
                listed += batch
                if len(listed) >= data.get('hitCount', 0) or not batch:
                    break
                page += 1
            epmc_hits = len(listed)
            pm = []
            if target.get('pmid'):
                pm = self.elink_citedin(target['pmid'], responses)
            found = [((c['source'], c['id']), 'europepmc') for c in listed] + [(('MED', p), 'pubmed') for p in pm]
            try:
                oa, oa_error = self.openalex_citing(target, limit, responses), None
            except (SearchError, KeyError, ValueError) as e:
                oa, oa_error = [], str(e)
            found += [(('MED', w['pmid']), 'openalex') for w in oa if w['pmid']]
            records = self.epmc_lookup([key for key, _ in found], responses)
            missing = list(dict.fromkeys(key[1] for key, _ in found if key[0] == 'MED' and key not in records))
            summaries = {w['pmid']: w for w in self.pubmed_works(missing, responses)} if missing else {}
            works = {}
            for key, by in found:
                r = records.get(key)
                if r:
                    w = work_epmc(r)
                elif key[1] in summaries and key[0] == 'MED':
                    w = dict(summaries[key[1]], note='listed as citing; no Europe PMC record, read from PubMed')
                else:
                    w = {'source_id': f'{key[0]}:{key[1]}', 'pmid': key[1] if key[0] == 'MED' else None,
                         'pmcid': None, 'doi': None, 'title': None, 'year': None, 'type': None, 'licence': None,
                         'licence_from': None, 'note': 'listed as citing; no Europe PMC record returned'}
                w = works.setdefault(w['source_id'], w)
                w['found_by'] = sorted({*w.get('found_by', []), by})
            by_doi = {w['doi'].lower(): w for w in works.values() if w.get('doi')}
            for w in oa:
                if w['pmid']:
                    continue
                w = by_doi.get((w['doi'] or '').lower()) or works.setdefault(w['source_id'], w)
                w['found_by'] = sorted({*w.get('found_by', []), 'openalex'})
            extra = {'service': 'Europe PMC citations + NCBI elink pubmed_pubmed_citedin + OpenAlex cites',
                     'target': work_epmc(target),
                     'counts': {'europepmc': epmc_hits, 'pubmed': len(pm), 'openalex': None if oa_error else len(oa)}}
            if oa_error:
                extra['openalex_error'] = oa_error
            return (len(works), *bounded(list(works.values()), extra, as_of))
        return self.call('cited_by', {'id': ident, 'limit': limit, **window}, run)

    def responses(self, ident, as_of=None):
        """Works that answer ident: the comment/correction links Europe PMC attaches to it, the
        Crossref relations of its DOI, and the citing works whose type is a comment or reply. With
        as_of, only works known by then are kept."""
        window = {} if as_of is None else {'as_of': cutoff_day(as_of)}
        cites = self.cited_by(ident, as_of=as_of)

        def run(responses):
            target = self.epmc_record(ident, responses)
            if target is None:
                raise SearchError(f'{ident}: not in Europe PMC')
            links = [c for c in (target.get('commentCorrectionList') or {}).get('commentCorrection', [])
                     if c.get('type') in RESPONSE_LINKS]
            records = self.epmc_lookup([(c['source'], c['id']) for c in links], responses)
            works = {}
            for c in links:
                r = records.get((c['source'], c['id']))
                w = work_epmc(r) if r else {'source_id': f"{c['source']}:{c['id']}", 'pmid': None, 'pmcid': None,
                                            'doi': None, 'title': None, 'year': None, 'type': None,
                                            'licence': None, 'licence_from': None, 'citation': c.get('reference')}
                w['relation'] = c['type']
                w['found_by'] = ['europepmc commentCorrectionList']
                works[w['source_id']] = w
            doi = target.get('doi')
            if doi:
                msg = self.json(CROSSREF + urllib.parse.quote(doi, safe='/'), responses)['message']
                for rel, items in (msg.get('relation') or {}).items():
                    if rel not in ('has-comment', 'has-reply', 'has-review'):
                        continue
                    for it in items:
                        key = f"DOI:{it.get('id', '').lower()}"
                        w = works.setdefault(key, {'source_id': key, 'doi': it.get('id'), 'pmid': None,
                                                   'pmcid': None, 'title': None, 'year': None, 'type': None,
                                                   'licence': None, 'licence_from': None})
                        w['relation'] = w.get('relation') or rel
                        w.setdefault('found_by', []).append('crossref relation')
            for w in cites['works']:
                if is_response(w.get('type')):
                    hit = works.setdefault(w['source_id'], dict(w, found_by=[]))
                    hit['relation'] = hit.get('relation') or 'cites it; type ' + w['type']
                    hit['found_by'] = sorted({*hit['found_by'], 'citing work of a response type'})
            return (len(works), *bounded(list(works.values()), {
                'service': 'Europe PMC commentCorrectionList + Crossref relation + typed citing works',
                'target': work_epmc(target), 'cited_by_call': cites['call_id'],
                'cited_by_outcome': cites['outcome']}, as_of))
        return self.call('responses', {'id': ident, **window}, run)

    def status(self, ident, as_of=None):
        """Whether ident is retracted, partially retracted, corrected or under a concern.

        Crossref update notices (including those Crossref takes from Retraction Watch) and Europe PMC
        links and publication types are read; each notice found is listed with where it came from.
        "none_found" means these sources record no notice, not that none exists. With as_of, the status
        is the article's on that day: a notice dated later is left out, and one with no date, which
        may be later, is listed as `undetermined` and not counted."""
        window = {} if as_of is None else {'as_of': cutoff_day(as_of)}

        def run(responses):
            target = self.epmc_record(ident, responses)
            doi = (target or {}).get('doi') or (ident if is_doi(ident) else None)
            notices = []
            if target:
                for c in (target.get('commentCorrectionList') or {}).get('commentCorrection', []):
                    if status_of(c.get('type')):
                        notices.append({'status': status_of(c['type']), 'kind': c['type'], 'from': 'europepmc',
                                        'notice': f"{c['source']}:{c['id']}", 'citation': c.get('reference')})
                for t in set(pub_types(target)) | {p for p in str(target.get('type') or '').split(';')}:
                    if t and status_of(t):
                        notices.append({'status': status_of(t), 'kind': t.strip(),
                                        'from': 'europepmc pubType'})
                # The structural field, as a signal beside the types and never as the key: it was null
                # on a work whose type said "Retracted Publication".
                if target.get('retracted') not in (None, '', 0, False):
                    notices.append({'status': 'partial' if 'partial' in retraction_classes(target) else 'retracted',
                                    'kind': 'retracted field',
                                    'from': 'europepmc record field'})
            checked = ['europepmc'] if target else []
            if doi:
                msg = self.json(CROSSREF + urllib.parse.quote(doi, safe='/'), responses)['message']
                checked.append('crossref')
                for u in msg.get('updated-by') or []:
                    kind = (u.get('type') or '').lower()
                    notices.append({'status': status_of(kind) or 'other', 'kind': u.get('type'),
                                    'from': 'crossref ' + (u.get('source') or 'publisher'),
                                    'notice': u.get('DOI'), 'date': date_of(u.get('updated'))})
                if msg.get('update-to'):
                    notices.append({'status': 'is_a_notice', 'kind': 'update-to', 'from': 'crossref',
                                    'notice': [u.get('DOI') for u in msg['update-to']]})
            if not checked:
                raise SearchError(f'{ident}: neither in Europe PMC nor a DOI')
            extra = {}
            if as_of is not None:
                judged = [(n, as_of_record(n['status'], n.get('date'), as_of)) for n in notices]
                notices = [n for n, j in judged if j['value'] is not None]
                extra = {'left_out': [n for n, j in judged if j['reason'] == 'after_cutoff'],
                         'undetermined': [n for n, j in judged if j['reason'] in ('undated', 'straddles_cutoff')]}
            worst = max((n['status'] for n in notices if n['status'] in SEVERITY), key=SEVERITY.index,
                        default='none_found')
            return len(notices), [], {'service': 'Crossref updated-by (incl. Retraction Watch) + Europe PMC',
                                      'target': work_epmc(target) if target else {'doi': doi},
                                      'status': worst, 'notices': notices, 'checked': checked, **extra}
        return self.call('status', {'id': ident, **window}, run)

    def notice_read(self, ident, notice, status_call, locator, notice_sha256, reader):
        """Attest reading one identified partial notice, without retaining its body or fetching it.

        status_call identifies the discovery record, hashed into this attestation. The caller gives
        the hash of the notice actually read, its locator and the reader; the kit checks the binding,
        not whether a human/agent truly read it or which scientific results it withdraws.
        """
        with store_lock(self.workdir):
            at = now()
            calls = read_log(self.workdir)
            matches = [r for r in calls if r.get('call_id') == status_call]
            if len(matches) != 1:
                raise SearchError('notice-read needs one existing status call')
            record = {'call_id': uuid.uuid4().hex[:12], 'tool': 'notice_read', 'kit': f'ohf-extractor/{VERSION}',
                      'started_at': at, 'finished_at': at, 'outcome': 'ok', 'responses': [], 'works': [],
                      'ask': {'id': ident, 'notice': notice},
                      'status_record': {'call_id': status_call, 'sha256': record_hash(matches[0])},
                      'reading': {'kind': 'attestation', 'notice_sha256': notice_sha256,
                                  'locator': locator, 'reader': reader}}
            if not bound_notice_reading(record, calls):
                raise SearchError('notice-read needs the specific partial notice bound to this work and status '
                                  'record, plus its read hash, locator and reader; metadata alone is not reading')
            return self.log(record)

    def similar(self, ident, limit=100, as_of=None):
        """PubMed's related articles for ident, in its own order (the score is recorded), looked up in
        Europe PMC for DOI and licence. Finds disagreement that does not cite the article. With as_of,
        only works known by then are kept; PubMed's order is computed today, over later works too."""
        window = {} if as_of is None else {'as_of': cutoff_day(as_of)}

        def run(responses):
            target = self.epmc_record(ident, responses)
            if target is None or not target.get('pmid'):
                raise SearchError(f'{ident}: no PMID in Europe PMC; PubMed related articles need one')
            data = self.json(self.eutils('elink', {'dbfrom': 'pubmed', 'db': 'pubmed', 'linkname': 'pubmed_pubmed',
                                                   'cmd': 'neighbor_score', 'id': target['pmid']}), responses)
            ranked = [x for ls in data.get('linksets', []) for db in ls.get('linksetdbs', [])
                      if db.get('linkname') == 'pubmed_pubmed' for x in db.get('links', [])]
            ranked = [x for x in ranked if str(x['id']) != target['pmid']]
            records = self.epmc_lookup([('MED', str(x['id'])) for x in ranked[:limit]], responses)
            works = []
            for rank, x in enumerate(ranked[:limit], 1):
                r = records.get(('MED', str(x['id'])))
                w = work_epmc(r) if r else {'source_id': f"MED:{x['id']}", 'pmid': str(x['id']), 'pmcid': None,
                                            'doi': None, 'title': None, 'year': None, 'type': None, 'licence': None,
                                            'licence_from': None, 'note': 'no Europe PMC record returned'}
                works.append(dict(w, rank=rank, score=x.get('score')))
            return (len(ranked), *bounded(works, {'service': 'NCBI elink pubmed_pubmed (related articles) + '
                                                         'Europe PMC lookup', 'target': work_epmc(target)}, as_of))
        return self.call('similar', {'id': ident, 'limit': limit, **window}, run)

    def terms(self, ident):
        """The indexing terms of ident: MeSH headings (major topics marked) and the authors' keywords, as
        Europe PMC gives them. They widen a literature query beyond the article's own wording."""
        def run(responses):
            target = self.epmc_record(ident, responses)
            if target is None:
                raise SearchError(f'{ident}: not in Europe PMC')
            mesh = [{'heading': m.get('descriptorName'), 'major': m.get('majorTopic_YN') == 'Y',
                     'qualifiers': [q.get('qualifierName') for q in (m.get('meshQualifierList') or {}).get(
                         'meshQualifier', [])]}
                    for m in (target.get('meshHeadingList') or {}).get('meshHeading', [])]
            keywords = (target.get('keywordList') or {}).get('keyword', [])
            return len(mesh) + len(keywords), [], {'service': 'Europe PMC core record (MeSH, keywords)',
                                                   'target': work_epmc(target), 'mesh': mesh, 'keywords': keywords}
        return self.call('terms', {'id': ident}, run)

    def trial(self, nct, as_of=None):
        """One ClinicalTrials.gov study by its NCT number: status, phases, dates, conditions,
        interventions and primary outcomes as registered (`trial_record`), with the release of the data
        read. With as_of, the record as known on that day (`trial_as_of`)."""
        window = {} if as_of is None else {'as_of': cutoff_day(as_of)}

        def run(responses):
            if not re.fullmatch(r'NCT\d{8}', nct):
                raise SearchError(f'{nct!r}: an NCT number is NCT and eight digits')
            study = self.json(CTGOV + f'studies/{nct}?format=json', responses)
            release = self.json(CTGOV + 'version', responses).get('dataTimestamp')
            t = trial_record(study)
            extra = {'service': 'ClinicalTrials.gov API v2', 'release': release}
            if as_of is None:
                return 1, [], dict(extra, trial=t)
            return 1, [], dict(extra, trial=trial_as_of(t, as_of), stated=t)
        return self.call('trial', {'id': nct, **window}, run)

    def trials(self, query, limit=100, as_of=None):
        """ClinicalTrials.gov studies matching query (its own search, which also matches synonyms of
        conditions and interventions), each with status, phases and dates. With as_of, only studies
        registered by that day, each as known then."""
        window = {} if as_of is None else {'as_of': cutoff_day(as_of)}

        def run(responses):
            params = {'query.term': query, 'fields': TRIAL_FIELDS, 'countTotal': 'true', 'format': 'json'}
            if as_of is not None:
                params['filter.advanced'] = f'AREA[StudyFirstPostDate]RANGE[MIN,{as_of}]'
            studies, total, token = [], 0, None
            while len(studies) < limit:
                page = self.json(CTGOV + 'studies?' + urllib.parse.urlencode(
                    dict(params, pageSize=min(1000, limit - len(studies)), **({'pageToken': token} if token else {}))),
                    responses)
                total = page.get('totalCount', total)
                studies += page.get('studies', [])
                token = page.get('nextPageToken')
                if not token or not page.get('studies'):
                    break
            found = ranked([dict(trial_record(x), source_id=f"NCT:{trial_record(x)['nct']}") for x in studies[:limit]])
            release = self.json(CTGOV + 'version', responses).get('dataTimestamp')
            works, extra = bounded(found, {'service': 'ClinicalTrials.gov API v2', 'release': release}, as_of)
            if as_of is not None:
                works = [trial_as_of(w, as_of) for w in works]
            return total, works, extra
        return self.call('trials', {'query': query, 'limit': limit, **window}, run)

    def text(self, ident):
        """Where the full text of a work can be read openly, with the licence each place states: the
        Europe PMC JATS XML and PMC BioC of a PMC article, the free copies Europe PMC lists, the JATS
        XML of a bioRxiv or medRxiv preprint, an arXiv PDF, and, with OHF_CONTACT set, the open copies
        Unpaywall knows. It finds; it does not download. A card takes text only from a copy the kit
        reads itself (docs.json), under its licence rule; a place that refuses is not tried another way."""
        def run(responses):
            return self.places(ident, responses)
        return self.call('text', {'id': ident}, run)

    def licence(self, ident):
        """The licence of a work, **measured from its own bytes** and logged as a record.

        Why this exists. Every licence in the log until now came from a service: `europepmc license
        field`, `openalex primary_location license`, `unpaywall license`. The standard's rule is the
        opposite - a card may quote a work only when the version is in the article's own permissions
        element - and the conversions did read those bytes, but the reading lived in the report's prose
        while the record beside it carried the service's field. An acceptance then found a work whose
        licence the card asserted from the field and whose bytes nobody had opened; the field happened
        to be right, which is luck, not provenance. So the measurement is a record: the JATS is
        fetched, the article's own permissions element is read by `ohfkit.licence_of_jats`, and the
        answer - the licence with its version, or the refusal and its reason - is logged with the
        response status and hash, the hash of the permissions text, and that text itself, which is a
        licence notice and not content of the work.

        `licence_from` is `article permissions (measured)`, which is the only value in the log that
        means the bytes were read. A work this refuses may be named by a card and never quoted.
        """
        # Imported here, not at the top: `ohfkit` needs OHF_REPO at import time, and every other
        # command in this file runs without a checkout of the standard. Only this one reads a licence.
        import ohfkit

        def run(responses):
            record = self.epmc_record(ident, responses)
            pmcid = (record or {}).get('pmcid')
            # Before a URL is built from it, and before it names a file. This value comes from a
            # service's metadata, and until a review tried it, `{"body": …}` there went into the
            # fullTextXML URL, into the responses and into the log - a payload reflected into a
            # request, which is the furthest a value can travel before anything checks it.
            if pmcid is not None:
                pmcid = reflect('pmcid', pmcid, path='the metadata record pmcid')
            if not pmcid:
                raise SearchError(f'{ident}: no PMCID, so there is no JATS to measure a licence in; '
                                  f'record the places with `text` and measure the licence where the '
                                  f'work states it')
            # keep_body=False everywhere below: the answer is hashed and not written to disk. This
            # command asks a work what its licence is, which must be answerable about a work the kit
            # may have no licence to reproduce - and for a refused one, keeping the full text would be
            # the very thing the refusal forbids. What the record keeps is the hash of those bytes and
            # the licence notice itself. The full text of a work the card does read is cached by the
            # ordinary read of it, where the licence has already been measured.
            #
            # Two routes, and the record always says which one answered. The JATS permissions element
            # is the standard's own place for the article's licence and is tried first. When it
            # refuses - PMC10592076 answered HTTP 500 while its BioC JSON read perfectly - the PMC
            # BioC front passage carries a `license` infon, and measuring there is measuring the
            # work's own record rather than falling back on a service's metadata field. An acceptance
            # found that gap: a refusal recorded as `europepmc license field` while the measurement
            # was available by a route this command did not try.
            route, statement, extra, perm, perm_route = None, None, {}, None, False
            jats_refusal = None
            try:
                url = EPMC + f'{pmcid}/fullTextXML'
                raw = self.fetch(url, responses, keep_body=False)
                perm = ohfkit.article_permissions(ET.fromstring(raw))
                perm_route = True
                statement = ohfkit.norm(ohfkit.permissions_text(perm)) if perm is not None else None
                route = JATS_ROUTE
                extra = {'service': 'Europe PMC JATS, article/front/article-meta/permissions',
                         'jats_sha256': sha256(raw)}
            # **Only a route that did not answer sends the question elsewhere.** A JATS that answered
            # a document the kit could read has given this route's verdict, and a verdict of "this
            # article states no licence" is an answer, not a reason to ask another service: the owner's
            # rule is that the BioC infon is read when the JATS *refuses*, and a review found that a
            # catch added for the escaping-exception leak had quietly widened that to "or says no" -
            # so an article with no permissions element came out quotable from the other route's
            # sentence. Transport failures and an unreadable answer are the only fallbacks.
            except ohfkit.LicenceError as jats_said_no:
                jats_refusal = refusal_record(jats_said_no)
                route, statement, perm_route = JATS_ROUTE, None, True
                extra = {'service': 'Europe PMC JATS, article/front/article-meta/permissions',
                         'jats_sha256': sha256(raw), 'jats_status': jats_status(responses)}
            except (SearchError, OSError, ET.ParseError) as jats_refused:
                bioc = self.fetch(BIOC.format(pmcid), responses, keep_body=False)
                front, identity = bioc_front(json.loads(bioc), pmcid, route_evidence(responses))
                statement = ohfkit.norm((front.get('infons') or {}).get('license') or '')
                route = BIOC_ROUTE
                extra = {'service': 'PMC BioC JSON, front passage license infon',
                         'bioc_sha256': sha256(bioc),
                         # Why the first route did not answer, as facts rather than as its words: the
                         # kit's phrase or refusal code, and the status of its own response, read from
                         # the response record instead of from the exception's message - where a
                         # review found body bytes, through a decompressor's complaint.
                         'jats_refused': (refusal_record(jats_refused)['phrase']
                                          if isinstance(jats_refused, ohfkit.LicenceError)
                                          else reflect('foreign', jats_refused)),
                         'jats_refused_code': (refusal_record(jats_refused)['code']
                                               if isinstance(jats_refused, ohfkit.LicenceError)
                                               else type(jats_refused).__name__),
                         'jats_status': jats_status(responses), **identity}
            # The statement is hashed whole, whatever its length, and carried in the record only if
            # it is the length of a notice: an answer that puts a megabyte where a licence sentence
            # belongs is still measured, and is not copied into the log to be measured again.
            kept_text, bound = answer_notice(statement, route_evidence(responses))
            out = {'licence_from': route, 'measured_from': route,
                   'permissions_sha256': sha256((statement or '').encode()),
                   'permissions_text': kept_text, 'work': work_metadata(record), **bound, **extra}
            # A verdict the JATS route already gave stands as it is; nothing else was measured.
            licence, refusal = ((None, jats_refusal) if jats_refusal is not None
                                else licence_verdict(ohfkit, statement, perm, perm_route))
            # The condition the owner set when the BioC infon became an acceptable record: when the kit
            # holds answers from both routes for one article and they disagree, it refuses with
            # `licence_sources_disagree` and chooses neither. The answers it holds are not only the one
            # measured now - a full text cached in this work directory by an ordinary read, and every
            # earlier `licence` record in the log, are answers the kit has, and they are read here
            # without a new request.
            held, aside = self.licence_held(pmcid, ohfkit)
            # An answer is a route that gave a **verdict** - a licence, or a coded refusal of the
            # work's own record - and not merely a route that produced some text. A JATS that says the
            # article has no permissions element has answered; a route that could not be read at all
            # has not, and that distinction is what keeps a silent route from contradicting a real
            # measurement while letting a real refusal contradict one.
            code = refusal['code'] if refusal else None
            answers = ([route_answer(route, licence, code, 'measured now',
                                     statement_sha256=out['permissions_sha256'])]
                       if answered(licence, code) else []) + held
            clashes = routes_disagree(answers)
            if len(answers) > 1:
                out['licence_answers'] = answers
            # What the kit holds and did not compare, named rather than dropped: an unreadable cache,
            # and an earlier call whose own outcome was a disagreement rather than a route's answer.
            if aside:
                out['licence_held_aside'] = aside
            if clashes:
                out['licence'] = None
                out['quotable'] = False
                out['refusal_code'] = 'licence_sources_disagree'
                out['refusal'] = disagreement_text(clashes)
            else:
                out['licence'] = licence
                out['quotable'] = licence is not None
                if refusal is not None:
                    # `licence_refusal_code` is the measurement's own code; `refusal_code` is the
                    # call's outcome, and `licence_sources_disagree` is the only value it takes. They
                    # were one key for an hour, and `licence_held` then read a measured refusal as an
                    # aggregate and dropped the answer - the same shape of defect as R3b, by naming.
                    out['licence_refusal_code'] = refusal['code']
                    out['refusal'] = refusal['phrase']
                    out['refusal_facts'] = {k: v for k, v in refusal.items()
                                            if k not in ('code', 'phrase')} or None
            return 1, [], out
        return self.call('licence', {'id': ident}, run)

    def licence_held(self, pmcid, ohfkit):
        """`(answers, aside)` for one article, read without a new request.

        `answers` are **route answers**: what the article's own record said about its licence by a
        named route, each one a `{route, held_as, licence, refusal}` that `routes_disagree` may
        compare. Two places hold them - the full text cached beside the work (`PMC….xml`, which an
        ordinary read writes) measured through the article's own permissions element, and the earlier
        `licence` records in the log.

        `aside` is everything the kit holds that is **not** a route answer, named in the record
        rather than dropped. A review found both kinds being compared as though they were answers,
        and each produced a refusal on a work both routes actually agreed about:

        - *An unreadable cache.* A cached file that does not parse states nothing; compared as a
          refusal, it contradicted a perfectly good measurement. The same goes for a cache with no
          permissions element of the article's own, and for an earlier record whose
          `permissions_text` is empty: silence is not an answer, and a route that never spoke cannot
          contradict one that did.
        - *An earlier call's own outcome.* A call that refused with `licence_sources_disagree` writes
          `licence: null` with the route it measured by - but that null is the **call's** verdict,
          not that route's answer. Read back as a route answer it made the refusal permanent: the
          route had said CC BY 4.0, the aggregate said nothing, and the next measurement disagreed
          with its own earlier self. So an aggregate is opened instead of trusted: the answer of the
          route it measured is recovered from its `licence_answers` (the entry `measured now`), which
          is that route's own evidence, and the answers it had merely derived from cache and log at
          the time are left alone, since they are recovered here from their own sources anyway.
        """
        answers, aside = [], []
        cached = self.workdir / f'{pmcid}.xml'
        if cached.exists():
            raw, perm, cached_refusal = cached.read_bytes(), None, None
            try:
                perm = ohfkit.article_permissions(ET.fromstring(raw))
            # `article_permissions` refuses a document with no permissions element of the article's
            # own. That cache says nothing about the licence, and a refusal raised over what the kit
            # already holds must not fail a measurement the kit can make by the other route.
            # A document that does not parse says nothing: no verdict, and it is named in the
            # record rather than compared. A document that parses and states no licence of the
            # article's own does give a verdict, and it is kept below.
            except ET.ParseError as e:
                aside.append({'held_as': f'{cached.name} in the work directory',
                              'not_an_answer': 'the cached full text cannot be read',
                              'not_an_answer_code': reflect('foreign', e),
                              'jats_sha256': sha256(raw)})
            except ohfkit.LicenceError as e:
                cached_refusal = refusal_record(e)
            # The cached document's own verdict, by the same definition: `article_permissions` or
            # `licence_of_jats` may refuse it, and a coded refusal of the work's own record is an
            # answer - a cache that states no licence contradicts a route that grants one, and must.
            # Only a document that cannot be read at all says nothing (above).
            if perm is not None or cached_refusal is not None:
                statement = ohfkit.norm(ohfkit.permissions_text(perm)) if perm is not None else None
                licence, refusal = ((None, cached_refusal) if cached_refusal is not None
                                    else licence_verdict(ohfkit, statement, perm, True))
                code = refusal['code'] if refusal else None
                if answered(licence, code):
                    answers.append(route_answer(
                        JATS_ROUTE, licence, code, f'{cached.name} in the work directory',
                        jats_sha256=sha256(raw)))
        for call in read_log(self.workdir):
            answer = logged_answer(call, pmcid)
            if answer is not None:
                answers.append(answer)
            elif (call.get('tool') == 'licence' and call.get('outcome') == 'ok'
                    and (call.get('work') or {}).get('pmcid') == pmcid
                    and call.get('refusal_code') == 'licence_sources_disagree'):
                aside.append({'held_as': f"an earlier measurement, call {call.get('call_id')}",
                              'not_an_answer': "the call's own outcome was a disagreement, and it "
                                               "kept no answer of the route it measured"})
        return answers, aside

    def locate(self, ident, find, limit=5):
        """Passage addresses without retaining or returning the fetched JATS body.

        OHF 1.1 permits `quote_withheld` instead of a quote and requires a locator for that line.
        For a work whose licence refuses quotation, the kit must produce this address without
        keeping the body. This command returns the paragraph and sentence addresses the native
        reader uses.

        What it does: fetches the work's JATS, splits it into paragraphs exactly as `ohfkit`'s reader
        does (`.//p` in document order, so an address here is an address there), reports the paragraph
        and sentence numbers where the caller's words occur. The fullTextXML response is fetched
        with keep_body=False; its text is not included in the returned addresses. The record holds
        work metadata, the document hash, locator strings and counts. The inherited metadata route
        caches its raw response, which may include abstractText; this is not a no-text cache.

        `find` is the caller's own words - it travels in the `ask`, as every other command's question
        does - and is persisted in the record and log. It may itself contain source words. A match
        says those words occur at that address; it does not return the paragraph or its sentences.
        """
        import ohfkit

        def run(responses):
            if type(limit) is not int or limit < 1:
                raise SearchError('locate limit must be a positive integer')
            record = self.epmc_record(ident, responses)
            pmcid = (record or {}).get('pmcid')
            if pmcid is not None:
                pmcid = reflect('pmcid', pmcid, path='the metadata record pmcid')
            if not pmcid:
                raise SearchError(f'{ident}: no PMCID, so there is no JATS to address a passage in')
            raw = self.fetch(EPMC + f'{pmcid}/fullTextXML', responses, keep_body=False)
            try:
                root = ET.fromstring(raw)
            except (ET.ParseError, LookupError) as e:
                raise RouteUnavailable(f'{pmcid}: the full text does not parse, so it has no '
                                       f'addresses ({reflect("foreign", e)})') from e
            # The same split as `ohfkit.JatsDocument`, so that an address from here is the address a
            # card's locator means. Nothing of the text leaves this function.
            paragraphs = [ohfkit.norm(''.join(el.itertext())) for el in root.iter('p')]
            needle = ohfkit.norm(find).casefold()
            hits = []
            for n, text in enumerate(paragraphs, 1):
                flat = text.casefold()
                if needle and needle in flat:
                    sentences = ohfkit.sentences_of(text)
                    which = [i for i, sentence in enumerate(sentences, 1)
                             if needle in sentence.casefold()]
                    hits.append({'locator': ohfkit.LOCATOR.format(n), 'paragraph': n,
                                 'sentences': which, 'sentences_in_paragraph': len(sentences),
                                 'paragraph_characters': len(text)})
                if len(hits) >= limit:
                    break
            out = {'work': work_metadata(record), 'document_sha256': sha256(raw),
                   'paragraphs': len(paragraphs), 'locator_form': ohfkit.LOCATOR,
                   # Not `found`: `call` writes that key itself, from the works a search returned, and
                   # a locate returns no works. A record whose own count is overwritten by the
                   # wrapper reads as "nothing found" beside a list of addresses.
                   'addresses': len(hits), 'at': hits,
                   'service': 'Europe PMC JATS, paragraphs in document order', 'kept': False}
            return len(hits), [], out
        return self.call('locate', {'id': ident, 'find': find, 'limit': limit}, run)

    def not_read(self, ident, atom=None):
        """A work the kit found and could **not** read: every place it lists, tried, with what each answered.

        Why this exists: a conversion that says "the strongest candidate critique could not be fetched"
        is making a claim about particular requests, and until now that claim lived only in the report's
        prose while the search log showed the work as *found*, every call `ok` and every response 200. A
        reader checking the log would conclude that nothing had refused. This command tries each place
        and logs the answer, so the refusal is in the bytes the artifact carries: `fetch` records
        {url, at, status, sha256} for a response it rejects, and the record's `places` says which places
        answered what. A place that answers 200 is recorded as readable, which contradicts the claim -
        that is the point of making the kit do the trying instead of taking the converter's word.

        It downloads what it is given, and nothing else: an answered place is recorded by hash and
        status with its payload **not written to disk** (`kept: false`), no second route is tried for a
        place that refuses, and nothing here works around a refusal. The first version of this command
        said the bytes were not kept while `fetch` wrote every 200 payload into `search-responses/`;
        the reviewer found that, and the probe above is the fix.
        """
        ask = {'id': ident, **({'atom': atom} if atom else {})}

        def run(responses):
            found, _, extra = self.places(ident, responses)
            tried, readable = [], 0
            for place in extra['places']:
                row = {'kind': place.get('kind'), 'url': place['url'], 'from': place.get('from')}
                try:
                    # A probe, not a reading: the answer is hashed and its status recorded, and the
                    # payload is not written to disk. Keeping it would retain a copy of a work this kit
                    # may not reproduce, for no gain - what this call needs to know is whether the place
                    # answers at all.
                    self.fetch(place['url'], responses, keep_body=False)
                except SearchError as e:
                    row['refused'] = str(e)
                else:
                    row['read'] = True
                    readable += 1
                tried.append(row)
            return readable, [], {**extra, 'places': tried, 'places_found': found,
                                  'readable': readable}
        return self.call('not_read', ask, run)

    def places(self, ident, responses):
        """The places the full text of a work can be read, as `text` reports them."""
        if True:  # kept indented so the body reads as it did when it lived inside text()
            arxiv = ARXIV_DOI.match(ident)
            target = None if arxiv else self.epmc_record(ident, responses)
            doi = (target or {}).get('doi') or (ident if is_doi(ident) else None)
            if arxiv is None and doi:
                arxiv = ARXIV_DOI.match(doi)
            places, skipped, errors = [], [], {}

            def add(place):
                if place['url'] not in {p['url'] for p in places}:
                    places.append(place)
            if target:
                if target.get('pmcid') and target.get('inEPMC') == 'Y':
                    add({'kind': 'jats', 'url': EPMC + f"{target['pmcid']}/fullTextXML", 'from': 'europepmc',
                         'licence': target.get('license'), 'licence_from': 'europepmc license field'
                         if target.get('license') else None})
                    if target.get('isOpenAccess') == 'Y':
                        add({'kind': 'bioc_json', 'url': BIOC.format(target['pmcid']), 'from': 'pmc bioc',
                             'licence': target.get('license'), 'licence_from': 'europepmc license field'
                             if target.get('license') else None})
                for u in (target.get('fullTextUrlList') or {}).get('fullTextUrl', []):
                    if u.get('availabilityCode') in ('OA', 'F') and u.get('documentStyle') in ('pdf', 'html'):
                        add({'kind': u['documentStyle'], 'url': u['url'],
                             'from': f"europepmc fullTextUrlList ({u.get('site')})", 'licence': None,
                             'licence_from': None})
            sources = (('biorxiv', lambda: self.preprint_places(doi, responses))
                       if doi and doi.lower().startswith(PREPRINT_PREFIXES) else None,
                       ('arxiv', lambda: self.arxiv_places(arxiv.group(1), responses)) if arxiv else None,
                       ('unpaywall', lambda: self.unpaywall_places(doi, responses)) if doi and CONTACT else None)
            for name, find in filter(None, sources):
                try:
                    for place in find():
                        add(place)
                except (SearchError, KeyError, ValueError, ET.ParseError) as e:
                    errors[name] = str(e)
            if doi and not CONTACT:
                skipped.append('unpaywall: it asks for a contact address; set OHF_CONTACT')
            if target is None and not doi and not arxiv:
                raise SearchError(f'{ident}: neither in Europe PMC nor a DOI or an arXiv id')
            return len(places), [], {'service': 'Europe PMC + PMC BioC + bioRxiv/medRxiv + arXiv + Unpaywall',
                                     'target': work_epmc(target) if target else {'doi': doi},
                                     'places': places, 'skipped': skipped, 'errors': errors}

    def preprint_places(self, doi, responses):
        """The JATS XML and PDF of the latest version of a bioRxiv or medRxiv preprint, with its licence."""
        for server in ('biorxiv', 'medrxiv'):
            versions = self.json(BIORXIV + f'{server}/{doi}', responses).get('collection') or []
            if versions:
                v = versions[-1]
                licence = {'licence': v.get('license'), 'licence_from': f'{server} api license field',
                           'version': v.get('version'), 'date': v.get('date'),
                           'published': None if v.get('published') in (None, 'NA') else v['published']}
                return [dict(licence, kind='jats', url=v['jatsxml'], **{'from': server})] if v.get('jatsxml') else []
        return []

    def arxiv_places(self, arxiv_id, responses):
        """The PDF of an arXiv paper, with the licence arXiv records for it (OAI-PMH, arXiv format)."""
        root = ET.fromstring(self.fetch(ARXIV_OAI + '?' + urllib.parse.urlencode(
            {'verb': 'GetRecord', 'identifier': f'oai:arXiv.org:{arxiv_id}', 'metadataPrefix': 'arXiv'}), responses))
        licence = next((e.text for e in root.iter() if e.tag.endswith('}license')), None)
        if not any(e.tag.endswith('}arXiv') for e in root.iter()):
            raise SearchError(f'arXiv has no record {arxiv_id}')
        return [{'kind': 'pdf', 'url': f'https://arxiv.org/pdf/{arxiv_id}', 'from': 'arxiv', 'licence': licence,
                 'licence_from': 'arxiv oai-pmh license' if licence else None}]

    def unpaywall_places(self, doi, responses):
        """The open copies Unpaywall knows of a DOI, each with its licence, version and host type."""
        data = self.json(UNPAYWALL + urllib.parse.quote(doi, safe='/') + '?' + urllib.parse.urlencode(
            {'email': CONTACT}), responses)
        return [{'kind': 'pdf' if loc.get('url_for_pdf') else 'html', 'url': loc.get('url_for_pdf') or loc['url'],
                 'from': f"unpaywall ({loc.get('host_type')}, {loc.get('version')})", 'licence': loc.get('license'),
                 'licence_from': 'unpaywall license' if loc.get('license') else None}
                for loc in data.get('oa_locations') or []]

    def check_ref(self, ref):
        """One reference of a submitted text, checked: `exists` (the work is found by the identifier the
        reference gives, or, with none, by its author, year and title) and `matches` (what the reference
        says of the work, title, first author, year and journal, against the record). `relevance`, whether
        the work bears on the sentence that cites it, is never decided here: it is `not_assessed`, for a
        reader to judge and record. A work that exists says nothing about the claim; a work not found is
        not a refutation of it."""
        def run(responses):
            record, how = None, None
            for kind in ('pmcid', 'pmid', 'doi'):
                if ref['ids'].get(kind):
                    record, how = self.ref_record(kind, ref['ids'][kind], responses), kind
                    break
            if how is None and ref['claimed'].get('first_author') and ref['claimed'].get('year'):
                found, how = self.ref_by_description(ref['claimed'], responses)
                if len(found) == 1:
                    record = found[0]
                elif len(found) > 1:
                    return 0, [], {'exists': 'ambiguous', 'found_by': how, 'candidates': found,
                                   'matches': 'not_checked', 'differences': [], 'relevance': 'not_assessed',
                                   'reference': ref}
            if how is None:
                return 0, [], {'exists': 'not_checked', 'found_by': None, 'matches': 'not_checked', 'differences': [],
                               'relevance': 'not_assessed', 'reference': ref,
                               'note': 'no identifier, and not enough of author, year and title to search by'}
            if record is None:
                return 0, [], {'exists': 'not_found', 'found_by': how, 'matches': 'not_checked', 'differences': [],
                               'relevance': 'not_assessed', 'reference': ref}
            verdict, differences = compare(ref['claimed'], record)
            if how not in ('pmcid', 'pmid', 'doi') and any(d['field'] == 'title' for d in differences):
                # Found by its description, under another title: a work that contains the words, not the
                # work cited (a book cited, a précis of it found). Not found; the closest record is kept.
                return 0, [], {'exists': 'not_found', 'found_by': how, 'closest': record, 'matches': 'not_checked',
                               'differences': differences, 'relevance': 'not_assessed', 'reference': ref}
            work = {k: record.get(k) for k in ('pmid', 'pmcid', 'doi', 'title', 'year', 'licence', 'licence_from')}
            work['source_id'] = record['source_id']
            return 1, [work], {'exists': 'verified', 'found_by': how, 'record': record, 'matches': verdict,
                               'differences': differences, 'relevance': 'not_assessed', 'reference': ref}
        return self.call('check_ref', {'id': ref['text'][:200], 'paragraph': ref['paragraph']}, run)

    def ref_by_description(self, claimed, responses):
        """(records, how) of a reference with no identifier. With a title, Europe PMC by author and title,
        the year left out of the query because a work's online year can precede the year cited, then
        narrowed to the works dated in the cited year; with no hit, Crossref's bibliographic search,
        kept only where title and first author agree. Without a title, Europe PMC by author, year and
        journal."""
        if not claimed.get('title'):
            q = f"AUTH:\"{claimed['first_author']}\" AND PUB_YEAR:{claimed['year']}"
            if claimed.get('journal'):
                q += f" AND JOURNAL:\"{claimed['journal']}\""
            return [record_of_epmc(r) for r in self.epmc_search(q, 5, responses)[1]], 'author, year and journal'
        # An apostrophe is dropped ("Prisoner’s" → "Prisoners", as Europe PMC indexes it); other
        # punctuation inside a phrase breaks its parse and becomes a space.
        words = ' '.join(re.sub(r"[^\w\s-]", ' ', re.sub(r"['’`]", '', claimed['title'])).split())
        author = claimed['first_author'].replace('’', "'")
        q = f"AUTH:\"{author}\" AND TITLE:\"{words}\""
        found = [record_of_epmc(r) for r in self.epmc_search(q, 5, responses)[1]]
        if len(found) > 1:
            found = [r for r in found if claimed['year'] in years_of(r)] or found
        if found:
            return found, 'author and title'
        data = self.json(CROSSREF.rstrip('/') + '?' + urllib.parse.urlencode(
            {'query.bibliographic': f"{claimed['first_author']} {claimed['year']} {claimed['title']}", 'rows': 5}),
            responses)
        found = [record_of_crossref(m) for m in data.get('message', {}).get('items', [])]
        found = [r for r in found if same_text(r.get('title'), claimed['title']) or title_cut(claimed['title'], r.get('title'))]
        found = [r for r in found if folded(r.get('first_author')) == folded(claimed['first_author'])]
        return found, 'author and title (Crossref bibliographic search)'

    def ref_record(self, kind, value, responses):
        """The catalogue record of a work by PMCID, PMID or DOI: Europe PMC, or for a DOI it does not
        hold, Crossref. None when neither has it."""
        r = self.epmc_record(value, responses)
        if r is not None:
            return record_of_epmc(r)
        if kind == 'doi':
            try:
                return record_of_crossref(self.json(CROSSREF + urllib.parse.quote(value, safe='/'), responses)['message'])
            except SearchError as e:
                if not str(e).endswith('HTTP 404'):
                    raise
        return None

    def similar_cards(self, text, cards, limit=10):
        """Log the accepted cards that may state the same hypothesis as text (see similar_cards)."""
        def run(responses):
            found = similar_cards(text, cards, limit)
            return len(cards), [], {'candidates': found}
        return self.call('similar_cards', {'id': f"text {sha256(text.encode())}", 'text_sha256': sha256(text.encode()),
                                           'cards': [[c.get('id'), c.get('version')] for c in cards],
                                           'limit': limit}, run)

    def check_refs(self, text):
        """Every reference in a submitted text, each checked by check_ref and logged."""
        return [self.check_ref(ref) for ref in references_in(text)]

    # -- PubMed ----------------------------------------------------------------------------------

    def eutils(self, tool, params):
        params = dict(params, tool='ohf-extractor', retmode='json')
        if CONTACT:
            params['email'] = CONTACT
        return EUTILS + tool + '.fcgi?' + urllib.parse.urlencode(params)

    def esearch(self, term, limit, responses, sort=None):
        params = {'db': 'pubmed', 'term': term, 'retmax': limit}
        if sort:
            params['sort'] = sort
        data = self.json(self.eutils('esearch', params), responses)
        r = data['esearchresult']
        return int(r.get('count', 0)), r.get('idlist', [])

    def openalex(self, path, params, responses):
        if CONTACT:
            params = dict(params, mailto=CONTACT)
        return self.json(OPENALEX + path + '?' + urllib.parse.urlencode(params), responses)

    def openalex_citing(self, target, limit, responses):
        """The works OpenAlex lists as citing the target (a Europe PMC record), by its DOI or PMID."""
        ident = f"doi:{target['doi']}" if target.get('doi') else f"pmid:{target['pmid']}" if target.get('pmid') else None
        if ident is None:
            raise SearchError('neither a DOI nor a PMID to find the work in OpenAlex')
        wid = self.openalex(f'works/{ident}', {'select': 'id'}, responses)['id'].rsplit('/', 1)[-1]
        out, page = [], 1
        while len(out) < limit:
            data = self.openalex('works', {'filter': f'cites:{wid}', 'per-page': OPENALEX_PAGE, 'page': page,
                                           'select': OPENALEX_FIELDS}, responses)
            batch = data.get('results', [])
            out += [work_openalex(w) for w in batch]
            if len(batch) < OPENALEX_PAGE:
                break
            page += 1
        return out[:limit]

    def elink_citedin(self, pmid, responses):
        data = self.json(self.eutils('elink', {'dbfrom': 'pubmed', 'linkname': 'pubmed_pubmed_citedin',
                                               'id': pmid}), responses)
        out = []
        for ls in data.get('linksets', []):
            for db in ls.get('linksetdbs', []):
                out += db.get('links', [])
        return [str(x) for x in out]

    def pubmed_works(self, pmids, responses):
        works = []
        for i in range(0, len(pmids), 200):
            part = pmids[i:i + 200]
            res = self.json(self.eutils('esummary', {'db': 'pubmed', 'id': ','.join(part)}), responses)['result']
            works += [work_pubmed(res[p]) for p in res.get('uids', part) if p in res]
        return works


# -- records ---------------------------------------------------------------------------------------

def ranked(works):
    """The works with their rank in the service's answer, from 1."""
    return [dict(w, rank=n) for n, w in enumerate(works, 1)]


def is_doi(ident):
    return bool(re.match(r'^10\.\d{4,9}/\S+$', ident))


def id_query(ident):
    """A Europe PMC query that finds one work by PMID, PMCID or DOI."""
    ident = ident.strip()
    if re.fullmatch(r'\d+', ident):
        return f'EXT_ID:{ident} AND SRC:MED'
    if re.fullmatch(r'PMC\d+', ident, re.I):
        return f'PMCID:{ident.upper()}'
    if is_doi(ident):
        return f'DOI:"{ident}"'
    raise SearchError(f'{ident}: give a PMID, a PMCID or a DOI')


def is_response(kind):
    kind = (kind or '').lower()
    return any(t in kind for t in RESPONSE_TYPES)


def date_of(d):
    parts = (d or {}).get('date-parts', [[None]])[0]
    return '-'.join(f'{p:02d}' if i else str(p) for i, p in enumerate(parts) if p is not None) or None


# -- dates and the state of a source on a date -----------------------------------------------------------

DAY = re.compile(r'(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?')
# Why a field that changes with time has no value on the cutoff date.
AS_OF_REASONS = {'undated': 'the source gives no date for the value, and its release is not before the cutoff',
                 'after_cutoff': 'the value holds only from a date after the cutoff',
                 'straddles_cutoff': "the value's date is a year or month that contains the cutoff"}


def day_span(d):
    """(first, last) day, as YYYY-MM-DD, that a date of a year, a month or a day can mean; None for none."""
    if d is None or d == '':
        return None
    m = DAY.fullmatch(str(d))
    if not m:
        raise SearchError(f'a date is YYYY, YYYY-MM or YYYY-MM-DD, not {d!r}')
    y, mo, dd = (int(g) if g else None for g in m.groups())
    try:
        first = datetime.date(y, mo or 1, dd or 1)
        last = first if dd else datetime.date(y, mo or 12, calendar.monthrange(y, mo or 12)[1])
    except ValueError:
        raise SearchError(f'not a date: {d!r}') from None
    return first.isoformat(), last.isoformat()


def cutoff_day(t):
    """The cutoff T: a day YYYY-MM-DD, inclusive, as OHF added.cutoff_date; not a time."""
    if not (isinstance(t, str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}', t) and day_span(t)):
        raise SearchError(f'the cutoff is a day YYYY-MM-DD, not {t!r}')
    return t


def earliest(dates):
    """(name, date) of the earliest of named dates, {name: YYYY[-MM[-DD]] or None}, by the first day each
    can mean; (None, None) when none is given. A work's date for a cutoff is the earliest of its online,
    print and database-record dates: a work online before it was printed was known from then."""
    given = [(day_span(d)[0], name, d) for name, d in sorted(dates.items()) if day_span(d)]
    return min(given)[1:] if given else (None, None)


def as_of(value, dated, cutoff, release=None):
    """The value a field that changes with time (a trial's status, a compound's phase) had on the cutoff.

    value: the field as the source states it in the state read. dated: the date from which the source
    says that value holds (YYYY, YYYY-MM or YYYY-MM-DD), or None. cutoff: T, YYYY-MM-DD inclusive.
    release: the date of the source state read (a database release, or the day it was fetched), or None.

    The value is kept when it is known to hold by T: its own date is on or before T, or, with no date
    of its own, the state read was released on or before T. Otherwise the value is None with the
    reason; nothing later than T is let in. The record keeps the value as stated, the dates and the
    reason, for the search log: {'value', 'stated', 'dated', 'release', 'cutoff', 'basis', 'reason'},
    basis 'dated' or 'release' for a kept value and reason a key of AS_OF_REASONS for one that is not."""
    cutoff_day(cutoff)
    record = {'value': None, 'stated': value, 'dated': dated, 'release': release, 'cutoff': cutoff,
              'basis': None, 'reason': None}
    for basis, d in (('dated', dated), ('release', None if dated else release)):
        span = day_span(d)
        if span is None:
            continue
        if span[1] <= cutoff:
            record.update(value=value, basis=basis)
        elif basis == 'release':
            record['reason'] = 'undated'
        else:
            record['reason'] = 'after_cutoff' if span[0] > cutoff else 'straddles_cutoff'
        return record
    record['reason'] = 'undated'
    return record


# The methods of Searcher take a cutoff named as_of; this name reaches the function from inside them.
as_of_record = as_of


MONTHS = {m: i for i, m in enumerate(('jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov',
                                      'dec'), 1)}


def iso_date(text):
    """A date as a service writes it ("2024-10-24", "2024/10/24 08:22", "2025 Jan 13", "2025 Jan-Feb",
    "2025 Spring") as YYYY[-MM[-DD]], to the precision it states; None for none. A season or a range
    keeps only what is certain: the year, or the year and first month."""
    m = re.match(r'\s*(\d{4})(?:[-/](\d{1,2})(?:[-/](\d{1,2}))?|\s+([A-Za-z]{3})[a-z]*(?:\s+(\d{1,2})\b)?)?', text or '')
    if not m:
        return None
    y, mo, d, name, nd = m.groups()
    mo = int(mo) if mo else MONTHS.get((name or '').lower())
    d = d or (nd if name and mo else None)
    return y + (f'-{mo:02d}' if mo else '') + (f'-{int(d):02d}' if mo and d else '')


def work_dates(r):
    """The dates of a work from its Europe PMC record (resultType core), each YYYY[-MM[-DD]] or None, for
    `earliest`: online (electronic publication), first (Europe PMC's first publication date), print and
    record (the day Europe PMC first indexed it, which for a work online ahead of print is often the
    earliest)."""
    return {'online': iso_date(r.get('electronicPublicationDate')), 'first': iso_date(r.get('firstPublicationDate')),
            'print': iso_date((r.get('journalInfo') or {}).get('printPublicationDate')),
            'record': iso_date(r.get('firstIndexDate'))}


def work_dates_pubmed(s):
    """The dates of a work from its PubMed summary, as `work_dates`: online (epubdate), print (pubdate)
    and record (the day the record entered PubMed, its entrez date). Received and accepted dates are
    not dates the work was public, and are left out."""
    entrez = [h.get('date') for h in s.get('history', []) if h.get('pubstatus') == 'entrez']
    return {'online': iso_date(s.get('epubdate')), 'print': iso_date(s.get('pubdate')),
            'record': iso_date(entrez[0] if entrez else None)}


def cut(works, cutoff):
    """Found works split at a cutoff day: (kept, left_out). A work is dated by the earliest of its
    `dates`; it is left out when that date is after the cutoff, and kept otherwise, marked
    `cutoff: {by, date, before}`, before null when it has no date or one (a year, a month) that contains
    the cutoff: such a work is not known to be later, and is not dropped unseen. left_out names each
    work dropped with the date that dropped it."""
    kept, left = [], []
    for w in works:
        by, d = earliest(w.get('dates') or {})
        span = day_span(d)
        before = None if span is None else True if span[1] <= cutoff else False if span[0] > cutoff else None
        mark = {'by': by, 'date': d, 'before': before}
        if before is False:
            left.append({'source_id': w['source_id'], 'title': w.get('title'), **mark})
        else:
            kept.append(dict(w, cutoff=mark))
    return kept, left


def bounded(works, extra, cutoff):
    """(works, extra) of a search, cut at the cutoff when there is one; left_out goes into the record."""
    if cutoff is None:
        return works, extra
    kept, left = cut(works, cutoff)
    return kept, dict(extra, left_out=left)


def epmc_until(query, cutoff):
    """A Europe PMC query narrowed to works it indexed or first published by the cutoff day."""
    return f'({query}) AND (FIRST_IDATE:[1000-01-01 TO {cutoff}] OR FIRST_PDATE:[1000-01-01 TO {cutoff}])'


def pubmed_until(term, cutoff):
    """A PubMed term narrowed to records entered (EDAT) or published (PDAT) by the cutoff day."""
    t = cutoff.replace('-', '/')
    return f'({term}) AND ("1000/01/01"[EDAT] : "{t}"[EDAT] OR "1000/01/01"[PDAT] : "{t}"[PDAT])'


def trial_record(study):
    """What the kit records of a ClinicalTrials.gov study: identifiers, title, status, phases, the
    planned or actual dates with their type, conditions, interventions by type and name, and primary
    outcomes by measure and time frame, with the record's own dates (registered, results posted, last
    updated). No descriptions: the registry text is the sponsor's."""
    ps = study.get('protocolSection', {})
    ident, st, design = ps.get('identificationModule', {}), ps.get('statusModule', {}), ps.get('designModule', {})
    posted = lambda key: (st.get(key) or {}).get('date')  # noqa: E731
    return {'nct': ident.get('nctId'), 'aliases': ident.get('nctIdAliases', []), 'title': ident.get('briefTitle'),
            'status': st.get('overallStatus'), 'status_verified': st.get('statusVerifiedDate'),
            'phases': design.get('phases'), 'study_type': design.get('studyType'), 'enrollment': design.get('enrollmentInfo'),
            'start': st.get('startDateStruct'), 'primary_completion': st.get('primaryCompletionDateStruct'),
            'completion': st.get('completionDateStruct'),
            'conditions': ps.get('conditionsModule', {}).get('conditions'),
            'interventions': [{'type': i.get('type'), 'name': i.get('name')}
                              for i in ps.get('armsInterventionsModule', {}).get('interventions', [])] or None,
            'primary_outcomes': [{'measure': o.get('measure'), 'time_frame': o.get('timeFrame')}
                                 for o in ps.get('outcomesModule', {}).get('primaryOutcomes', [])] or None,
            'has_results': study.get('hasResults'),
            'dates': {'registered': posted('studyFirstPostDateStruct'), 'results': posted('resultsFirstPostDateStruct'),
                      'last_update': posted('lastUpdatePostDateStruct')}}


def trial_as_of(t, cutoff):
    """A trial record as known on the cutoff day. The registry's API gives the current version only. A
    record last updated by the cutoff is the version of that day, and every field stands; a record
    updated later may have changed, and each field that changes with time (TRIAL_CHANGING) is null,
    with the reason and the record's last update in `as_of` (search.as_of decides). A trial registered
    after the cutoff was not known: `registered` is false and nothing stands. Results count only when
    first posted by the cutoff."""
    cutoff_day(cutoff)
    reg = day_span(t['dates']['registered'])
    registered = None if reg is None else True if reg[1] <= cutoff else False if reg[0] > cutoff else None
    decision = as_of(True, None, cutoff, t['dates']['last_update'] if registered else None)
    out = dict(t, **{k: t[k] if decision['value'] else None for k in TRIAL_CHANGING})
    res = day_span(t['dates']['results'])
    out['has_results'] = (False if not t.get('has_results') and decision['value'] else
                          None if res is None or res[0] <= cutoff < res[1] else res[1] <= cutoff)
    out['as_of'] = {'registered': registered, **{k: decision[k] for k in ('release', 'cutoff', 'basis', 'reason')}}
    return out


def work_openalex(w):
    """A found work from an OpenAlex record. The licence is OpenAlex's reading of the work's primary
    location, as given. Its only date is the publication date: OpenAlex's record dates are those of its
    own rebuilds, not of the day the work became known."""
    ids = w.get('ids') or {}
    tail = lambda u: u.rsplit('/', 1)[-1] if u else None  # noqa: E731
    doi = (w.get('doi') or '').replace('https://doi.org/', '') or None
    licence = (w.get('primary_location') or {}).get('license')
    return {'source_id': f'DOI:{doi}' if doi else f"OA:{tail(w.get('id'))}", 'pmid': tail(ids.get('pmid')),
            'pmcid': tail(ids.get('pmcid')), 'doi': doi, 'title': w.get('title'),
            'year': str(w['publication_year']) if w.get('publication_year') else None, 'type': w.get('type'),
            'licence': licence, 'licence_from': 'openalex primary_location license' if licence else None,
            'dates': {'first': iso_date(w.get('publication_date'))}}


def work_epmc(r):
    """A found work from a Europe PMC record: identifiers, title, type and the licence the record states.
    The licence is Europe PMC's own field, as given; a record without one has none."""
    types = (r.get('pubTypeList') or {}).get('pubType') or r.get('pubType') or []
    return {'source_id': f"{r.get('source')}:{r.get('id')}", 'pmid': r.get('pmid'), 'pmcid': r.get('pmcid'),
            'doi': r.get('doi'), 'title': r.get('title'), 'year': r.get('pubYear'),
            'type': '; '.join(types) if isinstance(types, list) else types,
            'licence': r.get('license'), 'licence_from': 'europepmc license field' if r.get('license') else None,
            'dates': work_dates(r)}


def work_pubmed(s):
    """A found work from a PubMed summary. PubMed states no licence."""
    ids = {a['idtype']: a['value'] for a in s.get('articleids', [])}
    return {'source_id': f"MED:{s.get('uid')}", 'pmid': s.get('uid'), 'pmcid': ids.get('pmc'),
            'doi': ids.get('doi'), 'title': s.get('title'), 'year': (s.get('pubdate') or '')[:4] or None,
            'type': '; '.join(s.get('pubtype', [])), 'licence': None, 'licence_from': None,
            'dates': work_dates_pubmed(s)}


# -- report ----------------------------------------------------------------------------------------

def read_log(workdir):
    path = Path(workdir) / LOG
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()] if path.exists() else []


# -- references in a submitted text -----------------------------------------------------------------

REF_LINK = re.compile(r'\[([^\]]+)\]\((https?://[^)\s]+)\)')
REF_ID_IN_URL = (('pmcid', re.compile(r'/(PMC\d+)', re.I)), ('pmid', re.compile(r'pubmed\.ncbi\.nlm\.nih\.gov/(\d+)')),
                 ('doi', re.compile(r'doi\.org/(10\.\d{4,9}/[^\s?#]+)')))
REF_BARE = (('doi', re.compile(r'(?<![/\w])(10\.\d{4,9}/[^\s)\]>"]+)')), ('pmid', re.compile(r'\bPMID:?\s*(\d{4,9})\b', re.I)),
            ('pmcid', re.compile(r'(?<![/\w])(PMC\d{4,9})\b')))
AUTHOR_YEAR = re.compile(r"\b([A-Z][\w'-]+)(?: et al\.?| and [A-Z][\w'-]+| и соавт\.?)?,\s*(?:\*([^*]+)\*,\s*)?((?:19|20)\d{2})\b")
# A numbered reference list, as a blog or a preprint ends: a heading "References", then entries
# "12. Brembs B (1996) Chaos, cheating and cooperation. Oikos 76: 14-24.", cited in the text as [12],
# [3,4] or [62-64].
REF_HEADING = re.compile(r'^\s*(?:references|literature cited|bibliography|литература|список литературы)\s*:?\s*$', re.I)
REF_ENTRY = re.compile(r'^\s*\[?(\d{1,3})[.\]]\s+(.+)$', re.S)
REF_PARTS = re.compile(r"^(?P<authors>[^()]+?)\s*\((?P<year>(?:19|20)\d{2})[^)]*\)\.?\s*(?P<title>.+?[.?!])(?:\s+(?P<rest>.*))?$", re.S)
CITE_MARK = re.compile(r'\[(\d{1,3}(?:\s*[-–,]\s*\d{1,3})*)\]')


def cited_numbers(mark):
    """The reference numbers of an in-text mark's inside: "3,4" or "62-64"."""
    out = []
    for part in re.split(r'\s*,\s*', mark):
        ends = [int(x) for x in re.split(r'\s*[-–]\s*', part)]
        lo, hi = ends[0], ends[-1]
        out += list(range(lo, hi + 1)) if 0 < hi - lo < 50 else sorted({lo, hi})
    return out


def numbered_references(paras):
    """The entries of a numbered reference list in paras (1-based paragraph numbers), each with what it
    claims and the paragraphs that cite it by number; and the set of list paragraphs. An entry broken
    over two paragraphs is joined; two paragraphs in a row that are not entries end the list."""
    start = next((n for n, p in enumerate(paras, 1) if REF_HEADING.match(p)), None)
    if start is None:
        return [], set()
    entries, listed, misses = [], set(), 0
    for n in range(start + 1, len(paras) + 1):
        m = REF_ENTRY.match(paras[n - 1])
        if m:
            entries.append({'number': int(m.group(1)), 'paragraph': n, 'text': paras[n - 1].strip(), 'body': m.group(2)})
            listed.add(n)
            misses = 0
        elif entries and misses == 0:
            entries[-1]['body'] += ' ' + paras[n - 1].strip()
            listed.add(n)
            misses = 1
        else:
            break
    cites = {}
    for n, p in enumerate(paras[:start - 1], 1):
        for m in CITE_MARK.finditer(p):
            for k in cited_numbers(m.group(1)):
                cites.setdefault(k, [])
                if n not in cites[k]:
                    cites[k].append(n)
    out = []
    for e in entries:
        body = ' '.join(e['body'].split())
        ids = {kind: rx.search(body).group(1) for kind, rx in REF_BARE if rx.search(body)}
        parts = REF_PARTS.match(body)
        claimed = {}
        if parts:
            first = surname(parts.group('authors').split(',')[0])
            claimed = {'first_author': first, 'year': parts.group('year'),
                       'title': parts.group('title').rstrip('.').strip()}
        out.append({'paragraph': e['paragraph'], 'text': e['text'][:300], 'url': None, 'ids': ids, 'claimed': claimed,
                    'number': e['number'], 'cited_in': cites.get(e['number'], [])})
    return out, listed


def references_in(text):
    """The references of a text, one per Markdown link or bare identifier, with the paragraph (split on
    blank lines, as SubmittedText splits) and what the reference claims: title (an emphasised link
    text), first author, journal and year (an "Author et al., *Journal*, year" link text)."""
    paras = [p for p in re.split(r'\n[ \t]*\n', text.replace('\r\n', '\n')) if p.strip()]
    out, listed = numbered_references(paras)
    for n, para in enumerate(paras, 1):
        if n in listed:
            continue
        spans = []
        for m in REF_LINK.finditer(para):
            label, url = m.group(1), m.group(2)
            ids = {k: rx.search(url).group(1) for k, rx in REF_ID_IN_URL if rx.search(url)}
            claimed = {}
            ay = AUTHOR_YEAR.search(label)
            if ay:
                claimed = {'first_author': ay.group(1), 'year': ay.group(3), **({'journal': ay.group(2)} if ay.group(2) else {})}
            else:
                claimed['title'] = label.strip('*_ ').strip()
            out.append({'paragraph': n, 'text': m.group(0), 'url': url, 'ids': ids, 'claimed': claimed})
            spans.append(m.span())
        for kind, rx in REF_BARE:
            for m in rx.finditer(para):
                if any(a <= m.start() < b for a, b in spans):
                    continue
                out.append({'paragraph': n, 'text': m.group(0), 'url': None, 'ids': {kind: m.group(1)}, 'claimed': {}})
                spans.append(m.span())
        for m in AUTHOR_YEAR.finditer(para):
            if any(a <= m.start() < b for a, b in spans):
                continue
            out.append({'paragraph': n, 'text': m.group(0), 'url': None, 'ids': {},
                        'claimed': {'first_author': m.group(1), 'year': m.group(3),
                                    **({'journal': m.group(2)} if m.group(2) else {})}})
    return out


def record_of_epmc(r):
    """What a reference is compared with, from a Europe PMC record."""
    w = work_epmc(r)
    first = (r.get('authorString') or '').split(',')[0].strip()
    journal = ((r.get('journalInfo') or {}).get('journal') or {}).get('title') or r.get('journalTitle')
    return dict(w, first_author=surname(first) if first else None, journal=journal, catalogue='europepmc')


def surname(author):
    """The surname of "Surname INITIALS": all but the initials, so "de Ruyter van Steveninck RR" keeps
    its particles."""
    words = author.split()
    return ' '.join(words[:-1] if len(words) > 1 and words[-1].isupper() else words)


def record_of_crossref(m):
    first = next((a for a in m.get('author', []) if a.get('sequence') == 'first'), (m.get('author') or [{}])[0])
    year = date_of(m.get('issued') or m.get('published'))
    lic = [x.get('URL') for x in m.get('license', []) if x.get('content-version') in ('vor', 'unspecified')]
    return {'source_id': f"DOI:{m.get('DOI', '').lower()}", 'pmid': None, 'pmcid': None, 'doi': m.get('DOI'),
            'title': norm_title(' '.join(m.get('title') or [])) or None, 'year': year[:4] if year else None,
            'type': m.get('type'), 'licence': lic[0] if lic else None,
            'licence_from': 'crossref license (vor)' if lic else None, 'first_author': first.get('family'),
            'journal': (m.get('container-title') or [None])[0], 'catalogue': 'crossref'}


def norm_title(t):
    t = re.sub(r'<[^>]+>|[*_]', '', t or '')
    return re.sub(r'\s+', ' ', t).strip().rstrip('.').strip()


def same_text(a, b, ratio=0.9):
    a, b = (re.sub(r'[^\w ]', '', norm_title(x).lower()) for x in (a, b))
    return a == b or difflib.SequenceMatcher(None, a, b).ratio() >= ratio


def folded(name):
    """A name without its diacritics, lower case: "Jabłoński" and "Jablonski" are one author."""
    name = unicodedata.normalize('NFKD', norm_title(name or '')).translate(str.maketrans('łŁøØđĐß’', "lLoOdDs'"))
    return ''.join(c for c in name if not unicodedata.combining(c)).lower()


def years_of(record):
    """Every year a record dates the work by: its year, and its online, print and other dates."""
    years = {str(record.get('year'))} if record.get('year') else set()
    return years | {str(d)[:4] for d in (record.get('dates') or {}).values() if d}


def title_cut(claimed, have):
    """A title read from a reference list up to its question or exclamation mark, where the record's
    title goes on with a subtitle: the reader could not tell where the title ended."""
    a, b = (re.sub(r'[^\w ]', '', norm_title(x).lower()) for x in (claimed or '', have or ''))
    return bool(a) and norm_title(claimed)[-1:] in '?!' and b.startswith(a)


def compare(claimed, record):
    """("match" | "mismatch" | "not_checked", differences): each thing the reference claims of the work
    against the record. A thing the reference does not claim is not checked."""
    diffs, checked = [], 0
    for k in ('title', 'first_author', 'year', 'journal'):
        if not claimed.get(k):
            continue
        checked += 1
        have = record.get(k)
        if k == 'year':
            ok = str(claimed[k]) in years_of(record)
        elif k == 'first_author':
            ok = bool(have) and folded(have) == folded(claimed[k])
        elif k == 'journal':
            ok = bool(have) and (same_text(have, claimed[k], 0.8) or norm_title(claimed[k]).lower() in norm_title(have).lower())
        else:
            ok = bool(have) and (same_text(have, claimed[k]) or title_cut(claimed[k], have))
        if not ok:
            diffs.append({'field': k, 'reference': claimed[k], 'record': have})
    if not checked:
        return 'not_checked', []
    return ('mismatch' if diffs else 'match'), diffs


def refs_text(records):
    """The reference lines of the conversion report."""
    lines = ['References in the submitted text (search.py check-refs; relevance is a reader\'s judgement):']
    for r in records:
        if r['outcome'] != 'ok':
            lines.append(f"  p{r['ask']['paragraph']} {r['ask']['id']!r}: check FAILED ({r['error']})")
            continue
        diff = '; '.join(f"{d['field']}: {d['reference']!r} vs {d['record']!r}" for d in r['differences'])
        lines.append(f"  p{r['ask']['paragraph']} {r['ask']['id'][:90]!r}: exists {r['exists']}"
                     f"{' by ' + r['found_by'] if r.get('found_by') else ''}, matches {r['matches']}"
                     f"{' (' + diff + ')' if diff else ''}, relevance {r['relevance']}")
    return '\n'.join(lines)


# -- relevance of a reference: a separate checker ------------------------------------------------------

def paragraphs_of(text):
    """The paragraphs of a submitted text as references_in numbers them (split on blank lines)."""
    return [p for p in re.split(r'\n[ \t]*\n', text.replace('\r\n', '\n')) if p.strip()]


def where_to_read(record):
    """Addresses where a checker can read a verified work: its Europe PMC page (abstract), PubMed and DOI."""
    out = []
    src, _, ident = (record.get('source_id') or '').partition(':')
    if src and ident:
        out.append(f'https://europepmc.org/article/{src}/{ident}')
    if record.get('pmcid'):
        out.append(f"https://pmc.ncbi.nlm.nih.gov/articles/{record['pmcid']}/")
    if record.get('pmid'):
        out.append(f"https://pubmed.ncbi.nlm.nih.gov/{record['pmid']}/")
    if record.get('doi'):
        out.append(f"https://doi.org/{record['doi']}")
    return out


def relevance_input(text, workdir, recheck=None):
    """The input of the relevance checker for a text check-refs has checked in workdir: one item per
    reference that exists and matches, with the paragraph that cites it, the work, and where to read it.
    The other references are not sent: an unverified reference is never a source, and its relevance stays
    not_assessed. The input holds the submitted text's paragraphs, not the works' text.

    With recheck (an outcome), only the items whose latest verdict is that outcome are sent again, to be
    read in the full text: each with the open places a logged `text` call found for its work. An item
    whose work has no open full text is not sent; its verdict stands as it was read."""
    paras = paragraphs_of(text)
    checks = [r for r in read_log(workdir) if r['tool'] == 'check_ref']
    if not checks:
        raise SearchError('no check_ref in the log: run check-refs on the text first')
    latest = {}
    for r in checks:
        latest[(r['ask']['paragraph'], r['ask']['id'])] = r
    items, not_sent = [], []
    for (n, ref), r in sorted(latest.items(), key=lambda x: (x[0][0], x[0][1])):
        if n > len(paras) or ref not in paras[n - 1]:
            raise SearchError(f'paragraph {n}: the logged reference {ref[:60]!r} is not in this text; '
                              'run check-refs on it')
        state = r.get('exists') if r['outcome'] == 'ok' else 'check_failed'
        if state != 'verified' or r.get('matches') != 'match':
            not_sent.append({'check': r.get('call_id'), 'paragraph': n, 'reference': ref,
                             'why': state if state != 'verified' else f"matches {r.get('matches')}"})
            continue
        rec = r['record']
        # An entry of a numbered list is judged where the text cites it by number, once per paragraph.
        citing = r.get('reference', {}).get('cited_in') if 'number' in r.get('reference', {}) else [n]
        if not citing:
            not_sent.append({'check': r.get('call_id'), 'paragraph': n, 'reference': ref,
                             'why': 'listed, never cited in the text'})
        for c in citing or []:
            items.append({'item': len(items) + 1, 'check': r.get('call_id'), 'paragraph': c, 'reference': ref,
                          **({'number': r['reference']['number']} if c != n else {}),
                          'cited_in': paras[c - 1], 'cited_in_sha256': sha256(paras[c - 1].encode()),
                          'work': {k: rec.get(k) for k in ('source_id', 'pmid', 'pmcid', 'doi', 'title', 'year')},
                          'read_at': where_to_read(rec)})
    out = {'text_sha256': sha256(text.encode()), 'prompt': RELEVANCE_PROMPT.name,
           'prompt_sha256': sha256(RELEVANCE_PROMPT.read_bytes()), 'outcomes': sorted(RELEVANCE),
           'basis': 'abstract_first', 'items': items, 'not_sent': not_sent}
    return out if recheck is None else recheck_input(out, workdir, recheck)


def latest_relevance(records):
    """{(check call, paragraph): the latest relevance record}: a later reading replaces an earlier one,
    except that a later failure to read the work (not_retrievable, a full text behind a block) leaves
    the earlier reading standing."""
    out = {}
    for r in records:
        if r['tool'] == 'relevance' and r['outcome'] == 'ok':
            key = (r['ask'].get('check'), r['ask']['paragraph'])
            if r['relevance'] == 'not_retrievable' and key in out and out[key]['relevance'] != 'not_retrievable':
                continue
            out[key] = r
    return out


def recheck_input(inp, workdir, outcome):
    """The items of inp whose latest verdict is outcome and whose work has open full text, renumbered,
    each with the places of its full text (from the logged `text` calls)."""
    if outcome not in RELEVANCE:
        raise SearchError(f'recheck: one of {sorted(RELEVANCE)}')
    records = read_log(workdir)
    latest = latest_relevance(records)
    places = {}
    for r in records:
        if r['tool'] == 'text' and r['outcome'] == 'ok' and r.get('places'):
            places[str(r['ask']['id']).lower()] = [{k: p.get(k) for k in ('kind', 'url', 'licence')} for p in r['places']]
    items, not_sent = [], list(inp['not_sent'])
    for i in inp['items']:
        last = latest.get((i['check'], i['paragraph']))
        if last is None or last['relevance'] != outcome:
            continue
        w = i['work']
        found = next((places[str(w[k]).lower()] for k in ('pmcid', 'pmid', 'doi') if w.get(k) and
                      str(w[k]).lower() in places), None)
        if not found:
            not_sent.append({'check': i['check'], 'paragraph': i['paragraph'], 'reference': i['reference'],
                             'why': 'no open full text (search.py text found none, or was not run)'})
            continue
        # The earlier verdict is not shown: the checker reads the work afresh.
        items.append(dict(i, item=len(items) + 1, full_text=found))
    return dict(inp, basis='full_text', items=items, not_sent=not_sent)


def relevance_merge(text, inp, verdicts, extractor, workdir, extractor_model=None):
    """Log the checker's verdicts on a relevance input, one record per item. Refused, with nothing
    logged, when: the checker is unnamed or is the extractor; the text or any cited paragraph is not what
    the input showed; an item has no verdict, or a verdict names no item; an outcome is outside RELEVANCE;
    a locator is blank; a verdict carries anything but item, cited_in_sha256, outcome and locator (no
    text of the work enters the log)."""
    checker = verdicts.get('checker') or {}
    if not (checker.get('name') or '').strip():
        raise SearchError('checker: the name of the separate checker is required')
    if not (extractor or '').strip() or checker['name'].strip() == extractor.strip():
        raise SearchError('checker: the checker must not be the extractor of the card')
    if sha256(text.encode()) != inp['text_sha256']:
        raise SearchError('the text is not the one the input was built from')
    paras = paragraphs_of(text)
    items = {i['item']: i for i in inp['items']}
    got = {}
    for v in verdicts.get('verdicts', []):
        extra = set(v) - {'item', 'cited_in_sha256', 'outcome', 'locator'}
        if extra:
            raise SearchError(f"item {v.get('item')}: only item, cited_in_sha256, outcome and locator are kept, "
                              f'not {sorted(extra)}')
        i = items.get(v.get('item'))
        if i is None:
            raise SearchError(f"verdict for item {v.get('item')}, which the input does not have")
        if v.get('cited_in_sha256') != i['cited_in_sha256'] or sha256(paras[i['paragraph'] - 1].encode()) != \
                i['cited_in_sha256']:
            raise SearchError(f"item {i['item']}: the verdict is not on the paragraph the input showed")
        if v.get('outcome') not in RELEVANCE:
            raise SearchError(f"item {i['item']}: outcome one of {sorted(RELEVANCE)}")
        if not (v.get('locator') or '').strip():
            raise SearchError(f"item {i['item']}: locator: where in the work the checker read it, or tried to")
        got[i['item']] = v
    missing = sorted(set(items) - set(got))
    if missing:
        raise SearchError(f'items without a verdict: {missing}')
    s, at = Searcher(workdir), now()
    who = {'name': checker['name'].strip(), 'model': checker.get('model')}
    # A separate run of the same model is allowed, as for entailment, and said in the report.
    same_model = bool(who['model'] and who['model'] == extractor_model)
    out = []
    for n, i in sorted(items.items()):
        v = got[n]
        out.append(s.log({'call_id': uuid.uuid4().hex[:12], 'tool': 'relevance', 'started_at': at,
                          'finished_at': at, 'kit': f'ohf-extractor/{VERSION}', 'outcome': 'ok',
                          'ask': {'id': i['reference'], 'paragraph': i['paragraph'], 'check': i['check'],
                                  'cited_in_sha256': i['cited_in_sha256']},
                          'relevance': v['outcome'], 'locator': v['locator'].strip(), 'work': i['work'],
                          'checker': who, 'extractor': extractor.strip(), 'extractor_model': extractor_model,
                          'same_model': same_model, 'prompt_sha256': inp['prompt_sha256'],
                          'basis': inp.get('basis', 'abstract_first'),
                          'responses': [], 'hit_count': None, 'found': 0, 'works': []}))
    return out


# -- similar hypotheses among accepted cards -------------------------------------------------------

WORD = re.compile(r'[^\W_][\w\-]{2,}')
# Words too common in hypothesis cards to say two of them are alike.
COMMON = set('''the and that this with from for are was were which have has had not but its their than
also into such these those been being can may might could would should will more most less other
some only very both each between within while when where what how there then they them our your
using used use shown show shows study studies result results effect effects increase increased
decrease decreased level levels model models hypothesis cell cells data based level human humans mice
mouse even article journal doi http https www org pmc pubmed ncbi nlm nih biology research paper это что как для при или его она они так также который которые если чтобы может быть была было
были этот эта эти того этой этого более менее только уже ещё нет'''.split())


def terms_of(text):
    """The distinctive words of a text, lower case, a plural s dropped from long Latin words."""
    out = set()
    text = re.sub(r'https?://\S+', ' ', REF_LINK.sub(lambda m: m.group(1), text))
    for w in WORD.findall(text.lower()):
        w = w.strip('-')
        if len(w) > 4 and w.isascii() and w.endswith('ies'):
            w = w[:-3] + 'y'
        elif len(w) > 4 and w.endswith('s') and w.isascii() and not w.endswith('ss'):
            w = w[:-1]
        if len(w) >= 3 and w not in COMMON and not w.isdigit():
            out.add(w)
    return out


def card_text(card):
    """The words a card states: every string value of its author and added layers, and its topics."""
    parts = []

    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if k in ('value', 'summary', 'statement', 'text') and isinstance(v, str):
                    parts.append(v)
                else:
                    walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    if 'author' not in card:  # an arena hypothesis record: statement, mechanism, predictions at the top
        parts += [card[k] for k in ('statement', 'mechanism') if isinstance(card.get(k), str)]
        walk(card.get('predictions', []))
    walk(card.get('author', {}).get('layers', {}))
    walk(card.get('added', {}).get('layers', {}))
    parts += [str(t) for t in (card.get('facets') or {}).get('topic', [])]
    return '\n'.join(parts)


def card_works(card):
    """The works a card rests on: its main source and the sources it adds, as identifiers."""
    if 'author' not in card:
        return ids_in(json.dumps(card.get('sources') or card.get('provenance') or ''))
    main, cited = card_sources(card)
    return main | set(cited)


def similar_cards(text, cards, limit=10):
    """Accepted cards that may state the same hypothesis as a submitted text, best first, each with why:
    the distinctive words both state (rarest among the cards first) and the works both cite.

    The score is the cosine of the two texts' words, each weighted by how few cards state it. A long
    text shares common words with every card, so a card is a candidate only when it stands out: twice
    the median score of all cards and at least two shared words, or a work both cite. The reference
    list of the text is left out. A candidate is for a reader to judge; nothing is filtered or refused
    here. Words in another language than the card's are not matched: a hypothesis translated with no
    shared term or work is missed."""
    paras = paragraphs_of(text)
    _, listed = numbered_references(paras)
    body = '\n\n'.join(p for n, p in enumerate(paras, 1) if n not in listed)
    mine, my_works = terms_of(body), ids_in(text)
    bags = [(c, terms_of(card_text(c)), card_works(c)) for c in cards]
    df = {}
    for _, t, _ in bags:
        for w in t:
            df[w] = df.get(w, 0) + 1

    def weight(w):
        return 1 + len(bags) / df.get(w, 1)

    def norm(words):
        return math.sqrt(sum(weight(w) ** 2 for w in words)) or 1.0
    scored = []
    for c, t, works in bags:
        shared = sorted(mine & t, key=lambda w: (df[w], w))
        scored.append((c, round(sum(weight(w) ** 2 for w in shared) / (norm(mine) * norm(t)), 4), shared,
                       sorted(my_works & works)))
    ranked_scores = sorted(x[1] for x in scored)
    median = ranked_scores[len(ranked_scores) // 2] if ranked_scores else 0.0
    out = []
    for c, score, shared, both in scored:
        if both or len(shared) >= 2 and score > 0 and score >= 2 * median:
            out.append({'card': c.get('id'), 'version': c.get('version'), 'content_hash': c.get('content_hash'),
                        'score': score, 'median': median, 'shared_terms': shared[:15], 'shared_works': both})
    out.sort(key=lambda x: (-x['score'], str(x['card'])))
    return out[:limit]


# -- known result or duplicate ---------------------------------------------------------------------

# What a separate checker may say of one work found for a submitted hypothesis (references/known-result.md).
KNOWN = {'tests_supports': 'the work reports its own test of the claim (experiment, trial, observation or '
                           'analysis that could have come out against it), and the result agrees with it',
         'tests_refutes': 'the work reports its own test of the claim, and the result disagrees with it',
         'tests_mixed': 'the work reports its own test of the claim, and the result agrees in part or in some '
                        'conditions only',
         'proposes_or_discusses': 'the work states, proposes, reviews or argues the claim with no test of its own',
         'unrelated': 'the work is not about this claim',
         'not_retrievable': 'the checker could not read the work'}
TESTS = ('tests_supports', 'tests_refutes', 'tests_mixed')
# A decisive test: the result agrees or disagrees. tests_mixed is a test with no outcome either way.
DECISIVE = ('tests_supports', 'tests_refutes')
# How the population a test enrolled stands to the claim's: only a test of the claim's own population (or of
# a subgroup of a wider one, reported with its result, which is that population) is decisive.
POPULATION_MATCH = {'same': "the claim's population, or a reported subgroup of a wider one that is",
                    'narrower': "a part of the claim's population only: a test without an outcome for the claim",
                    'broader': "a wider population with no reported subgroup of the claim's: context, not a test",
                    'not_comparable': "a population the claim's cannot be compared with: context, not a test"}
# How precise a test is, each stated by the reader with a passage of the work, or not_stated: {field: (the
# passage's field, the values)}. A decisive test of the claim's population also needs a pre-specified primary
# outcome and a randomized or experimental design: an observational association is a test, never a decisive
# one, whichever way it points. A test stopped for operational reasons (funding, slow enrolment, organisation)
# never decides either way, not even a support whose interval excludes none. A refuting test then decides: a
# null result never excludes no effect, and a stop for futility or harm is made by a data monitoring committee
# on pre-set boundaries, while an abstract that does not say why it stopped is not an under-enrolment. A
# supporting test decides only with an effect whose interval excludes none: a stop on completion or for
# efficacy does not decide a support by itself, and an efficacy stop whose interval includes none is not
# decisive.
YES_NO = ('yes', 'no', 'not_stated')
STOP_REASONS = ('completed', 'futility', 'harm', 'efficacy', 'operational', 'not_stated')
DESIGNS = ('randomized', 'experimental', 'observational', 'not_stated')
DECISIVE_DESIGNS = ('randomized', 'experimental')
# A test the work itself calls underpowered (whatever its stop) never refutes decisively; underpowered_stated is
# yes only with its passage, and no when the work does not say so. It is a direct statement about power or
# enrolment (underpowered, short of its planned size, power not reached), never a hedge on a null result
# ("may be due to limited numbers").
PRECISION = {'design': ('design_quote', DESIGNS),
             'primary_prespecified': ('primary_quote', YES_NO), 'stop_reason': ('stop_quote', STOP_REASONS),
             'effect_excludes_null': ('effect_quote', YES_NO), 'underpowered_stated': ('underpowered_quote', ('yes', 'no'))}
# A claim the kit could not find in the work: never decisive, whichever way its verdict points.
UNVERIFIED_BLOCKS = ('stop_reason', 'underpowered_stated')
DECIDES = {'tests_refutes': ('completed', 'futility', 'harm', 'not_stated')}
# What a checker may say of one candidate card.
CARD_RELATION = {'same_claim': 'the card states the same claim: same cause, effect, direction, system and context',
                 'variant': 'the same claim in another context (species, sex, age, dose, regimen, measure)',
                 'competitor': 'another explanation of the same thing',
                 'related': 'shares a topic or a mechanism, not the claim',
                 'unrelated': 'not about this claim'}
KNOWN_PROMPT = SKILL / 'references' / 'known-result.md'
KNOWN_SCHEMA = 'ohf-extractor/known-result'
KNOWN_SCHEMA_VERSION = 1
QUOTE_WORDS = 25
CARD_SCORE = {'metric': 'cosine of the distinctive words of the text and the card, each weighted by how few '
                        'cards of the pool state it (similar_cards)',
              'scale': '0 to 1; a ranking of candidates, not a probability that the card states the claim'}


def card_statement(card):
    """What a checker reads of a candidate card: its statement, explanandum and mechanism."""
    if 'author' not in card:
        return {k: card[k] for k in ('statement', 'mechanism') if isinstance(card.get(k), str)}
    layers = card['author'].get('layers', {})
    core, mech = layers.get('core', {}), layers.get('mechanism', {})
    out = {k: core[k]['value'] for k in ('statement', 'explanandum') if isinstance(core.get(k), dict)}
    if isinstance(mech.get('summary'), dict):
        out['mechanism'] = mech['summary']['value']
    return out


def epmc_text(record):
    """The title and abstract of a Europe PMC core record, as a checker reads them and as a quote is
    checked against them: tags removed, whitespace collapsed."""
    def clean(t):
        return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', t or '')).strip()
    return {'title': clean(record.get('title')), 'abstract': clean(record.get('abstractText'))}


def pub_types(record):
    """The publication types a Europe PMC record states, as given."""
    types = (record.get('pubTypeList') or {}).get('pubType') or []
    return [types] if isinstance(types, str) else list(types)


def secondary(record):
    """The publication types of a record that make it a work with no test of its own (SECONDARY)."""
    return sorted({t for t in pub_types(record) if t.lower().replace('-', ' ').strip() in SECONDARY})


def kept_records(workdir, call):
    """The Europe PMC core records in the responses a logged call kept, by source_id, each with the
    sha256 of the response it came from (`_response`)."""
    out = {}
    for resp in call['responses']:
        body = Path(workdir) / RESPONSES / (resp['sha256'].split(':')[1] + '.body')
        if sha256(body.read_bytes()) != resp['sha256']:
            raise SearchError(f'{body.name}: the kept response is not the one the log names')
        for r in json.loads(body.read_text()).get('resultList', {}).get('result', []):
            out[f"{r.get('source')}:{r.get('id')}"] = dict(r, _response=resp['sha256'])
    return out


def known_input(text, cards, workdir, per_query=10, max_works=60, literature=True, searcher=None):
    """The input of the known-result checker for a submitted hypothesis: the candidate cards (similar_cards
    over the pool given) and the works the literature searches logged in workdir found, each work with its
    title and abstract from its Europe PMC record, fetched once and kept by hash so that a quote can be
    checked against the same bytes. The searches are the caller's (search.py literature, run first); this
    takes the first per_query works of each successful search, in rank order, at most max_works in all;
    the first RCT_FIRST of each search of the publication-type trial probe come before the others.
    The log record holds identifiers only; the abstracts are in the input, for the checker. With
    literature=False only the cards are compared (completion 'cards_only': the result can then be a
    duplicate, never new or a known result)."""
    s = searcher or Searcher(workdir)
    lit = [r for r in read_log(workdir) if r['tool'] == 'literature'] if literature else []
    if literature and not lit:
        raise SearchError('no literature search in the log: run search.py literature with the queries first')
    order, seen = [], set()
    rct = [r for r in lit if r['ask'].get('probe') == 'rct']
    for records, depths in ((rct, RCT_FIRST), (lit, per_query)):
        for depth in range(depths):
            for r in records:
                if r['outcome'] == 'ok' and depth < len(r['works']):
                    w = r['works'][depth]
                    key = (w.get('doi') or '').lower() or w.get('pmid') or w.get('pmcid') or w['source_id']
                    if key not in seen and len(order) < max_works:
                        seen.add(key)
                        order.append(w)
    pairs = []
    for w in order:
        src, _, ident = w['source_id'].partition(':')
        pairs.append(('MED', w['pmid']) if w.get('pmid') else (src, ident) if src in ('MED', 'PMC', 'PPR', 'AGR', 'CBA',
                                                                                        'CTX', 'ETH', 'HIR', 'PAT')
                     else None)

    def run(responses):
        found = s.epmc_lookup([x for x in pairs if x], responses)
        return len(found), [work_epmc(r) for r in found.values()], {'service': 'Europe PMC REST search (core)'}
    call = s.call('known_works', {'ids': [list(x) if x else None for x in pairs]}, run) if literature else \
        {'outcome': 'ok', 'call_id': None}
    kept = kept_records(workdir, call) if literature and call['outcome'] == 'ok' else {}
    works = []
    for w, pair in zip(order, pairs):
        rec = kept.get(f'{pair[0]}:{pair[1]}') if pair else None
        item = {'item': len(works) + 1, 'found_by': w['source_id'],
                'work': {k: (rec or {}).get(k) or w.get(k) for k in ('pmid', 'pmcid', 'doi', 'title')},
                'date': (rec or {}).get('firstPublicationDate') or (rec or {}).get('pubYear') or w.get('year'),
                'licence': (rec or {}).get('license'), 'record_call': call['call_id']}
        if rec:
            item.update(epmc_text(rec), source_id=f'{pair[0]}:{pair[1]}', pub_types=pub_types(rec))
        else:
            item.update(title=w.get('title'), abstract=None, source_id=None, pub_types=[])
        works.append(item)
    sim = s.similar_cards(text, cards, limit=5)
    by_id = {(c.get('id'), c.get('version')): c for c in cards}
    cand = [{'item': n, 'card': c['card'], 'version': c['version'], 'content_hash': c['content_hash'],
             'file_sha256': by_id[(c['card'], c['version'])].get('_file_sha256'),
             'score': c['score'], 'shared_terms': c['shared_terms'][:8],
             'states': card_statement(by_id[(c['card'], c['version'])])}
            for n, c in enumerate(sim.get('candidates', []), 1)]
    failed = [r['call_id'] for r in lit if r['outcome'] != 'ok'] + ([] if call['outcome'] == 'ok' else [call['call_id']])
    completion = 'failed' if sim['outcome'] != 'ok' or literature and all(r['outcome'] != 'ok' for r in lit) else \
        'cards_only' if not literature else 'partial' if failed else 'complete'
    return {'schema': KNOWN_SCHEMA + '/input', 'schema_version': KNOWN_SCHEMA_VERSION,
            'text_sha256': sha256(text.encode()), 'text': text,
            'prompt': KNOWN_PROMPT.name, 'prompt_sha256': sha256(KNOWN_PROMPT.read_bytes()),
            'work_verdicts': sorted(KNOWN), 'card_relations': sorted(CARD_RELATION), 'quote_words': QUOTE_WORDS,
            'population_matches': sorted(POPULATION_MATCH),
            'precision': {f: list(values) for f, (_, values) in PRECISION.items()},
            'cards': cand, 'card_call': sim['call_id'], 'card_pool': len(cards), 'card_score': CARD_SCORE,
            'works': works,
            'searched': {'queries': [{'call_id': r['call_id'], 'query': r['ask']['query'], 'source': r['ask']['source'],
                                      'variant': r['ask'].get('variant'), 'probe': r['ask'].get('probe'),
                                      'outcome': r['outcome'],
                                      'hit_count': r['hit_count'], 'found': r['found']} for r in lit],
                         'works_read': len(works), 'per_query': per_query, 'max_works': max_works,
                         'rct_first': RCT_FIRST,
                         'cards_pool': len(cards), 'cards_candidates': len(cand),
                         'failed_calls': failed, 'completion': completion}}


def quote_in(quote, fields):
    """The name of the first of fields ({name: text}) of which quote, whitespace collapsed, is an exact
    passage (case as given), or None."""
    q = re.sub(r'\s+', ' ', quote or '').strip()
    return next((name for name, t in fields.items() if q and q in re.sub(r'\s+', ' ', t or '')), None)


def _verdict_sets(inp, reader):
    """Check one reader's verdicts against the input; {('work'|'card', item): verdict}. Refused on a
    structural fault: an unknown item, an outcome off the list, a field that is not kept."""
    works, cards = {w['item']: w for w in inp['works']}, {c['item']: c for c in inp['cards']}
    got = {}
    for kind, items, field, allowed, keep in (('work', works, 'verdict', KNOWN, {'item', 'verdict', 'quote', 'locator', 'population',
                                                                             'population_match', *PRECISION,
                                                                             *(q for q, _ in PRECISION.values())}),
                                             ('card', cards, 'relation', CARD_RELATION, {'item', 'relation', 'locator'})):
        for v in reader.get(kind + 's', []):
            extra = set(v) - keep
            if extra:
                raise SearchError(f"{kind} {v.get('item')}: only {sorted(keep)} are kept, not {sorted(extra)}")
            if v.get('item') not in items:
                raise SearchError(f"{kind} {v.get('item')}: the input has no such item")
            if v.get(field) not in allowed:
                raise SearchError(f"{kind} {v['item']}: {field} one of {sorted(allowed)}")
            if kind == 'work' and v.get('population_match') is not None and v['population_match'] not in POPULATION_MATCH:
                raise SearchError(f"work {v['item']}: population_match one of {sorted(POPULATION_MATCH)}")
            for f, (_, values) in PRECISION.items():
                if kind == 'work' and v.get(f) is not None and v[f] not in values:
                    raise SearchError(f"work {v['item']}: {f} one of {list(values)}")
            if (kind, v['item']) in got:
                raise SearchError(f"{kind} {v['item']}: two verdicts")
            got[(kind, v['item'])] = v
    need = {('work', i) for i in works} | {('card', i) for i in cards}
    missing = sorted(need - set(got))
    if missing:
        raise SearchError(f"{reader.get('checker', {}).get('name')}: no verdict on {missing}")
    return got


def passage_check(text, fields):
    """How a reader's passage (a quote, or a population's selection criterion) stands against a work's title and
    abstract (fields, as epmc_text gives them): (check, where), check one of missing, too_long, verified, not_found."""
    text = (text or '').strip() or None
    where = quote_in(text, fields) if fields and text else None
    return ('missing' if not text else 'too_long' if len(text.split()) > QUOTE_WORDS else
            'verified' if where else 'not_found'), where


def precision(v, fields):
    """A reader's precision of one test, each field one of its values: anything but not_stated (and, for
    underpowered_stated, anything but no) only with its passage found in the work's title or abstract
    (passage_check). A yes or no without it is not_stated; a stop reason or an underpowered yes without it is
    unverified, which never decides: read as not stated, a stop said to be operational, or a trial said to be
    underpowered, would let a refutation decide."""
    out = {}
    for f, (q, _) in PRECISION.items():
        silent = 'no' if f == 'underpowered_stated' else 'not_stated'
        said = v.get(f) or silent
        found = said == silent or passage_check(v.get(q), fields)[0] == 'verified'
        out[f] = said if found else 'unverified' if f in UNVERIFIED_BLOCKS else 'not_stated'
    return out


def precise(verdict, p):
    """Whether a test with this precision can decide: a randomized or experimental design, a pre-specified
    primary outcome, nothing the kit could not verify and no operational stop; then, for a refuting test, a stop
    reason that lets it decide (DECIDES) and no statement that it was underpowered, and for a supporting test an
    effect that excludes none, whatever its stop."""
    if p.get('primary_prespecified') != 'yes' or p.get('design') not in DECISIVE_DESIGNS or \
            p.get('stop_reason') == 'operational' or any(p.get(f) == 'unverified' for f in UNVERIFIED_BLOCKS):
        return False
    if verdict == 'tests_refutes':
        return p.get('stop_reason') in DECIDES[verdict] and p.get('underpowered_stated') != 'yes'
    return verdict == 'tests_supports' and p.get('effect_excludes_null') == 'yes'


def _kept_fields(inp, workdir):
    """{item: the title and abstract of each work as the kit fetched it (epmc_text of the kept record)}, None for
    a work with no kept record."""
    calls = {r['call_id']: r for r in read_log(workdir) if r['tool'] == 'known_works'}
    kept = {}
    for w in inp['works']:
        if w.get('source_id') and w['record_call'] in calls and w['record_call'] not in kept:
            kept[w['record_call']] = kept_records(workdir, calls[w['record_call']])
    out = {}
    for w in inp['works']:
        rec = kept.get(w['record_call'], {}).get(w.get('source_id')) if w.get('source_id') else None
        out[w['item']] = (rec, epmc_text(rec) if rec else None)
    return out


def known_check(inp, reader, workdir):
    """The passages of a reader's tests that known-merge would not verify, before the reader hands them in:
    [{item, field, check}], check one of missing, too_long, not_found (passage_check). A reader rewrites each one
    once, from the title or abstract, and hands in; nothing is logged, and a passage still listed is lost as
    known-merge says. Refused, as known-merge refuses, on a structural fault."""
    got, kept = _verdict_sets(inp, reader), _kept_fields(inp, workdir)
    out = []
    for (kind, item), v in sorted(got.items()):
        if kind != 'work' or v['verdict'] not in TESTS:
            continue
        fields = kept[item][1]
        asked = [('quote', v.get('quote')), ('population', v.get('population'))]
        for f, (q, _) in PRECISION.items():
            silent = 'no' if f == 'underpowered_stated' else 'not_stated'
            if (v.get(f) or silent) != silent:
                asked.append((q, v.get(q)))
        for field, passage in asked:
            check = passage_check(passage, fields)[0]
            if check != 'verified':
                out.append({'item': item, 'field': field, 'check': check})
    return out


def known_merge(text, inp, first, query_writer, workdir, second=None, query_writer_session=None):
    """Log a checker's verdicts on a known-result input and return the detector's result.

    `first` reads every work and card of the input; `second`, a reader independent of the first, reads them
    all too, so that it can see a test the first did not. Refused, with nothing logged, when a reader is unnamed, is
    the query writer, or the two readers are one; the text is not the input's; an item is unknown or
    unread; an outcome is off the list; a verdict carries other fields.

    A work is evidence when the first reader says tests_*, with a quote of at most QUOTE_WORDS words that is
    an exact passage of the work's title or abstract as the kit fetched it (the bytes kept by hash). A quote
    not found there, or too long, is logged as such and is not evidence. A work whose record states a
    publication type of SECONDARY (a review, meta-analysis, comment, protocol) is never evidence: a tests_*
    on it is listed as context. A test also needs a population: a selection criterion found in the work the
    same way, and its match to the claim's (POPULATION_MATCH); a broader or not comparable one is context,
    a narrower one a test without an outcome for the claim, and only a test of the same population is
    decisive. A decisive test must also be precise for both readers (PRECISION, each stated with a passage
    found in the work): a randomized or experimental design, a pre-specified primary outcome and no operational
    stop; for a supporting test, also an effect that excludes none, whatever its stop. An imprecise
    test has no outcome either way. A card is evidence when the first reader says same_claim. With a second
    reader the result rests only on the items both readers gave the same verdict (same_claim; the same
    tests_* with the same population match on a work); an item the readers judged differently, as a test,
    in its direction or its population, is disputed. The result is duplicate when a card is evidence; else
    known_result when the decisive tests (tests_supports or tests_refutes) all point one way, that direction
    given; else tested_unresolved when a work is an agreed tests_mixed, narrower or imprecise test, or the decisive
    tests point both ways across works; else new when the
    search completed;
    else incomplete: an incomplete search is never new. Without a second reader, or for a known result
    from an incomplete search, the result is a recommendation only."""
    readers = [first] + ([second] if second else [])
    names = [((r.get('checker') or {}).get('name') or '').strip() for r in readers]
    if not all(names):
        raise SearchError('checker: every reader needs a name')
    if not (query_writer or '').strip() or query_writer.strip() in names:
        raise SearchError('checker: a reader must not be the query writer')
    sessions = [(r.get('checker') or {}).get('session') for r in readers]
    if second and sessions[0] and sessions[0] == sessions[1]:
        raise SearchError('checker: the second reader must run in another session than the first')
    if len(set(names)) != len(names):
        raise SearchError('checker: the second reader must be another reader than the first')
    if sha256(text.encode()) != inp['text_sha256']:
        raise SearchError('the text is not the one the input was built from')
    v1 = _verdict_sets(inp, first)
    v2 = _verdict_sets(inp, second) if second else {}  # the second reader also reads every item
    s, at = Searcher(workdir), now()
    kept = _kept_fields(inp, workdir)
    works_out, cards_out, evidence, context = [], [], [], []
    for w in inp['works']:
        v = v1[('work', w['item'])]
        rec, fields = kept[w['item']]
        quote = (v.get('quote') or '').strip() or None
        check, where, pop_check, pop_where = None, None, None, None
        if v['verdict'] in TESTS:
            check, where = passage_check(quote, fields)
            pop_check, pop_where = passage_check(v.get('population'), fields)
        match = v.get('population_match') if v['verdict'] in TESTS else None
        s2 = v2.get(('work', w['item']), {})
        second_v = s2.get('verdict')
        # the second reader agrees on a test only with the same population match and its own criterion found
        second_match = s2.get('population_match') if second_v in TESTS else None
        second_pop = passage_check(s2.get('population'), fields)[0] if second_v in TESTS else None
        prec = precision(v, fields) if v['verdict'] in TESTS else None
        second_prec = precision(s2, fields) if second_v in TESTS else None
        entry = {**{k: w['work'].get(k) for k in ('doi', 'pmid', 'pmcid', 'title')}, 'date': w['date'],
                 'licence': w['licence'], 'verdict': v['verdict'], 'record_call': w['record_call'],
                 'second_reader': second_v}
        if v['verdict'] in TESTS:
            entry.update(population=(v.get('population') or '').strip() or None if pop_check == 'verified' else None,
                         population_check=pop_check, population_in=pop_where, population_match=match,
                         second_population_match=second_match, precision=prec, second_precision=second_prec)
        if v['verdict'] != 'not_retrievable':
            entry.update(quote=quote if check == 'verified' else None,
                         locator=(v.get('locator') or '').strip() or None)
        entry['quote_check'] = check
        if check == 'verified':
            entry['quote_verification'] = {'in': where, 'of': 'Europe PMC core record ' + w['source_id'],
                                           'response_sha256': rec['_response'], 'method': 'exact passage after '
                                           'tags removed and whitespace collapsed (epmc_text)'}
        log = s.log({'call_id': uuid.uuid4().hex[:12], 'tool': 'known_check', 'started_at': at, 'finished_at': at,
                     'kit': f'ohf-extractor/{VERSION}', 'outcome': 'ok',
                     'ask': {'id': w['work'].get('doi') or w['work'].get('pmid') or w['found_by'],
                             'text_sha256': inp['text_sha256'], 'item': w['item']},
                     'verdict': v['verdict'], 'quote_check': check, 'quote_in': where, 'second_reader': second_v,
                     'population_check': pop_check, 'population_match': match, 'second_population_match': second_match,
                     'checker': first['checker'], 'second': (second or {}).get('checker'),
                     'query_writer': query_writer.strip(), 'prompt_sha256': inp['prompt_sha256'],
                     'responses': [], 'hit_count': None, 'found': 0, 'works': []})
        entry['call_id'] = log['call_id']
        works_out.append(entry)
        # A review, meta-analysis, comment or protocol (by the types its record states) reports no test of
        # its own: whatever a reader says, it is context, never evidence.
        kinds = secondary(rec) if rec else []
        if kinds:
            entry['secondary'] = kinds
        if kinds and (v['verdict'] in TESTS or second_v in TESTS):
            context.append({'kind': 'work', 'index': len(works_out) - 1, 'pub_types': kinds})
        elif v['verdict'] in TESTS and check == 'verified' and match in ('broader', 'not_comparable') \
                and pop_check == 'verified':
            # a test of a wider population with no subgroup of the claim's, or of one that cannot be compared
            # with it, is not a test of the claim
            context.append({'kind': 'work', 'index': len(works_out) - 1, 'population_match': match})
            if second_v in TESTS and second_match in ('same', 'narrower') and second_pop == 'verified':
                # the second reader held it a test of the claim's population: the disagreement is listed
                evidence.append({'kind': 'work', 'index': len(works_out) - 1, 'stands': False, 'decisive': False,
                                 'direction': None, 'raised_by': 'second'})
        elif v['verdict'] in TESTS and check == 'verified' and match in ('same', 'narrower') and pop_check == 'verified':
            # an item stands only when the second reader gives the same verdict and the same population match,
            # with its own criterion found: two readers who differ, on whether it is a test, on its direction
            # or on its population, leave it disputed
            agreed = second_v == v['verdict'] and second_match == match and second_pop == 'verified'
            # only a precise test of the claim's own population is decisive: a narrower one tests a part of it,
            # and an imprecise one (an outcome not pre-specified, enrolment stopped early or not stated) has no
            # outcome either way; with a second reader, it must be precise for both
            decisive = v['verdict'] in DECISIVE and match == 'same' and precise(v['verdict'], prec) and \
                (not second or precise(v['verdict'], second_prec or {}))
            evidence.append({'kind': 'work', 'index': len(works_out) - 1, 'stands': agreed, 'decisive': decisive,
                             'direction': v['verdict'] if decisive else None, 'raised_by': 'first'})
        elif second_v in TESTS:
            # a test only the second reader saw: listed, never evidence
            evidence.append({'kind': 'work', 'index': len(works_out) - 1, 'stands': False, 'decisive': False,
                             'direction': None, 'raised_by': 'second'})
    for c in inp['cards']:
        v = v1[('card', c['item'])]
        second_v = v2.get(('card', c['item']), {}).get('relation')
        cards_out.append({'card': c['card'], 'version': c['version'], 'content_hash': c['content_hash'],
                          'file_sha256': c.get('file_sha256'),
                          'identity': 'content_hash' if c['content_hash'] else 'id, version and file_sha256', 'score': c['score'], 'relation': v['relation'],
                          'locator': (v.get('locator') or '').strip() or None, 'second_reader': second_v})
        if v['relation'] == 'same_claim':
            evidence.append({'kind': 'card', 'index': len(cards_out) - 1, 'stands': second_v == 'same_claim',
                             'decisive': True, 'direction': None, 'raised_by': 'first'})
        elif second_v == 'same_claim':
            evidence.append({'kind': 'card', 'index': len(cards_out) - 1, 'stands': False, 'decisive': False,
                             'direction': None, 'raised_by': 'second'})
    completion = inp['searched']['completion']
    # With a second reader, the result rests only on items both readers gave; the first reader's other
    # items are listed as disputed.
    resting = [e for e in evidence if e['stands']] if second else evidence
    disputed = [e for e in evidence if not e['stands']] if second else []
    # The directions of the decisive tests the result rests on, across works: decisive tests that point
    # both ways are a conflict between works, tested with no decisive outcome, never a known result.
    directions = sorted({e['direction'] for e in resting if e['decisive'] and e['kind'] == 'work'})
    if any(e['kind'] == 'card' for e in resting):
        result = 'duplicate'
    elif len(directions) == 1:
        result = 'known_result'
    elif resting:
        result = 'tested_unresolved'  # tested, with no decisive outcome: never a known result
    else:
        result = 'new' if completion == 'complete' else 'incomplete'  # cards_only: never new
    kind = 'card' if result == 'duplicate' else 'work'
    leading = [e for e in resting if e['kind'] == kind and (result != 'known_result' or e['decisive'])]
    direction = directions[0] if result == 'known_result' else None
    return {'schema': KNOWN_SCHEMA, 'schema_version': KNOWN_SCHEMA_VERSION,
            'input': {'text_sha256': inp['text_sha256']},
            'detector': {'name': 'ohf-extractor search.py known-result', 'version': VERSION,
                         'prompt_sha256': inp['prompt_sha256']},
            'readers': [{'name': n, 'model': (r.get('checker') or {}).get('model'),
                         'session': (r.get('checker') or {}).get('session'), 'role': role,
                         'verdicts_sha256': sha256(json.dumps(r, sort_keys=True, ensure_ascii=False,
                                                              separators=(',', ':')).encode()),
                         'verdicts_method': 'sha256 of the verdicts JSON, keys sorted, no whitespace, UTF-8'}
                        for n, r, role in zip(names, readers, ('first', 'second'))],
            'merge_calls': [w['call_id'] for w in works_out],
            'checked_at': at,
            'result': result,
            'direction': direction,
            'directions': {d: sum(1 for e in resting if e['direction'] == d) for d in DECISIVE},
            # A result stands only when the second reader agrees on an item it rests on, and, for a known
            # result, the search completed; anything else is a recommendation.
            'standing': 'second_reader_agrees' if second and leading and
                        (result != 'known_result' or completion == 'complete') else 'recommendation',
            'finder': {'query_writer': query_writer.strip(), 'session': query_writer_session,
                       'card_call': inp['card_call'], 'record_calls': sorted({w['record_call'] for w in inp['works']}),
                       'query_calls': [q['call_id'] for q in inp['searched']['queries']]},
            'cards': cards_out, 'card_score': inp['card_score'], 'works': works_out,
            'evidence': [{'kind': e['kind'], 'index': e['index'], 'decisive': e['decisive'],
                          'direction': e['direction'], 'second_reader_agrees': e['stands'] if second else None}
                         for e in resting],
            'disputed': [{'kind': e['kind'], 'index': e['index'], 'raised_by': e['raised_by']} for e in disputed],
            'context': context,
            'searched': inp['searched']}


# -- attribution -----------------------------------------------------------------------------------

def ids_in(text):
    """The work identifiers in a string: PMCIDs, DOIs and PMIDs of PubMed or Europe PMC links, lower case."""
    text = str(text)
    out = {m.lower() for m in re.findall(r'PMC\d+', text, re.I)}
    out |= {m.rstrip('.,;)').lower() for m in re.findall(r'\b10\.\d{4,9}/[^\s"<>]+', text)}
    out |= {f'pmid:{m}' for m in re.findall(r'(?:pubmed\.ncbi\.nlm\.nih\.gov/|/MED/|EXT_ID:)(\d+)', text)}
    return out


def work_ids(w):
    """Identifiers by which a found work can be matched to a card source."""
    out = set()
    if w.get('pmid'):
        out.add(f"pmid:{w['pmid']}")
    for k in ('pmcid', 'doi'):
        if w.get(k):
            out.add(str(w[k]).lower())
    for k in ('url', 'page'):
        if w.get(k):
            out.add(str(w[k]))
    return out


def card_sources(card):
    """{identifier: [added.sources keys]} for the works a card cites, and the main source's identifiers."""
    main = ids_in(json.dumps(card['author']['source']))
    cited = {}
    for key, rec in (card.get('added', {}).get('sources') or {}).items():
        url = rec.get('source', '') if isinstance(rec, dict) else ''
        for i in (ids_in(url) or {url} if url else set()):
            cited.setdefault(i, []).append(key)
    return main, cited


# The calls whose answer is a bounded set of candidates: each of their works needs a record.
ANSWER_TOOLS = ('similar', 'cited_by', 'responses')
# A work returned only by literature queries is reported from this many distinct calls up. The two
# counter-works that were missed came back four and eighteen times, so the floor is below four.
EXPOSURE = 3


# What a licence record may say about the work it measured: enough to identify and cite it, and
# nothing of its content. The first version of this command put the whole Europe PMC core record in,
# abstract included, for refused works as much as for quotable ones - a review found it, and it is the
# same boundary the kit keeps everywhere else: a record carries identifiers and hashes, not text the
# card has no licence to carry. The service's own licence field is left out on purpose: the point of
# this record is the measurement, and standing the field beside it is what made a card's licence claim
# look measured when it was not.
WORK_METADATA = ('source_id', 'pmcid', 'pmid', 'doi', 'title', 'journal', 'year', 'type', 'dates')


# A full-text route, as against a metadata answer. Only a full text is removed: the metadata answers
# are what make a call repeatable from the hashes it recorded, every search keeps them for every work
# it returns, and the services distribute them as metadata. Measured when this was written: the first
# form of the rule covered every response of a record about a refused work, which named 21 bodies on
# one conversion and 8 on the other - all of them `search?query=PMCID:…` answers, none a full text.
# Removing those would have taken out the repeatability of every call about the work to no purpose.
# A digest, and nothing that merely looks like one: 64 hexadecimal characters.
HEX64 = re.compile(r'^[0-9a-f]{64}$')
FULL_TEXT_URL = re.compile(r'/fullTextXML|pdf=render|/articles/PMC\d+|/unicode/|/bioc|\.pdf(?:$|\?)'
                           r'|/content/(?:early|biorxiv|medrxiv)|/pdf(?:$|/|\?)')


def purge(workdir, remove=False):
    """Response bodies that a measured licence forbids keeping, listed and - with remove - deleted.

    Why this is a command of its own. A retained full text of a work whose licence refuses
    reproduction is a copy the kit has no right to keep, so it has to go; but a deletion decided and
    done inside another step is a deletion nobody can audit. That is how it went wrong once: a defect
    put such bodies on disk, the repair removed sixteen files with `os.remove` inside a repair script,
    and what was lost was not data - every file is reproducible from its URL, and its hash is in the
    record - but the owner's chance to decide. So: one command, a record of what it removed, and
    nothing removed unless asked.

    What may be removed, and nothing else: a body whose hash is the `jats_sha256` of a `licence`
    record that measured the work as not quotable, or whose hash appears among the responses of a
    record about such a work. A work measured quotable is never touched, and neither is a work never
    measured - no measurement, no removal, because the rule being enforced is the measurement.

    The record is logged whether or not anything was removed, since "the check ran and found nothing"
    is the fact a reader of the log needs; and each entry carries the path, the hash, the size and the
    work, so a removed file can be fetched again and checked against the hash it had.
    """
    # Everything below happens under one lock when removing: the log is read, the decision about what
    # a measurement protects is made, the body is quarantined, unlinked, and the record written,
    # without letting go in between. Reading the log before taking the lock was a defect of its own -
    # `Searcher.log` is a cooperative writer of this kit and so is inside the model, and it had time
    # to record a `quotable` measurement between the read and the lock, after which the removal acted
    # on a snapshot that was already wrong.
    #
    # A listing takes no lock and creates nothing, not even the lock file: it is advisory, it writes
    # no record, and it must leave the tree exactly as it found it.
    if remove:
        with store_lock(workdir):
            return _purge(workdir, True)
    return _purge(workdir, False)


def _purge(workdir, remove):
    """The sweep itself, under the caller's lock when it removes anything."""
    calls = read_log(workdir)
    # A measurement that says a work may be quoted protects it, whenever it was made. The owner's
    # licence rule of 2026-10-24 turned works that had been refused into works that may be quoted, so
    # a store holds measurements that disagree - the same bytes refused in the morning and quotable in
    # the afternoon - and deleting on the strength of the older one destroys a body the card may now
    # quote. Disagreement is held and recorded, never acted on: a review found this by measuring one
    # work both ways, in both orders.
    # One work, whatever label an ask happened to carry. A negative measurement asked by PMID and a
    # positive one asked by PMCID are the same work, and binding the protection to the raw label let
    # the body be removed anyway - a review found it with two records differing only in the label.
    # The alias groups are the screen's, built from the identifiers the records themselves carry.
    alias = alias_map(calls)

    def label(ident):
        """An ask's id as the records key it: a bare number is a PMID, which the works carry as
        `pmid:<n>`. Without this the same work under two labels stays two works - the defect this
        grouping exists to close, and the one my first attempt at it still had."""
        ident = str(ident or '').strip().lower()
        if not ident:
            return set()
        return {f'pmid:{ident}', ident} if re.fullmatch(r'\d+', ident) else {ident}

    def group(record):
        ids = label((record.get('ask') or {}).get('id')) | set(work_ids(record.get('work') or {}))
        return set().union(ids, *(alias.get(i, set()) for i in ids))

    protected_bytes, protected_works = {}, {}
    refused = {}
    for r in calls:
        if r['tool'] == 'licence' and r.get('outcome') == 'ok' and r.get('quotable') is True:
            h = (r.get('jats_sha256') or '').replace('sha256:', '')
            if h:
                protected_bytes[h] = r.get('call_id')
            for i in group(r):
                protected_works[i] = r.get('call_id')
    for r in calls:
        if r['tool'] == 'licence' and r.get('outcome') == 'ok' and r.get('quotable') is False:
            ident = str((r.get('ask') or {}).get('id') or '')
            for h in [r.get('jats_sha256')]:
                if h:
                    refused[h.replace('sha256:', '')] = {'work': ident, 'measured_by': r.get('call_id'),
                                                         'licence': r.get('refusal')}
            ids = group(r)
            for other in calls:
                if label((other.get('ask') or {}).get('id')) & ids:
                    for x in other.get('responses', []):
                        h = (x.get('sha256') or '').replace('sha256:', '')
                        if h and x.get('kept') is not False and h not in refused \
                                and FULL_TEXT_URL.search(x.get('url') or ''):
                            refused[h] = {'work': ident, 'measured_by': r.get('call_id'),
                                          'licence': r.get('refusal'), 'fetched_by': other.get('call_id')}
    store = Path(workdir) / RESPONSES
    found, gone, denied = [], [], []
    started = now()
    for h in sorted(refused):
        why = refused[h]
        labels = label(why.get('work'))
        kin = set().union(labels, *(alias.get(i, set()) for i in labels))
        guard = protected_bytes.get(h) or next((protected_works[i] for i in kin
                                                if i in protected_works), None)
        if guard:
            denied.append({'sha256': f'sha256:{h}', **why,
                           'why': f'held: another measurement of this work says quotable, in call '
                                  f'{guard}. Measurements that disagree are recorded and not acted '
                                  f'on, because a licence rule can change what a record says and the '
                                  f'newer answer may be the quotable one'})
            del refused[h]

    def record(forbidden, removed, refused):
        rec = {'call_id': uuid.uuid4().hex[:12], 'tool': 'purge', 'started_at': started,
               'finished_at': now(), 'kit': f'ohf-extractor/{VERSION}', 'outcome': 'ok',
               'ask': {'remove': bool(remove)}, 'service': 'local response store',
               'forbidden': forbidden, 'removed': removed, 'refused': refused, 'responses': [],
               'hit_count': len(forbidden), 'found': len(removed), 'works': []}
        # A listing is a read, so it writes nothing: a purge record in the log always means something
        # was removed. The reviewer's call, and the right one - a log full of "I looked and did
        # nothing" entries makes the entries that matter harder to find.
        return Searcher(workdir).log(rec) if remove else rec

    if not store.exists():
        return record([], [], denied)
    # The store must be a real directory of this work directory. A symlink in its place turns every
    # removal below into the deletion of whatever it points at, which a review found by doing it.
    if store.is_symlink() or not store.is_dir():
        denied.append({'path': str(store), 'why': 'the response store is a symlink or not a '
                                                  'directory, and a removal must not follow it'})
        return record([], [], denied)
    # Opened once, and every name below is resolved against this descriptor rather than re-walked as
    # a path: the directory cannot be swapped between the check and the unlink.
    fd = os.open(store, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for h, why in sorted(refused.items()):
            # A digest comes out of the log, and a log is a file: a record naming `../../outside` as
            # its hash made this command delete a file outside the store. A digest is exactly 64 hex
            # characters, and anything else is refused before a path is built from it.
            if not HEX64.match(h or ''):
                denied.append({'sha256': h, 'why': 'not a digest: a hash is 64 hexadecimal '
                                                   'characters, and no path is built from anything '
                                                   'else', **why})
                continue
            name = f'{h}.body'
            try:
                st = os.lstat(name, dir_fd=fd)
            except FileNotFoundError:
                continue
            if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):
                denied.append({'sha256': f'sha256:{h}', 'why': 'the body is a symlink or not a '
                                                               'regular file, and a removal must not '
                                                               'follow it', **why})
                continue
            # Isolation rather than another look at the name. Checking a name and then acting on it
            # loses every time, because the name can be made to point elsewhere in between; so the
            # body is moved to a private name inside the store first, and everything after - the
            # open, the hash, the unlink - is about that name, which nothing else knows. If it turns
            # out not to be what was measured it goes back under its own name. The owner's
            # concurrency contract, after two rounds of review on the weaker version.
            private = f'.purging-{uuid.uuid4().hex}.{h}'
            if remove:
                try:
                    os.rename(name, private, src_dir_fd=fd, dst_dir_fd=fd)
                except FileNotFoundError:
                    continue
                except OSError as e:
                    denied.append({'sha256': f'sha256:{h}', 'why': f'cannot be isolated: {e}', **why})
                    continue
            else:
                private = name
            # The name is a claim about the bytes, not the bytes. Hash them before removing, or a
            # record says it removed bytes it never saw - a record that lies about what it deleted is
            # worse than no record at all.
            # O_NONBLOCK as well as O_NOFOLLOW: a regular file swapped for a FIFO between the
            # lstat above and this open blocks an ordinary open for ever, which a review found by
            # doing it - the command hung. And what opened is checked again by fstat, because the
            # lstat said something about a name a moment ago, not about this file.
            def restore(reason, extra=None):
                if remove and private != name:
                    with contextlib.suppress(OSError):
                        os.rename(private, name, src_dir_fd=fd, dst_dir_fd=fd)
                denied.append({'sha256': f'sha256:{h}', 'why': reason, **(extra or {}), **why})

            try:
                body = os.open(private, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
            except OSError as e:
                restore(f'cannot be read: {e}')
                continue
            # The descriptor is kept open past the hash on purpose: a body rewritten in place keeps
            # its inode, so the inode alone says nothing, and what says it is that the size and the
            # times have not moved by the time the hash is in hand. Closing the file before hashing
            # would take that second look too early to see anything - which is how the first version
            # of this check passed a test it should have failed.
            try:
                opened = os.fstat(body)
                data = None
                if stat.S_ISREG(opened.st_mode):
                    with open(body, 'rb', closefd=False) as f:
                        data = f.read()
                got = sha256(data) if data is not None else None
                again = os.fstat(body) if data is not None else None
            finally:
                os.close(body)
            if data is None:
                restore('what opened under this name is not a regular file, so it is not the body '
                        'that was measured')
                continue
            if got != f'sha256:{h}':
                restore('the bytes do not hash to the name they are under, so what this file holds '
                        'was never measured: nothing is removed and the mismatch is recorded',
                        {'bytes': len(data), 'hash_of_the_bytes': got})
                continue
            if (again.st_size, again.st_mtime_ns, again.st_ctime_ns) != \
                    (opened.st_size, opened.st_mtime_ns, opened.st_ctime_ns):
                restore('the file changed while it was being read, so the hash is of bytes that are '
                        'no longer there: nothing is removed', {'bytes': len(data)})
                continue
            # The descriptor binds the directory, not the file: between the hash and the unlink the
            # name can be made to point at something else, and then the removal takes bytes nobody
            # measured while the measured bytes survive under another name - with the record saying
            # the opposite. So the name must still be the file that was just hashed, by device and
            # inode, or nothing is removed. A review found this by swapping the file inside the
            # hashing call.
            entry = {'path': f'{RESPONSES}/{name}', 'sha256': f'sha256:{h}', 'bytes': len(data), **why}
            found.append(entry)
            if remove:
                # The private name is this command's own, so what it unlinks is what it hashed.
                os.unlink(private, dir_fd=fd)
                gone.append(entry)
    finally:
        os.close(fd)
    return record(found, gone, denied)


def purge_text(record):
    """The purge as a reader reads it."""
    found, gone = record['forbidden'], record['removed']
    denied = record.get('refused') or []
    if not found:
        head = ('Purge (search.py purge): no retained body belongs to a work a measured licence '
                'refuses. Nothing to remove.')
        return head if not denied else head + '\n' + '\n'.join(
            f"  refused   {d.get('sha256') or d.get('path')}: {d['why']}" for d in denied)
    head = (f'Purge (search.py purge): {len(found)} retained bodies belong to works a measured licence '
            f'refuses to let this kit reproduce.' +
            ('' if gone else ' Nothing was removed: pass --remove to remove them.'))
    lines = [head]
    for e in found:
        lines.append(f"  {e['bytes']:>9} bytes  {e['sha256'][:23]}…  {e['work']}  "
                     f"(measured by {e['measured_by']})")
    if gone:
        lines.append(f'Removed {len(gone)} of them; each is recorded above with its hash, so a copy '
                     f'fetched again can be checked against what was removed.')
    for d in denied:
        lines.append(f"  refused   {d.get('sha256') or d.get('path')}: {d['why']}")
    return '\n'.join(lines)


def work_metadata(record):
    """The identifying metadata of a work, with no abstract and no body - and no value of a shape this
    kit did not expect.

    The whitelist said which keys may be reflected and nothing said what their values may be, so a
    service answering `{"title": {"body": "..."}}` had that structure copied into the record and the
    log. The same rule as everywhere else in this command applies here: a value is reflected when it
    is a bounded scalar, or a flat object of bounded scalars for `dates`, and otherwise it is dropped
    and named by its path and its type under `metadata_dropped`. This one is a drop rather than a
    refusal because the metadata is not what the command measures - the licence is read from the
    work's own bytes - so a strange `journal` must not stop a measurement; it must only not be copied.
    """
    if not isinstance(record, dict):
        return {}
    out, dropped = {}, {}
    for key in WORK_METADATA:
        value = record.get(key)
        if value is None:
            continue
        # One key is an object by design - `dates`, a flat map of names to days - and its values are
        # scalars like any other. Every other key is one line of bibliography, so an object there is
        # a shape the kit does not reflect, whatever it contains.
        if key in METADATA_OBJECTS and isinstance(value, dict):
            inner = {k: reflect('metadata', v, strict=False) for k, v in value.items()
                     if isinstance(k, str) and len(k) <= 40}
            kept = {k: v for k, v in inner.items() if v is not None}
            if len(kept) == len([v for v in value.values() if v is not None]):
                out[key] = {k: value[k] for k in kept}
            else:
                dropped[key] = f'object with {len(value) - len(kept)} value(s) the kit does not reflect'
            continue
        kept = reflect('metadata', value, strict=False)
        if kept is None:
            text = answer_scalar(value)
            dropped[key] = (f'{type(value).__name__} longer than {METADATA_LIMIT} characters'
                            if text is not None else type(value).__name__)
        else:
            out[key] = kept
    return dict(out, metadata_dropped=dropped) if dropped else out


# -- what the kit may reflect out of an answer -----------------------------------------------------
#
# Every value below comes from a service's answer, and a review walked the series of leaks they caused
# one field at a time until the rule became general: **a value from an answer is validated before it
# is reflected anywhere** - into an error, into the log, into a record - and a value that does not
# pass is named by its type and its path and never by its content. Stringifying first and checking
# afterwards is how `{"body": "..."}` as an `article-id_pmc` ended up in a refusal message, which is a
# copy of the answer however short the slice.
#
# These are the fields the `licence` command reflects, and each one's shape:
#   from the BioC answer - the document id, `article-id_pmc`, `article-id_pmcid` (identifiers);
#                          `article-version`, `article-id_pmc-version` (revisions); the `license`
#                          infon (a licence notice, bounded);
#   from the JATS answer - the article's own permissions text (a licence notice, bounded) and the
#                          licence or refusal measured from it, which quotes that notice by design;
#   from either          - the hash of the bytes, the status and the URL, which are not content;
#   from the metadata    - the `WORK_METADATA` whitelist of the Europe PMC record.
# Where a BioC answer may state the article's identity and its revision. Each field is read on its
# own and none may overwrite another: two identifiers that disagree are a payload whose own identity
# is in dispute.
BIOC_ID_FIELDS = ('article-id_pmc', 'article-id_pmcid')
BIOC_REVISION_FIELDS = ('article-version', 'article-id_pmc-version')
IDENTIFIER = re.compile(r'(?:PMC)?\d{1,12}', re.I)
DOCUMENT_ID = re.compile(r'(?:PMC)?\d{1,12}(?:\.[0-9A-Za-z]{1,8})?', re.I)
REVISION = re.compile(r'[0-9A-Za-z][0-9A-Za-z._-]{0,15}')
DIGEST = re.compile(r'sha256:[0-9a-f]{64}')
SERVICE_URL = re.compile(r'https://[A-Za-z0-9._~:/?#\[\]@!$&()*+,;=%-]{1,400}')
STATUS = re.compile(r'[1-5][0-9][0-9]')
# A licence notice is prose and may be reflected whole, which is the measurement itself; a megabyte of
# it is not a notice, and the record keeps the hash and says the text was withheld for its length.
NOTICE_LIMIT = 2000
# A metadata value is one line of bibliography; `dates` alone is a flat object of them.
METADATA_LIMIT = 300
METADATA_OBJECTS = ('dates',)
# Anything a third party quoted inside its own message: `ohfkit` writes a refusal as prose with the
# statement, the restriction marker or the document's root element in `!r` quotes, and each of those
# is a piece of the answer. A quoted span is reflected only when it is part of a notice the record is
# carrying anyway.
EMPTY_STATEMENT = sha256(b'')
# The refusals a measurement can produce, and the kit's own sentence for each. A record's `refusal` is
# built from this table and from facts of the kit's own vocabulary - a marker name out of `_MARKERS`, a
# count, a licence id, a release - and from nothing in the answer.
#
# Five reviews of this command ended here. Every attempt to reflect a refusal's own words safely
# failed in a new way: a slice of the statement, then a slice the bound had withheld, then a `repr`
# in double quotes because the statement held an apostrophe, then a `str(e)` one call further out.
# Free text from a document cannot be filtered; it can only not be quoted. So the text of a statement
# now lives in exactly one field, `permissions_text`, under its own length rule, and every other
# mention of a refusal is a code.
REFUSAL_PHRASES = {
    'no_statement': 'the record states no licence at all',
    'no_licence_named': 'the statement names no versioned CC BY, CC0 or public-domain licence',
    'restriction_marker': 'the permissions carry a restriction marker, so the work is not converted',
    'several_versions': 'the statement names more than one CC BY version',
    'version_not_allowed': 'the licence version is not one this kit converts',
    'no_version_before_1_1_4': 'an Attribution licence with no version, against a standard before '
                               '1.1.4, which is where that value is defined',
    'no_permissions_block': 'the document has no permissions block',
    'no_article_permissions': "the article has no permissions element of its own",
    'no_license_element': 'the permissions block has no licence element of the article',
    'several_license_elements': 'the permissions block has more than one licence element',
    'root_not_article': 'the document root is not an article',
    'unclassified': 'the licence was refused, and this kit has no code for the reason',
}
# The facts a refusal may carry, as a contract per code: which keys that code may have at all, and
# what each of them may be. A shape wide enough to match an identifier is still wide enough to match a
# body fragment, which is how `marker` and `licence` passed a review carrying a canary - so a marker
# must be one of the kit's own marker names, a licence one of the ids the kit itself can produce, a
# release a three-part version, and a count a small whole number. A key that the code does not
# declare is dropped even when its value is perfectly shaped: a fact belongs to a reason or to
# nothing.
def _licence_ids():
    """The licence ids this kit can emit: what it accepts, and the CC BY versions it can read out of
    a statement, which are a closed list and not whatever digits a document shows."""
    import ohfkit
    versions = ('1.0', '2.0', '2.5', '3.0', '4.0')
    return (frozenset(ohfkit.ALLOWED_LICENCES) | {f'CC-BY-{v}' for v in versions}
            | {'CC0-1.0', 'public-domain', ohfkit.UNVERSIONED_LICENCE})


def _markers():
    import ohfkit
    return frozenset(ohfkit._MARKERS)


REFUSAL_FACTS = {
    'restriction_marker': {'marker': ('vocabulary', _markers)},
    'several_versions': {'count': ('count', (2, 50))},
    'several_license_elements': {'count': ('count', (2, 500))},
    'version_not_allowed': {'licence': ('vocabulary', _licence_ids)},
    'no_version_before_1_1_4': {'release': ('release', re.compile(r'\d{1,3}\.\d{1,3}\.\d{1,3}'))},
}

SHAPES = {'identifier': IDENTIFIER, 'document_id': DOCUMENT_ID, 'revision': REVISION,
          'pmcid': IDENTIFIER, 'hash': DIGEST, 'url': SERVICE_URL, 'status': STATUS}
SHAPE_NAMES = {'identifier': 'an article identifier', 'document_id': 'a document id',
               'revision': 'a revision', 'pmcid': 'a PMCID', 'hash': 'a sha256 digest',
               'url': 'a service URL', 'status': 'an HTTP status'}


def answer_scalar(value):
    """`value` as text if it is a scalar the kit may read - a string, or an integer or float written
    as one - and None for anything else. `True` is an int in Python and is not a scalar here: a
    boolean where an identifier belongs is a wrong shape, not the number one."""
    if isinstance(value, bool):
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)):
        return repr(value) if isinstance(value, float) else str(value)
    return None


def reflect(kind, value, path=None, notice=None, note=None, strict=True):
    """**The one gate** every value out of a service's answer passes before it is reflected anywhere:
    into a record, into the log, into a URL, into an error message, into the name of a file.

    Four reviews found the same defect in different places - a value stringified first and checked
    afterwards, or quoted inside somebody else's message - and the lesson was that patching the
    places does not end: a new sink gets written and the rule is not applied to it. So the rule has
    one implementation, and every sink calls it:

    - `identifier`, `document_id`, `revision`, `pmcid`, `hash`, `url`, `status` - a scalar matching
      that shape, or a refusal that names the type and the path and nothing of the value. A string of
      the wrong shape fails too, because a string is exactly what a body fragment is. The `pmcid`
      shape is checked **before a URL is built from it**, since the URL then goes to a service, into
      the responses and into the log.
    - `metadata` - one line of bibliography, bounded. With `strict=False` an unexpected shape is
      dropped (returns None) instead of refusing, which is right where the value is not what the
      command measures.
    - `notice` - a licence statement: prose the record carries whole, or, past `NOTICE_LIMIT`, None,
      so the caller can say the text was withheld and keep the hash.
    - `reason` - a measured verdict's own words, with every span the author quoted out of the answer
      removed unless it is part of `notice`, the statement this record is carrying. That is how a
      refusal stops copying 300 characters of a statement the record withheld, and how the root
      element name of a cached document stops reaching the log through a raw `LicenceError`.
    - `foreign` - an exception from outside the kit: its kind, and for a parse failure where in the
      document it happened. Never its words, which are about the bytes.

    `path` is where the value was found and is reflected in a refusal; `note` is how the answer may be
    described (see `answer_note`) and is appended to it.
    """
    if kind == 'foreign':
        # Never `str(value)`, for any exception. A review found body bytes inside one: a response that
        # claims gzip and is not carries its first bytes in the decompressor's message, and the kit's
        # own wrapper had put that message in the record. So an exception leaving the kit is its class
        # and the kit's own phrase, with numbers where there are numbers - a parse failure's place.
        if isinstance(value, ET.ParseError):
            line, column = getattr(value, 'position', (None, None))
            return f'xml not well formed at line {line}, column {column}'
        return f'{type(value).__name__}: the route did not answer in a form this kit can read'
    if kind == 'code':
        # **No code means no code.** A grant has no refusal code, and the first form of this returned
        # `unclassified` for `None` - so a licence recovered from an earlier call came back as
        # CC-BY-4.0 *with a refusal code beside it*, and the next call wrote that invented refusal
        # into a new log, where a third would read it as a real one. A reflection that fills in a
        # value is not a reflection. An unknown code on a real refusal is the other case and keeps
        # its refusal: that mapping belongs to `refusal_record`, which knows there was an error.
        if value is None:
            return None
        return value if value in REFUSAL_PHRASES else 'unclassified'
    if kind == 'notice':
        text = value if isinstance(value, str) else None
        return text if text is not None and len(text) <= NOTICE_LIMIT else None
    text = answer_scalar(value)
    if kind == 'metadata':
        if text is not None and len(text) <= METADATA_LIMIT and '\n' not in text:
            return value
        if strict:
            raise RouteUnavailable(f'the value at {path} is {type(value).__name__} and is not one '
                                   f'line of bibliography' + (f' ({note})' if note else ''))
        return None
    if text is None or not SHAPES[kind].fullmatch(text):
        raise RouteUnavailable(f'the value at {path} is {type(value).__name__} and does not have the '
                               f'shape of {SHAPE_NAMES[kind]}, so nothing is read from this answer '
                               f'and nothing of it is reported' + (f' ({note})' if note else ''))
    return text


def answer_note(evidence):
    """How an unusable answer may be described in an error and in the log: **where** it came from,
    what it answered and the hash of its bytes - and nothing out of those bytes.

    A review found the opposite in the first form of these refusals: the message carried
    `json.dumps(payload)[:120]` and `json.dumps(infons)[:80]`, so a payload whose body the work's
    licence forbids keeping was written into the log by the diagnostics, through the one command that
    fetches every route with `keep_body=False` precisely so that nothing of the kind is kept. A
    diagnostic that quotes the answer is a copy of the answer.

    Each part passes `reflect`, so this description cannot become a sink of its own: a URL, a status
    and a digest that do not have the shape of one are left out by name.
    """
    parts = []
    for kind, key, label in (('url', 'url', 'answer from'), ('status', 'status', 'HTTP'),
                             ('hash', 'sha256', '')):
        try:
            parts.append(f'{label} {reflect(kind, evidence.get(key), path=f"response.{key}")}'.strip())
        except RouteUnavailable:
            parts.append(f'{key} of an unexpected shape')
    return ', '.join(parts) + ', body not kept'


def jats_status(responses):
    """The status the JATS route answered with, from the responses this call recorded."""
    answers = [r for r in responses if 'fullTextXML' in (r.get('url') or '')]
    return answers[-1].get('status') if answers else None


def route_evidence(responses):
    """The last answer's url, status and hash, for `answer_note`; no body and no payload."""
    last = responses[-1] if responses else {}
    return {k: last.get(k) for k in ('url', 'status', 'sha256')}


def answer_notice(text, evidence):
    """A licence notice as a record may carry it: the text when it is prose, or, when it is longer
    than a notice can be, its length and the hash of the bytes it came in."""
    kept = reflect('notice', text)
    if text is not None and kept is None:
        return None, {'permissions_text_withheld': f'longer than {NOTICE_LIMIT} characters '
                                                   f'({len(text)}), so the statement is kept by hash '
                                                   f'only ({answer_note(evidence)})'}
    return kept, {}


def bioc_identity(doc, front, pmcid, evidence):
    """The identity a BioC document states, bound to the work that was asked for.

    Why this is here rather than inline. The licence is read out of `documents[0]`'s front passage,
    and until a review tried it, nothing checked that the document *was* the requested article: a
    BioC answer carrying PMC99999999 was read as the licence of PMC10592076, because the only thing
    binding them was the URL the kit had asked. A licence recorded for the wrong work is worse than
    no licence, so this fails closed: every identity the payload states must be the requested one,
    and a payload that states none at all is unusable rather than assumed.

    A revision is reported, never claimed. The service's URL (`BioC_json/PMC…/unicode`) names no
    revision, so the kit asks for "the current one" and cannot have asked for a particular one; when
    the answer states a version, the record carries it beside `revision_requested: null`, which is
    the honest shape of a binding that does not exist.
    """
    want = re.sub(r'^PMC', '', str(pmcid), flags=re.I)
    stated, revisions = [], []
    # Every field at every level is read on its own and none can overwrite another. The first form of
    # this kept one identifier per level, so a document whose infons said `article-id_pmc: 99999999`
    # and `article-id_pmcid: 10592076` was accepted for the second: the fields contradicted each other
    # and the later one silently won. Two identifiers that disagree are not a work identified twice,
    # they are a payload whose own identity is in dispute, and nothing may be read out of it.
    if isinstance(doc, dict) and doc.get('id') not in (None, ''):
        raw = reflect('document_id', doc['id'], path='documents[].id', note=answer_note(evidence))
        ident, _, revision = re.sub(r'^PMC', '', raw, flags=re.I).partition('.')
        stated.append(('document id', ident))
        if revision:
            revisions.append(('document id', revision))
    for where, holder in (('document infons', doc), ('front passage infons', front)):
        if not isinstance(holder, dict) or 'infons' not in holder:
            continue
        infons = holder['infons']
        # `infons: null` is not the same as no infons at all. An absent infons is an answer that
        # states nothing there, which is ordinary; an explicit null is a shape the kit does not know,
        # and `.get` on it raised AttributeError out of the command with no record.
        if infons is None:
            raise RouteUnavailable(f'{pmcid}: the BioC {where} is null rather than absent, so the '
                                   f'answer\'s shape is not one this kit reads ({answer_note(evidence)})')
        # A BioC infons is an object. Anything else - a list, a string, a number - is a shape this
        # kit does not know, and `.get` on it used to raise straight out of the command.
        if not isinstance(infons, dict):
            raise RouteUnavailable(f'{pmcid}: the BioC {where} is {type(infons).__name__}, not an '
                                   f'object, so the identity and the licence it would carry cannot be '
                                   f'read ({answer_note(evidence)})')
        path = 'documents[].infons' if holder is doc else 'documents[].passages[0].infons'
        for field in BIOC_ID_FIELDS:
            if infons.get(field):
                raw = reflect('identifier', infons[field], path=f'{path}[{field}]',
                              note=answer_note(evidence))
                stated.append((f'{where} {field}', re.sub(r'^PMC', '', raw, flags=re.I)))
        for field in BIOC_REVISION_FIELDS:
            if infons.get(field):
                revisions.append((f'{where} {field}',
                                  reflect('revision', infons[field], path=f'{path}[{field}]',
                                          note=answer_note(evidence))))
    if not stated:
        raise RouteUnavailable(
            f'{pmcid}: the BioC answer states no article identity (neither the document id nor an '
            f'{" or ".join(BIOC_ID_FIELDS)} infon), so the licence it carries cannot be bound to the '
            f'work asked for - the URL is not evidence of what the payload holds '
            f'({answer_note(evidence)})')
    wrong = [(where, ident) for where, ident in stated if ident != want]
    if wrong:
        raise RouteUnavailable(
            f'{pmcid}: the BioC answer is about another article: ' +
            ', '.join(f'{where} says PMC{ident}' for where, ident in sorted(wrong)) +
            f' where PMC{want} was asked for' +
            (f', and it also says PMC{want} elsewhere, so its own identity is in dispute'
             if len(wrong) < len(stated) else ''))
    # Revisions are recorded as stated, each with the field that stated it, and not reduced to one
    # value: a document id ending `.1` beside an `article-version` of 99 are two different claims, and
    # a single unqualified `revision` would report agreement that is not there.
    return {'bioc_document_id': f'PMC{want}',
            'bioc_identity_from': [where for where, _ in stated],
            'bioc_revision_stated': {where: value for where, value in revisions} or None,
            'bioc_revisions_agree': len({value for _, value in revisions}) < 2 if revisions else None,
            'revision_requested': None}


def bioc_front(payload, pmcid, evidence):
    """The front passage of the BioC document for `pmcid`, with the identity it states.

    Every step is checked, because a malformed 200 used to escape the call with an IndexError or a
    TypeError and leave no record at all - the one outcome a log must never have, since a reader
    cannot distinguish a call that was never made from one whose answer was unusable.
    """
    collections = payload if isinstance(payload, list) else [payload]
    documents = []
    for part in collections:
        if isinstance(part, dict) and isinstance(part.get('documents'), list):
            documents += [d for d in part['documents'] if isinstance(d, dict)]
    if not documents:
        raise RouteUnavailable(f'{pmcid}: the BioC answer holds no document, so there is no front '
                              f'passage to read a licence statement from ({answer_note(evidence)})')
    want = re.sub(r'^PMC', '', str(pmcid), flags=re.I)

    def claims(doc):
        # Only for choosing which document the answer means; the identity itself is validated in
        # `bioc_identity`, which refuses what this merely fails to recognise. The infons are typed
        # here as well, because a list of them used to raise AttributeError on `.get` from here.
        infons = doc.get('infons') if isinstance(doc.get('infons'), dict) else {}
        ids = {re.sub(r'^PMC', '', str(doc.get('id') or ''), flags=re.I).partition('.')[0]}
        ids |= {re.sub(r'^PMC', '', str(infons[f]), flags=re.I)
                for f in BIOC_ID_FIELDS if infons.get(f)}
        return want in ids

    named = [d for d in documents if claims(d)]
    if len(named) > 1:
        raise RouteUnavailable(f'{pmcid}: the BioC answer holds {len(named)} documents that each '
                              f'claim to be this article, so which one states its licence is ambiguous '
                              f'({answer_note(evidence)})')
    doc = named[0] if named else documents[0]
    # Each step is typed before it is used. `doc['passages']` was taken as a sequence, so a `passages`
    # of 7 raised a TypeError out of the command with no record of the call at all - and a route that
    # answered something unusable has to be a logged outcome, not a traceback.
    if not isinstance(doc.get('passages'), list):
        raise RouteUnavailable(f'{pmcid}: the BioC document\'s passages are '
                               f'{type(doc.get("passages")).__name__}, not a list, so it has no front '
                               f'passage to read a licence statement from ({answer_note(evidence)})')
    passages = [p for p in doc['passages'] if isinstance(p, dict)]
    if not passages:
        raise RouteUnavailable(f'{pmcid}: the BioC document holds no passage, so it carries no front '
                              f'passage and no licence infon ({answer_note(evidence)})')
    front = passages[0]
    # `bioc_identity` reads the infons of both the document and this passage, and refuses either that
    # is not an object - so by the time it returns, the infons the caller takes the licence out of has
    # been typed. That is why there is no second check for it here.
    identity = bioc_identity(doc, front, pmcid, evidence)
    # The licence statement itself is typed here, where the other shapes are, so that the caller can
    # normalise it. A `license` infon that is a list or an object raised TypeError out of `norm` and
    # escaped the call with no record - the same defect as the shapes above, one field deeper.
    licence_infon = (front['infons'] if isinstance(front.get('infons'), dict) else {}).get('license')
    if licence_infon is not None and not isinstance(licence_infon, str):
        raise RouteUnavailable(f'{pmcid}: the BioC front passage\'s licence infon is '
                               f'{type(licence_infon).__name__}, not a string, so there is no licence '
                               f'statement to measure ({answer_note(evidence)})')
    return front, identity


def answered(licence, refusal_code):
    """Whether a route **answered** about the work's licence: it is a verdict or it is nothing.

    One definition, in one place, because this command has now been through three reviews of the same
    confusion wearing different clothes. A route answers when it produces a verdict - a licence, or a
    coded refusal of the work's own record - and the shape of the text it read is no part of that.
    What is not an answer is a route that could not be reached or whose document could not be read:
    those are silence, and silence cannot contradict a measurement.

    Twice I wrote this rule a second time by hand, in the routing and in `licence_held`, and twice the
    two copies drifted: first a withheld text looked like silence, then an empty statement did - so a
    coded refusal was forgotten and the other route's CC BY 4.0 made the work quotable. A definition
    kept in two places is two definitions.
    """
    return licence is not None or refusal_code is not None


def route_answer(route, licence, refusal_code, held_as, **evidence):
    """One answer of one route, in the shape every comparison expects."""
    return {'route': route, 'held_as': held_as, 'licence': licence, 'refusal_code': refusal_code,
            **{k: v for k, v in evidence.items() if v is not None}}


def logged_answer(call, pmcid):
    """The route answer a logged `licence` call carries for `pmcid`, or None when that call is not an
    answer: another work, another tool, a failure, or a call that kept no verdict of its own route.

    An aggregate (`licence_sources_disagree`) is opened rather than trusted: the verdict of the route
    it measured is recovered from its own `licence_answers`, because the aggregate's `licence: null`
    is the call's outcome and not that route's answer.
    """
    if (call.get('tool') != 'licence' or call.get('outcome') != 'ok'
            or (call.get('work') or {}).get('pmcid') != pmcid
            or call.get('measured_from') not in (JATS_ROUTE, BIOC_ROUTE)):
        return None
    route = call['measured_from']
    where = f"an earlier measurement, call {call.get('call_id')}"
    if call.get('refusal_code') == 'licence_sources_disagree':
        own = [a for a in (call.get('licence_answers') or [])
               if a.get('held_as') == 'measured now' and a.get('route') == route]
        if not own:
            return None
        licence, code = own[0].get('licence'), reflect('code', own[0].get('refusal_code'))
        where += ', the answer of the route it measured'
    else:
        licence = call.get('licence')
        code = (reflect('code', call['licence_refusal_code'])
                if call.get('licence_refusal_code') else None)
    if not answered(licence, code):
        return None
    return route_answer(route, licence, code, where, at=call.get('finished_at'),
                        statement_sha256=call.get('permissions_sha256'))


def licence_verdict(ohfkit, statement, perm=None, jats=False):
    """(licence, refusal) for one licence statement, where `refusal` is a **code and facts**, never a
    message: `{'code': …, 'phrase': …, …facts}` or None.

    The JATS route reads the article's own `<license>` element with the restriction scan over the
    whole block (`licence_of_jats`); the BioC route has the flat text of the infon only, so it is read
    as a statement (`licence_of`). Each is the work's own record, and both answer in this shape so
    that two routes can be compared without choosing between them.

    What is not here any more is the refusal's own words. `LicenceError` writes the statement into its
    message, and no filter over that text survived review: the statement, then the slice a length
    bound had withheld, then a `repr` in double quotes because the statement held an apostrophe. The
    code comes from the error, the sentence from the kit's own table, and the facts from the kit's own
    vocabulary.
    """
    try:
        return (ohfkit.licence_of_jats(perm) if jats else ohfkit.licence_of(statement or '')), None
    except ohfkit.LicenceError as e:
        return None, refusal_record(e)


def refusal_record(error):
    """A refused measurement as a record may carry it: the code, the kit's sentence for it, and the
    facts that code declares, each checked against its own vocabulary or range.

    Anything else is left out. A fact is not a free field beside a reason - it is part of the reason,
    and a value the kit cannot name is no part of it.
    """
    # A refusal always has a code, even when the error did not name one: there *was* an error, and
    # `unclassified` says the kit has no name for it. That is the opposite of a grant, which has no
    # code at all, and the two must not be written the same way.
    code = reflect('code', getattr(error, 'code', None)) or 'unclassified'
    allowed = REFUSAL_FACTS.get(code, {})
    facts = {}
    for key, value in (getattr(error, 'facts', None) or {}).items():
        if key not in allowed:
            continue
        kind, against = allowed[key]
        if kind == 'vocabulary':
            if isinstance(value, str) and value in against():
                facts[key] = value
        elif kind == 'count':
            low, high = against
            if isinstance(value, int) and not isinstance(value, bool) and low <= value <= high:
                facts[key] = value
        elif kind == 'release':
            if isinstance(value, str) and against.fullmatch(value):
                facts[key] = value
    return {'code': code, 'phrase': REFUSAL_PHRASES[code], **facts}


def routes_disagree(answers):
    """The pairs of answers from **different** routes whose licence differs.

    The owner's rule of 2026-10-24 accepts the BioC `license` infon as the article's own record on one
    condition: when the kit holds answers from both routes for one article and they disagree, it
    refuses and does not choose. This is that comparison, and it is deliberately narrow in two ways.

    Across routes only. Two answers by the same route are one route measured twice - a re-measurement,
    which the later record supersedes - not two records of the article contradicting each other.

    By the licence, not by the words. Two routes quote the same grant in different prose (the infon is
    the publisher's sentence, the permissions block is JATS), so the texts differ on almost every
    article where both answer; what must not differ is the answer about the licence. Two refusals agree
    (neither licenses anything, and the refusal that stands keeps its own reason); a licence against a
    refusal is a disagreement, because one route would let a card quote what the other would not.
    """
    out = []
    for i, a in enumerate(answers):
        for b in answers[i + 1:]:
            if a['route'] != b['route'] and a['licence'] != b['licence']:
                out.append((a, b))
    return out


def disagreement_text(clashes):
    """The reason of a `licence_sources_disagree` refusal: each pair, by route, with what each says -
    a licence id, or the code of the refusal, and never a refusal's words."""
    def says(a):
        return (f"{a['route']} ({a['held_as']}) says {a['licence']}" if a.get('licence')
                else f"{a['route']} ({a['held_as']}) refuses it as {a.get('refusal_code') or 'unclassified'}")
    return ('licence_sources_disagree: the article\'s own record answers differently by route, and the '
            'kit does not choose between them: ' + '; '.join(f'{says(a)}, while {says(b)}' for a, b in clashes))


def alias_map(calls):
    """Identifier -> the set of identifiers of the same work, as the logged records give them
    together: a card that cites a work by its PMCID is matched to a record that found it by its DOI.
    The screen and the purge both group by this, so neither takes two labels of one work for two
    works."""
    alias = {}
    for r in calls:
        for w in r.get('works', []) + [x for x in (r.get('target'), r.get('work')) if isinstance(x, dict)]:
            group = set().union(work_ids(w), *(alias.get(i, set()) for i in work_ids(w)))
            for i in group:
                alias[i] = group
    return alias


def screen(card, workdir, exposure=EXPOSURE):
    """Every work a call returned that the card neither cites nor otherwise accounts for.

    Why this exists, and why it is not the same as `attribute`. `attribute` and the coverage it
    carries work per **call**: a call is accounted for when the card cites something it returned. That
    hides the failure this screen is for. On two conversions the decisive counter-work was returned by
    calls the card does use - once four times, once eighteen - and fell out at the screening step,
    because the screen was a filter over the titles, written from the words the card already used. A
    work whose title says melanin, endosymbiont, phagosome or reasoning passes such a filter unread
    however many calls return it, and nothing in the record shows that it was never looked at.

    So the accounting here is per work. A work is accounted for when the card cites it, when a
    `not_cited` record says it was read and why it is not cited, when a `not_read` record says the kit
    could not read it, or when a `relevance` verdict names it. Anything else a call returned is
    unscreened, and is reported most-returned first, because exposure is the signal: a work eighteen
    calls returned and no record mentions is the shape of the defect, not a long tail.

    Two populations, because they need different rules. The calls whose whole purpose is "what answers
    this article" - `similar`, `cited_by`, `responses` - return a bounded set, and every work in it
    needs a record. A `literature` query is a net: forty works come back and most are not about the
    claim, so demanding a record for each would make the screen unreadable and the demand would be
    ignored, which is worse than no demand. There the signal is exposure - the counter-works that were
    missed came back four and eighteen times - so a literature-only work is reported once at least
    `exposure` distinct calls returned it.

    This says nothing about whether an unscreened work matters. It says that no work can leave the
    search without a record of someone having looked at it."""
    main, cited = card_sources(card)
    calls = read_log(workdir)
    alias = {}
    for r in calls:
        for w in r.get('works', []) + ([r['target']] if isinstance(r.get('target'), dict) else []):
            group = set().union(work_ids(w), *(alias.get(i, set()) for i in work_ids(w)))
            for i in group:
                alias[i] = group
    def expand(ids):
        return set().union(set(ids), *(alias.get(i, set()) for i in ids))

    def named_by(r):
        """The identifiers a single-work record names: the one it was asked about and any its lookup
        found. A failed metadata lookup still names the work the caller gave."""
        ids = work_ids(r['work']) if isinstance(r.get('work'), dict) else set()
        given = (r.get('ask') or {}).get('id')
        if given:
            given = str(given).strip()
            ids |= {f'pmid:{given}'} if re.fullmatch(r'\d+', given) else {given.lower()}
        return expand(ids)

    # What each record is worth as an answer to "did anyone look at this", which is not the same for
    # every tool. `not_cited` is an attestation by the converter - it was read, here is the reason and
    # where the reason shows - so it counts whatever the metadata lookup did, since the lookup is not
    # what the attestation rests on. `relevance` is a checker's verdict and counts when it was made.
    # `not_read` counts only when it attests that the work could **not** be read: a record whose
    # lookup failed attests nothing, and one that found a readable place says the opposite of what
    # would take the work off the screen - a work the kit can read must be read or accounted for some
    # other way. Treating every `not_read` record as an answer was a defect found in review: a probe
    # that succeeded closed the work it had just proved readable.
    accounted = expand(set(main) | set(cited))
    for r in calls:
        if valid_not_cited(r):
            accounted |= expand(not_cited_ids(r)) | named_by(r)
        elif r['tool'] == 'relevance' and r.get('outcome') == 'ok':
            accounted |= named_by(r)
        elif r['tool'] == 'not_read' and r.get('outcome') == 'ok' and not r.get('readable'):
            accounted |= named_by(r)
        elif r['tool'] == 'licence' and r.get('outcome') == 'ok' and r.get('quotable') is False:
            # The licence was measured from the work's own bytes and refuses quotation: that is a
            # reading of the work's own permissions element and a reason the card may name it only.
            accounted |= named_by(r)

    # One work, counted once. The identifiers a service returns differ between calls - PMCID here,
    # PMCID and DOI there, DOI alone in a third - so keying by the identifiers of a single answer
    # splits one work into several rows, each with a fraction of the calls that returned it. Review
    # found three calls for one work split 1 + 2, both parts under the exposure floor, and the command
    # exiting 0 on a work it should have named. The key is the alias group, which is what makes the
    # count a count of the work.
    seen = {}
    for r in calls:
        if r.get('outcome') != 'ok' or r['tool'] in ('not_cited', 'not_read', 'relevance', 'licence'):
            continue
        cid = r.get('call_id') or f"{r['tool']}@{r['started_at']}"
        for w in r.get('works', []):
            ids = work_ids(w)
            if not ids or ids & accounted:
                continue
            group = expand(ids)
            key = sorted(group)[0]
            rec = seen.setdefault(key, {'ids': sorted(group), 'title': w.get('title'), 'calls': [],
                                        'tools': set()})
            rec['ids'] = sorted(set(rec['ids']) | group)
            rec['calls'].append(cid)
            rec['tools'].add(r['tool'])
            rec['title'] = rec['title'] or w.get('title')
    rows = [{'ids': v['ids'], 'title': v['title'], 'returned_by': len(set(v['calls'])),
             'tools': sorted(v['tools']), 'calls': sorted(set(v['calls'])),
             'answer_call': bool(set(v['tools']) & set(ANSWER_TOOLS))} for v in seen.values()]
    rows.sort(key=lambda r: (not r['answer_call'], -r['returned_by'], r['ids'][0]))
    out = [r for r in rows if r['answer_call'] or r['returned_by'] >= exposure]
    below = [r for r in rows if not (r['answer_call'] or r['returned_by'] >= exposure)]
    return {'unscreened': out, 'below_exposure': len(below), 'exposure': exposure,
            'unscreened_all': len(rows), 'accounted': sorted(accounted)}


# The classes of work a conversion may not leave without a verdict, however few calls returned them.
# These are the works that answer the article - a published comment, a reply, an erratum, a notice -
# and the review of the extractor found exactly this failure: an official published Comment on the
# converted article sat in the first search output and was only picked up by the fourth wave of
# critics. A search log is not a review of what the search found.
ANSWERING_TYPES = ({'comment', 'editorial', 'letter', 'reply', 'author reply', 'comment on',
                    'article commentary'}
                   # Every notice class is an answering work too, and the list is taken from the
                   # vocabularies rather than retyped: a class added to one and forgotten in the other
                   # is a work the gate stops seeing, which is this item's own failure mode.
                   | {t for t in RETRACTION_TYPES + CORRECTION_TYPES + CONCERN_TYPES + PARTIAL_TYPES})
# What a verdict may be. Three, as the review requires: carried by the card, read and set aside with
# a reason, or unavailable with the measurement that says so.
CLOSEOUT_VERDICTS = ('carried', 'set_aside', 'unavailable')


def answering(work):
    """The answering classes a work's publication types put it in, as the kit names them.

    Both shapes are read, because a work arrives in two of them. A Europe PMC answer carries
    `pubTypeList`; the record this kit **logs** carries `type`, the same list joined with semicolons -
    and the first form of this function read only the first, so the gate found no answering work in
    either finished conversion. A check that reads a shape the log does not use is a check that passes
    for the wrong reason, which is the defect this whole item is about.
    """
    stated = set(pub_types(work))
    for part in str(work.get('type') or '').split(';'):
        stated.add(part)
    return sorted({t.lower().replace('-', ' ').strip() for t in stated if t} & ANSWERING_TYPES)


def closeout(card, workdir, exposure=EXPOSURE):
    """Every work of an answering class that the search found, and the verdict the conversion gave it.

    Item 3 of the extractor review, as a gate rather than an instruction: *a search is not closed
    while a comment, a reply, a rebuttal, a correction or an erratum it found has no verdict.* The
    three verdicts are the review's own - carried by the card, read and set aside with a reason,
    unavailable with the measurement that says so - and `closeout` reports a work without one and
    exits non-zero, which is what makes the requirement a check instead of a sentence in a skill.

    It is deliberately narrower and stricter than `screen`. Narrower, because it asks only about the
    classes that answer the article, which a publication type names: a comment, a reply, an erratum, a
    notice. Stricter, because for those there is no exposure floor - one call returning an official
    Comment once is the case the review found, and a floor would have hidden it exactly as the screen
    did.

    What it cannot do, said here rather than implied: a *direct test of a prediction* is not a
    publication type, so no metadata names it. Those works are declared by the conversion or not at
    all, and the result carries `declared_only` to say so, so that a reader does not read this check
    as covering what it cannot see.
    """
    main, cited = card_sources(card)
    calls = read_log(workdir)
    alias = {}
    for r in calls:
        for w in r.get('works', []) + ([r['target']] if isinstance(r.get('target'), dict) else []):
            group = set().union(work_ids(w), *(alias.get(i, set()) for i in work_ids(w)))
            for i in group:
                alias[i] = group

    def expand(ids):
        return set().union(set(ids), *(alias.get(i, set()) for i in ids))

    def named_by(r):
        ids = work_ids(r['work']) if isinstance(r.get('work'), dict) else set()
        given = (r.get('ask') or {}).get('id')
        if given:
            given = str(given).strip()
            ids |= {f'pmid:{given}'} if re.fullmatch(r'\d+', given) else {given.lower()}
        return expand(ids)

    # The verdicts, by the record that carries each. `carried` is the card itself citing the work.
    # `set_aside` is a `not_cited` record - the converter attests it was read and says why it is not
    # cited - or a checker's `relevance` verdict. `unavailable` is a `not_read` record that attests
    # the work could not be read, or a `licence` measurement that refuses quotation: a work a card may
    # name and not quote still needs its reason on the record.
    verdict, evidence = {}, {}
    for i in expand(set(main) | set(cited)):
        verdict[i], evidence[i] = 'carried', 'the card cites it'
    for r in calls:
        if valid_not_cited(r):
            for i in expand(not_cited_ids(r)) | named_by(r):
                verdict.setdefault(i, 'set_aside')
                evidence.setdefault(i, f"not_cited {r.get('ask', {}).get('reason') or ''}".strip())
        elif r.get('outcome') != 'ok':
            continue
        elif r['tool'] == 'relevance':
            for i in named_by(r):
                verdict.setdefault(i, 'set_aside')
                evidence.setdefault(i, f"relevance call {r.get('call_id')}")
        elif r['tool'] == 'not_read' and not r.get('readable'):
            for i in named_by(r):
                verdict.setdefault(i, 'unavailable')
                evidence.setdefault(i, f"not_read call {r.get('call_id')}")
        elif r['tool'] == 'licence' and r.get('quotable') is False:
            for i in named_by(r):
                verdict.setdefault(i, 'unavailable')
                evidence.setdefault(i, f"licence refused: {r.get('licence_refusal_code') or 'measured'}")

    # A later status lookup can discover a notice that the answering search did not label.
    # Bind that discovery to the work before deciding which classes need notice readings.
    # Only included notices/the measured aggregate supply notice classes. The target supplies
    # identifiers, never current publication types that an as-of measurement left out or deferred.
    measured_classes, measured_notice = {}, {}
    notice_types = {'retracted': RETRACTION_TYPES[0], 'corrected': CORRECTION_TYPES[0],
                    'concern': CONCERN_TYPES[0], 'partial': PARTIAL_TYPES[0]}
    for r in calls:
        if r.get('tool') != 'status' or r.get('outcome') != 'ok':
            continue
        target = r.get('target') or r.get('work') or {}
        ids = named_by(r) | expand(work_ids(target))
        statuses = {n.get('status') for n in r.get('notices', [])} | {r.get('status')}
        statuses &= notice_types.keys()
        classes = {notice_types[s] for s in statuses}
        for ident in ids:
            measured_classes.setdefault(ident, set()).update(classes)
            measured_notice.setdefault(ident, set()).update(statuses)

    works, rows = {}, []
    for r in calls:
        if r.get('outcome') != 'ok' or r['tool'] in ('not_cited', 'not_read', 'relevance', 'licence'):
            continue
        for w in r.get('works', []):
            ids = work_ids(w)
            group = expand(ids)
            classes = set(answering(w)) | set().union(*(measured_classes.get(i, set()) for i in group))
            if not classes or not ids:
                continue
            key = sorted(group)[0]
            rec = works.setdefault(key, {'ids': sorted(group), 'title': w.get('title'),
                                         'classes': set(), 'calls': set(), 'tools': set(),
                                         'notice': set()})
            rec['classes'].update(classes)
            rec['notice'].update(retraction_classes(w))
            rec['notice'].update(set().union(*(measured_notice.get(i, set()) for i in group)))
            rec['calls'].add(r.get('call_id') or f"{r['tool']}@{r['started_at']}")
            rec['tools'].add(r['tool'])
            rec['title'] = rec['title'] or w.get('title')
    # Discovery is not reading. Require a separate attestation bound to the exact discovery record
    # and an identified partial notice; ordinary corrections and unidentified pubType flags cannot do it.
    read_notice = {}
    required_notice = {}
    for r in calls:
        if r.get('tool') == 'status' and r.get('outcome') == 'ok':
            partial_ids = {notice_key(n.get('notice')) for n in r.get('notices', [])
                           if n.get('status') == 'partial' and status_of(n.get('kind')) == 'partial'} - {None}
            for ident in named_by(r):
                required_notice.setdefault(ident, set()).update(partial_ids)
        for ident in bound_notice_reading(r, calls):
            read_notice.setdefault(ident, []).append({'call_id': r['call_id'],
                'notice': r['ask']['notice'], **r['reading']})
    for key, rec in works.items():
        given = next((verdict[i] for i in rec['ids'] if i in verdict), None)
        shown = next((evidence[i] for i in rec['ids'] if i in evidence), None)
        # A partial retraction is the one class whose verdict is not enough by itself. Part of the
        # work is withdrawn and only the notice says which part, so a verdict that uses the work -
        # carried, or set aside after reading - stands only when the notice was read. A work recorded
        # as unavailable needs nothing further: nobody rested on it.
        partial = 'partial' in rec['notice']
        readings = {r['call_id']: r for ident in rec['ids'] for r in read_notice.get(ident, [])}
        required = set().union(*(required_notice.get(i, set()) for i in rec['ids']))
        read_ids = {notice_key(r['notice']) for r in readings.values()}
        notice_read = bool(readings) and required <= read_ids
        wanting = (partial and given in ('carried', 'set_aside') and not notice_read)
        rows.append({'ids': rec['ids'], 'title': rec['title'], 'classes': sorted(rec['classes']),
                     'notice': sorted(rec['notice']), 'notice_read': notice_read,
                     'notice_readings': list(readings.values()),
                     'partial_notices_required': sorted(required),
                     'returned_by': len(rec['calls']), 'tools': sorted(rec['tools']),
                     'answer_call': bool(rec['tools'] & set(ANSWER_TOOLS)),
                     'verdict': None if wanting else given,
                     'needs': ('the partial retraction notice must be read before the work is used: '
                               'which results were withdrawn is in the notice and nowhere else'
                               if wanting else None),
                     'record': shown})
    rows.sort(key=lambda r: (r['verdict'] is not None, not r['answer_call'], -r['returned_by'],
                             r['ids'][0]))
    # Two populations, for the reason `screen` gives at length: the calls whose purpose is "what
    # answers this article" return a bounded set, and every answering work in it needs a verdict - that
    # is where a published Comment on the article appears, and where the review's missed Comment was.
    # A literature query is a net: measured on the two finished conversions, it returns editorials and
    # letters on other subjects by the dozen (`Introducing Evolution Letters`, `The Materiality of
    # Images`), and demanding a verdict for each would make the gate unreadable and the demand ignored,
    # which is worse than no demand. There the signal is exposure, as in the screen.
    def gates(row):
        return row['verdict'] is None and (row['answer_call'] or row['returned_by'] >= exposure)

    gated = [r for r in rows if gates(r)]
    quiet = [r for r in rows if r['verdict'] is None and not gates(r)]
    return {'answering_works': rows, 'without_verdict': gated, 'below_exposure': quiet,
            'exposure': exposure, 'closed': not gated, 'verdicts': sorted(CLOSEOUT_VERDICTS),
            'classes_checked': sorted(ANSWERING_TYPES),
            'declared_only': ['a direct test of a prediction is not a publication type: no metadata '
                              'names it, so such a work is declared by the conversion or not at all, '
                              'and this check does not see it']}


def closeout_text(result):
    """The closeout as a person reads it: what has no verdict first, because that is the gate."""
    lines = []
    for r in result['without_verdict']:
        lines.append(f"NO VERDICT  {r['ids'][0]}  [{', '.join(r['classes'])}]  {(r['title'] or '')[:70]}")
        if r.get('needs'):
            lines.append(f"            {r['needs']}")
    for r in result['answering_works']:
        if r['verdict']:
            lines.append(f"{r['verdict']:11s} {r['ids'][0]}  [{', '.join(r['classes'])}]  {r['record'] or ''}")
    lines.append('')
    lines.append(f"{len(result['answering_works'])} answering works, "
                 f"{len(result['without_verdict'])} without a verdict, "
                 f"{len(result['below_exposure'])} more under the exposure floor of "
                 f"{result['exposure']} literature calls; "
                 f"the search is {'closed' if result['closed'] else 'NOT closed'}")
    lines.append(f"not seen by this check: {result['declared_only'][0]}")
    return '\n'.join(lines)


def screen_text(result):
    """The screen as a reader reads it: the unscreened works, most-returned first."""
    rows = result['unscreened']
    tail = ('' if not result['below_exposure'] else
            f"\n  Below the exposure floor: {result['below_exposure']} works returned by fewer than "
            f"{result['exposure']} literature calls each and by no similar, cited-by or responses call. "
            f"They are in the log; raise --exposure 1 to list them.")
    if not rows:
        return ('Screen (search.py screen): every work a similar, cited-by or responses call returned '
                'is accounted for, and so is every literature work at or above the exposure floor.'
                + tail)
    answer = sum(1 for r in rows if r['answer_call'])
    lines = [f'Screen (search.py screen): {len(rows)} works accounted for nowhere - not cited, not '
             f'read-and-not-cited, not recorded unreadable, no relevance verdict. {answer} of them '
             f'came from a similar, cited-by or responses call, where every work needs a record; the '
             f'rest are literature works {result["exposure"]} or more calls returned. Candidates '
             f'first, then by exposure.']
    for r in rows:
        where = 'answer' if r['answer_call'] else 'literature'
        lines.append(f"  {r['returned_by']:>3} calls  {where:<10} {', '.join(r['ids'])}  "
                     f"[{', '.join(r['tools'])}]")
        if r['title']:
            lines.append(f"            {r['title'][:150]}")
    return '\n'.join(lines) + tail


def attribute(card, workdir):
    """Which logged call found each work the card cites, which calls found none of them, and which cited
    works no logged call found (the converter knew them, or found them with a tool the kit did not repeat)."""
    main, cited = card_sources(card)
    calls, found_by = read_log(workdir), {}
    # The PMID, PMCID and DOI of one work, as any logged record gives them together: a card that cites a
    # work by its PMCID is matched to a record that found it by its DOI.
    alias = {}
    for r in calls:
        for w in r.get('works', []) + ([r['target']] if isinstance(r.get('target'), dict) else []):
            group = set().union(work_ids(w), *(alias.get(i, set()) for i in work_ids(w)))
            for i in group:
                alias[i] = group
    main = set().union(main, *(alias.get(i, set()) for i in main))
    for r in calls:
        if r.get('outcome') != 'ok':
            continue
        cid = r.get('call_id') or f"{r['tool']}@{r['started_at']}"
        for w in r.get('works', []):
            for i in work_ids(w):
                found_by.setdefault(i, {})[cid] = {'call_id': cid, 'tool': r['tool'], 'ask': r['ask']}
    sources, used = [], set()
    for i, keys in sorted(cited.items()):
        hits = list({h['call_id']: h for j in alias.get(i, {i}) for h in found_by.get(j, {}).values()}.values())
        used |= {h['call_id'] for h in hits}
        sources.append({'id': i, 'card_sources': keys, 'main': i in main, 'found_by': hits})
    idle = [{'call_id': r.get('call_id') or f"{r['tool']}@{r['started_at']}", 'tool': r['tool'], 'ask': r['ask'],
             'outcome': r.get('outcome'), 'found': r.get('found'), 'status': r.get('status')}
            for r in calls if r['tool'] != 'not_cited'
            and (r.get('call_id') or f"{r['tool']}@{r['started_at']}") not in used]
    # A work logged as read and not cited that the card does cite: one of the two is wrong.
    read = []
    for r in calls:
        if r['tool'] != 'not_cited':
            continue
        ids = not_cited_ids(r)
        ids = set().union(ids, *(alias.get(i, set()) for i in ids))
        read.append({'call_id': r.get('call_id'), 'id': r['ask']['id'], 'reason': r['ask'].get('reason'),
                     'locator': r['ask'].get('locator'), 'cited_as': sorted(i for i in ids if i in cited)})
    return {'sources': sources, 'calls_without_card_source': idle, 'read_not_cited': read,
            'not_found_by_search': [s['id'] for s in sources if not s['found_by'] and not s['main']]}


def not_cited_ids(record):
    """The identifiers of the work a not_cited record names: those it was given, and those its lookup found."""
    given = record['ask']['id'].strip()
    ids = {f'pmid:{given}'} if re.fullmatch(r'\d+', given) else {given.lower()}
    return ids | (work_ids(record['work']) if record.get('work') else set())


def attribution_text(result):
    """The attribution lines of the conversion report."""
    lines = ['Attribution (search.py attribute):']
    for s in result['sources']:
        keys = ', '.join(s['card_sources'])
        if s['main']:
            lines.append(f"  {s['id']} [{keys}]: the article converted")
        elif s['found_by']:
            how = '; '.join(f"{h['tool']}{' ' + h['ask']['source'] if 'source' in h['ask'] else ''} "
                            f"{h['ask'].get('query') or h['ask'].get('id')!r} ({h['call_id']})"
                            for h in s['found_by'])
            lines.append(f"  {s['id']} [{keys}]: found by {how}")
        else:
            lines.append(f"  {s['id']} [{keys}]: NOT found by a logged search")
    for c in result['calls_without_card_source']:
        ask = c['ask'].get('query') or c['ask'].get('id')
        src = ' ' + c['ask']['source'] if 'source' in c['ask'] else ''
        what = f"status {c['status']}" if c['tool'] == 'status' and c['outcome'] == 'ok' else \
            f"{c['outcome']}, {c['found']} found, none cited"
        lines.append(f"  call {c['call_id']} {c['tool']}{src} {ask!r}: {what}")
    for r in result.get('read_not_cited', []):
        line = f"  read, not cited: {r['id']} ({r['reason']}; at {r['locator']}; {r['call_id']})"
        if r['cited_as']:
            line += f" CONFLICT: the card cites it as {', '.join(r['cited_as'])}"
        lines.append(line)
    return '\n'.join(lines)


def order_of(record):
    """The order a literature search asked for, as the report names it. PubMed's Best Match is not
    repeatable (the service retrains it), so the report says so; the rank of each work is in the log."""
    if record['tool'] != 'literature':
        return ''
    order = record['ask'].get('sort')
    variant = ', reviews excluded' if record['ask'].get('variant') == 'no_reviews' else ''
    if order is None:
        return f"{variant}, order: the service's default, most recent first"
    if order == 'relevance':
        return f'{variant}, order: Best Match (not repeatable; each work\'s rank is in the log)'
    return f'{variant}, order: {order}'


def support_lines(records):
    """The support of each claim of a submitted text: for every paragraph whose citations a checker
    judged, how many of its works were judged to state what it attaches to them (supports_claim), of
    those that could be read. A claim is measured by this share, not by how many works it cites: five
    works on the topic that do not state the claim are no support. The latest reading of a pair counts;
    a reading of the full text replaces one of the abstract."""
    latest = latest_relevance(records)
    if not latest:
        return []
    by_para = {}
    for (_, para), r in latest.items():
        by_para.setdefault(para, []).append(r)
    lines = ['  Support per claim (relevance; supports_claim of the works that could be read, per paragraph):']
    readable_total = supported_total = with_support = 0
    for para in sorted(by_para):
        rs = by_para[para]
        readable = [r for r in rs if r['relevance'] != 'not_retrievable']
        supported = sum(1 for r in readable if r['relevance'] == 'supports_claim')
        readable_total += len(readable)
        supported_total += supported
        with_support += supported > 0
        unread = len(rs) - len(readable)
        lines.append(f"    p{para}: {supported}/{len(readable)} supports_claim"
                     f"{f'; {unread} not retrievable' if unread else ''}"
                     f"{'; NO SUPPORT' if readable and not supported else ''}")
    full = [r for r in latest.values() if r.get('basis') == 'full_text']
    lines.append(f"    {with_support} of {len(by_para)} claims have a supporting work; supports_claim in "
                 f"{supported_total} of {readable_total} readable pairs"
                 + (f"; {len(full)} pairs read again in the full text, "
                    f"{sum(1 for r in full if r['relevance'] == 'supports_claim')} of them now supports_claim"
                    if full else ''))
    return lines


def literature_gaps(records):
    """Report lines for literature queries not also run without reviews: a query (with its source, order
    and cutoff) needs a successful no_reviews record whose sent query excludes reviews. A record from
    before the variants has none."""
    lit = [r for r in records if r['tool'] == 'literature']

    def key(r):
        a = r['ask']
        return a.get('query'), a.get('source'), a.get('sort'), a.get('as_of')
    done, lines = set(), []
    for r in lit:
        if r['ask'].get('variant') != 'no_reviews':
            continue
        if NO_REVIEWS.get(r['ask'].get('source'), '\0') not in r['ask'].get('sent', ''):
            lines.append(f"  CHECK: {r.get('call_id', '-')} is marked without reviews, but its query does not "
                         f"exclude them")
        elif r['outcome'] == 'ok':
            done.add(key(r))
    for k in dict.fromkeys(key(r) for r in lit):
        if k not in done:
            lines.append(f"  CHECK: literature {k[1]} {k[0]!r} has no successful run without reviews; "
                         f"reviews can push the primary works off the first page")
    return lines


def report(workdir):
    """The "Search" section of the conversion report: every call, its sources, date and count."""
    lines = ['Search (scripts/search.py; log ' + LOG + '):']
    records = read_log(workdir)
    if not records:
        return 'Search: none recorded. "Nothing against" cannot be claimed without a search.'
    read = []
    for r in records:
        ask = r['ask'].get('query') or r['ask'].get('id')
        if r['tool'] == 'not_cited':
            read.append(r)
            reason, locator = r['ask'].get('reason'), (r['ask'].get('locator') or '').strip()
            bad = '' if reason in NOT_CITED and locator else \
                f" INVALID: the reason must be one of {', '.join(NOT_CITED)}, with a locator"
            work = '' if r['outcome'] == 'ok' and r.get('work') else \
                ' (work not resolved' + (f": {r['error']})" if r['outcome'] != 'ok' else ')')
            lines.append(f"  {r.get('call_id', '-')} read, not cited {ask!r} [{reason}; at {locator or '?'}]"
                         f"{work}{bad}")
            continue
        if r['tool'] == 'not_read':
            tried = r.get('places') or []
            answers = ', '.join(f"{x.get('kind') or '?'} {'read' if x.get('read') else x.get('refused', '?')}"
                                for x in tried) or 'no place listed'
            lines.append(f"  {r.get('call_id', '-')} found, NOT READ {ask!r}: {answers}"
                         + ('' if not r.get('readable') else
                            f" -- WARNING {r['readable']} place(s) answered: this work is readable"))
            continue
        if r['tool'] == 'relevance':
            same = ' (the same model, a separate run)' if r.get('same_model') else ''
            lines.append(f"  {r.get('call_id', '-')} relevance p{r['ask']['paragraph']} {ask[:80]!r}: "
                         f"{r['relevance']} at {r['locator']} (checker {r['checker']['name']}"
                         f"{', ' + r['checker']['model'] if r['checker'].get('model') else ''}{same}; "
                         f"extractor {r['extractor']})")
            continue
        if r['tool'] == 'similar_cards' and r['outcome'] == 'ok':
            found = '; '.join(f"{c['card']} v{c['version']} ({c['score']}: "
                              f"{', '.join(c['shared_terms'][:6]) or '-'}"
                              f"{'; works ' + ', '.join(c['shared_works']) if c['shared_works'] else ''})"
                              for c in r['candidates']) or 'none'
            lines.append(f"  {r.get('call_id', '-')} similar cards of {ask} among {r['hit_count']}: {found}")
            continue
        where = r.get('service', r['ask'].get('source', '')) + order_of(r)
        if r['ask'].get('as_of'):
            where += f", as of {r['ask']['as_of']}"
        if r['outcome'] != 'ok':
            lines.append(f"  {r['tool']} {ask!r} [{where}] at {r['started_at']}: FAILED ({r['error']})")
            continue
        extra = f", status {r['status']}" if r['tool'] == 'status' else ''
        if r['tool'] == 'trial':
            known = r['trial']['status'] or f"unknown on the cutoff ({r['trial']['as_of']['reason']})"
            extra = f", status {known} (registry data of {r['release']})"
        if 'left_out' in r:
            extra += f"; {len(r['left_out'])} left out as later than the cutoff"
        if r.get('undetermined'):
            extra += f"; {len(r['undetermined'])} notices undated, not counted"
        lines.append(f"  {r.get('call_id', '-')} {r['tool']} {ask!r} [{where}] at {r['started_at']}: "
                     f"{r['hit_count']} reported, {r['found']} recorded{extra}; "
                     f"{len(r['responses'])} responses hashed")
    lines += literature_gaps(records)
    lines += support_lines(records)
    if read:
        counts = {}
        for r in read:
            counts[r['ask'].get('reason')] = counts.get(r['ask'].get('reason'), 0) + 1
        lines.append(f"  Read, not cited: {len(read)} ("
                     + ', '.join(f'{k} {n}' for k, n in sorted(counts.items(), key=lambda x: str(x[0]))) + ')')
    return '\n'.join(lines)


def load_cards(dirs):
    """The cards in each directory (DIR/cards or DIR; *.json, or */card.json for a card per directory),
    each with the sha256 of its file as `_file_sha256`."""
    out = []
    for d in dirs:
        root = Path(d)
        root = root / 'cards' if (root / 'cards').is_dir() else root
        for path in sorted(root.glob('*.json')) + sorted(root.glob('*/card.json')):
            data = path.read_bytes()
            card = json.loads(data)
            if isinstance(card, dict) and card.get('id'):
                out.append(dict(card, _file_sha256=sha256(data)))
    return out


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    p.add_argument('command', choices=('literature', 'cited-by', 'responses', 'status', 'similar', 'terms', 'report',
                                       'not-read',
                                       'attribute', 'screen', 'closeout', 'licence', 'locate', 'purge', 'check-refs', 'trial', 'trials', 'text', 'not-cited',
                                       'relevance-input', 'relevance-merge', 'similar-cards', 'known-input',
                                       'known-check', 'known-merge', 'known-search', 'notice-read', 'close-step'))
    p.add_argument('arg', nargs='?')
    p.add_argument('files', nargs='*', help='relevance-input, known-input: OUT.json; relevance-merge, known-merge: IN.json VERDICTS.json')
    p.add_argument('--workdir', default='.')
    p.add_argument('--remove', action='store_true',
                   help='purge: delete the bodies it names, instead of only naming them')
    p.add_argument('--exposure', type=int, default=EXPOSURE,
                   help='screen: report a work only literature queries returned when at least this '
                        'many distinct calls returned it (default %(default)s)')
    p.add_argument('--limit', type=int, default=None,
                   help='maximum results (locate: positive integer, default 5; other commands: 100)')
    p.add_argument('--sources', default='europepmc,pubmed')
    p.add_argument('--fallback-query', action='append',
                   help='literature: opt in to at most two ordered broader fallback queries')
    p.add_argument('--min-works', type=int, default=None,
                   help='fallback: unique candidate threshold (default 3), not scientific relevance')
    p.add_argument('--max-works', type=int, default=None,
                   help='fallback: selected result cap, at most 60 (default 60)')
    p.add_argument('--sort', choices=sorted(SORTS), default='default',
                   help='literature: "cited" for the established works (Europe PMC by citations, PubMed by Best Match)')
    p.add_argument('--as-of', metavar='YYYY-MM-DD',
                   help='literature, cited-by, responses, similar, status: only what was known on that day (inclusive)')
    p.add_argument('--find', help='locate: the words whose address in the work is wanted')
    p.add_argument('--reason', choices=sorted(NOT_CITED), help='not-cited: why the work read is not cited')
    p.add_argument('--locator', help='not-cited: where in the work the reason shows (section, table, figure)')
    p.add_argument('--atom', help='not-cited: the card atom the work was read against')
    p.add_argument('--extractor', help='relevance-merge: who extracted the card (the checker must differ)')
    p.add_argument('--extractor-model', help="relevance-merge: the extractor's model, if known")
    p.add_argument('--recheck', choices=sorted(RELEVANCE),
                   help='relevance-input: only the pairs whose latest verdict is this, with their open full text')
    p.add_argument('--cards', action='append',
                   help='similar-cards, known-input: a directory of cards (DIR/cards or DIR); known-input takes several')
    p.add_argument('--cards-only', action='store_true', help='known-input: compare the cards only, no literature')
    p.add_argument('--exclude', action='append', default=[], help='known-input: a card ID@VERSION left out of the pool')
    p.add_argument('--query-writer', help='known-merge: who wrote the literature queries (no reader may be them)')
    p.add_argument('--query-writer-session', help='known-merge: the session the queries were written in')
    p.add_argument('--second', help='known-merge: the second reader\'s verdicts (JSON)')
    p.add_argument('--notice', help='notice-read: exact notice identifier in the status record')
    p.add_argument('--status-call', help='notice-read: discovery call id')
    p.add_argument('--notice-sha256', help='notice-read: sha256 of the notice the reader actually read')
    p.add_argument('--reader', help='notice-read: the reader making the attestation')
    a = p.parse_args(argv)
    if a.fallback_query is not None or a.min_works is not None or a.max_works is not None:
        if a.command != 'literature' or not a.fallback_query:
            p.error('fallback options require literature --fallback-query QUERY')
        if a.limit is None:
            a.limit = FALLBACK_PER_CALL
    if a.command == 'close-step':
        from stages import close_step, StageError
        try:
            result = close_step(a.workdir)
        except (StageError, StepClosedError, OSError, ValueError) as error:
            print(str(error), file=sys.stderr)
            return 1
        print(json.dumps(result, ensure_ascii=False, indent=1))
        return 0
    if a.command == 'locate' and a.limit is not None and a.limit < 1:
        p.error('locate --limit must be a positive integer')
    if a.limit is None:
        a.limit = 5 if a.command == 'locate' else 100
    if a.as_of and a.command not in ('literature', 'cited-by', 'responses', 'similar', 'status', 'trial', 'trials'):
        p.error(f'--as-of does not apply to {a.command}')
    if a.command == 'attribute':
        if not a.arg:
            p.error('attribute needs the card file')
        print(attribution_text(attribute(json.loads(Path(a.arg).read_text()), a.workdir)))
        return 0
    if a.command == 'purge':
        record = purge(a.workdir, a.remove)
        print(purge_text(record))
        # Non-zero while a forbidden body is still on disk, so the check reads as a check.
        return 1 if (record['forbidden'] and not record['removed']) else 0
    if a.command == 'screen':
        if not a.arg:
            p.error('screen needs the card file')
        result = screen(json.loads(Path(a.arg).read_text()), a.workdir, a.exposure)
        print(screen_text(result))
        # Non-zero while any returned work has no record of having been looked at: the screen is meant
        # to be run as a check, not read as a note.
        return 1 if result['unscreened'] else 0
    if a.command == 'report':
        print(report(a.workdir))
        return 0
    if a.command == 'relevance-input':
        if not a.arg or len(a.files) != 1:
            p.error('relevance-input TEXT OUT.json')
        inp = relevance_input(Path(a.arg).read_text(), a.workdir, a.recheck)
        Path(a.files[0]).write_text(json.dumps(inp, ensure_ascii=False, indent=1) + '\n')
        print(f"{len(inp['items'])} references for the checker, {len(inp['not_sent'])} not sent (see not_sent)")
        return 0
    if a.command == 'relevance-merge':
        if not a.arg or len(a.files) != 2 or not a.extractor:
            p.error('relevance-merge TEXT IN.json VERDICTS.json --extractor NAME')
        out = relevance_merge(Path(a.arg).read_text(), json.loads(Path(a.files[0]).read_text()),
                              json.loads(Path(a.files[1]).read_text()), a.extractor, a.workdir, a.extractor_model)
        for r in out:
            print(f"p{r['ask']['paragraph']} {r['ask']['id'][:70]!r}: {r['relevance']} at {r['locator']}")
        return 0
    if a.command == 'similar-cards':
        if not a.arg or not a.cards:
            p.error('similar-cards TEXT --cards DIR')
        cards = load_cards(a.cards)
        r = Searcher(a.workdir).similar_cards(Path(a.arg).read_text(), cards, a.limit if a.limit != 100 else 10)
        print(json.dumps(r['candidates'], ensure_ascii=False, indent=1))
        return 0
    if a.command == 'known-search':
        if not a.arg:
            p.error('known-search QUERIES.json (a JSON list of the query writer\'s queries) [--limit N]')
        out = Searcher(a.workdir).known_search(json.loads(Path(a.arg).read_text()), a.limit if a.limit != 100 else 20)
        for r in out:
            print(f"{r['ask']['source']} {r['ask']['probe']} {r['ask']['variant']}: {r['outcome']}, {r['found']} works")
        return 0
    if a.command == 'known-input':
        if not a.arg or len(a.files) != 1 or not a.cards:
            p.error('known-input TEXT OUT.json --cards DIR [--cards DIR ...] [--exclude ID@VERSION]')
        cards = [c for c in load_cards(a.cards) if f"{c.get('id')}@{c.get('version')}" not in a.exclude]
        inp = known_input(Path(a.arg).read_text(), cards, a.workdir, literature=not a.cards_only)
        Path(a.files[0]).write_text(json.dumps(inp, ensure_ascii=False, indent=1) + '\n')
        print(f"{len(inp['works'])} works and {len(inp['cards'])} cards for the checker; search "
              f"{inp['searched']['completion']}")
        return 0
    if a.command == 'known-check':
        if not a.arg or len(a.files) != 1:
            p.error('known-check IN.json VERDICTS.json')
        out = known_check(json.loads(Path(a.arg).read_text()), json.loads(Path(a.files[0]).read_text()), a.workdir)
        print(json.dumps(out, ensure_ascii=False))
        return 1 if out else 0
    if a.command == 'known-merge':
        if not a.arg or len(a.files) != 2 or not a.query_writer:
            p.error('known-merge TEXT IN.json VERDICTS.json --query-writer NAME [--second VERDICTS2.json]')
        inp = json.loads(Path(a.files[0]).read_text())
        out = known_merge(Path(a.arg).read_text(), inp, json.loads(Path(a.files[1]).read_text()), a.query_writer,
                          a.workdir, json.loads(Path(a.second).read_text()) if a.second else None,
                          a.query_writer_session)
        Path(a.files[1]).with_name(Path(a.files[1]).stem + '-result.json').write_text(
            json.dumps(out, ensure_ascii=False, indent=1) + '\n')
        print(f"{out['result']} ({out['standing']}); evidence {out['evidence']}")
        return 0
    if not a.arg:
        p.error(f'{a.command} needs an argument')
    s = Searcher(a.workdir)
    if a.command == 'notice-read':
        try:
            out = s.notice_read(a.arg, a.notice, a.status_call, a.locator, a.notice_sha256, a.reader)
        except SearchError as error:
            print(str(error), file=sys.stderr)
            return 1
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return 0
    if a.command == 'literature':
        if a.fallback_query:
            try:
                out = s.literature_fallback(a.arg, a.fallback_query, a.limit, tuple(a.sources.split(',')),
                                            a.sort, a.as_of,
                                            a.min_works if a.min_works is not None else 3,
                                            a.max_works if a.max_works is not None else FALLBACK_WORKS)
            except SearchError as error:
                print(str(error), file=sys.stderr)
                return 1
            print(json.dumps(out, ensure_ascii=False, indent=1))
            return 0 if out['outcome'] == 'ok' else 1
        out = s.literature(a.arg, a.limit, tuple(a.sources.split(',')), a.sort, a.as_of)
    elif a.command == 'check-refs':
        out = s.check_refs(Path(a.arg).read_text())
        print(refs_text(out))
        return 0 if all(r['outcome'] == 'ok' for r in out) else 1
    elif a.command == 'similar':
        out = [s.similar(a.arg, a.limit, as_of=a.as_of)]
    elif a.command == 'terms':
        out = [s.terms(a.arg)]
    elif a.command == 'not-read':
        out = s.not_read(a.arg, a.atom)
        print(json.dumps(out, ensure_ascii=False, indent=1))
        # 1 when the work turned out to be readable after all: the claim it was logged for is false.
        return 0 if out['outcome'] == 'ok' and not out.get('readable') else 1
    elif a.command == 'not-cited':
        if not a.reason or not a.locator:
            p.error('not-cited needs --reason and --locator')
        out = s.not_cited(a.arg, a.reason, a.locator, a.atom)
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return 0 if out['outcome'] == 'ok' else 1
    elif a.command == 'closeout':
        if not a.arg:
            p.error('closeout needs the card file')
        out = closeout(json.loads(Path(a.arg).read_text()), a.workdir)
        print(closeout_text(out))
        # The gate: a search with an answering work that has no verdict is not closed.
        return 0 if out['closed'] else 1
    elif a.command == 'licence':
        if not a.arg:
            p.error('licence needs the identifier of a work')
        out = s.licence(a.arg)
        print(json.dumps(out, ensure_ascii=False, indent=1))
        # Non-zero when the measurement did not happen or the licence refuses quotation: a caller
        # asking "may I quote this" gets the answer in the exit code as well as the record.
        return 0 if out['outcome'] == 'ok' and out.get('quotable') else 1
    elif a.command == 'locate':
        if not a.arg or not a.find:
            p.error('locate needs the identifier of a work and --find')
        out = s.locate(a.arg, a.find, limit=a.limit)
        print(json.dumps(out, ensure_ascii=False, indent=1))
        # Non-zero when nothing was found, so that a caller cannot read "no address" as an address.
        return 0 if out['outcome'] == 'ok' and out.get('addresses') else 1
    elif a.command in ('trial', 'trials', 'text'):
        out = [s.trial(a.arg, as_of=a.as_of) if a.command == 'trial' else s.text(a.arg) if a.command == 'text'
               else s.trials(a.arg, a.limit, as_of=a.as_of)]
        for r in out:
            print(json.dumps(r, ensure_ascii=False, indent=1))
        return 0 if all(r['outcome'] == 'ok' for r in out) else 1
    else:
        out = [{'cited-by': s.cited_by, 'responses': s.responses, 'status': s.status}[a.command](a.arg, as_of=a.as_of)]
    for r in out:
        print(json.dumps({k: v for k, v in r.items() if k != 'works'} | {
            'works': [{k: w.get(k) for k in ('source_id', 'doi', 'pmcid', 'year', 'type', 'licence', 'relation', 'title')}
                      for w in r['works']]}, ensure_ascii=False, indent=1))
    return 0 if all(r['outcome'] == 'ok' for r in out) else 1


if __name__ == '__main__':
    sys.exit(main())
