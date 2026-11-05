# Fields, layer by layer

The full definition of every field is in `spec/fields.md` of the open-hypothesis-format
repository, and the schema is `schema/hypothesis-1.schema.json`. This page says how to
fill each field from an article and where conversions have gone wrong. The worked example
is `examples/cards/muller-sheltering.json`: open it next to this page.

Every added value is a wrapper `{"value": ..., "src": "<key of added.sources>"}`, with
`paraphrase: true` and `basis_quote` when it restates the authors. Identifiers (`id`,
`atom_refs`) are plain strings.

## Author zone

| Field | Fill with |
| --- | --- |
| `core.statement` | The sentence in which the authors state the hypothesis, exactly. Prefer the abstract or the end of the introduction. |
| `core.explanandum` | The phenomenon or question, in the authors' words. Not a goal ("to treat X"). |
| `mechanism.summary` | The authors' own mechanism sentence, if there is one. |

Each value is whole sentences: `doc.author(n, text)` and `check_card.py` refuse a value
that does not start and end on a sentence boundary of paragraph n.

- A sentence starts at the start of the paragraph, or after a sentence end and its space.
- A sentence ends at the end of the paragraph, or at a ".", "?" or "!" followed by a space
  or the paragraph end; closing quotes and brackets right after the mark belong to the
  sentence (`He wrote "Z holds."`, `(Yes, it does.)`).
- Not an end: the dot of an abbreviation (e.g., i.e., et al., Fig., Figs., vs., cf., Eq.,
  Ref., No., approx., ca., etc. and others listed in `ohfkit.ABBREVIATIONS`), and a dot
  followed by a digit (3.5).
- A citation that follows the sentence ("... stops [34, 68].") is part of it: quote it.
- To cut on purpose, use `doc.author_part(n, text, reason)`. The locator then ends with
  `; part of a sentence, cut by the converter: <reason>`, and the check accepts the cut.
  The schema allows no other member next to `value` and `locator`, so the locator is
  where the cut is recorded.

Leave the other author layers empty. Author-zone predictions and evidence are for a
submitter's own card, not for a conversion.

## Core (added)

- `kind`: `mechanism`, `association`, `intervention_effect` or `prediction`. Use the
  claim the authors make, not the method they use.
- `scope`: the systems and conditions the claim applies to, **with every condition the
  authors attach**. Take `src` from the paragraph that states the conditions; if they are
  spread over several paragraphs, the record will be `partial` and the report names the
  other paragraphs.
- `atoms[]`: one bounded claim each, with `claim_type`, `role` and `modality`.
  - `modality` rests on the authors' hedge, quoted in `basis_quote`: "we show" →
    `claimed_shown`; "likely" → `likely`; "we propose", "plausible" → `proposed`;
    "might", "could", "speculate" → `speculative`.
  - A firmly asserted inference ("there must be", "assuredly") has no value of its own:
    record `likely`, never `claimed_shown`, and keep the `partial` the check gives. A
    reader takes modality as the author's confidence, so overstating it is worse than
    understating it.
  - Keep conditions inside the atom ("when the Y carries functional copies"). An atom
    without its condition is stronger than the authors' claim.
- `explains[]`: observations the hypothesis accounts for. `status` is how the observation
  stands **under the other accounts, not under this hypothesis**: `unexplained` if no
  account explains it, `contested` if accounts disagree, `explained_by_rival` if a rival
  explains it, `explained` if an accepted account does. Only unexplained and contested
  items count as gaps in knowledge. Give `atom_refs`, and `observation_ref` to the
  evidence line that reports the observation when there is one.
- `reinterprets[]`: a finding, its current interpretation, the proposed one, `atom_refs`.
  The current interpretation must be one the article attributes to the literature.
- `opens[]`: new questions the hypothesis makes worth asking, why they are not asked
  today, and the enabling method if the article names one.
- `alternative_explanations[]`, `uncertainties[]`: as the article names them. A list has
  one `src`; if the items come from several paragraphs, the record will be `partial`.
- `testability` (assessment): in principle and in practice, a justification and the
  cheapest test. Every clause of the justification needs support in the cited paragraph.
- `first_proposed`: the date the idea was first proposed, from the article (its own
  publication date if the authors propose it there; otherwise the earlier work they
  credit), with `precision` and `basis: author_statement`.
- `falsification_condition`: only if the authors state what would count against the
  claim. Otherwise a `not_supplied` gap; do not derive one from a prediction.

## Predictions

One item per testable prediction the authors state. `system.kind`, `endpoint` (usually a
paraphrase with `basis_quote`), `direction` for a directional contrast, `form`,
`epistemic_status` (`novel` if stated before the result was known; `retrodicted` or
`accommodated` need `known_result_ref`), `derives_from_atom_refs`.

`discrimination` and `also_expected_under[]` need grounds in the article: an alternative
it names that would expect the same outcome, or a statement that only this hypothesis
predicts it. Without such grounds, both are `not_supplied` gaps. Do not rate
discrimination from general knowledge.

`resolution` (outcome of a prediction) is filled only from a published test, with its
source. For an open hypothesis there is none.

## Evidence

Each line: `id`, `target_ref` (an atom), `direction` (`supports`, `disputes`, `neutral`),
`quote` (exact, from the line's own source), `study_type`, `study_system`, `items` (the
artifact and locator), `argument_kind`, `indirectness` (assessment), and when assessed
`risk_of_bias` (assessment). Write `direction`, `study_type` and `study_system` as
`{"value": ..., "src": ...}`: they are the converter's reading and each gets its own
entailment check (the checker sees `direction` with the statement of the target atom).
`study_type` and `study_system` say only what the line's own passage says; a model name
or dataset from the methods section belongs in a line whose `src` is that section.

- `direction` is toward the target atom, as the source reports it. A model result that
  the authors present as a limit or a caveat is `neutral` or `disputes`, not `supports`.
- `indirectness` is distance from the claim: a different system, endpoint, intervention
  or comparison. **Imprecision is not indirectness.** A wide interval or a low-power
  estimate does not make the endpoint indirect.
- `risk_of_bias`: `not_assessed` unless the converter examined the methods of the study.
  Sampling bias named by a published reanalysis is grounds for `high` or `some`, with that
  reanalysis as the source.
- `independence_group`: set the same label on lines that rest on the same data, study or
  laboratory, when a source says so. Lines from different groups need different labels.
- Conditions of the line (OHF 1.1): what the study behind the line was, as the line's own passage
  states it, each `{value, src}`. A line may hold `system` (the members of a prediction's system),
  `intervention` (`agent`, `dose`, `regimen`, `duration`, `route` with its closed `term`, ...),
  `sample_size` (an integer, the number the source gives for this result) and `multi_site_program`
  (`{program, sites}`, only when a source names the programme and at least two sites). The
  intervention describes the study, not the claim, so it is given whatever the domain profile.
  Each is the converter's reading and gets its own entailment check, like `study_system`. A dose or an
  age that the quote names is recorded, or given a gap with its reason: otherwise the standard's
  `check_refs` warns `REF_CONDITION_IN_QUOTE`.
- `result_estimate` (OHF 1.1): when the quote states the result in numbers, an object
  `{reported, measure, contrast, scale}`, `{value, src}` like the quote. `reported` is words of the quote,
  cut from it, never retyped; `measure`, `contrast` and `scale` are as the source states them, or
  `not_stated`. Where it cannot be given, a gap on that line's `evidence.lines[N].result_estimate`
  (not on the whole list) whose disposition is not `not_supplied`, since the estimate can always say
  `not_stated`. `line_figures.py CARD --standard DIR` lists, per line, the spans the standard's patterns
  take for a result, a dose or an age, the sentences of the quote that hold the result (cut `reported`
  from these), what the line records for them, and the standard's codes: `REF_ESTIMATE_IN_QUOTE` (a
  number with neither an estimate nor such a gap), `REF_ESTIMATE_NOT_QUOTED` (`reported` not in the
  quote), `REF_CONDITION_IN_QUOTE` (a dose or age not recorded). The patterns and the codes are the
  standard's `check_refs`, run in the checkout DIR. The estimate, like the quote, gets its entailment check.
- `system.taxon_id` (OHF 1.1): the NCBI Taxonomy id of the taxon the line's `system.taxon` names, of
  any rank: a species, a genus (Drosophila), an order (Carnivora), a class (Mammalia). Run
  `biodb.py taxon-ids CARD [--reading FILE] --taxa taxa.json --out CARD --standard DIR`. Each line's
  word, or the converter's reading of it (`{line id: name or NCBITaxon id}`), is looked up; it is
  placed as `{value, src: "biodb_<call>"}`, with the call among `added.sources` (the efetch URL, the
  taxon, the time, the call), only when it names exactly one taxon: its id, its scientific name, or
  (in the reading) one of its NCBI common names, whole. A line's own word that matches only a
  common name is a candidate, not placed: NCBI gives "humans" to the genus Homo and "flies" to the
  order Diptera, so confirm it or name the taxon meant (Homo sapiens) in the reading. A group no
  taxon is named for ("ruminants", "amphibians and reptiles", a list of species) and a name of
  several taxa ("mouse") get a gap on `evidence.lines[N].system.taxon_id`, `searched_not_found` with
  the call in `query_ids`; a failed lookup, `blocked`. A declared id is kept and compared, and a
  value placed later removes that line's gap. `taxa.json` then feeds `proximity`.
- `human_proximity` (OHF 1.1): the line's rung, derived, never chosen. Run
  `biodb.py proximity CARD --standard DIR [--taxa taxa.json] --out CARD` with DIR a checkout of the
  OHF release (its `VERSION` 1.1.1 or later): the standard's own `check_refs.derived_proximity`
  derives the rung from `system.taxon_id` and the endpoint kind's `term`, and the value is
  `{value, src}` with the `src` of the taxon id (the `biodb_<call>` source of the taxonomy lookup).
  For humans the endpoint kind decides: biomarker, physiological, molecular give `human_marker`;
  lifespan, mortality, function, disease, adverse_event give `human_clinical`. Where nothing is
  derived (no system, no one taxon by id, a taxon in neither table, a human line with behaviour,
  other or no endpoint kind) the line gets a `not_supplied` gap that says why, not a rung by
  default: a group such as "mice and marmosets" has no rung of its own even when its members
  agree. A rung the line already declares (`in_vitro`, `ex_vivo`, or one set by hand) is kept and
  compared. The command rehashes the card and reports `check_refs`' `REF_PROXIMITY_*` issues.

## Provenance and profile

Provenance (`claim_author`, `author_type`, `licence`, `original_artifact`,
`origin_method: published_restatement`) comes from the article metadata, with a `meta`
source whose locator is the contrib-group and permissions block. `profile.domain` is
`none` unless the claim is about an intervention given to an organism.

## Gaps and completeness

Every field the catalogue expects for the card's level and the article does not give is a
gap: `path`, `disposition`, `reason`, `query_ids`, `inspected_artifacts`. `not_supplied`
is for what only the author can state; `searched_not_found` needs at least one query.
`check_gaps.py` checks the supplied gap rows. `completeness.level` is `accepted` when the
author voice is an exact quotation and the article is open; `missing_for_next` says what
would raise it.
