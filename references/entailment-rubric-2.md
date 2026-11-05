# Entailment rubric 2

Judge each item against its own `source_passage`. Each input item has exactly
`id`, `pointer`, `basis`, `value`, `source_passage`. Return one object per item,
in the same order, with `id`, `verdict` and an optional `note`. Verdicts are
`entails`, `partial`, `no`; a `partial` or `no` requires a nonempty note.

`entails`: the passage warrants the complete recorded value within its declared
scope, with its conditions, uncertainty and negation intact.
`partial`: the passage gives identifiable partial or qualified support for that
value, but does not warrant all of it. Name what is supported and what is missing.
`no`: the passage gives no warranted support for the recorded classification, or
contradicts it. Unsupported does not mean biologically false.

## A. Atom and modality scope

A modality question is about how the author asserts one specified atomic claim.
Read `modality` together with the complete `atomic_claim` and `modality_scope`
in the value. The atom and its scope name the question; they are not evidence.
A bare `proposed`, an atom identifier without its statement, or missing scope is
not an admissible modality question. Preparation must refuse such an input.

Classify the author's assertion, not whether this paper proves the claim.
Do not transfer “we propose” from a method, a different atom or one independent
clause to the whole target. Keep all conditions, uncertainty and negation.
A hedge on a proper subclaim needs a separately bounded atom/question before
freeze. A matching hedge word alone is insufficient for `entails`.

## B. Direction and complete support

`supports` records positive direction: this finding bears on this bounded target.
It does not assert truth, full demonstration, an exclusive explanation, independent
replication or support beyond the target's conditions. Judge whether the passage
warrants the complete directional classification, not whether it proves the
hypothesis. Keep the target, finding quotation, system, comparison, indirectness
and term conditioning. A positive word or related observation is insufficient.

Prepare separate questions for independent compound assertions before freezing.
Do not mechanically split on “and”: conditions, negation and inherited assumptions
of one relation stay attached. A child answer does not authorize an unsplit parent.
If only part of an unsplit compound is supported, it cannot receive `entails`;
apply `partial` or `no` as defined above. Do not change targets, split/reorder
output rows or aggregate child answers. Explicit multiple target units without
separately bound questions are a preparation refusal, not a scientific verdict.

## C. Antecedents and provenance

Only this item's `source_passage` supplies evidential premises. Atom/target
context defines the question and does not supply evidence. For `basis_quote`,
the passage is that quotation; the surrounding paragraph is not implied.
Resolve an antecedent only when its defining text is inside this passage.
Do not recover it from another item, an article, card, citation, sidecar,
conversion notes, advisory, prior question or general knowledge.

Use `partial` only when the passage gives identifiable partial or qualified
support. An unresolved antecedent alone is not partial support; without such
support use `no` (unsupported, not a finding of biological falsity). A missing
or structurally incomplete question is instead a preparation refusal.

Source identifiers, versions, locators and declared provenance outside the
passage may bind work/byte/locator identity and route an item. They do not
establish that a finding used a particular dataset/cohort or was independent
of another finding. Mentioning a study does not establish use of its data.
Keep deterministic reference resolution separate from scientific support.

Do not fetch or infer extra evidence. An expanded passage needs a new explicitly
sourced question and input freeze; no invisible configuration/sidecar premise or
answer reuse. Preserve source tensions without reconciling them by assumption.
No external-context admission mode is defined here.

The result is local to this question and rubric. It is not whole-card acceptance,
source completeness, biological truth or an agreement/accuracy statistic.
