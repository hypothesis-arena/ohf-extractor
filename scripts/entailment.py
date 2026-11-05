"""Build the input of the separate entailment pass, and merge its verdicts back.

Usage:
  entailment.py input CARD WORKDIR OUT.json     # every sourced added value, with its passage
  entailment.py merge CARD WORKDIR INPUT.json OUTPUT.json   # write verdicts with the current time
  entailment.py carry OLD_CARD CARD WORKDIR REST.json [--recheck REGEX]  # after a rebuild
  entailment.py export CARD WORKDIR LEDGER.json  # check the ledger, then copy it (examples/ledgers/)
  entailment.py restore CARD WORKDIR ARCHIVED_CARD [ARCHIVED_CARD...]  # put back lost checks

`merge` rebuilds the items from the current card and refuses if any value or passage differs
from INPUT.json: a verdict is written only for the text the checker saw. It appends each check
(the hashes of that text, the time, the verdict, the note) to the history in
WORKDIR/entailment-ledger.json, and then sets every record of the card from the ledger: the
worst verdict among the checks of the value and passage as they now stand, the earliest on a
tie. Re-running the checker on the same text cannot replace a 'no' with an 'entails'
(check_ledger.py says what the ledger holds and how it is checked). No command removes or
rewrites a ledger entry.

A builder writes the card from scratch, so a rebuild drops its entailment records. `carry`
sets a record of the rebuilt card from the ledger, by the same rule, only when the ledger has
a check of exactly the new card's value and passage and the check shown is not older than an
assessment it covers; everything else goes to REST.json for a new checker run.

`restore` puts back checks that an earlier ledger lost (a /1 ledger kept one check per value):
for each record of an archived merged card it hashes THAT card's value and passage, appends
the check with its original time, verdict and note unless the same entry is there, and then
sets the card's records from the ledger. Notes are kept in the ledger's "notes", keyed by
note_sha256. Both inputs are rebuilt with the current
script, so after a change to what the checker is shown, name the affected pointers with
--recheck.

A reference to a value in the same card ({"kind": "card", "pointer": ...}, such as a
prediction's test_plan_ref) is not sent to the checker. It is decided by resolution
(references/resolution.md): the pointer must resolve to text in the card, and that text must
occur in the passage of the source the value's src names. `merge` and `carry` write these
verdicts to the ledger, as checks by RESOLVER, for every reference with no check of its
current text.

The checker sees only ENTAILMENT-PROMPT.md and the input file. It must not see the
conversion, the article or this card, so that its verdict rests on the passage alone.
"""
import copy
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_ledger  # noqa: E402
import ohfkit  # noqa: E402

PROMPT = ohfkit.REPO / 'examples/cards/ENTAILMENT-PROMPT.md'
CHECKER = {'name': 'ohf-entailment-check', 'version': '1.0.0',
           'prompt_sha256': ohfkit.sha256(PROMPT.read_bytes())}
RESOLUTION = Path(__file__).resolve().parent.parent / 'references/resolution.md'
# The resolver's identity carries the **version of the binding rule**, because a resolution verdict is
# only as good as the rule that produced it. Version 1 decided a cited item by the card's own
# consistency; version 2 decides it against the saved sources, and an independent review showed why
# that difference matters. Without the version in the identity, a verdict made under version 1 sits in
# the ledger with the same checker as a verdict made under version 2 and is reused from there: the new
# rule would hold for a card checked today and not for any card checked before it. Raising the version
# makes every earlier resolution inactive - it stays in the history, which is only ever appended to,
# and it no longer authorises anything - so each such key is resolved again, against the manifest.
RESOLVER = {**check_ledger.RESOLVER_IDENTITY,
            'prompt_sha256': ohfkit.sha256(RESOLUTION.read_bytes())}
# What makes two resolvers the same resolver is declared by the reading side, with the predicates that
# use it: a record from an earlier binding rule stays in the ledger as history and authorises nothing.
by_current_resolver, superseded = check_ledger.by_current_resolver, check_ledger.superseded
SKIP_PREFIXES, LINE_FIELDS, LINE_FIELD, WITH_TARGET = (check_ledger.SKIP_PREFIXES, check_ledger.LINE_FIELDS,
                                                    check_ledger.LINE_FIELD, check_ledger.WITH_TARGET)
skip, target_statement, checked_value, sourced = (check_ledger.skip, check_ledger.target_statement,
                                                  check_ledger.checked_value, check_ledger.sourced)


def metadata_passage(doc, locator):
    """Read only explicitly named direct children of the article's front metadata.

    Keep their complete XML text, in document order, separated by a newline. No title
    inference, whitespace rewriting, arbitrary XPath or deterministic verdict is involved.
    """
    match = re.fullmatch(r'XML \./front/article-meta \(([^()]*)\)', locator)
    if match is None:
        raise ValueError('META_LOCATOR: expected named elements under ./front/article-meta')
    names = [part.strip() for part in match.group(1).split(',')]
    if (any(re.fullmatch(r'[A-Za-z_][A-Za-z0-9_.-]*', name) is None for name in names)
            or len(set(names)) != len(names)):
        raise ValueError('META_LOCATOR: distinct direct element names required; paths are not allowed')
    root = getattr(doc, 'root', None)
    metas = root.findall('./front/article-meta') if root is not None else []
    if len(metas) != 1:
        raise ValueError('META_ROOT: expected exactly one ./front/article-meta')
    elements = [element for element in metas[0] if element.tag in names]
    if set(names) != {element.tag for element in elements}:
        raise ValueError('META_ELEMENT_MISSING: a named article-meta element is absent')
    texts = [''.join(element.itertext()) for element in elements]
    if any(not text.strip() for text in texts):
        raise ValueError('META_ELEMENT_EMPTY: a named article-meta element has no text')
    return '\n'.join(texts)


def passage(card, docs, key):
    rec = card['added']['sources'][key]
    doc = docs[rec['source']]
    loc = rec['locator']
    if loc.startswith('XML ./front/article-meta'):
        return metadata_passage(doc, loc)
    if './/p[' in loc:
        return doc.para(int(loc.split('.//p[')[1].split(']')[0]))
    if loc.startswith(('PDF page ', 'HTML <p> ', 'HTML block ')):
        return doc.para(int(loc.split()[2]))
    if loc.startswith('API record field '):
        return doc.para(int(loc.split()[3]))
    if 'table-wrap' in loc:
        tid = loc.split("@id='")[1].split("'")[0]
        return ohfkit.norm(''.join(doc.root.find(f".//table-wrap[@id='{tid}']").itertext()))
    raise ValueError(f'source {key}: locator {loc} has no passage rule')


def build(card, docs):
    items = []
    for x in check_ledger.value_items(card):
        if 'src' in x:
            x = {'pointer': x['pointer'], 'basis': x['basis'], 'value': x['value'],
                 'source_passage': passage(card, docs, x.pop('src'))}
        items.append(x)
    return [{'id': f'r{i}', **x} for i, x in enumerate(items, 1)]


BY_RESOLUTION = re.compile(r'^/added/layers/evidence/lines/(\d+)/(independence_group|items/\d+)$')


def is_resolved(item):
    """An item decided by resolution, not by the checker.

    Two kinds. A reference to a value in the card — that was always so. And a value that says
    **which work a line rests on**: its `independence_group` and its cited `items[]`. The truth of
    those lies in the line's own cited artifact and in the card's source records, never in the
    prose of a passage, and a checker shown only the passage answers a different question. Measured
    across the two accepted flagship cards: 78 `independence_group` records, of which 76 are
    `entails` with no note — right by accident, because their paragraph happened to name a study —
    one `partial` and one `no`; the acceptor established the cause and the owner asked for this
    fix (K10).
    """
    v = item['value']
    if (isinstance(v, dict) and set(v) in ({'reference', 'target'}, {'reference', 'names'})
            and check_ledger.is_card_reference(v['reference'])):
        return True
    return bool(BY_RESOLUTION.match(item['pointer']))


def checker_items(items):
    """The items the checker is given, numbered again."""
    out = [dict(x) for x in items if not is_resolved(x)]
    for i, x in enumerate(out, 1):
        x['id'] = f'r{i}'
    return out


def resolution_inputs(card, item, docs=None):
    """The digests a resolution of this item rests on: `{file name: sha256}` for every saved source it
    consults, or None where the manifest was not opened.

    Why a resolution has to record this. A ledger entry is keyed by the value and the passage, and
    neither of those changes when a **source** changes: an item naming `(C.xml, digest C)` has the same
    value after C.xml is refetched and hashes to something else, so the cached `entails` was reused for
    a card whose own source no longer matches it. The third input of the verdict is the manifest, and a
    verdict that does not record its inputs cannot be known to be about them. The independent review's
    fourth finding; the fix is the lead's, and general rather than one more case: a cached resolution is
    valid only while the rule version, the passage and these digests are all what they were.
    """
    if docs is None:
        return None
    saved = {doc.file: doc.sha for doc in docs.values() if getattr(doc, 'file', None)}
    m = BY_RESOLUTION.match(item['pointer'])
    if m is None:
        return {}
    lines = card['added']['layers']['evidence']['lines']
    line = lines[int(m.group(1))]
    if m.group(2).startswith('items/'):
        named = {item['value'].get('artifact')}
    else:
        # a group rests on the artifacts of every line in it, which is what its verdict is about
        group = item['value']
        named = {it['value']['artifact'] if isinstance(it.get('value'), dict) else it.get('artifact')
                 for ln in lines if (ln.get('independence_group') or {}).get('value') == group
                 for it in ln.get('items', [])}
        named |= {it['value']['artifact'] if isinstance(it.get('value'), dict) else it.get('artifact')
                  for it in line.get('items', [])}
    # Only the saved sources are recorded, by name: an artifact the manifest does not hold has no
    # digest to record, and that absence is already what makes the verdict `partial`.
    return {name: saved[name] for name in sorted(n for n in named if n in saved)}


def resolve_provenance(card, item, docs=None):
    """(verdict, note) for a value that says which work a line rests on.

    A cited `items[]` resolves against the **saved sources**: the digest it names must be the digest
    of a document the card's own manifest holds (`docs_for`, which opens every source
    `added.sources` names), or of a witness the card records for the converted article. Consistency
    between the items of one card is not membership: a file no source of this card names, with a
    well-formed digest of its own, is self-consistent and binds nothing. Such an item is `partial`
    with `source_not_bound`, not `entails` and not `no` — the bytes may be a real source whose
    manifest entry is missing, and calling that a scientific `no` would say the line is wrong when
    what is missing is the binding. The boundary is the lead's decision of 2026-10-23, after an
    independent review found that the first rule let a foreign file through.

    An `independence_group` is a claim about **where the data come from**, and that is not the same
    as which document a line cites. A Bayesian reanalysis of another study's published dataset
    belongs in that dataset's group while citing its own paper — a real case on the first flagship,
    where `e_dujon_reanalysis` and `e_dujon_longevity` cite Dujon's paper and rest on Vincze's ZIMS
    data, which is exactly why the group exists. So a group whose lines cite more than one artifact
    is **not** a contradiction and is not refused: it resolves to `partial`, with the artifacts named
    and the reason stated. OHF 1.0 has no member in which the card could say which work a group
    names; 1.1's `independence_key` (scheme + id) is where that becomes resolvable, and for a line
    without a key the question stays the cited item. Measuring the strict rule first was what showed
    this: it would have turned 15 correct records into `no` on one card.
    """
    m = BY_RESOLUTION.match(item['pointer'])
    line_no = int(m.group(1))
    lines = card['added']['layers']['evidence']['lines']
    line = lines[line_no]
    arts = {i['value']['artifact'] if isinstance(i.get('value'), dict) else i['artifact']
            for i in line.get('items', []) if isinstance(i, dict)}
    if m.group(2).startswith('items/'):
        # The binding is the **pair**: this artifact with this digest. Where the card records that
        # pair itself it must match; and every item naming the same artifact must name the same
        # digest, because two digests for one file mean one of them is stale or mistyped.
        #
        # In OHF 1.0 `added.sources` carries a URL, a locator and an access time, not a digest, so
        # the card alone cannot say which bytes an added document had. The saved sources can: every
        # document the card names is opened by `docs_for`, and each one knows its own file name and
        # digest. That manifest is what membership is decided against; the converted article has a
        # second witness in `author.source.source_text_sha256` and `added.source_verification.sha256`.
        # A first version of this rule tested the pair against `added.sources` and refused all 80
        # items of the two accepted cards, which is how the gap in 1.0 was found — measured before it
        # was believed. The version after it tested the pair against the card's own items, which an
        # independent review broke with one synthetic file: self-consistent, and bound to nothing.
        art, sha = item['value'].get('artifact'), item['value'].get('sha256')
        if not isinstance(sha, str) or not re.fullmatch(r'(?:sha256:)?[0-9a-f]{64}', sha):
            return 'no', (f'The item names {art!r} with {sha!r}, which is not a sha256 digest, so nothing '
                          'binds this line to any bytes.')
        recorded = {}
        main = card.get('author', {}).get('source', {}).get('source_text_sha256')
        verify = (card['added'].get('source_verification') or {}).get('sha256')
        for other in lines:
            for it in other.get('items', []):
                v = it.get('value') if isinstance(it.get('value'), dict) else it
                if isinstance(v, dict) and v.get('artifact') and v.get('sha256'):
                    recorded.setdefault(v['artifact'], set()).add(v['sha256'])
        clash = sorted(recorded.get(art, set()) - {sha})
        if clash:
            return 'no', (f'The item names ({art!r}, {sha}), while other items of this card name the same '
                          f'artifact with {", ".join(clash)}: one of the digests is stale or mistyped.')
        # Membership, in the order that says the most about what went wrong.
        saved = {doc.file: doc.sha for doc in (docs or {}).values() if getattr(doc, 'file', None)}
        witness = {name: digest for name, digest in
                   (('author.source.source_text_sha256', main), ('added.source_verification.sha256', verify))
                   if digest}
        if docs is None:
            return 'partial', (f'The item names ({art!r}, {sha}), and nothing here can say whether those bytes '
                               'are a source of this card: the saved sources were not opened '
                               '(source_not_bound). Resolve this item where the documents are, which is '
                               'where the passages are read.')
        if art in saved:
            if saved[art] == sha:
                return 'entails', (f'The item names ({art!r}, {sha}), which is the digest of the saved source '
                                   f'of that name' + (' and the digest this card records for the converted '
                                   'article' if sha in witness.values() else '') + '. What the source states '
                                   'is decided by the line\'s own value records.')
            elsewhere = sorted(f for f, s in saved.items() if s == sha)
            return 'no', (f'The item names ({art!r}, {sha}), while the saved source of that name hashes to '
                          f'{saved[art]}: the line does not rest on the bytes it names.' +
                          (f' Those bytes are {", ".join(elsewhere)}.' if elsewhere else ''))
        held = sorted(f for f, s in saved.items() if s == sha)
        if held:
            return 'no', (f'The item names ({art!r}, {sha}), but that digest is the digest of '
                          f'{", ".join(held)}: the pair names one file and the bytes of another.')
        bound = sorted(name for name, digest in witness.items() if digest == sha)
        if bound:
            return 'entails', (f'The item names ({art!r}, {sha}). No saved source has that file name, and the '
                               f'digest is the one this card records at {", ".join(bound)}, so the bytes are '
                               'the converted article\'s and the name is the only thing out of step.')
        return 'partial', (f'The item names ({art!r}, {sha}), which is no saved source of this card '
                           f'({", ".join(sorted(saved)) or "none opened"}) and no digest this card records '
                           '(source_not_bound). The pair is well formed and consistent with the rest of the '
                           'card, and consistency is not membership: these bytes may be a real source whose '
                           'manifest entry is missing, so this is not a `no` about the line either. Add the '
                           'source to the manifest, or correct the item, and it resolves.')
    group = item['value']
    same = [i for i, ln in enumerate(lines)
            if (ln.get('independence_group') or {}).get('value') == group]
    others = {a for i in same for ln in [lines[i]]
              for it in ln.get('items', [])
              for a in [it['value']['artifact'] if isinstance(it.get('value'), dict) else it.get('artifact')]}
    if len(others) > 1:
        return 'partial', (
            f'The group {group!r} holds lines citing more than one artifact '
            f'({", ".join(sorted(str(o) for o in others))}). That is not a contradiction: a reanalysis '
            f'of another study\'s data belongs in that data\'s group while citing its own paper, which '
            f'is what a group is for. It is also not established by the card\'s bytes, because OHF 1.0 '
            f'has no member naming the work a group stands for — 1.1 decides it by independence_key. '
            f'The lines\' own study_type says which case each is.')
    return 'entails', (f'The group {group!r} holds the lines {", ".join(lines[i]["id"] for i in same)}, all '
                       f'resting on {", ".join(sorted(str(a) for a in arts)) or "no cited artifact"}. '
                       'Resolved against the cited artifacts, not against a passage.')


def resolve(item, card=None, docs=None):
    """(verdict, note) for a card reference.

    A reference to text: entails when the text it points at occurs in the passage (both
    whitespace-normalised), else no.

    A reference to a part of the card (an evidence line, a prediction, an atom): entails, because
    the reference names a part of this card by its id and claims nothing about the source. What
    the source states about that part is decided by that part's own records. The check earns its
    place in the ledger through the id it hashes: point the reference at another part and the
    value has changed, so this check no longer binds it and it is resolved again.
    """
    if card is not None and BY_RESOLUTION.match(item['pointer']):
        return resolve_provenance(card, item, docs)
    ptr = item['value']['reference']['pointer']
    if 'names' in item['value']:
        return 'entails', (f'The reference names {item["value"]["names"]!r}, a part of this card at {ptr}. '
                           'This says nothing about the source: what the source states about that part is '
                           'decided by its own records.')
    if ohfkit.norm(item['value']['target']) in ohfkit.norm(item['source_passage']):
        return 'entails', None
    return 'no', (f'The value at {ptr} does not occur in the passage, so the reference does not point at '
                  'text of the cited source.')


def resolve_references(card, docs, ledger):
    """Append a resolution check to the ledger for every reference item that has no check of
    its current value and passage. Returns the new records."""
    at, records = ohfkit.now(), []
    for x in build(card, docs):
        if not is_resolved(x):
            continue
        k = check_ledger.key_of(x)
        # An active record counts only if the resolver now in force made it. A verdict from an earlier
        # binding rule is history, not authority: it is left in the ledger and the key is resolved
        # again here, which appends the new verdict beside the old one.
        inputs = resolution_inputs(card, x, docs)
        if check_ledger.active(ledger['entries'].get(k, []), check_ledger.value_sha256(x['value']),
                               check_ledger.passage_sha256(x['source_passage']),
                               resolved=True, inputs=inputs):
            continue
        verdict, note = resolve(x, card, docs)
        r = {'pointer': x['pointer'], 'basis': x['basis'], 'verdict': verdict,
             'checker': copy.deepcopy(RESOLVER), 'checked_at': at}
        if inputs is not None:
            r['resolver_inputs'] = inputs
        if note:
            r['note'] = note
        check_ledger.add_entry(ledger, k, check_ledger.entry(x, r), note)
        records.append(r)
    return records


def ledger_path(workdir):
    return Path(workdir) / check_ledger.LEDGER_NAME


def read_ledger(card, workdir):
    """The ledger in WORKDIR in format /2 (a /1 ledger is read as lists of one), or a new
    empty one. A ledger of another card is refused."""
    led = check_ledger.load(ledger_path(workdir))
    if led is None:
        return check_ledger.new_ledger(card)
    if led.get('format') not in check_ledger.FORMATS:
        raise ValueError(f'{ledger_path(workdir)}: unknown ledger format {led.get("format")!r}')
    if led.get('card_id') != card['id']:
        raise ValueError(f"{ledger_path(workdir)} is the ledger of {led.get('card_id')!r}, not {card['id']!r}: "
                         'one work directory holds one card')
    return check_ledger.upgrade(led)


def write_ledger(card, workdir, ledger):
    """Write the whole ledger, stamped with the card as it now stands (call after the card
    is rehashed). Every entry it was read with is written back."""
    led = check_ledger.new_ledger(card, ledger['entries'], ledger.get('notes'))
    ledger_path(workdir).write_text(json.dumps(led, indent=1, ensure_ascii=False) + '\n')
    return led


def stale_items(card, docs, inp):
    """Input items whose value or passage is not what the current card would send."""
    now = {(x['pointer'], x['basis']): x for x in build(card, docs)}
    bad = []
    for x in inp:
        cur = now.get((x['pointer'], x['basis']))
        if cur is None:
            bad.append(f"{x['id']} {x['pointer']} ({x['basis']}): no longer a sourced value of the card")
        elif cur['value'] != x.get('value'):
            bad.append(f"{x['id']} {x['pointer']} ({x['basis']}): the value changed after the input was written")
        elif cur['source_passage'] != x.get('source_passage'):
            bad.append(f"{x['id']} {x['pointer']} ({x['basis']}): the passage changed after the input was written")
    return bad


def shown_record(item, ledger, prior=(), not_before=None, inputs=None):
    """The record a card shows for `item`: the worst check of its current value and passage,
    the earliest on a tie not older than `not_before` (check_ledger.choose), or None when no
    check of that text exists.
    The note comes from the ledger's notes; the checker from a prior record of that check."""
    k = check_ledger.key_of(item)
    # For a value decided by resolution only the resolver now in force counts. Before this, an old
    # verdict was not merely reused: the line below stamps the current RESOLVER on a record whose
    # entry had no prior record to take a checker from, so a version 1 verdict was written into the
    # card as a version 2 resolution. The card now shows no record for such a value until it is
    # resolved again, which is the hold rather than a relabelled verdict.
    act = check_ledger.active(ledger['entries'].get(k, []), check_ledger.value_sha256(item['value']),
                              check_ledger.passage_sha256(item['source_passage']),
                              resolved=is_resolved(item), inputs=inputs, item=item)
    e = check_ledger.choose(act, not_before)
    if e is None:
        return None
    same = [r for r in prior if check_ledger.key_of(r) == k and r['checked_at'] == e['checked_at']
            and r['verdict'] == e['verdict']]
    r = {'pointer': item['pointer'], 'basis': item['basis'], 'verdict': e['verdict'],
         'checker': copy.deepcopy(same[0]['checker'] if same else RESOLVER if is_resolved(item) else CHECKER),
         'checked_at': e['checked_at']}
    note = ledger['notes'].get(e.get('note_sha256')) or (same[0].get('note') if same else None)
    if note:
        r['note'] = note
    elif e['verdict'] != 'entails':
        raise ValueError(f"{k}: the {e['verdict']} check at {e['checked_at']} has no note in the ledger or a record")
    return r


def write_records(card, docs, ledger, prior=()):
    """Set every record of the card from the ledger (shown_record), in card order. A value
    with no check of its current text gets no record."""
    out, nodes = [], dict(sourced(card))
    for x in build(card, docs):
        r = shown_record(x, ledger, prior, check_ledger.not_before(card, nodes[x['pointer']]),
                         inputs=resolution_inputs(card, x, docs) if is_resolved(x) else None)
        if r is not None:
            out.append(r)
    card['added']['integrity']['entailment'] = out
    return out


def merge(card, inp, outp, docs, ledger):
    """Append the verdicts to the ledger, then set the card's records from it. Refuses
    unless every input item is what the current card would send to the checker. A new
    'entails' does not hide an earlier 'no' on the same text: the record shows the worst."""
    by_id = {o['id']: o for o in outp}
    if [x['id'] for x in inp] != [o['id'] for o in outp]:
        raise ValueError('checker output does not match the input ids in order')
    bad = stale_items(card, docs, inp)
    if bad:
        raise ValueError('the card no longer matches the checker input, so these verdicts are about other text; '
                         'write a new input and run the pass again:\n  ' + '\n  '.join(bad))
    at = ohfkit.now()
    records = []
    for x in inp:
        v = by_id[x['id']]
        if v['verdict'] not in ('entails', 'partial', 'no'):
            raise ValueError(f"{x['id']}: verdict {v['verdict']!r}")
        r = {'pointer': x['pointer'], 'basis': x['basis'], 'verdict': v['verdict'],
             'checker': copy.deepcopy(CHECKER), 'checked_at': at}
        if v['verdict'] != 'entails':
            if not v.get('note'):
                raise ValueError(f"{x['id']}: {v['verdict']} without a note")
            r['note'] = v['note']
        records.append(r)
    if any(is_resolved(x) for x in inp):
        raise ValueError('the input holds a card reference; references are decided by resolution, not by the '
                         'checker: write the input with entailment.py input')
    for x, r in zip(inp, records):
        check_ledger.add_entry(ledger, check_ledger.key_of(x), check_ledger.entry(x, r), r.get('note'))
    records += resolve_references(card, docs, ledger)
    write_records(card, docs, ledger, card['added']['integrity']['entailment'] + records)
    return records


def assessment_nodes(card):
    """{pointer: node} for every added value that carries an assessment with assessed_at."""
    out = {}

    def walk(o, p):
        if isinstance(o, dict):
            a = o.get('assessment')
            if isinstance(a, dict) and isinstance(a.get('assessed_at'), str):
                out[p] = o
            for k, v in o.items():
                walk(v, f'{p}/{k}')
        elif isinstance(o, list):
            for i, v in enumerate(o):
                walk(v, f'{p}/{i}')
    walk(card['added']['layers'], '/added/layers')
    return out


def _without_stamp(node):
    """The judgement of an assessed node: its value and assessment without the stamp
    (assessed_at, and the assessor, which names the kit version that wrote the stamp)."""
    n = copy.deepcopy(node)
    del n['assessment']['assessed_at']
    n['assessment'].pop('assessor', None)
    return check_ledger.canonical(n)


def keep_assessment_times(card, earlier_cards):
    """A rebuild that leaves a judgement unchanged (the value and everything in the assessment
    except its stamp, assessed_at and assessor) did not re-assess anything. The assessment gets
    back the stamp of its earliest identical judgement in `earlier_cards`: both its time and
    the assessor that made it then. A new stamp would be a false time, and a new assessor name
    would claim a re-assessment by a kit version that made none. Any other change keeps the new
    stamp. Returns the pointers whose stamp was restored."""
    olds = [assessment_nodes(c) for c in earlier_cards]
    restored = []
    for p, node in assessment_nodes(card).items():
        same = _without_stamp(node)
        earlier = [o[p]['assessment'] for o in olds if p in o and _without_stamp(o[p]) == same]
        if not earlier:
            continue
        first = min(earlier, key=lambda a: a['assessed_at'])
        if first['assessed_at'] < node['assessment']['assessed_at']:
            node['assessment']['assessed_at'] = first['assessed_at']
            if 'assessor' in first:
                node['assessment']['assessor'] = first['assessor']
            restored.append(p)
    return restored


def outcome_nodes(card):
    """{pointer: node} for every added value that carries a recorded outcome with recorded_at,
    such as a prediction's resolution.outcome."""
    out = {}

    def walk(o, p):
        if isinstance(o, dict):
            if isinstance(o.get('recorded_at'), str):
                out[p] = o
            for k, v in o.items():
                walk(v, f'{p}/{k}')
        elif isinstance(o, list):
            for i, v in enumerate(o):
                walk(v, f'{p}/{i}')
    walk(card['added']['layers'], '/added/layers')
    return out


def _outcome_without_stamp(node):
    """A recorded outcome without its stamp (recorded_at, and recorded_by, which names the kit
    version that wrote it)."""
    n = copy.deepcopy(node)
    del n['recorded_at']
    n.pop('recorded_by', None)
    return check_ledger.canonical(n)


def keep_recorded_times(card, earlier_cards):
    """A rebuild that leaves a recorded outcome unchanged did not record it again. The outcome
    gets back the stamp of its earliest identical record in `earlier_cards`: both recorded_at
    and the recorded_by of that time. A new stamp would say the outcome was recorded when the
    card was last built, which is a false time; this is the rule keep_assessment_times applies
    to an assessment. Returns the pointers whose stamp was restored."""
    olds = [outcome_nodes(c) for c in earlier_cards]
    restored = []
    for p, node in outcome_nodes(card).items():
        same = _outcome_without_stamp(node)
        earlier = [o[p] for o in olds if p in o and _outcome_without_stamp(o[p]) == same]
        if not earlier:
            continue
        first = min(earlier, key=lambda o: o['recorded_at'])
        if first['recorded_at'] < node['recorded_at']:
            node['recorded_at'] = first['recorded_at']
            if 'recorded_by' in first:
                node['recorded_by'] = first['recorded_by']
            restored.append(p)
    return restored


def restore(card, archived_cards, docs_of, ledger):
    """Append to the ledger the checks recorded in archived merged cards, each hashed from
    THAT card's value and passage, with its own checked_at, verdict and note; an identical
    entry is not added twice. An assessment of the card that is byte-identical to one in the
    archived cards gets back its earliest assessed_at (keep_assessment_times), and a recorded
    outcome that is byte-identical to one there gets back its earliest recorded_at
    (keep_recorded_times); for an assessment that is the time the
    old checks were made after. Then set the card's records from the ledger.
    `docs_of(card)` opens the source documents. Returns the counts (entries added, archived
    records skipped, assessment times restored)."""
    archived_cards = tuple(archived_cards)
    projected_archives = {}
    for index, old in enumerate(archived_cards):
        if old.get('standard_version') == '1.4' and any(
                check_ledger.LINE_FIELD.match(r.get('pointer', ''))
                and check_ledger.LINE_FIELD.match(r['pointer']).group(2) == 'direction'
                for r in old['added']['integrity']['entailment']):
            if old.get('id') != card['id']:
                raise ValueError(f"archived card {old.get('id')!r} is not card {card['id']!r}")
            items = {check_ledger.key_of(x): x for x in build(old, docs_of(old))}
            original_entries = {}
            for record in old['added']['integrity']['entailment']:
                key = check_ledger.key_of(record)
                item = items.get(key)
                if item is None or check_ledger.direction_projection(item) is None:
                    continue
                expected = check_ledger.entry(item, record)
                matching = [entry for entry in ledger['entries'].get(key, [])
                            if all(entry.get(name) == value for name, value in expected.items())]
                if not matching:
                    raise ValueError('format-1.4 direction restoration requires the original ledger target '
                                     'bindings; an archived card alone cannot reconstruct them')
                original_entries[key] = copy.deepcopy(matching[0])
            projected_archives[index] = items, original_entries
    added = skipped = 0
    prior = list(card['added']['integrity']['entailment'])
    for index, old in enumerate(archived_cards):
        if old.get('id') != card['id']:
            raise ValueError(f"archived card {old.get('id')!r} is not card {card['id']!r}")
        if index in projected_archives:
            items, original_entries = projected_archives[index]
        else:
            items, original_entries = {check_ledger.key_of(x): x for x in build(old, docs_of(old))}, {}
        for r in old['added']['integrity']['entailment']:
            x = items.get(check_ledger.key_of(r))
            if x is None:  # the archived card has a record for a value it does not source
                skipped += 1
                continue
            key = check_ledger.key_of(r)
            entry = original_entries[key] if key in original_entries else check_ledger.entry(x, r)
            added += check_ledger.add_entry(ledger, key, entry, r.get('note'))
            prior.append(r)
    times = keep_assessment_times(card, archived_cards)
    times += keep_recorded_times(card, archived_cards)
    write_records(card, docs_of(card), ledger, prior)
    return added, skipped, len(times)


def assessed_times(node):
    out = []

    def walk(o):
        if isinstance(o, dict):
            if isinstance(o.get('assessed_at'), str):
                out.append(o['assessed_at'])
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(node)
    return out


def carry(old_card, card, docs, ledger, recheck=None):
    """Records for the rebuilt card from the ledger (shown_record), and the items that need a
    new check. First, an assessment the rebuild left byte-identical gets back the old card's
    assessed_at (keep_assessment_times), and so does a recorded outcome the rebuild left
    byte-identical (keep_recorded_times). An item is kept when the ledger has a check of its
    current value and passage,
    it is not named by --recheck, and the check it shows is not older than an assessment it
    covers. A card reference with no check of its current text is resolved first
    (resolve_references): that is the only entry carry adds, and nothing is dropped from the
    ledger. Times are compared as strings: OHF writes them all as YYYY-MM-DDTHH:MM:SSZ."""
    key = lambda x: (x['pointer'], x['basis'])  # noqa: E731
    keep_assessment_times(card, [old_card])
    keep_recorded_times(card, [old_card])
    nodes = dict(sourced(card))
    prior = old_card['added']['integrity']['entailment'] + resolve_references(card, docs, ledger)
    kept, rest = [], []
    for x in build(card, docs):
        floor = check_ledger.not_before(card, nodes[x['pointer']])
        r = (None if (recheck and re.search(recheck, x['pointer']) and not is_resolved(x))
             else shown_record(x, ledger, prior, floor,
                               inputs=resolution_inputs(card, x, docs) if is_resolved(x) else None))
        # A check older than the floor is not carried: it predates either the assessment it would
        # cover or the retrieval of the passage it claims to have read, and the standard's check_refs
        # refuses such a record. `choose` falls back to the earliest check when none is new enough,
        # so without this the card is rebuilt, passes carry, and fails the repository checkers with
        # nothing to do about it. Measured when this was found: 3 such records on one flagship and
        # 56 on the other. They go to the rest file and are checked again.
        stale = r is not None and floor is not None and r['checked_at'] < floor and not is_resolved(x)
        # A resolution from an earlier binding rule is not carried either, for the same reason in a
        # different dress: the verdict was produced by a question this kit no longer asks. It stays in
        # the ledger's history and the key goes to the rest file, where it is resolved against the
        # saved sources. Without this, a rebuild would carry every old `entails` forward untouched.
        if r is not None and is_resolved(x) and not by_current_resolver(r):
            stale = True
        if r is not None and not stale and all(a <= r['checked_at'] for a in assessed_times(nodes[x['pointer']])):
            kept.append(r)
        else:
            rest.append(x)
    rest = checker_items(rest)
    order = {key(x): i for i, x in enumerate(build_order(card))}
    card['added']['integrity']['entailment'] = sorted(kept, key=lambda r: order[key(r)])
    return kept, rest


def build_order(card):
    """Pointers of the sourced values in card order, without reading any document."""
    out = []
    for p, node in sourced(card):
        out.append({'pointer': p, 'basis': 'src'})
        if 'basis_quote' in node:
            out.append({'pointer': p, 'basis': 'basis_quote'})
    return out


def docs_for(card, workdir):
    """Open every document that added.sources names.

    Europe PMC XML is found by its URL. Any other source must be listed in
    WORKDIR/docs.json as {"<url>": {"kind": "pdf" | "html" | "record" | "submitted", "file": "<name>"}}.
    """
    listed = {}
    manifest = Path(workdir) / 'docs.json'
    if manifest.exists():
        listed = json.loads(manifest.read_text())
    docs = {}
    for rec in card['added']['sources'].values():
        url = rec['source']
        if url in docs:
            continue
        if url in listed:
            kind = listed[url].get('kind', 'pdf')
            if kind == 'html-blocks':
                docs[url] = ohfkit.HtmlBlocksDocument(url, listed[url]['file'], workdir, listed[url]['work'])
                continue
            cls = {'pdf': ohfkit.PdfDocument, 'html': ohfkit.HtmlDocument, 'record': ohfkit.RecordDocument,
                   'submitted': ohfkit.SubmittedText}[kind]
            docs[url] = cls(url, listed[url]['file'], workdir)
        elif url.startswith('https://www.ebi.ac.uk/europepmc/'):
            docs[url] = ohfkit.Document(url.rsplit('/', 2)[-2], workdir)
    return docs


if __name__ == '__main__':
    cmd, card_path = sys.argv[1], Path(sys.argv[2])
    card = json.loads(card_path.read_text())
    if cmd == 'input':
        items = checker_items(build(card, docs_for(card, sys.argv[3])))
        Path(sys.argv[4]).write_text(json.dumps(items, indent=1, ensure_ascii=False) + '\n')
        print(len(items), 'items')
    elif cmd == 'merge':
        if len(sys.argv) != 6:
            sys.exit(__doc__)
        workdir = sys.argv[3]
        inp = json.loads(Path(sys.argv[4]).read_text())
        outp = json.loads(Path(sys.argv[5]).read_text())
        ledger = read_ledger(card, workdir)
        try:
            recs = merge(card, inp, outp, docs_for(card, workdir), ledger)
        except ValueError as e:
            sys.exit(f'merge refused: {e}')
        ohfkit.rehash(card, card_path)
        write_ledger(card, workdir, ledger)
        from collections import Counter
        print(len(recs), dict(Counter(r['verdict'] for r in recs)), card['content_hash'])
        check_ledger.print_summary(card, ledger)
    elif cmd == 'carry':
        old = card
        card_path = Path(sys.argv[3])
        card = json.loads(card_path.read_text())
        workdir = sys.argv[4]
        recheck = sys.argv[7] if len(sys.argv) > 7 and sys.argv[6] == '--recheck' else None
        try:
            ledger = read_ledger(old, workdir)
        except ValueError as e:
            sys.exit(f'carry refused: {e}')
        kept, rest = carry(old, card, docs_for(card, workdir), ledger, recheck)
        Path(sys.argv[5]).write_text(json.dumps(rest, indent=1, ensure_ascii=False) + '\n')
        ohfkit.rehash(card, card_path)
        write_ledger(card, workdir, ledger)
        print(len(kept), 'records kept,', len(rest), 'items to check')
    elif cmd == 'export':
        workdir, out = sys.argv[3], Path(sys.argv[4])
        ledger = check_ledger.load(ledger_path(workdir))
        errors = check_ledger.check(card, ledger, check_ledger.source_passages(card, workdir))
        for e in errors:
            print('FAIL', e)
        if errors:
            sys.exit(f'export refused: {len(errors)} ledger errors')
        ledger = check_ledger.upgrade(ledger)
        out.write_text(json.dumps(ledger, indent=1, ensure_ascii=False) + '\n')
        print('ledger written to', out, len(ledger['entries']), 'keys,',
              sum(len(v) for v in ledger['entries'].values()), 'history entries')
    elif cmd == 'restore':
        if len(sys.argv) < 5:
            sys.exit(__doc__)
        workdir = sys.argv[3]
        archived = [json.loads(Path(a).read_text()) for a in sys.argv[4:]]
        try:
            ledger = read_ledger(card, workdir)
            added, skipped, times = restore(card, archived, lambda c: docs_for(c, workdir), ledger)
        except ValueError as e:
            sys.exit(f'restore refused: {e}')
        ohfkit.rehash(card, card_path)
        write_ledger(card, workdir, ledger)
        print(added, 'entries restored,', skipped, 'archived records skipped (value not sourced),',
              times, 'unchanged assessments given back their earlier assessed_at,', card['content_hash'])
        check_ledger.print_summary(card, ledger)
    else:
        sys.exit(__doc__)
