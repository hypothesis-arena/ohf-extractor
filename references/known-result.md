# Known result or duplicate: the checker's instructions

A submitted hypothesis may already be on the arena (a card states the same claim) or already tested in
published work (a known result). `search.py known-input` gives a checker the candidates; the checker
reads them and says what each is; `search.py known-merge` checks the verdicts against the bytes the kit
fetched and decides. Finding a candidate is not evidence: a work or card counts only through a checker's
verdict, and a work's verdict only with a quote the kit finds in the work.

## Who reads

- The **query writer** writes the literature queries from the hypothesis text alone. `search.py
  known-search` runs each one as given, narrowed to trials and experiments, narrowed to null results, and
  restricted to trials by publication type with the most cited first (`PROBES`), each in Europe PMC and
  PubMed and each also without reviews: a test is looked for whichever way it came out, so that both
  sides of a disputed claim can be found. The trial probe's first works go into the input first. It never reads the verdicts' gold or any answer.
- The **first reader** reads every work and every card of the input. It is not the query writer.
- The **second reader**, in another session, reads every work and every card of the input too, without
  seeing the first reader's verdicts, so that it can see a test the first did not. A result stands only
  when the second reader gives the same verdict class on an item it rests on; otherwise it is a
  recommendation.

## For the checker

You get the hypothesis text, up to five cards (each with what it states) and up to sixty works (each
with its title, its abstract and its publication types as Europe PMC gives them). For each card, say `relation`:

| relation | when |
|---|---|
| same_claim | the card states the same claim: same cause, effect, direction, system and context |
| variant | the same claim in another context (species, sex, age, dose, regimen, measure) |
| competitor | another explanation of the same thing |
| related | shares a topic or a mechanism, not the claim |
| unrelated | not about this claim |

For each work, say `verdict`:

| verdict | when |
|---|---|
| tests_supports | the work reports its own test of the claim — an experiment, trial, observation or analysis that could have come out against it — and the result agrees with it |
| tests_refutes | the work reports its own test of the claim, and the result disagrees with it |
| tests_mixed | the work reports its own test, and the result agrees in part or in some conditions only |
| proposes_or_discusses | the work states, proposes, reviews or argues the claim, with no test of its own |
| unrelated | the work is not about this claim |
| not_retrievable | you could not read it (no abstract and no open text) |

Rules:
1. Judge the claim as the text states it, not a nearby one. A test of a weaker form (another dose,
   comparator or outcome) is `tests_mixed` only if the work itself says what it means for the claim;
   otherwise it is about another claim (`unrelated` or `proposes_or_discusses`). A test of the same
   intervention and outcome in another population is a test: say how its population stands to the
   claim's with `population_match` (rule 4).
2. A work that proposes the hypothesis is `proposes_or_discusses`, even if it is the original article.
   A review or meta-analysis that reports others' tests is `proposes_or_discusses`: the evidence is the
   primary trial or experiment itself. The kit enforces this for every work whose record states such a
   publication type (`SECONDARY`): a tests_* on it is listed as `context`, never evidence. A review whose
   record does not say so (typed as a research article) is caught only by you.
3. For every tests_* verdict give `quote`: at most 25 words, copied exactly from the title or abstract
   shown, that states the result. Give `locator`: `title` or `abstract`. A verdict whose quote the kit
   cannot find verbatim is logged and is not evidence.
4. For every tests_* verdict also give `population`: at most 25 words, copied exactly from the title or
   abstract, that state whom or what the work enrolled (its selection criterion), and `population_match`,
   how that population stands to the claim's:

   | population_match | when | counts as |
   |---|---|---|
   | same | the claim's population; or a wider one with a subgroup of the claim's population whose result the work reports (quote the subgroup's criterion) | a test; decisive if tests_supports or tests_refutes |
   | narrower | a part of the claim's population only | a test of a part: tested, never decisive for the claim |
   | broader | a wider population, with no reported result for the claim's | context, not a test |
   | not_comparable | a population the claim's cannot be compared with | context, not a test |

   Judge it from the selection criterion and the claim as written: a trial that enrolled whoever the
   claim names, by the criterion that defines them, is `same` even when the claim's words are more
   general (a claim about "systemic inflammation" and a trial selecting by CRP). A test with no
   `population_match`, or whose `population` the kit cannot find verbatim, is logged and is not evidence;
   a `population_match` off the list is refused.
5. For every tests_* verdict also say how precise the test is, with the passage of the title or abstract
   that states it (at most 25 words, copied exactly); say `not_stated`, with no passage, when the title
   and abstract do not say, and do not infer it:

   | field | passage | values |
   |---|---|---|
   | design | design_quote | `randomized` when the work assigned the intervention by randomization; `experimental` when the investigators assigned it without randomizing (a controlled laboratory or animal experiment); `observational` when they did not assign it (a cohort, registry, case-control or "real-world" study of whoever received it); `not_stated` |
   | primary_prespecified | primary_quote | `yes` when the outcome the result is about was the work's pre-specified primary outcome; `no`; `not_stated` |
   | stop_reason | stop_quote | why enrolment ended: `completed` (its planned size or number of events, even if later follow-up was cut short), `futility`, `harm`, `efficacy`, `operational` (funding, slow enrolment, organisation), `not_stated` |
   | effect_excludes_null | effect_quote | `yes` when the reported interval of the effect excludes no effect (supporting tests); `no`; `not_stated` |
   | underpowered_stated | underpowered_quote | `yes` when the work itself states directly that it lacked power: it was underpowered, it enrolled short of its planned size, or the planned power was not reached, whatever its stop; `no` (the default) otherwise |

   `underpowered_stated` is a statement about the trial's power or size, not a reading of its result.
   "The trial was underpowered to detect a difference in mortality" and "enrolment stopped at 120 of the
   planned 300 patients" are `yes`. "No difference was found, which may be due to limited numbers" and
   "larger trials are needed" are `no`: they explain a null result, they do not say the trial lacked power.

   Only a precise test decides (below). Every decisive test needs a `randomized` or `experimental` design
   and a pre-specified primary outcome: an observational association is a test, but it never decides,
   whichever way it points, because nobody assigned the intervention. A test stopped for `operational`
   reasons never decides either way, not even a support whose interval excludes none. A **refuting** test
   then decides: a null result never excludes no effect, a stop for futility or harm is made by a data
   monitoring committee on boundaries set in advance, and an abstract that does not say why the trial ended
   does not show an under-enrolment. A **supporting** test decides only with an effect that excludes
   none: a stop on completion or for `efficacy` does not decide it by itself, and a trial stopped for
   efficacy whose interval includes no effect is not decisive. A refuting test whose work says it was underpowered
   never decides; this does not touch a support by its interval. A `yes` or `no`, or a design, whose
   passage the kit cannot find verbatim counts as `not_stated`; a stop reason whose passage it cannot find
   counts as `unverified`, which never decides, and so does an `underpowered_stated: yes` whose passage it
   cannot find; a value off the list is refused.
6. Before handing in, run `search.py known-check IN.json VERDICTS.json --workdir WORKDIR`. It lists each
   passage (quote, population or precision passage) that known-merge would not verify, and why: `too_long`
   (over 25 words), `not_found` (not an exact passage of the title or abstract the kit fetched) or
   `missing`. Rewrite each listed passage once, from the title or abstract, and hand in. A passage still
   listed is lost, as known-merge says; do not change a verdict to make a passage pass.
7. For `not_retrievable` give no quote and no locator. Never invent a quote, a locator or a date.
8. Do not use what you remember about the work or the field: only what is shown.

Answer as JSON:

```json
{"checker": {"name": "...", "model": "...", "session": "..."},
 "cards": [{"item": 1, "relation": "related", "locator": "statement"}],
 "works": [{"item": 1, "verdict": "tests_refutes", "quote": "...", "locator": "abstract",
            "population": "...", "population_match": "same", "design": "randomized",
            "design_quote": "...", "primary_prespecified": "yes",
            "primary_quote": "...", "stop_reason": "completed", "stop_quote": "...",
            "effect_excludes_null": "not_stated"},
           {"item": 2, "verdict": "unrelated"}]}
```

## What the result is for, and what it may not be used for

**A result here is a record, never a filter.** `duplicate` and `known_result` are statements about
what was found, with the candidates, their hashes and the calls that found them; neither one drops a
submission, closes it, or decides what the arena does with it. A submission judged `duplicate` is
still a submission: its candidates are recorded beside `identity.duplicate_cluster_ref`, so a reader
can see which cards were considered and disagree with the judgement. A filter that silently drops a
near-duplicate leaves no trace that a decision was made, which is the same defect as a search whose
negative results are not logged — and this kit's own rule is that an absence is a finding only when
the search behind it is in the log.

The same holds for `new`: it says no match was found **in this search**, with that search's queries
and their counts beside it — and with **what that search is known to find**. The one measurement
there is: the work the gold set names was among the candidates for only **3 of 15** tested claims on
the second deferred run (2026-10-23, queries as given), and again **3 of 15** on the third (2026-10-23,
with the trial and null-result probes; the searches found 8 of its 22 gold works, and the limit on
works cut 5 of them). With the publication-type trial probe it was **15 of 15** on the fourth
(2026-10-23; 21 of its 23 gold works were found by that probe). A `new` from a search of that
recall is nearly empty of information, and shown without the figure it reads as the opposite. So a
`new` carries the probe set that produced it (`as_given`, trials, null results, publication-type trials) and the recall last
measured for that set; until a fresh held-out run re-measures it, the figure to quote is the one
above, with its date and run. It is not a claim that the hypothesis is new, and it must not be shown as
one.

## The result (known-merge)

With a second reader, the result rests only on the items both readers gave **the same verdict**
(same_claim on a card, the same tests_* with the same `population_match` on a work); an item the readers
judged differently — a test for one and not the other, a test in different directions, or of a population
matched differently — is listed as `disputed`, with `raised_by`
naming the reader who called it a test (the first, when both did). A work whose record states a
secondary publication type is listed as `context` whatever the readers say, and so is a test the first
reader matched to a `broader` or `not_comparable` population; if the second reader held that work a test
of the claim's own or a narrower population, it is also listed as `disputed`, raised by the second. `result` is `duplicate` when a
card is same_claim; else `known_result` when the **decisive** tests — tests_supports or tests_refutes of the
claim's `same` population, each with a verified quote and population, and **precise** by rule 5 for both
readers — all point one way, and `direction` says which; else `tested_unresolved` when a
work is an agreed tests_mixed, an agreed test of a `narrower` population or an agreed test that is not
precise, or when decisive tests point **both ways across works** (`directions` counts
each): tested, no outcome, never a known result. A tests_mixed work, a test of a narrower population or an
imprecise test, beside decisive tests that agree, leaves their direction; else `new` when the search completed; else `incomplete` — an incomplete search is never
`new`. `new` means no match found in this search, not that the claim is new to science. `standing` is
`second_reader_agrees` or `recommendation`; a known result also needs a completed search to stand.
Every item carries its hashes (card `content_hash` and file sha256; work record response sha256), the
calls that found it, the readers with their sessions and the sha256 of each reader's verdicts, the merge
calls, and, for a quote, where it was verified (`response_sha256` names the kept response,
`WORKDIR/search-responses/<hex>.body`; `epmc_text` in search.py is the text it is checked against). A
card is identified by its `content_hash`, or, for a record with none (an arena hypothesis record), by its
id, version and the sha256 of its file (`identity` says which).
