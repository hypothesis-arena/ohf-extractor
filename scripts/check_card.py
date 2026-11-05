"""Check a converted card: check_card.py CARD WORKDIR [COMMIT_ISO]

Runs the repository checkers, then the conversion checks they cannot make:
- author.source.license is the licence derived again from the main source's bytes;
- every author-zone value is an exact passage of the paragraph its locator names, made of
  whole sentences unless its locator records a cut (Document.author_part);
- every evidence quotation and every basis_quote is an exact passage of its source;
- every sourced added value has an entailment record, and each record is bound by the
  ledger WORKDIR/entailment-ledger.json to the value and passage it was given for
  (check_ledger.py): a value or passage changed after its check fails, and a record must
  show the worst verdict among the checks of the same text (disputed keys are printed);
- no assessment is later than its entailment check or than added.at, and no time is round.
Exit 0 only when every check passes. Each failure names how to fix it.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_ledger  # noqa: E402
import entailment  # noqa: E402
import gap_coverage  # noqa: E402
import ohfkit  # noqa: E402

ACCEPTED = Path(__file__).resolve().parent / 'tests' / 'fixtures' / 'exemplars' / 'cards'

TIME_CHECK = ohfkit.TIME_CHECK
para_of = ohfkit.para_number


def walk(o, p, src=None):
    """Every node under `o`, each with the src in force for it.

    A sourced value usually carries its own `src` beside its quotation. One field of the standard does
    not: `predictions[].effect_modifiers[]` puts `basis_quote` **inside** `value`, and the `src` is the
    item's, one level up. Reading the src from the node that holds the quotation therefore failed on
    the first card to fill that field, with 'cannot read the passage of src None'. The src in force is
    the nearest enclosing one, which is the same answer everywhere else.
    """
    if isinstance(o, dict):
        src = o.get('src', src)
        # Only a node that holds a quotation inherits, and only when it has no src of its own: every
        # other caller of this walker tests for `src` itself and must not be handed one.
        quoted = {'quote', 'basis_quote'} & set(o)
        yield p, (o if 'src' in o or not quoted else {**o, 'src': src})
        for k, v in o.items():
            yield from walk(v, f'{p}/{k}', src)
    elif isinstance(o, list):
        for i, v in enumerate(o):
            yield from walk(v, f'{p}/{i}', src)


def owned_error(doc, card, n, node):
    """Why an author value of a submitted text may not stand on the submitter's statement, or None."""
    try:
        ohfkit.owned(doc, ohfkit.decisions_in(card), n, node['value'])
    except ValueError as e:
        return str(e)
    return None


def ownership_errors(card, doc):
    """A recorded sentence decision must name a sentence of its paragraph, a decision, a reason and a time."""
    errors = []
    for d in ohfkit.decisions_in(card):
        where = f"added.sources[{ohfkit.OWNERSHIP_KEY!r}] paragraph {d.get('paragraph')}"
        try:
            if d.get('sentence') not in doc.sentences(d.get('paragraph')):
                errors.append(f"{where}: {d.get('sentence')!r} is not one of its sentences (decide again on the text)")
        except (ValueError, TypeError):
            errors.append(f'{where}: no such paragraph')
        if d.get('decision') not in ohfkit.DECISIONS or not (d.get('reason') or '').strip() or not d.get('assessed_at'):
            errors.append(f'{where}: a decision needs one of {ohfkit.DECISIONS}, a reason and assessed_at')
    return errors


def conversion_errors(card, workdir, legacy=None):
    """The checks of this skill (no repository checkers, no time check), as fix-naming messages.
    Keys read under an earlier rendering of their value are appended to `legacy`, not to the
    errors: they are records the kit honours and re-resolves at the next rebuild."""
    errors = []
    docs = entailment.docs_for(card, workdir)
    main_doc = next((d for d in docs.values() if d.sha == card['author']['source']['source_text_sha256']), None)
    if main_doc is None:
        errors.append('author.source.source_text_sha256 matches no downloaded document (re-download the article)')
    else:
        try:
            lic = ohfkit.source_licence(card, main_doc)
            if lic != card['author']['source']['license']:
                errors.append(f'author.source.license is {card["author"]["source"]["license"]!r}, but the source '
                              f'grants {lic!r} (rebuild: skeleton() derives the licence)')
        except ValueError as e:
            errors.append(f'licence of the main source: {e} (stop, or record the exact licence statement)')
        if isinstance(main_doc, ohfkit.SubmittedText):
            errors += ownership_errors(card, main_doc)
        for p, node in walk(card['author']['layers'], '/author/layers'):
            if 'locator' in node and 'value' in node and isinstance(node['value'], str):
                n = para_of(node['locator'])
                if n is None or node['value'] not in main_doc.para(n):
                    errors.append(f'{p}: author value is not in {node["locator"]} (copy the exact text of that paragraph)')
                elif isinstance(main_doc, ohfkit.SubmittedText) and (err := owned_error(main_doc, card, n, node)):
                    errors.append(f'{p}: {err}')
                elif ohfkit.PART_MARK not in node['locator'] and not ohfkit.whole_sentences(main_doc.para(n), node['value'],
                                                                                                         main_doc.closers):
                    errors.append(f'{p}: author value does not start and end on a sentence boundary of '
                                  f'{node["locator"]} (quote whole sentences, or cut with doc.author_part and a reason)')
    # `core.assumptions[].fundamental` is the author's own classification of a premise as fundamental
    # or not, and the standard says it is never guessed. Two readers refused such a value on two cards
    # before any check existed - a builder habit, not an accident - so it is refused here, before a
    # reader has to spend a verdict on it.
    #
    # The first version of this check demanded a `basis_quote`, and a review found that the schema
    # forbids one: `fundamental` in the added zone is either `{value, src}` with
    # `additionalProperties: false`, or a bare boolean. So the check refused every schema-valid form,
    # anything that satisfied it was schema-invalid, and the bare boolean - the form with no source at
    # all, which is exactly the guess being guarded against - went through untouched. Measured on both
    # 1.0.1 and 1.1.3, and on an accepted card whose twelve grounded values it refused.
    #
    # What makes the value honest is not a sibling quote but that it names the paragraph it came from:
    # the `{value, src}` form is a sourced value, so the entailment pass demands a record for it and a
    # reader checks the boolean against that paragraph, where a guess cannot be entailed. This check
    # therefore asks only for the form that carries a src, and leaves the grounding to the pass.
    for i, premise in enumerate(card['added']['layers'].get('core', {}).get('assumptions', [])):
        node = premise.get('fundamental')
        if 'fundamental' in premise and not (isinstance(node, dict) and 'src' in node):
            errors.append(f'/added/layers/core/assumptions/{i}/fundamental: the authors\' own '
                          'classification, never the extractor\'s - give it as {"value": ..., "src": ...} '
                          'naming the paragraph that classifies the premise, so the entailment pass '
                          'checks the value against that paragraph, or leave the field out and let the '
                          'gap for core.assumptions[].fundamental say the article classifies none')
    for i, line in enumerate(card['added']['layers'].get('evidence', {}).get('lines', [])):
        for field in entailment.LINE_FIELDS:
            if field in line and not (isinstance(line[field], dict) and 'src' in line[field]):
                errors.append(f'/added/layers/evidence/lines/{i}/{field}: write it as {{"value": ..., "src": ...}} '
                              'so that the entailment pass can check it')
    for p, node in walk(card['added']['layers'], '/added/layers'):
        for field in ('quote', 'basis_quote'):
            if field in node:
                text = node[field]['value'] if isinstance(node[field], dict) else node[field]
                try:
                    whole = entailment.passage(card, docs, node['src'])
                except Exception as e:  # noqa: BLE001
                    errors.append(f'{p}: cannot read the passage of src {node.get("src")!r}: {e}')
                    continue
                rec = card['added']['sources'].get(node['src'], {})
                if ohfkit.REFERENCE_ONLY_MARK in rec.get('tool', ''):
                    errors.append(f'{p}.{field}: src {node["src"]!r} is cited by src only ('
                                  f'{rec["tool"].split(ohfkit.REFERENCE_ONLY_MARK, 1)[1]}): remove the quotation')
                    continue
                if text not in whole:
                    errors.append(f'{p}.{field}: not an exact passage of src {node["src"]!r} (copy it from that paragraph)')
    try:
        items = entailment.build(card, docs)
        passages = {check_ledger.key_of(x): x['source_passage'] for x in items if x['basis'] == 'src'}
        # the digests each resolution rests on now: with the documents open, a resolution made when a
        # source hashed to something else is held rather than read as a verdict about this card
        inputs = {check_ledger.key_of(x): entailment.resolution_inputs(card, x, docs)
                  for x in items if entailment.is_resolved(x)}
    except Exception as e:  # noqa: BLE001
        errors.append(f'cannot build the entailment items: {e}')
        passages, inputs = None, None
    ledger = check_ledger.load(entailment.ledger_path(workdir))
    errors += check_ledger.check(card, ledger, passages, legacy, inputs)
    return errors


def notice_errors(card, workdir):
    """A source whose logged status call found a notice, where the card says nothing about it.

    `search.py status` records three things that are easy to read past: `outcome` ("ok" — the call
    worked), `found`/`hit_count`, and `status`, which is where a retraction, a correction or an
    expression of concern actually appears. A card may carry a corrected work — a correction is often
    a spelling fix — but it may not carry one silently, and the converter reading the wrong field of
    its own record is not a hypothetical: it happened on a flagship, eleven seconds before the work
    was fetched.

    The notice is recorded when its identifier (the notice id, or its DOI) occurs anywhere in the
    card's text. What the card says about it is the converter's business; that it says something is
    this check's.
    """
    log = Path(workdir) / 'search-log.jsonl'
    if not log.exists():
        return []
    text = json.dumps(card, ensure_ascii=False)
    cited = {m for m in re.findall(r'PMC\d+|MED:\d+|\b\d{7,8}\b', json.dumps(card['added'].get('sources', {})))}
    errors = []
    for line in log.read_text().splitlines():
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if rec.get('tool') != 'status' or rec.get('status') in (None, 'none_found'):
            continue
        target = rec.get('target') or {}
        asked = {str(v) for v in list((rec.get('ask') or {}).values()) + [target.get('pmcid'), target.get('pmid')] if v}
        if not (asked & cited):
            continue
        for notice in rec.get('notices') or []:
            ident = notice.get('notice') or ''
            bare = ident.split(':')[-1]
            if ident and ident not in text and bare not in text:
                errors.append(f'the status call {rec.get("call_id")} on {target.get("pmcid") or sorted(asked)[0]} '
                              f'found {notice.get("status")} ({notice.get("kind")}: {ident}) and the card says '
                              f'nothing about it (record it, or say why it does not bear on the value)')
    return errors


WORDING_FROM = (0, 9, 0)


def wording_errors(card):
    """The word for the thing that wrote the card, in text a reader sees, is "extractor".

    The owner's decision of 2026-10-22: visible texts say extractor, not converter. "Converter" is
    the role's name inside this kit and in its own documentation, and it may stand in a field name
    the standard defines (`added.by.converter`, `converter_version`, `converter_hash`); it may not
    stand in a value a reader reads. A card already accepted keeps its wording until its next
    rebuild — a card is not edited in place to satisfy a later rule.
    """
    errors = []
    for p, value in ((p, v) for p, v in _strings(card['added']) if re.search(r'\bconverters?\b', v, re.I)):
        errors.append(f'{p}: a value a reader sees says "converter"; the word in visible text is '
                      f'"extractor" (the field names of added.by keep theirs)')
    return errors


def _strings(node, p='/added'):
    """Every string value under `node`, by JSON pointer, skipping the keys that hold identifiers."""
    if isinstance(node, dict):
        for k, v in node.items():
            if k in ('converter', 'converter_version', 'converter_hash', 'schema', 'sha256', 'src'):
                continue
            yield from _strings(v, f'{p}/{k}')
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _strings(v, f'{p}/{i}')
    elif isinstance(node, str):
        yield p, node


def version_errors(card):
    """A version names one content, and a card carries that version in two places.

    Three rules, each found by a card that broke it:

    1. **The two version members move as a pair.** A card states its version at the top level and
       again at `identity.version`, and the standard's identity is the second one. An editorial
       revision of mine raised the first and left the second, so `(id, identity.version)` named an
       accepted card at a different content hash - the very thing rule 2 exists to stop, slipping
       past because rule 2 read the other member. Found by the acceptor, not by this kit.
    2. **A card may not reuse the version of an accepted card while saying something else.** Two
       cards of one id and one version with different content hashes both claim to be that version:
       seen between two directories of the same eight cards, where version 1 stood over two
       different hashes. A rebuild is a new version. Both members are compared now.
    3. **A version above the first says which version it replaces.** `identity.supersedes` names an
       earlier version of this same card, and never this one or a later one; otherwise a reader of
       version 5 cannot tell what it was a revision of. Measured against the accepted eight and both
       flagships before it was added: all of them already satisfy it.
    """
    errors, ident = [], card.get('identity') or {}
    top, inner = card.get('version'), ident.get('version')
    if inner is not None and top != inner:
        errors.append(f"version {top!r} at the top level and {inner!r} at identity.version: a version "
                      'names one content, so the two move together (raise both, or neither)')
    mine = [s for s in (ident.get('supersedes') or []) if str(s).split('@')[0] == card.get('id')]
    at = inner if inner is not None else top
    if isinstance(at, int):
        for named in mine:
            try:
                was = int(str(named).split('@')[1])
            except (IndexError, ValueError):
                errors.append(f'identity.supersedes names {named!r}, which is not "<id>@<version>"')
                continue
            if was >= at:
                errors.append(f'identity.supersedes names {named!r}, which is this version or a later '
                              'one: a card supersedes what came before it')
        if at > 1 and not mine:
            errors.append(f'version {at} supersedes nothing: identity.supersedes should name the version '
                          f'this one replaces ({card.get("id")}@<earlier>), so that a reader of this '
                          'version can tell what it was a revision of')
    for path in sorted(ACCEPTED.glob('*.json')) if ACCEPTED.is_dir() else []:
        other = json.loads(path.read_text())
        if other.get('id') != card.get('id'):
            continue
        theirs = {other.get('version'), (other.get('identity') or {}).get('version')} - {None}
        if not ({top, inner} - {None}) & theirs:
            continue
        if other.get('content_hash') != card.get('content_hash'):
            errors.append(f"id {card.get('id')!r} version {sorted(({top, inner}) - {None})} is the accepted "
                          f"{path.name} (version {sorted(theirs)}) with another content_hash "
                          f"({other.get('content_hash')}): a rebuilt card is a new version, so raise the "
                          'version rather than restate this one')
    return errors


def coverage_errors(card):
    """Every empty applicable field has a gap (gap_coverage), as one error with the count."""
    try:
        rows = gap_coverage.unrecorded(card)
    except Exception as e:  # noqa: BLE001  a missing standard or policy is reported, not hidden
        return [f'cannot check gap coverage: {type(e).__name__}: {e}']
    if not rows:
        return []
    named = ', '.join(r['path'] for r in rows[:6])
    more = f' and {len(rows) - 6} more' if len(rows) > 6 else ''
    return [f'{len(rows)} empty applicable field(s) with no gap: {named}{more} (fill each, or add a gap '
            'at its path; scripts/gap_coverage.py CARD prints the list)']


def main():
    path, workdir = Path(sys.argv[1]), sys.argv[2]
    commit = sys.argv[3] if len(sys.argv) > 3 else None
    card = json.loads(path.read_text())
    errors = []
    ok, out = ohfkit.run_checks(path)
    print(out)
    if not ok:
        errors.append('repository checkers failed (fix the errors printed above)')
    legacy = []
    errors += conversion_errors(card, workdir, legacy)
    errors += notice_errors(card, workdir)
    # The wording rule is a fail for a card this kit builds and a note for one built earlier: an
    # accepted card is a fact about the past and is brought up to a later rule at its next rebuild,
    # never by being edited in place.
    wording = wording_errors(card)
    built = tuple(int(x) for x in re.findall(r'\d+', card['added']['by'].get('converter_version', '0'))[:3])
    if wording and built >= WORDING_FROM:
        errors += wording
    else:
        for w in wording:
            print('NOTE', f'{w} — this card was built by {card["added"]["by"].get("converter_version")}, '
                          f'before the rule, so it is brought up to it at its next rebuild')
    errors += version_errors(card)
    errors += coverage_errors(card)
    for empty in gap_coverage.empty_lists(card):
        print('NOTE', f'{empty}: the list is empty and the standard has no gap path for it, so none is '
                      'demanded; it belongs in the report and in the map of missing answers')
    for k in sorted(set(legacy)):
        print('NOTE', f'{k}: record read under the rendering of the value in force when it was checked; '
                      'it is resolved again at the next rebuild (check_ledger.rendered_before)')
    ledger = check_ledger.load(entailment.ledger_path(workdir))
    if ledger is not None and ledger.get('format') in check_ledger.FORMATS:
        try:
            check_ledger.print_summary(card, ledger, check_ledger.source_passages(card, workdir))
        except Exception as e:  # noqa: BLE001  (the errors above already say what is wrong)
            print('LEDGER HISTORY not summarised:', e)
    r = subprocess.run([sys.executable, '-I', str(TIME_CHECK), str(path)] + ([commit] if commit else []),
                       capture_output=True, text=True)
    print(r.stdout.strip())
    if r.returncode:
        errors.append('time check failed (reassess or re-check with real times; see the lines above)')
    for e in errors:
        print('FAIL', e)
    print('CARD CHECK', 'FAIL' if errors else 'PASS', len(errors))
    sys.exit(1 if errors else 0)


if __name__ == '__main__':
    main()
