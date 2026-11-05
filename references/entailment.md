# The entailment pass

The pass asks one question per value: does the cited passage, read alone, support the
value as recorded? It is run by a model that did not convert the card and sees nothing
but the instructions and the input. Why: the converter knows what it meant, so it reads
its own paraphrase as supported. The checker does not know, so a dropped hedge shows.

## Run it

1. `scripts/entailment.py input CARD WORKDIR in.json`. The input holds every sourced
   added value except provenance and `first_proposed` (they come from metadata). Every
   record points at a `{"value", "src"}` wrapper, as `tools/check_refs.py` requires. An
   evidence line's `direction` and `indirectness` are each given to the checker with **what they are
   about**: the target statement (an atom's statement, or a prediction's population, endpoint and
   direction) and the line's own quotation. A direction is a relation between this line's finding and
   the target claim; an indirectness is the distance between the study and that claim. Neither can be
   judged from the passage alone, and a checker shown only the passage answers about the paragraph's
   overall tenor — which is how a line that extracts one finding from a mixed paragraph collects a
   `partial`: 18 of the 49 partial records on the two accepted flagship cards were of that kind. The
   quotation is still checked byte for byte by `check_card.py` as well; in the item it is context,
   not the thing judged. A value with `basis_quote` is checked twice: against its
   paragraph and against the quotation. A reference to a value in the same card
   (`{"kind": "card", "pointer": ...}`, such as `test_plan_ref`) is not in the input: `merge`
   and `carry` decide it by resolution and write that check to the ledger
   ([resolution.md](resolution.md)). **So are the two values that say which work a line rests on**:
   its `independence_group` and its cited `items[]`. Their truth is in bytes — the artifact and
   sha256 the line cites, against the **saved sources**, which is every document `docs_for` opens for
   the card — and never in the prose of a passage. A checker shown only the passage answers whether
   that paragraph names a study, which is a different question: measured across the two accepted
   flagship cards, 80 cited-item records and 79 group records were decided that way, 71 and 48 of
   them entailing because the paragraph happened to name one. Resolved against the saved sources
   instead, the same records are **80 `entails`** for the items and **50 `entails` with 29 `partial`**
   for the groups.

   `entails` for a cited item means the digest it names is the digest of a saved source of that name,
   or the digest the card records for the converted article (`author.source.source_text_sha256`,
   `added.source_verification.sha256`). Consistency between the items of one card is **not**
   membership: a file no source of the card names, carrying a well-formed digest of its own, agrees
   with everything and binds nothing, and it resolves to `partial` with `source_not_bound` — not
   `entails`, and not `no`, because a missing manifest entry is a missing binding and not a finding
   that the line is wrong. A name and a digest that belong to different saved sources is a `no`: that
   pair is wrong about bytes the card holds.

   **A resolution verdict is only as good as the rule that produced it**, so the resolver's identity
   carries the version of that rule (`saved-sources@2`) and every ledger entry records it. A verdict
   made under an earlier rule stays in the history and backs nothing: the key is **held**
   (`superseded_resolution`), the card shows no record for it, `carry` sends it to the rest file, and
   the next `merge` or `carry` resolves it again against the saved sources, appending the new verdict
   beside the old one. Without that, raising the rule would change nothing for a value already checked
   — the old verdict would be found in the ledger and reused, and worse, relabelled as a verdict of
   the new rule.

   **Known limitation (K10-R5).** A cited item is resolved against the saved sources it names **and**
   against what its sibling items declare, but only the first is recorded in its inputs. A sibling
   re-declared with another digest therefore leaves a cached `entails` in force while a fresh
   resolution answers `no`. Until that is fixed: **before accepting a card whose saved sources or item
   declarations changed after its first resolution, run the resolution pass without the cache** - a
   fresh `merge`, or `carry` with `--recheck` on those pointers - and compare. The test that holds this
   open is marked `xfail(strict=True)`, so it fails the suite when the limitation goes.

   A group whose lines cite more than one artifact resolves to `partial`, not `no`: a
   reanalysis of another study's data belongs in that data's group while citing its own paper, and
   OHF 1.0 has no member in which the card could say so. A list value that holds card references (such as
   `also_expected_under`) goes to the checker with what each reference names, as
   `{"value": ..., "targets": {pointer: text}}`, so that the checker judges the named claim.
2. Start a fresh agent. Give it only the path of `examples/cards/ENTAILMENT-PROMPT.md`
   and of `in.json`, and the path to write the output. Do not tell it what the card is
   about, what you expect, or which values you are unsure of.
3. `scripts/entailment.py merge CARD WORKDIR in.json out.json`. It first rebuilds the
   items from the card as it is now and refuses if any value or passage differs from
   `in.json`: the verdicts are about the text the checker saw, so a value changed in the
   meantime needs a new input and a new pass. It writes one record per item with the
   current time, refuses a `partial` or `no` without a note, appends the checks to the
   ledger, and sets every record from the ledger (the worst check of the current text).

## The ledger

The schema allows no extra member in a record, so the text each verdict is about is
recorded next to the card: `WORKDIR/entailment-ledger.json`, published as
`examples/ledgers/<slug>.json`, format `ohf-entailment-ledger/2`. Each key
(`"<pointer>|<basis>"`) holds the **whole history** of its checks, in time order: one entry
per check with `value_sha256` (canonical JSON of the value as checked), `passage_sha256`
(the passage as checked), `checked_at`, `verdict` and, for a note, `note_sha256`. The note
texts are kept in the ledger's `notes`, keyed by `note_sha256`. The header names the format,
the canonicalisation, the card id and the content_hash of the card it was last written for.
A format /1 ledger (one entry per key) is read as lists of one and written back as /2.

A rendering is the kit's work and not the card's text, so the kit remembers the renderings it used
before (`check_ledger.earlier_renderings`): a record made under an earlier one is read, named to the
caller as such, and re-resolved at the card's next rebuild. That list grows and is never shortened —
dropping a rendering makes every record made under it unreadable, which is what the accepted-card
regression exists to catch.

- Entries are only appended. `merge` adds the new checks; `carry`, `restore` and `export`
  keep every entry. No command removes or rewrites one.
- The **active** checks of a key are those of the card's current value and passage. The
  card's record shows the worst active verdict (`no` < `partial` < `entails`); on a tie,
  the earliest check of that verdict that is not older than the latest assessment of the
  value (else the earliest), with that check's time and note. Checks of an earlier value
  stay as history and are not active.
- A key whose active checks disagree is **disputed**. That is information, not a failure:
  `check_ledger.py`, `check_card.py`, `merge` and `restore` print the disputed keys and the
  number of history entries.
- `scripts/entailment.py export CARD WORKDIR examples/ledgers/<slug>.json` checks the
  ledger in full and copies the whole history for the repository.
- `scripts/check_ledger.py CARD LEDGER [WORKDIR]` checks it, and `check_card.py` runs that
  check with WORKDIR. It fails on a record with no ledger entry, a record that shows a
  better verdict than the worst active check, a record that no active check backs or that
  is not the check the rule shows, a note that is not that check's note, a sourced value
  with no record, and a card changed after the last merge, carry or restore.
- Limit: without WORKDIR (CI with only the repository) it verifies the value binding and
  the verdicts, and the passages of `basis_quote` items, which are in the card. The
  binding of a `src` passage needs the source bytes, whose SHA-256 is in the card; it is
  checked with WORKDIR. Without them, the passage is taken to be the one the record's own
  check names. So without WORKDIR, a check of the same value against another passage (made
  after the src changed) is not told apart from a check of the current one: a later `entails`
  with another passage hash can stand in for an earlier `no`. Run `check_card.py` with WORKDIR
  before a card is published.

## What to do with the verdicts

- `entails`: this exact item is supported under its pinned rubric, rendered question and admissible passage. It is not whole-card acceptance, source completeness, biological truth or an agreement/accuracy statistic.
- `partial` or `no`: read the note against the passage.
  - If the value overstates the passage (a dropped hedge or condition, an added detail),
    correct the value. Then re-run the pass **on the corrected values only**, in a new
    agent, and merge those records.
  - The builder writes the card from scratch, so a rebuild drops every record. Keep the
    merged card under another name, rebuild, then run
    `scripts/entailment.py carry OLD_CARD CARD WORKDIR rest.json`. **A check older than the floor is
    not carried**: the floor is the later of the value's latest assessment and the access time of
    the source it cites, so a check below it predates either the assessment it would cover or the
    retrieval of the passage it claims to have read — and the standard's `check_refs` refuses such
    a record. Those keys go to `rest.json` and are checked again. Without this the card is rebuilt,
    passes `carry`, and then fails the repository checkers with nothing to be done, because the
    tie-break falls back to the earliest check when none is new enough: 3 such records on one
    flagship and 56 on the other when it was found. It sets a record from
    the ledger, by the rule above, only when the ledger has a check of the new card's value
    and passage and the check shown is not older than an assessment it covers; the rest go
    to `rest.json` for a new agent, then `merge`. The ledger keeps every entry. A card with
    no ledger keeps nothing. Before deciding, `carry` gives an assessment whose judgement the
    rebuild left unchanged (its value and everything in the assessment except the stamp,
    `assessed_at` and `assessor`) the old card's stamp, both time and assessor. The builder
    stamps a new time and the current kit version on every run, but nothing was re-assessed.
    The new stamp would be a false time that makes earlier checks look older than the
    assessment they cover. A changed judgement keeps its new stamp, so the old checks stop
    backing it.
  - If the value is right but its content is spread over several paragraphs (a list with
    one `src`), keep the value and the `partial` record. Say so in the report, with the
    other paragraphs. Do not move content out of the value to make the verdict pass.
  - If the checker is plainly wrong (it misread the passage), keep the record as it is
    and say why in the report. Do not re-run until it agrees. Re-running gains nothing:
    a new check of the same text is appended, the record keeps showing the worst verdict,
    and the key is shown as disputed.
- A disputed key shows its worst verdict. Resolve it by correcting the reading (a new
  value or passage is new text, with its own checks) or by keeping it and explaining the
  disagreement in the report. Disputed keys are listed in the report.
- If an earlier ledger lost checks (a /1 ledger kept only the last check of each value),
  put them back with `scripts/entailment.py restore CARD WORKDIR ARCHIVED_CARD...`, giving
  every merged card that was archived. Each archived record is hashed from that card's own
  value and passage and appended with its original time, verdict and note. An assessment
  whose judgement is unchanged from one in the archived cards gets back the stamp of the
  earliest (`assessed_at` and `assessor`), the one the old checks were made after. The card's records are then set
  from the ledger and the card is rehashed.
- A `no` is information, not a defect. Remove it only by correcting the reading of the
  article, with a locator that shows the reading. Never delete the value or change its
  type to make the verdict go away. Check the whole article first, not only the cited
  passage, and date a prediction's `epistemic_status` by its first record, not by a later
  paper that retells it. If the value was right, keep it byte-identical so `carry` keeps
  the `no` record visible. Add a second basis if one helps; its verdict sits next to the
  old one, not in its place.
- Never edit a verdict or a note by hand.

A corrected assessment needs a new `assessed_at` (the time of the correction), and its
check must run after that. An unchanged assessment keeps its time (`carry`, `restore`). `check_card.py` refuses an assessment later than its check.

## What the pass does not show

It checks a value against one passage. It cannot see that the converter missed the
authors' main claim, chose a weak passage, or left out an alternative. That is the
reviewer's job.

## Ordinary OHF 1.4 direction checks

Legacy `/1` ledgers remain readable for pre-1.4 cards. A format-1.4 card refuses
a legacy ledger without the target-projection envelope. Its old checks stay in
history and cannot back a format-1.4 direction record by changing the format label.

An ordinary format-1.4 direction item uses the pinned Standard's
`ohf-target-projection/1` value, including the complete target and evidence conditions.
Its ledger entry binds that projection and its digest. Build, stale detection, merge,
carry, validation and export use this value and eligible history. An unbound or stale
entry remains historical and cannot acquire a projection binding through a refreshed hash.
Formats 1.0–1.3 retain their existing rendering and history rules.

Keep the original ledger for format-1.4 direction checks. Restore reuses its matching
original entries. Restoring from an archived card alone refuses, because the card does
not hold the original target-binding history. Carry also uses the retained ledger.

## Explicit OHF 1.4 native profile

The [native relational profile](native-renderer-profile.md) has a separate complete
entrypoint for schema, source, roster and frozen IO validation. Its selected
modules retain target, quotation and term conditioning through check and export.
The synthetic conformance recipe uses an injected fake checker; structural PASS
does not establish scientific truth or whole-card completeness.
