# Failure modes and checks

Use each row to identify a failure condition, why it is wrong, and the check or
reviewer action to apply. In "Caught by", "rule" means the reviewer must check the
condition; it does not name an automated check. Planted-defect tests are in
`scripts/tests/`.

| Failure (condition) | Why it is wrong | Caught by |
| --- | --- | --- |
| One constant time (`21:00:00Z`, `23:00:00Z`) is used for every assessment, or an assessment time is later than the commit | An invented time; a reviewer cannot tell which state of a value the check covers | `check_card.py` time check: round times, assessed after check, `added.at` before an assessment |
| An assessment keeps its old time after its value is revised, so it appears to have been made after its check | The check covers the old judgement | Time check; rule 7: re-assess, then re-check |
| A paraphrase adds a word the authors do not use ("a deterministic model") | The value claims more than the passage | Entailment pass (`partial`) |
| A paraphrase drops a condition: "at least half of losses are Y-linked" without "as the mutation rate approaches zero"; a mechanism summary omits "when recombination stops" | Same | Entailment pass |
| `scope` takes its `src` from the aim paragraph, while the conditions it states come from two later paragraphs | The checker sees only the cited paragraph | Entailment pass (`partial`); rule: cite the paragraph with the content |
| An `explains[]` item carries details from one paragraph but cites another | Same | Entailment pass; reviewer |
| `explains[].status` is flipped between rounds because it is read as "explained by this hypothesis" | Status is how the observation stands under other accounts | Rule (fields.md, `explains[]`) |
| An imprecise estimate is rated `serious` indirectness | Imprecision is not indirectness | Rule (fields.md, Evidence) |
| `discrimination` is rated from general knowledge | An ungrounded assessment | Entailment pass on the assessment; rule: gap without grounds |
| A reviewer requests a line against when none exists in the article | Adding one would invent evidence | Rule 6; the report records the unmet criterion |
| An evidence-line entailment record points at the whole line object | `check_refs` requires every record to point at a `{value, src}` node; the line's reading has no record | `check_card.py` (line fields must be wrappers); fields.md, Evidence |
| `study_type`/`study_system` carries a model name or dataset from the methods section while `src` points to the result paragraph | The value says more than its passage | Entailment pass; rule: the line's own passage only |
| The converter switches `profile.domain` to `none` for an intervention card | `none` forbids `predictions[].intervention`; the intervention content is lost | Schema; rule: fields.md, Provenance and profile |
| A rebuild after the entailment pass silently drops every record | The builder writes the card from scratch | `entailment.py carry` keeps only unchanged records |
| A sourced value states the converter's own work ("the registry record was not retrieved") | No passage can support it (`no`) | Entailment pass; such statements go to the report |
| Two checkers give opposite verdicts on the same unchanged indirectness values | Indirectness is distance from the claim, and the checker sees only the passage | Not caught. Giving the checker the target as well does not help: it then reads the target as a claim the passage must support. The reviewer checks indirectness against the target. |
| An evidence line targeting a prediction reaches the checker with no target, so its `direction` is judged blind | "supports" needs an object | `entailment.py` gives a prediction's population, endpoint and direction as the target |
| A real merge time falls on :00 seconds, and the time check refuses records as placeholders | The check cannot tell a real :00 from an invented one | `ohfkit.now()` waits out a :00 second |
| Local tests report green on an old copy of the tree | The result covers other bytes | Run the checks on the card file you hand over |
| A value changes after its entailment check (between `input` and `merge`, or by hand after `merge`); the record keeps `entails`, `check_card` passes and `carry` passes the record on | The verdict covers other text | `merge` refuses a stale input; the ledger binds each record to its value and passage; `check_card.py` / `check_ledger.py` fail on a mismatch; `carry` keeps a record only if the ledger hash matches |
| A builder passes `licence='CC-BY-4.0'` for an XML whose permissions say CC BY-NC-ND | Republishes NC-ND text | `skeleton()` derives the licence from the source and refuses NC, ND, SA, missing or ambiguous; `check_card.py` derives it again |
| A PDF or HTML main source has no rule for where its rights come from | The licence is only the builder's word | `skeleton(licence_statement=(n, text))`, checked against that page or paragraph and recorded as `added.sources["rights"]`; `check_card.py` re-reads it |
| An author-zone value drops a condition: "X causes Y" from "... X causes Y when recombination stops." | A trimmed passage no longer matches the authors' statement | `doc.author()` and `check_card.py`: whole sentences only; a cut needs `doc.author_part(n, text, reason)` |
| The HTML reader loses a paragraph after an unknown void element (`<source>`) or an unclosed `<p>`, and reads script text into a paragraph | Paragraph numbers shift and "not in the article" means "not read" | `HtmlDocument`: full void list, HTML implicit-close rules, script/style/template/noscript skipped, counted `<p>`, and `HtmlParseError` with line and column for a `<p>` it cannot close |
| To clear a `no`, an evidence line is deleted, and a prediction's `epistemic_status` is retyped from `novel` to `retrodicted` using a later paper's retelling | A fit to the checker, not a correction. The article contrasts the placements in other paragraphs, and the prediction's first record leaves the result open. Deleting the line also breaks the two-groups-against criterion | Rule (entailment.md, What to do with the verdicts): a `no` is information. Remove it only by correcting the reading of the article, with a locator; never by deleting or retyping the value. If the value was right, restore it byte-identical so the `no` record carries and stays visible, and record any added basis next to it |
| A value is rechecked until a convenient verdict appears; the overwritten ledger loses the earlier `no` | A re-roll: the record shows the last verdict, not the finding about the text, and the earlier `no` is no longer visible | Ledger history (format /2: every check appended, never removed) and `check_ledger.py`: the record must show the worst check of the current text, and the key is printed as disputed; `entailment.py restore` puts back checks from archived merged cards |
| A rebuild re-stamps unchanged assessments, so earlier checks appear older than the assessment they cover | No reassessment occurs: the new `assessed_at` is a false time, and the time check and `check_refs` refuse checks that still hold | `entailment.py carry` and `restore` give an unchanged judgement its earlier stamp (`assessed_at` and `assessor`); a changed one keeps the new stamp. A new kit version alone is not a re-assessment |
| `converter_hash` stays the same while `scripts/` changes | It does not attest the code that checks the card | `rules_hash()` covers `scripts/*.py` and the time-check bytes |

## Excuses that do not hold

| Excuse | Why it fails |
| --- | --- |
| "The time does not matter, the value is right" | The times are part of the record; a wrong time is a wrong fact in the card |
| "The checker is too strict; the paraphrase is fair" | Then the passage cited is the wrong one, or the paraphrase says more. Fix one of them |
| "Every showcase card needs two lines against" | A criterion of the example plan is not a licence to invent. Report it unmet |
| "The `no` would make the card look bad, so drop the value" | The verdict is a finding about the text. Hiding it removes information; fix the reading or keep the record |
| "The abstract is enough for this field" | The author zone and every `src` come from the full text you hashed |
