# Does a cited work say what the text attaches it to

A submitted text (a model's answer, a person's note or blog) cites works for its statements. `check-refs`
answers two questions: does each work exist, and does the reference describe it correctly (title, first
author, year, journal)? It leaves a third open, `relevance: not_assessed`: does the work say what the
paragraph that cites it attaches it to? A real paper cited for a claim it does not make is the commonest
fault of such texts. A verified, matching reference is still no evidence until this is answered.

This question is answered by a **separate checker**, not by the converter that extracted the card. The
checker sees only this file and the input, and reads the works itself. The code checks the form of the
answer. It never judges relevance.

## Steps

1. `search.py check-refs TEXT --workdir W`: existence and correspondence, logged.
2. `search.py relevance-input TEXT IN.json --workdir W`. This makes one item per reference that exists and
   matches. Each item holds:
   - the paragraph that cites the work, with its hash;
   - the work's identifiers and title;
   - where to read it (Europe PMC, PMC, PubMed, DOI).

   An entry of a numbered reference list is sent once for each paragraph that cites its number. An
   entry the text never cites is not sent. References not found, ambiguous or mismatched are listed
   under `not_sent` and stay `not_assessed`. They never become a source of the card. The input holds
   the submitted text, not the works' text.
3. The checker answers `VERDICTS.json`:
   `{"checker": {"name": ..., "model": ...}, "verdicts": [{"item", "cited_in_sha256", "outcome", "locator"}]}`.
4. `search.py relevance-merge TEXT IN.json VERDICTS.json --extractor NAME [--extractor-model M] --workdir W`
   logs one `relevance` record per item. It is refused, and nothing is logged, when any of these holds:
   - the checker is unnamed, or is the extractor;
   - the text or a paragraph changed since the input;
   - an item has no verdict, or a verdict has no item;
   - an outcome is outside the list;
   - a locator is blank;
   - a verdict carries any other field.

   A checker of the same model in a separate run is allowed, as for entailment, and the report says so.

5. `relevance-input TEXT IN2.json --recheck related_not_claim` sends again the pairs whose latest verdict
   is that outcome, for a reading of the full text. It runs only after `search.py text ID` has found
   the open places of each work. A pair with no open full text is not sent, and its verdict stands.
   The checker is not shown the earlier verdict. The new verdict, logged with `basis: full_text`,
   replaces the earlier one.

`search.py report` prints each verdict with its locator, the checker and the extractor. It then gives
the support of each claim: for every paragraph, how many of the works it cites that could be read were
judged `supports_claim`. A claim is measured by this share, not by the number of works it cites. A
paragraph whose readable works support none of it is marked NO SUPPORT.

## For the checker

You get IN.json. For each item, read the work at one of the `read_at` addresses: the abstract first, and
the open full text where the abstract does not settle it. Decide whether the work states what the
paragraph `cited_in` attaches to it. Use only the work: not the rest of the submitted text, not what you
know of the field. Answer each item with one outcome:

- `supports_claim`: the work states it, for the organism, system and condition the paragraph names. A
  claim the paragraph narrows ("in this cell system", "under leucine starvation") is judged as narrowed.
- `related_not_claim`: the work is on the topic but does not state it. This covers a weaker claim, another
  system, a claim the work only cites from elsewhere, or the reverse direction.
- `unrelated`: the work is not about it.
- `not_retrievable`: no abstract or open text could be read at the given addresses.

An item with `full_text` is a second reading: read the work at those places, the full text and not
only its abstract, and judge it afresh.

`locator` says where in the work you read it: "abstract", "Results, 2nd section", "Fig. 3". For
`not_retrievable`, it says what you tried. Do not copy the work's text into the answer: only these four
fields are kept. When in doubt between two outcomes, give the weaker one.

## Limits

- The checker reads the abstract and the open text. A claim made only in a closed full text comes out
  `related_not_claim` or `not_retrievable`, not `supports_claim`.
- A paragraph citing several works is judged once per work. The judgement is whether each work supports
  what the paragraph says, not whether the paragraph's argument holds.
