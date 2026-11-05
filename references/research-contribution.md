# Produce a research-contribution companion

Use `scripts/research_contribution.py` explicitly to associate an existing OHF
1.4 card with an existing `search.py known-merge` result. The producer runs
entirely on supplied local bytes. It emits `ohf-research-contribution/1` inside
the standard companion envelope and validates it with the selected standard's
`tools.companions.api.evaluate` before export.

Provide a separate checkout of standard commit
`0b6f5ef1003f696220d8bb0b8316260825e4a10c` (tree
`22fdde400cd18e29f268c886fdb2f0c63d27b3da`). The producer checks the source closure
in `research-standard.json` before executing captured modules in a private
namespace. This companion dependency is separate from `OHF_REPO` and the native
profile's standard association.

1. Retain the card and the known-merge JSON result unchanged. The selected
   proposal's UTF-8 hash must equal the result's `input.text_sha256`.
2. If a future card assessment needs a search association, obtain the bounded
   scope with `scope`. Retain its exact JSON bytes and bind their SHA256 in the
   assessment's existing `search_scope_ref`. The producer does not edit an
   assessment or retrofit a search association into an existing card.
3. Supply a request with the closed structure below. Pointers select existing
   card members. Indexes in `known_results` refer to the native result's `works`
   array, starting at zero. A selected work must be a recorded evidence item,
   and its identifier must match the selected card reference.
4. Call `produce` with a new output directory. Validation failure returns exit 2
   and no companion export; an existing output directory is never replaced.
   An export write failure may leave partial files, which must be preserved.

```sh
python scripts/research_contribution.py --standard-root /path/to/standard scope known-result.json
python scripts/research_contribution.py --standard-root /path/to/standard produce card.json known-result.json request.json contribution-bundle
```

An invented replication request:

```json
{
  "format": "ohf-extractor-research-request/1",
  "origin": "ai_addition",
  "actor": "named assistant",
  "novelty_claim": "not_new",
  "selections": {
    "proposal": "/added/layers/core/statement",
    "question": "/added/layers/core/uncertainties/value/0",
    "next_test": "/added/layers/core/testability",
    "novelty": "/added/layers/core/novelty_assessment",
    "positive_prediction": "/added/layers/predictions/0",
    "negative_prediction": "/added/layers/predictions/1",
    "known_results": [{
      "work_index": 0,
      "result": "/author/layers/evidence/lines/0/result_estimate",
      "reference": "/author/layers/evidence/references/0/identifier"
    }]
  },
  "annotations": {
    "contribution_type": "replication",
    "replication_justification": {
      "reason": "The invented earlier assay used one site.",
      "changed_conditions": "Repeat blinded at an independent invented site.",
      "prior_result_pointer": "/author/layers/evidence/lines/0/result_estimate"
    },
    "outcome_additions": {
      "positive": "Persistence would distinguish durable from transient action.",
      "negative": "Loss would bound the toy action to continued exposure."
    }
  }
}
```

`author_proposal` selects the proposal, question, test, assessment and predictions
in `author`; `ai_addition` and `other_addition` select them in `added`. Prior-result
context may select either zone. No field is copied into another zone. New
contribution annotations occur only in `contribution_type`,
`replication_justification` and `outcome_additions`; proposal, question, test,
assessment, prediction and result text remain in the retained card.

`published_result` requires bound prior results and a `known_result` assessment;
its claim is `not_new`. A replication additionally requires a reason, changed
conditions and one bound prior result. `not_new` without a bound result refuses.
A `new_test` with unavailable coverage remains `unknown`. To request `novel`,
the existing bounded-search assessment must already bind the exact generated
scope with nonempty queries and `complete_within_scope` coverage. A partial or
missing scope cannot authorize that request. With the same inputs,
`novelty_claim:unknown` stays unknown rather than becoming novel automatically.
A native `new` classification alone is insufficient.

The bounded scope names the recorded queries, native check timestamp, per-query
depth and maximum selected works. Native `complete` means completion within that
selection scope, never exhaustive literature coverage. A retained partial scope
can accompany an unknown assertion. Any recorded collection failure, failed
query or `incomplete` detector result refuses the entire export, including when
some prior results survived. It is never an empty successful search.

The bundle retains the original card, known-result result and request bytes,
the generated bounded scope, the annotation declaration, the envelope and the
standard's report. Results say `SUPPLIED_UNVERIFIED`. Supplied evidence links,
origin and coverage are not authenticated, and the report separately exposes
card structural shape. Companion validation does not establish source truth,
scientific support, novelty, ranking, score or whole-card acceptance. Missing
outcome bindings and their annotations must both be null; they are reported as
`not_supplied`.

For local full tests, set `OHF_RESEARCH_STANDARD` to the pinned companion checkout
in addition to the ordinary `OHF_REPO` for each supported test standard. Without
that explicit companion selection, its tests report a skip; the Forgejo full
matrix selects it for both standards. Tests
use invented cards, transport responses and checker declarations. The command
is opt-in; existing searches, default conversion and native rubric activation
are unchanged.
