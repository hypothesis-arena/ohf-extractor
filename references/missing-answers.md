# The map of missing answers

A card can pass every check and still leave a reader without the answers they came for. The gap
records say what the converter looked for and did not find; they do not say what was never asked.
This map asks, aspect by aspect, and gives each question one of six states. It is written for a
reader, not for a script: no state here is computed, and a state a script could compute
(`gap_coverage`, the search log) is taken from it rather than restated.

## The six aspects

Each is asked of the hypothesis the card carries, and of every atom where the atoms differ:

1. **Assumptions** — what must hold for the claim to be true, which the authors do not argue for.
2. **Scope** — the population, system, taxon or setting the claim is limited to.
3. **Conditions** — what the claim depends on, including the authors' own hedges.
4. **Predictions** — what should be observed if the claim holds, and what would count against it.
5. **Alternatives** — the other explanations, the authors' own and the literature's.
6. **Limitations** — what the work cannot settle, by its design or its data.

## The six states

| state | what it means | what the card holds |
| --- | --- | --- |
| `answered` | the card answers it from the source | the value, with its locator |
| `not_applicable` | the question does not arise for this kind of hypothesis, **with the reason** | a gap with a `not_applicable_*` disposition |
| `not_in_source` | the source does not give it | a gap, `not_supplied` |
| `searched_not_found` | looked for outside the source and not found, **within stated bounds** | a gap, `searched_not_found`, and the search in the log: the families, the services, the queries, the date |
| `not_yet_checked` | it could be answered and the work was not done — budget, time, or a source not reached | a gap, `budget_exhausted` or `blocked`, and the report says which |
| `unexplained_empty` | the field is empty and **nothing says why** | nothing — which is why this state exists |

`unexplained_empty` is the state the kit cannot always demand away: for a scalar field
`gap_coverage` now makes it an error, and for an empty list the standard has no gap path at all, so
it is named here and in the report. A question nobody asked is worse than one answered "unknown",
and this map is the only place it becomes visible.

## A converter's assumption is marked as interpretation

Where the map's answer is the converter's own reading rather than the source's words — an assumption
the authors leave implicit, a scope the converter infers from the methods — the row says so:

- `origin: interpretation` and the converter named, with what in the source the reading rests on;
- and the row carries the action it implies: **a question to the author** where an author is
  reachable, or a proposal recorded in a separate file, never written into the card as the authors'.

An interpretation that cannot be grounded in a locator is not written at all. The map is not a place
to put what the card could not hold.

## The file, and the row

The map is one JSON file, `missing-answers.json`, beside the card. It names itself, so that a reader
or a loader can tell what it is holding without being told:

```json
{"schema": "ohf-extractor:missing-answers@1", "kit": "ohf-extractor/<version>",
 "made_at": "2026-10-21T14:30:00Z", "card": "h_<slug>@<version>",
 "card_content_hash": "sha256:...", "rows": [ ... ]}
```

`card_content_hash` is the card the map was written against: a map whose hash does not match the card
beside it was written for another rendering of it, and says nothing about this one.

```json
{"aspect": "assumptions", "question": "...", "state": "searched_not_found",
 "origin": "source" | "interpretation" | "external_source" | "unknown",
 "evidence": "paragraph 7" | "DOI ... | GSE...", "gap": "core.falsification_condition",
 "action": "what would settle it", "note": "..."}
```

Every row has a state and an action; a row whose action is "nothing further is possible" says why.
The map goes beside the card with its SHA-256 in the report, and the report carries the count of
rows per state so that a reader sees the shape of what is missing before reading the rows.

## What the map is not

It is not a completeness score. The six states are kept apart and never summed into a number: a card
with ten honest `searched_not_found` rows is in better condition than one with ten
`unexplained_empty`, and no single figure can say that. The rubric of the acceptor decides what the
shape of a map is worth; the converter's job is that every question has a state and no state is
flattering.
