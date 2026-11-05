# Waves of critics

A critic reads the finished card against the article and the literature and says what is wrong with
it. Several critics with the same instruction find the same things, so the waves differ by **lens**:
each wave looks for one kind of defect and is given only what that lens needs.

A critic never edits the card. The reviewer is not the author: a critic that could edit would be
correcting its own reading, and the card would lose the one property this step gives it — that
someone other than the writer looked. The **same** converter makes the corrections, resumed rather
than replaced, because a fresh converter would have to re-read everything and would quietly change
values no finding touched.

## The three lenses

**(a) What is missing.** Given: the article, the card, and the second reader's inventory with the
coverage output (step 5). Asks: what does the article say that the card does not hold? Which layer
is empty where the article has something for it? Which typed gap is a gap only because the converter
did not look? This lens repeats the second reader's question against the whole card rather than
item by item, and it is the only lens that may call for a new value.

**(b) What was lost or strengthened.** Given: the article and the card. Asks, for each value that
paraphrases: is the authors' condition still there? their hedge? the population? Did "may" become
"does", "in mice" become nothing, "when recombination stops" disappear? Did a judgement the article
offers as one possibility become the card's assertion? A value that asserts what its source supposes
is the defect this lens exists for, and it is not caught by the entailment pass whenever the passage
contains the words without their condition.

**(c) Who disputes it.** Given: the card and the search log (step 2), with
[search.md](search.md). Asks: who in the literature disagrees, and is that in the card? Every
finding of this lens carries a source and a locator — a DOI, a PMID, a page or paragraph — and
nothing else counts. A work this lens names is a lead until a kit script has fetched it and the
converter has read it: a critic may not put a citation in the card, and a finding that cannot be
fetched is reported as not fetched.

A lens is given what it needs and no more. (b) is not given the search log, because a value's
fidelity to the article is not improved by knowing who else disagrees; (c) is not given the article's
full text, because its question is about the literature. A lens given everything drifts into the
others and the waves stop being different.

## What a finding must carry

| field | what it holds |
| --- | --- |
| `lens` | a, b or c |
| `priority` | P1: the card says something the sources do not support, or omits something it should hold. P2: the card is right but incomplete, unclear, or weaker than it could be |
| `pointer` | the JSON pointer of the value, or the layer that is empty |
| `evidence` | a paragraph of the article, or a source with its locator. A finding with no evidence is not a finding |
| `what_to_do` | what would settle it: the value to narrow, the condition to restore, the work to read |

A critic reports "nothing" when it finds nothing, and says what it looked for. A wave that found
nothing is a result, and the report carries it with the number of values or sources the lens
examined. Nothing is invented to make a wave look productive; a critic that must report a finding
finds one that is not there, which costs the converter a correction round and the card its accuracy.

## What a wave is, and how many

**A wave is one full cycle of the three lenses**, not one lens. The stopping rule is a statement
about the card as it now stands — that every lens has read it and found nothing — and with a wave of
one lens it would not be: two empty lenses in a row, say (b) and (c), would stop the waves while the
findings of (a) had only just been corrected, so the corrected card would never have been read by
the lens that had objected to it. A cycle makes "nothing further was found" true of the card in front
of the reader. **Every lens therefore runs at least once before the stopping rule can apply**, and a
card none of whose lenses has run is not a card the waves have seen.

Waves run until **the first wave in which no lens finds a P1**, with a ceiling of **four**. Within a
wave the lenses run in the order (a), (b), (c); each finding goes back to the converter, steps 4 to 6
of [SKILL.md](../SKILL.md) run again on what changed, and the next wave reads the corrected card. So
the shortest run is one wave — three critics — and the ceiling is four, twelve.

**P2 findings do not hold the handover.** They are handed over as a list, each with its pointer and
its locator, in the report or in a file the report names, under the heading that says what they are:
known, and not corrected. A P2 the converter chooses to correct is corrected like any other finding;
a P2 it does not is not a reason to run another wave.

Why the rule is written on P1 and not on an empty wave: an empty wave is the stronger evidence, and
the first two conversions run this way showed what it costs. Four waves of three lenses on two cards
produced 24 critic calls and corrections to the last hour; the P2 findings of the last wave were
leads to works not yet read, which a reader can act on from a list as well as from a card. A card
whose every lens has read it and found no claim it cannot support is a card worth handing to an
acceptor; waiting for a lens to find nothing at all buys less than it costs. The rule is the owner's
decision of 2026-10-22, carried in the kit from 0.9.0.

The report states the number of waves, the findings per lens per wave, "nothing" included with what
that lens examined, and which of the three outcomes ended the run:

- **stopped on a clean wave**: a wave in which no lens found a P1, with the P2 list handed over;
- **converged**: two consecutive waves in which no lens found anything — stronger than the rule
  demands, and worth stating when it happens;
- **stopped by the ceiling**: four waves ran and P1 findings were still arriving.

A card stopped by the ceiling **with substantive findings still open is handed over as "needs more
work", not as a finished card**, and the report names what the last wave found. The ceiling is a
limit on the work, never a verdict that the card is done; it is for the acceptor to decide what an
unconverged card is worth, and the converter does not describe such a card as complete.
