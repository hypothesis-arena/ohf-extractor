---
name: ohf-extractor
version: 0.9.14-dev
description: >-
  Convert one published biology article, whose full text is open under CC BY, into an
  Open Hypothesis Format (OHF) 1.0 hypothesis card: the authors' own words in the author
  zone, the converter's attributed reading in the added zone, typed gaps for what the
  article does not give, and a separate entailment pass. Use when asked to "convert this
  paper into an OHF card", "make an OHF card from <DOI or PMCID>", "turn this preprint into
  a hypothesis card", or "check this OHF card against its sources". Do not use to change the
  OHF standard or its schema (that is the
  open-hypothesis-format repository), to judge or rank hypotheses, to write a new
  hypothesis, or to put text from an NC, ND or closed work into the author zone.
---

# ohf-extractor

Skill type: hybrid. The card's shape, quotations, references and times are **code**: the
scripts check them and fail closed. Whether the added zone says what the article says is
**fidelity** (SKILL-CRAFT C5): it is checked by a separate entailment pass and by a human
or agent reviewer who did not convert the card. No script decides that a card is good.

## Inputs and outputs

- Input: one article (DOI or PMCID) and, when the task names it, its row in the example
  plan (what the card must show and which works answer it).
- Output: `examples/cards/<slug>.json`, a builder script that produces it, the entailment
  input and output, and a short conversion report (template in
  [references/report.md](references/report.md)).
- The work directory holds the downloaded XML. It is not committed; its SHA-256 is in the card.
- Setup: the scripts need a checkout of the open-hypothesis-format repository at the release
  the cards are written for. Set `OHF_REPO` to its path; without it they stop. Set `OHF_MODEL`
  to the model that reads the article: it is written to `added.by.model`, and a build without it
  stops rather than name a model that did no reading. Set `OHF_CONTACT` to an address of your own
  if you want catalogue requests to carry one; the kit has none.

## Steps

Every step ends with a **Done when** line, and there are two kinds. **Done when (checked)** is a
condition a script or a file settles: it is reproducible, and whoever repeats it gets the same
answer. **Done when (judged)** is a condition only a reader settles; no script can decide it, so it
names who judges and what they must be able to point at. A judged condition is never reported as
checked, and a checked condition is never waived by a judgement.

1. **Check rights before reading.** Download the Europe PMC full-text XML and read its
   `permissions` block. CC BY 4.0 or 3.0 (or public domain) allows author-zone text. Any
   NC, ND, SA or missing licence stops the conversion: report it, do not convert from
   metadata. `skeleton()` derives the licence from the source and fails otherwise; for a
   PDF or HTML page, give it the exact licence statement and its page or paragraph, or,
   for an old work with no statement, the years that put it in the public domain.
   Why: the author zone republishes the authors' words. Details:
   [references/rules.md](references/rules.md) §1.
   **Done when (checked):** `skeleton()` derived the licence from the source's own bytes, and the
   report names the licence statement with the paragraph or page it was read from. A work that is
   not CC BY or public domain has no card, and the report says which licence stopped it.
2. **Read the whole article, then find the hypothesis.** Write down, before building:
   the claim the authors make, its scope and conditions, what it explains, what it
   reinterprets, what it opens, its predictions, the evidence for and against, and the
   alternatives the authors name. Each with a paragraph number. Then **search** for what the
   article does not say about itself: its status, the works that answer it, and disagreement in
   the literature, with [scripts/search.py](scripts/search.py) (`status`, `responses`, `cited-by`,
   `literature`), and look up the genes, targets and interventions it names with
   [scripts/biodb.py](scripts/biodb.py). Read the works you cite. Procedure:
   [references/search.md](references/search.md).
   **Done when (checked):** the inventory of the article exists as a file, every item carrying its
   paragraph number ([references/inventory.md](references/inventory.md)), and the search log holds a
   record for each search run, with its service, query, time and count. "Nothing against" without a
   search in the log is not a finding, and a zero from a query the service never understood is not a
   search: the kit refuses a query written in the other service's field syntax and logs it as
   `malformed_query`. `search.py screen CARD` exits non-zero while any work a call returned is
   accounted for nowhere - not cited by the card, not recorded as read and not cited, not recorded
   unreadable, no relevance verdict - so no work leaves the search without a record of someone having
   looked at it. Screening by reading the titles for the words the card already uses is not a screen:
   twice it passed over the decisive counter-work, which the calls had returned four and eighteen
   times.
   **Done when (judged):** the converter has read every work the card will cite, and can say for each
   what in it bears on the claim. A title and an abstract are not a reading, and a work found by
   another tool is a lead until a kit script has fetched it.
   For a run measured in stages, stop here with `search.py close-step --workdir DIR`. This writes
   `step-1.json`: the log hash, call count and works with their publication types, without verdicts.
   Do not build lines until the independent labelling step has finished. The extractor does not
   read that labelling. Resume only from the fixed log, as described in
   [references/stages.md](references/stages.md).
3. **Write the builder** with [scripts/ohfkit.py](scripts/ohfkit.py), following
   [references/fields.md](references/fields.md) field by field. Author-zone values are exact
   passages of whole sentences through `doc.author(n, text)`; the helper fails if the text
   is not in that paragraph or cuts a sentence (a deliberate cut: `doc.author_part`).
   **Done when (checked):** the builder runs from end to end and writes the card; every author-zone
   value came through `doc.author`/`doc.author_part`, so no value of the authors' words is typed by
   hand into the builder.
   **Done when (judged):** a field the article does not support is a typed gap with its reason, not a
   value the converter inferred. Nothing was added to fill a layer.
   In a staged run, `stages.py build BUILDER.py --from-log --workdir DIR` gives the builder the
   fixed calls and blocks new search/network requests. It saves the first draft and its hash,
   timestamp and kit version under `first-draft/`. Keep that bundle unchanged; subsequent checks
   and critics work on a copy. This records the existing extraction procedure, without adding a
   search-closeout gate or changing what the extractor includes.
4. **Run the checks** with `scripts/check_card.py CARD WORKDIR`. Fix every failure; each
   names its fix. A failure is never waived by editing the check.
   Then write down the entities the card names — genes, proteins, complexes, processes, organisms,
   compounds — as mentions with their words and where they stand, and link them with
   [scripts/entities.py](scripts/entities.py), which writes `entities.json` beside the card. OHF
   cannot express how a link was made, so the status stays there and the card implies no match it
   cannot qualify: an identifier enters `added.sources` as found, never as confirmed. Procedure:
   [references/search.md](references/search.md).
   **Done when (checked):** `check_card.py` exits 0 — `CARD CHECK PASS 0` and `TIME CHECK PASS 0` —
   on the card as it stands, not on an earlier build. That includes two checks a reader cannot make
   by hand: every empty applicable field has a gap ([scripts/gap_coverage.py](scripts/gap_coverage.py);
   an empty field with no gap is a question nobody asked), and a rebuilt card does not keep the
   version of an accepted card with another content hash. A `NOTE` it prints is not a failure, and is
   repeated in the report.
5. **Have a blind second reader write the inventory, and reconcile it.** A separate agent receives
   the article and [references/inventory.md](references/inventory.md) and **never sees the card**: it
   writes its own inventory of the claims, the scope and conditions, the authors' hedges, the
   predictions, the arguments for and against and the named alternatives, each item with its
   paragraph number. `scripts/coverage.py INVENTORY CARD` reconciles that inventory with the card by
   paragraph and by type. Every item with no match is a P1: it goes into the card, or the pointer of
   the value that already holds it under another paragraph answers it (`--held`, checked), or the
   report carries a one-line reason with the paragraph. An item matched by paragraph and type alone
   is an address, not coverage, and is answered the same three ways.
   **Done when (checked):** `coverage.py` reports no unmatched item without a recorded reason, and
   the inventory and the script's output lie beside the card with their SHA-256 in the report.
   **Done when (judged):** each recorded reason says why the item is not in the card and is a reason a
   reader can weigh — not "out of scope" alone. The second reader did not see the card; the converter
   does not write that inventory itself.
6. **Run the entailment pass** as a separate agent that receives only
   `examples/cards/ENTAILMENT-PROMPT.md` and the input from
   `scripts/entailment.py input`. Merge with `scripts/entailment.py merge`, which writes
   the ledger that binds each verdict to the checked text and keeps every check (a record
   shows the worst check of its text); export it next to the card with
   `scripts/entailment.py export`. Procedure and what to do with `partial` and `no`:
   [references/entailment.md](references/entailment.md).
   **Done when (checked):** every sourced value has a record, each record is bound by the ledger to
   the value and the passage it was given for, and the ledger keeps every check. A `partial` or a
   `no` that stands is kept with its note, never removed by rewriting the value.
7. **Run waves of critics, with different lenses.** A wave is one cycle of three separate agents,
   one per lens, and the lenses differ rather than repeating one refuter ([references/critics.md](references/critics.md)): (a) what
   is missing, (b) which of the authors' conditions or hedges were lost or strengthened, (c) who in
   the literature disputes the hypothesis, with sources and locators only. A finding is P1 or P2 with
   its evidence — a paragraph or a source — and what to do. The **same** converter fixes it, resumed
   rather than replaced; steps 4 to 6 run again on what changed. A critic never edits the card: the
   reviewer is not the author.
   **Done when (checked):** a wave is one full cycle of the three lenses, every lens has run at
   least once, and either a wave found no P1 (stopped on a clean wave), or two consecutive waves
   found nothing at all (converged, which is more than the rule asks), or four waves have run
   (stopped by the ceiling). The P2 findings not corrected are handed over as a list with their
   pointers and locators, in the report or in a file it names. The report states the waves, the
   findings per lens per wave with "nothing" included, and which outcome ended the run. A card
   stopped by the ceiling with P1 findings still open is handed over as needing more work, not as a
   finished card.
   **Done when (judged):** each wave's findings are the lens's own, and a wave that found nothing was
   a wave that looked — the report says what it looked for.
8. **Correct, then re-check what changed.** A corrected value is checked again after the
   correction, and an assessment changed after its check is assessed and checked again.
   Then run step 4 once more on the final card.
   **Done when (checked):** nothing in the card is older than the correction it answers: every
   corrected value has a check later than its change, and `check_card.py` exits 0 on the final card.
9. **Hand over for acceptance** by someone who did not convert the card, with the report.
   The converter does not accept its own card.
   **Done when (checked):** the report carries the card's `content_hash`, the kit's version and rules
   hash, the counts of the entailment pass, the search section, the coverage output, the waves, and
   the map of missing answers ([references/missing-answers.md](references/missing-answers.md)) with
   a count of rows per state. Evidence is counted apart: lines, sources, primary datasets and the
   dependencies between them, never one total.
   **Done when (judged):** the acceptor, who did not convert the card, says it is accepted. A card the
   converter declares finished is not an accepted card, and this step cannot be completed by the
   converter alone.

## Rules that are easy to break

Read [references/failures.md](references/failures.md) before step 3. It lists failures
observed in real conversions, each with the check that now catches it. The short form:

- Every time in the card is the clock time of the step it records. A constant time in a
  builder is an invented time.
- A paraphrase keeps the authors' conditions and hedges. A dropped "in the limit", "may"
  or "when recombination stops" turns an entailed value into a partial one.
- "Nothing against" is a finding of a search. Without the search in the log and in the report,
  the card does not claim it.
- Nothing is added to meet a quota. If the literature has one line against, the card has
  one line against, and the report says which criterion is not met.
- A field the article does not support is a typed gap, not a guess.

## References

| File | Read when |
| --- | --- |
| [references/rules.md](references/rules.md) | Before starting: rights, sources, what the author and added zones hold |
| [references/search.md](references/search.md) | Step 2: status, responses, citing works, literature search, databases |
| [references/fields.md](references/fields.md) | While writing the builder: each layer and field, with the muller card as the worked example |
| [references/inventory.md](references/inventory.md) | Step 2 (the converter's own inventory) and step 5 (the blind second reader's) |
| [references/stages.md](references/stages.md) | Stop after search and record the first draft for a staged measurement |
| [references/entailment.md](references/entailment.md) | Step 6 |
| [references/resolution.md](references/resolution.md) | Step 6: how card references are decided |
| [references/missing-answers.md](references/missing-answers.md) | Step 9: the six aspects and six states of what the card does not answer |
| [references/critics.md](references/critics.md) | Step 7: the lenses, and what a finding must carry |
| [references/failures.md](references/failures.md) | Before step 3, and when a check fails |
| [references/report.md](references/report.md) | Step 9, and the seven points a card is accepted on |

## Limits

- The scripts check that quotations are exact, references resolve, times are ordered and
  every sourced value has a verdict. They do not check that a reading is right. The
  entailment pass checks a value against its passage only; it cannot see a hypothesis the
  converter missed or an alternative the converter left out.
- The converter is a language model. Its reading is attributed to it in `added.by` and in
  every `assessment`; the authors have not reviewed it.
- The helpers read Europe PMC JATS XML by paragraph, a PDF (`PdfDocument`, listed in
  `WORKDIR/docs.json`) by page, and an HTML article page (`HtmlDocument`, kind `html`) by
  `<p>` element; the HTML reader fails with a position on a `<p>` it cannot close. A page whose
  text is not all in `<p>` (a blog post in `<div>`s) is read by block instead
  (`HtmlBlocksDocument`, kind `html-blocks`, with `work` naming the element that holds the work;
  rules.md, "HTML blocks"). A record
  of a structured API (`RecordDocument`, kind `record`) is read field by field, by JSON
  Pointer, and an author value is a whole field; it is hashed in canonical form. A page
  locator is coarser than a paragraph, and PDF text extraction can split words at line
  ends, so a PDF card is checked less tightly. Figures, formula images and supplementary
  files are not read.
- Tests: `python -I -m pytest scripts/tests` (a Python with the repository requirements).

Development-only form: `scripts/negative_grounds.py` checks explicit local negative-claim sidecars.
See [negative-grounds.md](references/negative-grounds.md). This form is not integrated into the
conversion workflow and does not establish scientific absence or authorize a production run.

Development-only context form: `scripts/question_context.py` builds explicit question-conditioned
packets for scope, direction and indirectness; see [question-context.md](references/question-context.md).
It does not replace the native per-value entailment inputs, execute a checker or authorize production use.

### Explicit native relational profile

For the OHF 1.4 development profile, use the separately selected
[native renderer contract](references/native-renderer-profile.md). Its complete
validator checks schema, source and reference bindings, the item roster and
original frozen IO. The invented conformance scenario has a fake checker only;
it grants no source/model execution and makes no scientific acceptance claim.
General conversion entrypoints do not imply selected-profile acceptance.
