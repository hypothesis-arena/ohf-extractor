"""Native value rendering and append-only ledger primitives.

Complete selected validation belongs to native_profile.validate_bundle. A ledger
entry binds the complete native value, passage, checker result and original IO
proof. The worst eligible verdict remains visible for the same binding. Root
metadata and earlier renderings do not replace original relational context.
This module alone does not establish schema/profile or scientific acceptance.
"""
import hashlib
import copy
import json
import os
import re
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import projection_binding as projection
import checker_io

FORMAT = 'ohf-entailment-ledger/2'
FORMATS = ('ohf-entailment-ledger/1', FORMAT)  # /1 is read as lists of one
CANONICALISATION = ('value_sha256: SHA-256 of the UTF-8 bytes of json.dumps(value, ensure_ascii=False, '
                    "sort_keys=True, separators=(',', ':')), value as given to the checker; "
                    'passage_sha256: SHA-256 of the UTF-8 bytes of the passage text as given to the checker; '
                    'note_sha256: SHA-256 of the UTF-8 bytes of the note; '
                    'target_sha256: same canonical JSON hash of ohf-target-projection/1; '
                    'checker_binding: frozen request/input/result/configuration byte lineage, not checker authentication; '
                    'all written "sha256:<hex>"; entries keyed "<pointer>|<basis>", each a list of checks in time order')
LEDGER_NAME = 'entailment-ledger.json'

# ------------------------------------------------------------------ the item-building rules
# entailment.py imports these, so the checker input and this check cannot drift apart.

# Fields recorded from article metadata, and evidence lines checked by exact quotation.
SKIP_PREFIXES = ('/added/layers/provenance/',)
# Lists whose elements may name their own paragraph, from OHF 1.1. The standard's rule: an element
# without its own `src` is read from the src of its list, and a record for it names the list; an
# element with its own `src` is read from that src, and a record may name the element. Before this,
# the kit read only the first half - a list came to a reader whole, against one paragraph, so an
# element the article states elsewhere was reported missing from a paragraph it was never in. That is
# what three `partial` verdicts on a flagship card were, and they were structural: at 1.0 there was no
# way to say where the element came from, and at 1.1 there is.
ELEMENT_SRC_LISTS = ('/added/layers/core/alternative_explanations', '/added/layers/core/uncertainties',
                     '/added/layers/core/opens', '/added/layers/core/explains')
ELEMENT_POINTER = re.compile(r'^(' + '|'.join(ELEMENT_SRC_LISTS) + r')/value/(\d+)$')
LINE_FIELDS = ('direction', 'study_type', 'study_system')
LINE_FIELD = re.compile(r'^/added/layers/evidence/lines/(\d+)/'
                        r'(direction|study_type|study_system|indirectness|sample|sample_size|'
                        r'multi_site_program|result_estimate|endpoint_kind)$')
# Fields whose value is more than the string in `value`: the closed term beside the source's wording,
# and the note that a term of `other` requires. Sent whole, because a reader shown only the wording
# judges only the wording - which is what happened on sixteen of these: every one was checked for
# whether its phrase was in the passage, and not one for whether the term was the right reading of
# it, the half OHF 1.1 added. A reader must see all of what it is asked to judge.
WITH_TERM = ('endpoint_kind',)
# The OHF 1.1 members a line can carry whose value is unjudgeable on its own. A bare `48` against a
# paragraph means nothing without knowing what was counted, and the numbers of a `result_estimate` are
# read out of the line's quotation in the first place, so each of these is given to the checker with
# that quotation and the question is whether the passage states it **for this result**. They are not
# `WITH_TARGET`: the target claim is what a direction or an indirectness is about, and these are about
# the study.
WITH_QUOTE = ('sample', 'sample_size', 'multi_site_program', 'result_estimate')
TAXON_ID = re.compile(r'^/added/layers/predictions/(\d+)/system/taxon_id$')
# Judged against the target: "supports" needs an object. Indirectness is sent alone: with
# the target added, the checker read the target as a claim the passage must support.
# A value whose meaning is a relation to something else is sent with that something else, or the
# checker judges it against the passage alone and answers about another question (K1). A
# direction is a relation between the line's own finding and the target claim; an indirectness is
# the distance between the study and that claim. Both get the target statement and the line's own
# quotation, which the passage may state among others.
WITH_TARGET = ('direction', 'indirectness')


def skip(pointer, node):
    if pointer.startswith(SKIP_PREFIXES) or pointer == '/added/layers/core/first_proposed':
        return True
    return 'value' not in node  # an evidence line object: its fields are checked one by one


def target_statement(card, line):
    """Exact accepted standard ohf-target-projection/1, not an abbreviated display."""
    return projection.target_statement(card, line)


def is_card_reference(value):
    """A reference to a value in the same card: {"kind": "card", "pointer": ...}."""
    return isinstance(value, dict) and value.get('kind') == 'card' and isinstance(value.get('pointer'), str)


def card_reference(card, pointer):
    """What a card reference points at, as (kind, text).

    ('text', <the text>) when the pointer leads to a string, to a wrapper whose `value` is a
    string, or to an item whose own `claim_or_ref` states it in words. The reference then claims
    that the source states that text, and resolution decides it by occurrence in the passage.

    ('object', <its id>) when the pointer leads to a part of the card that carries an `id` — an
    evidence line, a prediction, an atom. There is no text for a passage to carry: the reference
    names a part of this card, and what the source states about that part is decided by that
    part's own records, not again here. The id is what is hashed, so repointing the reference at
    another part is a changed value and is resolved again.

    Raises when the pointer leads nowhere, or to something with neither text nor an id.
    """
    node = card_node(card, pointer)
    text = node['value'] if isinstance(node, dict) and 'value' in node else node
    if isinstance(text, str) and text.strip():
        return 'text', text
    claim = node.get('claim_or_ref') if isinstance(node, dict) else None
    if isinstance(claim, dict) and claim.get('kind') == 'literal' and str(claim.get('text', '')).strip():
        return 'text', claim['text']
    if isinstance(node, dict) and isinstance(node.get('id'), str) and node['id'].strip():
        return 'object', node['id']
    raise ValueError(f'card reference {pointer!r} resolves to neither text nor a part of the card with an id '
                     '(point it at a value, or at an evidence line, prediction or atom)')


def card_target(card, pointer):
    """The text a card reference points at, for a pointer that leads to text."""
    kind, text = card_reference(card, pointer)
    if kind != 'text':
        raise ValueError(f'card reference {pointer!r} does not resolve to text')
    return text


def card_node(card, pointer):
    """The node at a JSON pointer of the card, or ValueError."""
    if not pointer.startswith('/'):
        raise ValueError(f'card reference {pointer!r} is not a JSON pointer')
    node = card
    for part in pointer[1:].split('/'):
        part = part.replace('~1', '/').replace('~0', '~')
        if isinstance(node, list) and part.isdigit() and int(part) < len(node):
            node = node[int(part)]
        elif isinstance(node, dict) and part in node:
            node = node[part]
        else:
            raise ValueError(f'card reference {pointer!r} does not resolve in the card')
    return node


def inner_targets(card, value):
    """{pointer: what it names} for every card reference inside a list value (for example
    also_expected_under: [{"kind": "alternative", "ref": {"kind": "card", "pointer": ...}}]).
    An alternative item is named by its claim text; other targets by their text or value."""
    out = {}
    if not isinstance(value, list):
        return out
    for item in value:
        ref = item.get('ref') if isinstance(item, dict) else None
        if is_card_reference(ref):
            node = card_node(card, ref['pointer'])
            claim = node.get('claim_or_ref') if isinstance(node, dict) else None
            if isinstance(claim, dict) and claim.get('kind') == 'literal':
                out[ref['pointer']] = claim['text']
            elif isinstance(node, dict) and 'value' in node:
                out[ref['pointer']] = node['value']
            else:
                out[ref['pointer']] = node
    return out


def checked_value(card, pointer, node):
    """The value the checker judges. An evidence line's direction and indirectness are given with
    what the line's target states and with the line's own quotation, so that "supports" and
    "serious" each have an object: a direction is a relation between this line's finding and the
    target claim, and an indirectness is the distance between the study and that claim. Neither can
    be judged from the passage alone, and a checker shown only the passage answers about the
    paragraph's overall tenor instead (measured: 18 of the 49 partial records on the two accepted
    flagship cards). A reference to a value in the same card is given with the text it points at,
    or, for a reference to a part of the card, with the id of that part under `names`; either way it
    is decided by resolution, not by the checker (entailment.resolve)."""
    m = TAXON_ID.match(pointer)
    if m:
        # A passage cannot entail an NCBI identifier: the id's truth is in the recorded efetch call,
        # which is what its `src` points at, and that is resolution rather than reading (resolution.md).
        # What a reader of prose can answer is the other half - whether the passage names **that taxon**
        # - so the item carries the id together with the word the line states for it.
        system = card['added']['layers']['predictions'][int(m.group(1))].get('system') or {}
        out = {'taxon_id': node['value']}
        taxon = system.get('taxon')
        if isinstance(taxon, dict) and 'value' in taxon:
            out['taxon'] = taxon['value']
        return out
    m = LINE_FIELD.match(pointer)
    if m and m.group(2) in WITH_TERM:
        line = card['added']['layers']['evidence']['lines'][int(m.group(1))]
        out = {m.group(2): node['value'], 'term': node.get('term')}
        if node.get('note'):
            out['note'] = node['note']
        if isinstance(line.get('quote'), str):
            out['line_quote'] = line['quote']
        return out
    if m and m.group(2) in WITH_QUOTE:
        line = card['added']['layers']['evidence']['lines'][int(m.group(1))]
        out = {m.group(2): node['value']}
        if isinstance(line.get('quote'), str):
            out['line_quote'] = line['quote']
        return out
    if m and m.group(2) in WITH_TARGET:
        return projection.checked_relation(card, pointer, node)
    if is_card_reference(node.get('value')):
        kind, text = card_reference(card, node['value']['pointer'])
        return {'reference': node['value'], ('target' if kind == 'text' else 'names'): text}
    if ELEMENT_POINTER.match(pointer):
        # The element itself is the value, without the `src` that says where to read it.
        return {k: v for k, v in node.items() if k != 'src'}
    if pointer in ELEMENT_SRC_LISTS and isinstance(node.get('value'), list):
        # The list, less the elements that name their own paragraph: each of those is judged against
        # the paragraph it names, and judging it here a second time would ask a reader about a
        # paragraph it was never in.
        kept = [e for e in node['value'] if not (isinstance(e, dict) and 'src' in e)]
        return kept
    targets = inner_targets(card, node.get('value'))
    if targets:  # the checker judges the claim the references name, so it is shown them
        return {'value': node['value'], 'targets': targets}
    return node.get('value')


def sourced(card):
    """(pointer, node) of every added value that names a src and goes to the checker.

    An element of one of ELEMENT_SRC_LISTS that names its own src is one of these in its own right:
    it is read against the paragraph it names, and the value of its list is sent without it."""
    out = []

    def walk(o, p):
        if isinstance(o, dict):
            if 'src' in o and (not skip(p, o) or ELEMENT_POINTER.match(p)):
                out.append((p, o))
            for k, v in o.items():
                walk(v, f'{p}/{k}')
        elif isinstance(o, list):
            for i, v in enumerate(o):
                walk(v, f'{p}/{i}')
    walk(card['added']['layers'], '/added/layers')
    return out


def value_items(card):
    """The checker items without their src passages: dicts with pointer, basis, value, and
    either 'src' (the passage is a paragraph of a source) or 'source_passage' (a basis_quote)."""
    items = []
    for p, node in sourced(card):
        value = checked_value(card, p, node)
        items.append({'pointer': p, 'basis': 'src', 'value': value, 'src': node['src']})
        if 'basis_quote' in node:
            items.append({'pointer': p, 'basis': 'basis_quote', 'value': value, 'source_passage': node['basis_quote']})
    return items


# ------------------------------------------------------------------ hashes and the ledger

def _sha(data):
    return 'sha256:' + hashlib.sha256(data).hexdigest()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')


def value_sha256(value):
    return _sha(canonical(value))


def passage_sha256(passage):
    return _sha(passage.encode('utf-8'))


def note_sha256(note):
    return _sha(note.encode('utf-8'))


def key_of(x):
    return f"{x['pointer']}|{x['basis']}"


# Worst first: a record shows the worst verdict among the checks of the same text.
RANK = {'no': 0, 'partial': 1, 'entails': 2}


def entry(item, record, binding=None):
    """The ledger entry for a checker item (with its source_passage) and its record.

    A resolution verdict also writes **which resolver made it**, by the three members of its identity.
    Without that the entry says only `entails`, and an entry made under an earlier binding rule cannot
    be told from one made under the rule in force: raising the rule would then change nothing for any
    value already in a ledger. An entry written before this (there are such entries in the accepted
    cards' ledgers) carries no `resolver`, which is itself the answer - it was not made under the
    current rule, so it holds rather than backs.
    """
    e = {'value_sha256': value_sha256(item['value']), 'passage_sha256': passage_sha256(item['source_passage']),
         'checked_at': record['checked_at'], 'verdict': record['verdict']}
    if record.get('note'):
        e['note_sha256'] = note_sha256(record['note'])
    if binding is not None:
        if not isinstance(binding, checker_io.ItemBinding):
            raise ValueError('checker binding requires verified frozen IO, not an arbitrary dictionary')
        e['checker_binding'] = copy.deepcopy(binding.data)
        if not projection.valid_binding(item, e):
            raise ValueError('checker input/result binding does not describe this value/passage/result')
    if projection.is_projected(item):
        target = projection.target_of(item)
        e.update(target_projection=projection.TARGET_PROJECTION,
                 target_sha256=projection.value_sha256(target))
        proof_set = {binding.data['result_binding_sha256']:binding.proof} if isinstance(binding, checker_io.ItemBinding) else {}
        if not projection.eligible(item, e, proof_set):
            raise ValueError('relational entry requires frozen checker input/result binding; no hash-stamping old verdicts')
    checker = record.get('checker') or {}
    if checker.get('name') == RESOLVER_NAME:
        e['resolver'] = {member: checker.get(member) for member in RESOLVER_IDENTITY}
        # and the inputs the verdict rested on, so that a changed source invalidates it. A record made
        # without the sources open records none, and such an entry is never reused while they are.
        if record.get('resolver_inputs') is not None:
            e['resolver_inputs'] = record['resolver_inputs']
    return e


def new_ledger(card, entries=None, notes=None, checker_io_proofs=None):
    return {'format': FORMAT, 'canonicalisation': CANONICALISATION, 'card_id': card['id'],
            'card_version': card.get('version'), 'proposition_version': card.get('identity', {}).get('version'),
            'target_projection': projection.TARGET_PROJECTION, 'producer_contract': projection.PRODUCER_CONTRACT,
            'content_hash': card.get('content_hash'), 'entries': entries or {}, 'notes': notes or {},
            'checker_io_proofs': checker_io_proofs or {}}


def upgrade(ledger):
    """A ledger in format /2: format /1 entries become lists of one. None stays None."""
    if ledger is None or ledger.get('format') not in FORMATS:
        return ledger
    out = dict(ledger)
    entries = ledger.get('entries') or {}
    out['entries'] = {k: (list(v) if isinstance(v, list) else [v]) for k, v in entries.items()}
    out['notes'] = dict(ledger.get('notes') or {})
    out['format'] = FORMAT
    out['canonicalisation'] = CANONICALISATION
    return out


def add_entry(ledger, key, e, note=None):
    """Append a check to the history of `key`, in time order, unless an identical entry is
    there. No entry is ever removed or rewritten. Returns True when it was added."""
    history = ledger['entries'].setdefault(key, [])
    if note:
        ledger['notes'][note_sha256(note)] = note
    if e in history:
        return False
    history.append(e)
    history.sort(key=lambda x: x['checked_at'])  # stable: equal times keep their order
    return True


# The resolver now in force, by the three members that make two resolvers the same one. The binding
# rule is part of the identity because a resolution verdict is only as good as the rule that produced
# it: version 1 decided a cited item by the card's own consistency, version 2 decides it against the
# saved sources, and a verdict made under the first does not become a verdict under the second by
# sitting in the ledger. It lives here, on the reading side, so that reading a ledger and writing one
# cannot drift apart.
RESOLVER_NAME = 'ohf-reference-resolution'
RESOLVER_VERSION = '2.0.0'
# The rule the current version resolves by, for messages. It is **not** a member of the identity: the
# standard's `checker` object allows no extra properties, and a card carrying one fails validate - which
# is how this was found, on the first card built with fresh resolution records. The version carries the
# rule instead, and the convention is the point: **raise the version whenever the binding rule
# changes.** Version 1.0.0 resolved a cited item by the card's own consistency; 2.0.0 resolves it
# against the saved sources.
RESOLVER_BINDING_RULE = 'saved-sources@2 (version 2.0.0)'
RESOLVER_IDENTITY = {'name': RESOLVER_NAME, 'version': RESOLVER_VERSION}


def _resolver_of(x):
    """The resolver named by a card record (`checker`) or by a ledger entry (`resolver`), or {}.

    The two shapes are the same fact written in the two places it has to be written: a record says who
    checked it, an entry says who checked that text, and a verdict is reused from the entry.
    """
    x = x or {}
    if isinstance(x.get('resolver'), dict):
        return x['resolver']
    checker = x.get('checker') or {}
    return checker if checker.get('name') == RESOLVER_NAME else {}


def by_resolver(x):
    """Whether a record or entry was made by a resolver at all (as against a model checker)."""
    return bool(_resolver_of(x))


def by_current_resolver(x):
    """Whether a record or entry was made by the resolver now in force, binding rule included."""
    resolver = _resolver_of(x)
    return bool(resolver) and all(resolver.get(member) == value for member, value in RESOLVER_IDENTITY.items())


def superseded(history):
    """The resolutions of a history that an earlier binding rule produced.

    They stay in the ledger - a history is only ever appended to - and they authorise nothing: the key
    is held until it is resolved again under the current rule.
    """
    return [e for e in history if by_resolver(e) and not by_current_resolver(e)]


def active(history, value_sha, passage_sha=None, resolved=False, inputs=None, item=None, proofs=None):
    """The checks of the value as it now stands (and of its passage, when that is known).

    `resolved=True` for a value decided by resolution: then a check counts only if the resolver now in
    force made it. Without that, raising the binding rule would change nothing for any value already
    in a ledger - the old verdict would be found here and reused, so the new rule would hold for a card
    checked today and not for one checked yesterday.

    `inputs` are the digests the resolution rests on now (`entailment.resolution_inputs`): the saved
    sources it consults, by file name. A check counts only if it recorded the same ones. The value and
    the passage can both be untouched while a **source** changes - an item naming `(C.xml, digest C)`
    is the same value after C.xml is refetched and hashes to something else - and a verdict reused
    there would be a verdict about bytes that are gone. Where `inputs` is None the sources were not
    opened, so nothing here can say whether they moved, and the recorded digests are not compared.
    """
    out = [e for e in history if e['value_sha256'] == value_sha
           and (passage_sha is None or e['passage_sha256'] == passage_sha)]
    if item is not None:
        out = [e for e in out if projection.eligible(item, e, proofs)]
    if not resolved:
        return out
    out = [e for e in out if by_current_resolver(e)]
    if inputs is None:
        return out
    return [e for e in out if e.get('resolver_inputs') == inputs]


def choose(entries, not_before=None):
    """The check a record shows: the worst verdict; on a tie, the earliest check of that
    verdict that is not older than `not_before` (the latest assessment the value carries),
    else the earliest. The tie-break never changes the verdict shown; it keeps a record from
    predating its assessment when a later check of the same verdict exists."""
    if not entries:
        return None
    worst = min(RANK[e['verdict']] for e in entries)
    tied = sorted((e for e in entries if RANK[e['verdict']] == worst), key=lambda e: e['checked_at'])
    if not_before:
        later = [e for e in tied if e['checked_at'] >= not_before]
        if later:
            return later[0]
    return tied[0]


def reads_a_passage(card, src):
    """Whether the source `src` names something a passage can be read from.

    A document source's locator names a paragraph, a page or a table of that document — the forms
    `ohfkit.para_number` knows, plus a table-wrap. A source that is the record of a database call
    carries a locator in prose ("NCBI Taxonomy: Homo sapiens") and a tool that names the call: there
    is no passage, so a value citing it cannot be checked against one and is decided by resolution.
    An unknown src reads no passage either, and the error for that is raised where the src is used.
    """
    rec = (card['added'].get('sources') or {}).get(src)
    if not rec:
        return False
    locator = rec.get('locator') or ''
    return bool(re.search(r'\.//p\[\d+\]', locator)
                or re.match(r'(?:PDF page|HTML <p>|HTML block|API record field|Submitted text paragraph) \d+',
                            locator)
                or 'table-wrap' in locator
                or locator.startswith('XML .//'))


def not_before(card, node):
    """The earliest time a check of this value could have seen what it claims to have seen:
    the later of the latest assessment inside the value and the access time of the source
    record it cites. A check made before the value was assessed does not cover that
    assessment; a check made before the passage was retrieved cannot have read it.

    `choose` uses this to break a tie between checks of one text. Added in 0.8.16, after a
    carried check that predated the re-fetch of its source was kept by carry and then refused
    by the standard's check_refs, with no way out: re-checking did not help, because the
    tie-break preferred the earliest check of the same verdict, which was the stale one.
    """
    times = [t for t in (latest_assessment(node), source_access(card, node.get('src'))) if t]
    return max(times) if times else None


def source_access(card, src):
    """The accessed_at of a source record, or None."""
    rec = (card.get('added', {}).get('sources') or {}).get(src)
    return rec.get('accessed_at') if isinstance(rec, dict) else None


def latest_assessment(node):
    """The latest assessed_at inside a value node, or None."""
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
    walk(node)
    return max(times) if times else None


def unknown_verdicts(ledger):
    """Keys with an entry whose verdict is not one of RANK."""
    return {k for k, history in ledger['entries'].items() for e in history if e.get('verdict') not in RANK}


def by_passage(entries):
    """The entries grouped by the passage they were checked against."""
    groups = {}
    for e in entries:
        groups.setdefault(e.get('passage_sha256'), []).append(e)
    return groups


def disputed(entries):
    """Whether the checks of this value **against one passage** disagree.

    A value with several passages - a `src` paragraph and a `basis_quote`, or two sources that state
    it - is asked a separate question for each, and two answers to two questions are not a
    disagreement. Counting them as one was over-reporting: the acceptor measured it on an accepted
    card, where 11 keys held differing verdicts and not one of them differed within a single passage.
    What those 11 are is reported, under its own name, by `several_passages`.
    """
    return any(len({e['verdict'] for e in group}) > 1 for group in by_passage(entries).values())


def several_passages(entries):
    """Whether the verdicts differ only between passages: different questions, different answers."""
    return not disputed(entries) and len({e['verdict'] for e in entries}) > 1


def _kit_repo(here):
    """ohfkit.REPO when this file sits in the ohf-extractor scripts/, else None."""
    if not (here / 'ohfkit.py').exists():
        return None
    if str(here) not in sys.path:
        sys.path.insert(0, str(here))
    import ohfkit
    return ohfkit.REPO


def _content_hash():
    """tools/content_hash.content_hash of the OHF repository: found next to this file when it
    sits in the repository's tools/, else through OHF_REPO, else the repository the kit names."""
    here = Path(__file__).resolve().parent
    for root in (here.parent, os.environ.get('OHF_REPO'), _kit_repo(here)):
        if root and (Path(root) / 'tools' / 'content_hash.py').exists():
            if str(root) not in sys.path:
                sys.path.insert(0, str(root))
            from tools.content_hash import content_hash
            return content_hash
    raise RuntimeError('tools/content_hash.py not found: run from the OHF repository or set OHF_REPO')


RESOLVER_NAME = 'ohf-reference-resolution'


def earlier_renderings(card, pointer, node):
    """The values this kit used to show for `pointer`, before the rendering it uses now.

    A rendering is the kit's work and not the card's text, so a record made under an earlier one is
    honoured for reading. That only works if the kit remembers what its earlier renderings were:
    until 0.9.0 a direction was shown as the bare value and then as {direction, target_statement},
    and an indirectness as the bare value alone. Each is listed here, newest first, and a record is
    matched against them in turn. A rendering that is dropped from this list makes every record made
    under it unreadable, which is why the list grows and is never shortened.
    """
    out = []
    if 'value' in node:
        bare = node['value']
        m = LINE_FIELD.match(pointer)
        if m and m.group(2) in WITH_TARGET:
            line = card['added']['layers']['evidence']['lines'][int(m.group(1))]
            try:
                target = target_statement(card, line)
            except ValueError:
                target = None
            if target is not None:
                # 0.8.x: a direction with its target and no quotation of the line's own.
                out.append({m.group(2): bare, 'target_statement': target})
        out.append(bare)
    return out


def rendered_before(node, item, record, history, card=None, pointer=None):
    """The entries of a record whose check predates the kit's present way of showing the value.

    The kit shows a value to the checker in a rendering: a bare value, a direction with what its
    target states, a reference with the text or the part of the card it names. A rendering is the
    kit's work, not the card's text, so a new rendering is not a change the converter made, and a
    record made under the earlier one is honoured for reading rather than failed. It is honoured
    only where the card itself cannot have changed under it: the record was made by a checker that
    is not the resolver, so it predates resolution, and the card's own bare value is what was
    hashed. Such a record is re-resolved at the card's next rebuild; the caller is told, because a
    record read this way is not a record made under the rule now in force.
    """
    if projection.is_projected(item):
        return []  # legacy reading cannot authorize a full-context producer contract
    if record is None:
        # A value the card has no record for at all: there is no earlier rendering to honour, and
        # the caller says plainly that the value has never been checked.
        return []
    if (record.get('checker') or {}).get('name') == RESOLVER_NAME:
        return []
    if 'value' not in node or node['value'] == item['value']:
        return []
    for earlier in (earlier_renderings(card, pointer, node) if card is not None else [node['value']]):
        if earlier == item['value']:
            continue
        found = active(history, value_sha256(earlier))
        if found:
            return found
    return []


def _active_for(node, key, item, record, history, passages, legacy=None, card=None, inputs=None, proofs=None):
    """(active entries, error) for a card record. Without the src passage (no WORKDIR), the
    passage is taken to be the one the record's own entry was checked against."""
    vsha = value_sha256(item['value'])
    by_value = active(history, vsha, item=item, proofs=proofs)
    if projection.is_projected(item) and not by_value:
        return [], (f'{key}: missing/stale target projection or frozen input/result binding; '
                    'preserve historical entries, do not rehash an old verdict into current support')
    # A value decided by resolution, whose checks were all made under an earlier binding rule. The
    # checks stay in the history and they do not back the record: a verdict produced by the question
    # the kit used to ask is not a verdict on the question it asks now. This is the hold - the card
    # says what no current check supports until the resolution pass is run again, which needs no model
    # call, only the saved sources.
    held = [e for e in by_value if by_resolver(e)]
    if (held and len(held) == len(by_value) and not any(by_current_resolver(e) for e in by_value)) or \
            (by_resolver(record) and not by_current_resolver(record)):
        return [], (f'{key}: superseded_resolution - the record was resolved under binding rule '
                    f'version {(((held or [record])[0].get("checker")) or {}).get("version") or "1 (unnamed)"}, '
                    f'and the rule in force is {RESOLVER_BINDING_RULE}. The old verdict stays in the '
                    'ledger as history and backs nothing: re-run the resolution pass against the saved '
                    'sources (entailment.py carry, or merge) and the new verdict is appended beside it')
    # A resolution of the rule in force, made when its sources hashed to something else. Held for the
    # same reason: the verdict is about bytes this card's manifest no longer holds.
    if inputs is not None and held and not any(e.get('resolver_inputs') == inputs for e in held):
        was = next((e.get('resolver_inputs') for e in held if e.get('resolver_inputs') is not None), None)
        return [], (f'{key}: superseded_resolution - the record was resolved against '
                    f'{was if was is not None else "sources it did not record"}, and the saved sources '
                    f'now hash to {inputs}. The old verdict stays in the ledger as history: re-run the '
                    'resolution pass and the new verdict is appended beside it')
    if not by_value:
        earlier = rendered_before(node, item, record, history, card, item.get('pointer'))
        if earlier:
            if legacy is not None:
                legacy.append(key)
            by_value, vsha = earlier, earlier[0]['value_sha256']
        elif record is None:
            return [], (f'{key}: the card has no entailment record and the ledger holds no check of this '
                        'value (a value added since the last pass: run the pass on it and merge)')
        else:
            return [], (f'{key}: the value differs from the value that was checked (it changed after the '
                        'entailment pass: re-run the pass on it and merge)')
    passage = item.get('source_passage', (passages or {}).get(key))
    if passage is not None:
        act = active(by_value, vsha, passage_sha256(passage), item=item, proofs=proofs)
        if not act:
            return [], (f'{key}: the passage differs from the passage that was checked (src or quotation '
                        'changed after the entailment pass: re-run the pass on it and merge)')
        return act, None
    own = [e for e in by_value if record and e['checked_at'] == record['checked_at']
           and e['verdict'] == record['verdict']]
    return (active(by_value, vsha, own[0]['passage_sha256']) if own else by_value), None


def check(card, ledger, passages=None, legacy=None, inputs=None, *, expected_items=None):
    """Errors, each with how to fix it. `passages` maps "<pointer>|src" to the passage text
    read from the source documents; without it, src passages are not checked. Keys whose record
    was read under an earlier rendering of the value are appended to `legacy` (see
    rendered_before): they are not errors, and they are re-resolved at the next rebuild.

    `inputs` maps the same keys to the digests a resolution of that value rests on now
    (`entailment.resolution_inputs`). With it, a resolution whose sources have moved since it was made
    is held like one made under an earlier rule: the value and the passage can be untouched while a
    source is refetched, and a verdict about bytes that are gone is not a verdict about this card.
    Without it the sources were not opened, and nothing here pretends to know whether they moved."""
    errors = []
    if ledger is None:
        return [f'no entailment ledger (merge writes WORKDIR/{LEDGER_NAME}; re-run the entailment pass '
                'and merge, or carry from the previous card)']
    if ledger.get('format') not in FORMATS:
        return [f'ledger format {ledger.get("format")!r} is not one of {FORMATS} (write it with entailment.py merge)']
    led = upgrade(ledger)
    if led.get('card_id') != card.get('id'):
        errors.append(f'ledger is for card {led.get("card_id")!r}, not {card.get("id")!r} (use the ledger of this card)')
    actual = _content_hash()(card)
    if card.get('content_hash') != actual:
        errors.append(f'card content_hash {card.get("content_hash")} is not its hash {actual} (the card changed '
                      'after it was hashed: rebuild, then carry and merge)')
    elif led.get('content_hash') != actual:
        errors.append(f'ledger content_hash {led.get("content_hash")} is not the card\'s {actual} (the card '
                      'changed after the last merge or carry: carry, re-check what changed, merge)')
    entries, notes = led['entries'], led['notes']
    bad = unknown_verdicts(led)
    for k in sorted(bad):
        errors.append(f'{k}: ledger entry with a verdict not in {sorted(RANK)} (the ledger was not written '
                      'by entailment.py merge: rebuild it from the checker outputs)')
    try:
        nodes = dict(sourced(card))
        items = {key_of(x): x for x in (value_items(card) if expected_items is None else expected_items)}
    except ValueError as error:
        return errors + [f'cannot rebuild current scientific input: {error}']
    if any(projection.is_projected(x) for x in items.values()):
        if (led.get('target_projection') != projection.TARGET_PROJECTION
                or led.get('producer_contract') != projection.PRODUCER_CONTRACT
                or led.get('card_version') != card.get('version')
                or led.get('proposition_version') != card.get('identity', {}).get('version')):
            errors.append('ledger projection/producer/version envelope differs; explicit current lineage required')
    records = {key_of(r): r for r in card['added']['integrity']['entailment']}
    for k in items.keys() - records.keys():
        p, b = k.rsplit('|', 1)
        if not reads_a_passage(card, nodes[p].get('src')):
            # OHF 1.1: a value may cite a record of a database call rather than a passage of a
            # document — a taxon id from NCBI Taxonomy, a rung of closeness derived from it. Its src
            # names a call, its locator says what was read, and no paragraph exists to check it
            # against: it is decided by resolution, and the kit writes that record at the next merge
            # or carry rather than demanding one here. Asking a checker to read a passage that does
            # not exist is the defect this avoids, not the missing record.
            continue
        errors.append(f'{p} ({b}): no entailment record (run the entailment pass on it)')
    for k in records.keys() - items.keys():
        p, b = k.rsplit('|', 1)
        errors.append(f'{p} ({b}): record for a value that is not sourced (remove the record)')
    for k, r in records.items():
        history = entries.get(k) or []
        if k in bad:
            continue
        if not history:
            errors.append(f'{k}: entailment record with no ledger entry (its checked text is unknown: '
                          're-run the entailment pass on it and merge)')
            continue
        x = items.get(k)
        if x is None:
            continue
        act, err = _active_for(nodes[x['pointer']], k, x, r, history, passages, legacy, card,
                               (inputs or {}).get(k), led.get('checker_io_proofs'))
        if err:
            errors.append(err)
            continue
        worst = choose(act, not_before(card, nodes[x['pointer']]))
        if RANK.get(r['verdict'], -1) > RANK[worst['verdict']]:
            errors.append(f"{k}: verdict {r['verdict']!r} in the card, {worst['verdict']!r} in the ledger is the "
                          f"worst check of this text, at {worst['checked_at']} (never edit a verdict by hand; "
                          'a later check does not hide an earlier one: entailment.py merge writes the record)')
            continue
        if not any(e['verdict'] == r['verdict'] and e['checked_at'] == r['checked_at'] for e in act):
            errors.append(f"{k}: no ledger entry for this text backs the record ({r['verdict']!r} checked at "
                          f"{r['checked_at']}): the record does not come from a merge of this ledger")
            continue
        if (r['verdict'], r['checked_at']) != (worst['verdict'], worst['checked_at']):
            errors.append(f"{k}: the record shows the check at {r['checked_at']}, but the rule shows the worst "
                          f"verdict, earliest on a tie (not older than its assessment): {worst['verdict']!r} at "
                          f"{worst['checked_at']} (merge or restore writes the record)")
            continue
        if projection.is_projected(x) and r.get('checker') != worst['checker_binding'].get('checker'):
            errors.append(f'{k}: displayed checker differs from frozen input/result configuration')
            continue
        if 'note_sha256' in worst:
            if r.get('note') is None or note_sha256(r['note']) != worst['note_sha256']:
                errors.append(f'{k}: the note in the card is not the note of the check it shows (never edit a '
                              'note by hand)')
            elif worst['note_sha256'] not in notes:
                errors.append(f'{k}: the ledger has no text for note {worst["note_sha256"]}')
    return errors


def summary(card, ledger, passages=None):
    """(disputed keys, history entries, keys only in the history, keys with several passages).

    A key is **disputed** when two checks of its current text **against one passage** disagree; that
    is information. A key whose verdicts differ only between passages is not disputed: one value with
    two passages was asked two questions. The two were counted together until the acceptor measured
    the difference on an accepted card, and they are reported apart now."""
    led = upgrade(ledger)
    if not led or led.get('format') != FORMAT:
        return [], 0, 0, []
    items = {key_of(x): x for x in value_items(card)}
    records = {key_of(r): r for r in card['added']['integrity']['entailment']}
    nodes = dict(sourced(card))
    out, several = [], []
    bad = unknown_verdicts(led)
    for k, history in led['entries'].items():
        if k in items and k not in bad:
            act, err = _active_for(nodes[items[k]['pointer']], k, items[k], records.get(k), history,
                                   passages, None, card, proofs=led.get('checker_io_proofs'))
            if err:
                continue
            worst = choose(act, not_before(card, nodes[items[k]['pointer']]))
            line = (f"{k}: {', '.join(e['verdict'] + ' ' + e['checked_at'] for e in act)}; shown: "
                    f"{worst['verdict']} {worst['checked_at']}")
            if disputed(act):
                out.append(line)
            elif several_passages(act):
                several.append(f'{line} (one value, {len(by_passage(act))} passages: that many questions)')
    n = sum(len(v) for v in led['entries'].values())
    return sorted(out), n, len(led['entries'].keys() - items.keys()), sorted(several)


def source_passages(card, workdir):
    """Passages of the src items, read from the downloaded sources with the ohf-extractor readers."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        import entailment
    except ImportError as e:
        raise RuntimeError(f'passage binding needs the ohf-extractor readers (entailment.py next to this file): {e}')
    docs = entailment.docs_for(card, workdir)
    return {key_of(x): x['source_passage'] for x in entailment.build(card, docs) if x['basis'] == 'src'}


def load(path):
    path = Path(path)
    return json.loads(path.read_text()) if path.exists() else None


def print_summary(card, ledger, passages=None):
    keys, n, only, several = summary(card, ledger, passages)
    for line in keys:
        print('DISPUTED', line)
    for line in several:
        print('PASSAGES', line)
    print(f'LEDGER HISTORY {n} entries, {len(keys)} disputed keys, {len(several)} keys checked against '
          f'several passages, {only} keys only in the history')


def main(argv):
    if len(argv) not in (2, 3):
        sys.exit(__doc__)
    card = json.loads(Path(argv[0]).read_text())
    ledger = load(argv[1])
    passages = source_passages(card, argv[2]) if len(argv) == 3 else None
    errors = check(card, ledger, passages)
    for e in errors:
        print('FAIL', e)
    if ledger is not None and ledger.get('format') in FORMATS:
        print_summary(card, ledger, passages)
    scope = 'values, verdicts and passages' if passages is not None else 'values and verdicts (src passages not checked)'
    print('LEDGER CHECK', 'FAIL' if errors else 'PASS', len(errors), f'[{scope}]')
    return 1 if errors else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
