# Conversion report

Hand the card over with this report, for an acceptor who did not convert it. Keep it
short; the card holds the content.

```
Card: examples/cards/<slug>.json   content_hash: sha256:...
Source: <citation>, DOI, PMCID; licence from permissions: <text>; XML sha256: ...
Converter: ohf-extractor <version>, rules hash <added.by.converter_hash>, model <id>

Search: search.py report (status <status>; N responses; M citing works; queries with dates and
  counts); works against found and read: <id>: <why it bears on the claim>; found and not read: <ids>
Coverage: inventory <sha256> by a second reader that did not see the card; coverage.py <sha256>:
  N items, S matched with the quoted words, W by paragraph and type, R not in the card with a reason,
  0 unanswered; each reason with its paragraph
Critics: K waves (lens a/b/c per wave): wave 1 N findings (P1/P2), ... ; "nothing" with what the lens
  examined; the waves converged (two in a row found nothing) or reached the ceiling of four
Attribution: search.py attribute CARD — per cited work, the call and query that found it, or
  "NOT found by a logged search"; calls that found nothing cited
Submitted text (when the main source is one): submitter, basis and card licence as stated; generator
  and model as the manifest gives them, model basis; language and how it was read;
  third_party_candidate paragraphs: <n>: <references>; each sentence own / third_party / not judged,
  with the reason (only sentences judged own are in the author zone)
References in a submitted text: search.py check-refs, per reference: exists, matches (with
  differences), relevance (not_assessed by the tool; a reader's judgement with its reason, or "not judged")
Checks: check_card.py PASS (date, commit or file sha); any NOTE it printed, repeated here
Gaps: gap_coverage.py: N empty applicable fields with no gap (0 for a new card); empty lists the
  standard has no gap path for, named
Entities: entities.json <sha256>: N mentions, E exact, A ambiguous, F not found; symbol-like words of
  the source no mention covers; identifiers the card holds that are only candidates of their mention
  (a broader or narrower entry), named
Missing answers: missing-answers.json <sha256>: rows per state (answered / not_applicable /
  not_in_source / searched_not_found / not_yet_checked / unexplained_empty) across the six aspects;
  every row of origin "interpretation" named, with its action
Evidence counted apart (never one total): E evidence lines, S distinct sources, P primary datasets or
  first-source results, D dependencies between them (a line that rests on another's data)
Entailment: N records: E entails, P partial, X no; checked_at ...; ledger examples/ledgers/<slug>.json
  partial/no kept, with reason: <pointer>: <why kept>
  corrected after the pass: <pointer>: <what changed>, re-checked at ...

Plan criteria (when the card has a row in the example plan):
  met: ...
  not met, and why: ...   (nothing added to meet them)

Gaps: <path>: <disposition>, <why>
Not done: <what the converter did not read or check>
```

"Not done" is required. Name the cited works not read, assessments not made
(`risk_of_bias: not_assessed`), and anything the checks cannot see.

## The seven points a card is accepted on

The report above is the material; these seven are what the acceptor decides on. A report that holds
every line of the template and leaves one of these seven unanswered is not ready to be handed over.

1. **The source, the exact version of the code and instruction, and the card.** The article with its
   sha256, the released kit version with its rules hash, the model, and the card with its
   `content_hash` and its version number. A working tree is not a version.
2. **An independent inventory, the coverage map, and a substantive check of the weak matches.** The
   inventory is made by a reader who did not see the card. A match by paragraph and type is an
   address: each one is either confirmed by a sentence naming the value and what in it carries the
   item, or answered by a reason that the card read that paragraph and still does not hold the item,
   or it stays unanswered. Both answers are reported as **judged**, and separately: a confirmation
   claims coverage, a reason concedes a statement of the article that the card leaves out.
3. **The search log, the sources read, the accepted additions and the provenance of each — and,
   separately, what gave nothing.** The queries with their dates and counts, the families, the
   cut-off. A tool or family that returned nothing useful is named with its numbers, not left out:
   its absence from the report would read as if it had never been tried.
4. **Every direction of criticism, the corrections, and the questions left open.** All three lenses,
   per wave, "nothing" included with what that lens examined; what was corrected and what was not,
   with the reason. A card stopped by the ceiling with findings still open is handed over as needing
   more work.
5. **The comparison with the previous result, where there is one**: what was usefully added, what was
   lost, what was strengthened without a basis, and what stayed unknown. Where the kind of input has
   no comparable earlier result, the report says so plainly rather than comparing against something
   that is not alike.
6. **The measured cost**: clock time, agent calls, searches run, sources read, waves. Tokens are not
   measured here, and an estimate is never reported as a measurement.
7. **Acceptance by a checker independent of the converter.** The converter does not accept its own
   card. The report names who accepted it and against which rubric, and an acceptance conditional on
   corrections says which.

**The ownership decisions are an object of acceptance, not an implementation detail.** Where a
sentence of a submitted text was judged own or third-party, where a value's licence decided whether
a quotation or only a locator could be carried, and where a right-holder's permission was relied on —
each is named in the report with its reason, so the acceptor can disagree with the decision rather
than discover it in the card. A paragraph the tools flagged as carrying a reference is a hint, and
the report says what the converter judged it to be.

The result these seven are read for is one thing: that the substantive completeness of the card grew
**without a growth in unsupported additions**. New references and passing unit tests are not a
substitute for that finding, and neither is this template.
