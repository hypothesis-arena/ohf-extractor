# The inventory of an article

An inventory is a list of what one article says, written from the article alone, each item with the
paragraph it is in. It is written twice: by the converter, before building (step 2), and by a second
reader who **never sees the card** (step 5). `scripts/coverage.py` then reconciles the second
reader's inventory with the card, and every item with no match is a P1.

Why a second reader at all: the entailment pass checks a value against its passage, so it can catch
a value that says more than its source. It cannot see what the card never mentioned. A hypothesis
the converter missed, a condition it never wrote down and an alternative it passed over are all
invisible to every check in the kit. Only another reading of the article finds them.

## What the second reader is given, and what it is not

Given: the article (the same bytes the converter read — its `source_text_sha256`), this file, and
the work directory to write into. Nothing else.

Not given: the card, the builder, the converter's own inventory, the report, the entailment input or
output, the example plan, or any description of what the card is supposed to show. A reader who has
seen the card writes an inventory shaped by it, which measures nothing. The converter does not write
this inventory itself, and does not answer the reader's questions while it works.

## The form

One JSON file, `inventory.json`:

```json
{
  "article": {"id": "PMC8755536", "source_text_sha256": "sha256:..."},
  "read_at": "2026-10-21T10:30:00Z",
  "items": [
    {"id": "i1", "type": "claim", "paragraph": 7, "text": "...", "hedge": "may", "quote": "..."}
  ]
}
```

Each item carries:

| field | what it holds |
| --- | --- |
| `id` | `i1`, `i2`, … in the order they were written |
| `type` | one of the types below |
| `paragraph` | the paragraph number (or PDF page) the item is in; a second paragraph goes in `also_in` |
| `text` | what the article says, in the reader's own words, one sentence |
| `quote` | the exact words of the article the item rests on, copied, not retyped from memory |
| `hedge` | the authors' own hedge, in their words (`may`, `in mice`, `when recombination stops`), or `null` |
| `also_in` | further paragraph numbers, when the article states it in more than one place |
| `note` | optional: anything the reader cannot fit in the fields |

The types, and what belongs under each:

- `claim` — a hypothesis or a claim the authors make, including the central one.
- `scope` — the population, system, taxon or setting a claim is limited to.
- `condition` — a condition a claim depends on ("provided recombination has stopped").
- `hedge` — a place where the authors mark their own uncertainty, where it is not a hedge on one
  claim already listed.
- `prediction` — something the authors say should be observed, whether or not they test it.
- `evidence_for` — a result or argument the authors offer for the claim.
- `evidence_against` — a result or argument against it, including one the authors themselves report.
- `alternative` — another explanation the authors name, their own or someone else's.
- `limitation` — a limit the authors state on their own work.
- `open_question` — something the authors say is not settled.

## Rules for the reader

1. Only what the article says. Not what is true, not what the literature says, not what the reader
   believes. A claim the reader thinks is wrong is still an item.
2. Keep the authors' hedge in the item's own words. "X causes Y" and "X may cause Y in mice" are
   different items, and the second one is what the article says.
3. Copy the `quote`; never retype it from memory. If the words cannot be copied exactly, say so in
   `note` rather than paraphrase into `quote`.
4. One statement, one item. A paragraph with three claims gives three items.
5. Nothing is left out for being obvious, small, or already covered by another item.
6. Nothing is added to make the inventory look complete. An article with no `evidence_against` has
   none, and the inventory says nothing where the article says nothing.
7. The reader does not judge the card, because the reader has not seen it.

## What happens to the inventory

`coverage.py INVENTORY CARD` matches each item against the card by paragraph and by type
(`references/coverage` in the script's own documentation). Its output lies beside the card, with its
SHA-256 in the report, together with the inventory's. Each unmatched item is then one of three things,
and the report says which:

- it belongs in the card, and the card is corrected; or
- the card already holds it, sourced to another paragraph than the item's — an article states the
  same thing in its abstract and in the body paragraph that gives it in full, and the converter
  sources the value to the body. The answer is the pointer of that value (`--held`), which the
  script checks: it must be a sourced value of this card, in a place where an item of that type
  belongs, and in another paragraph. A pointer is a checked answer, so prefer it to a sentence; or
- it does not, and the report carries a one-line reason with the paragraph number.

"Out of scope" alone is not a reason. A reason names what the item is and why the card does not hold
it — a result about another species, a method detail with no bearing on the claim, a claim already
held by another value with a different wording. The reason is a sentence a reader can disagree with.
