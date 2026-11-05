# Resolution of card references

A value that is a reference to another value in the same card, `{"kind": "card", "pointer": "<JSON pointer>"}`
(for example a prediction's `test_plan_ref`), claims that the cited source states the text the pointer leads to.
That claim is decided by resolution, not by the entailment checker, because the pointer alone says nothing a
passage could support.

1. The pointer is resolved in the card. It leads to one of two things, and a reference to each is decided
   differently:
   - **text**: a string, a wrapper whose `value` is a string, or an item whose own `claim_or_ref` states it
     in words. The reference claims that the cited source states that text.
   - **a part of the card**: an evidence line, a prediction, an atom — anything that carries an `id`. The
     reference claims only that this card's value concerns that part.

   A pointer that leads to neither is not a reference the card can carry, and the card is not built:
   `entailment.py` stops with the pointer.
2. For a reference to **text**, the verdict is `entails` when that text, with whitespace normalised, occurs
   in the passage of the source the value's `src` names (or in its `basis_quote`, for that basis). Otherwise
   it is `no`, with a note naming the pointer.
3. For a reference to **a part of the card**, the verdict is `entails`, and the note says what it names and
   what it does not claim. There is no text for a passage to carry, and the check says **nothing about the
   source**: what the source states about that part is decided by that part's own records, one value at a
   time, and is not decided a second time here. A reference whose target does not exist never reaches this
   point, because step 1 stops the build.

   The check is not idle. What is hashed is the `id`, so pointing the reference at another part of the card
   is a changed value: the earlier check stops binding it, the reference is resolved again, and the earlier
   check stays in the history. That is the whole of what this check can know, and it is written so that it
   cannot be read as more.
4. The check is written to the ledger like any other check. The value hashed is
   `{"reference": <the reference>, "target": <the resolved text>}` for text, and
   `{"reference": <the reference>, "names": <the id>}` for a part of the card; the passage is the passage of
   the `src`. Its checker is `ohf-reference-resolution` 1.0.0, with this file's SHA-256 as `prompt_sha256`.
   A changed target or passage is a new text, and it is resolved again; earlier checks stay in the history.

## A record made before this rule

The kit shows a value to the checker in a *rendering*: the bare value, a direction together with what its
target states, a reference together with the text or the part of the card it names. A rendering is the kit's
work, not the card's text. When the kit changes a rendering, the converter has changed nothing, so a record
made under the earlier rendering is **read**, not failed (`check_ledger.rendered_before`). This is the same
rule as for an assessment: a new kit version alone is not a re-assessment.

It is allowed only where the card cannot have changed under it:

- the record's checker is not `ohf-reference-resolution`, so the record predates resolution, and
- what was hashed is the card's own bare value at that pointer, and
- the card's `content_hash` still matches the card and the ledger — which is what catches an edit, and the
  reason this allowance can hide none.

Such a record is **named** every time the card is read (`check_card.py` prints it as a `NOTE`), and it is
resolved again at the card's next rebuild, after which it is no longer read this way. A record read like this
is not a record made under the rule now in force, and the kit never says otherwise.

Other reference kinds (`artifact`, `external`, `unavailable`) are not resolved here; they go to the checker as
before.
