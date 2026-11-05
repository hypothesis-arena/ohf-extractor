# Question-conditioned context: isolated offline form

This development form builds a local packet for one of three verification tasks: `scope`,
`direction` or `indirectness`. These are assessment types, not grammatical question classes. The
strongest output is `grounded_input_contract_only`; `scientific_adequacy_verified` is always false
and `entailment_verdict` is null. Two paragraphs are a structural minimum, not a certificate that
context is scientifically adequate, complete or relevant.

The packet reader does not call a model, fetch a source, change a card or ledger, or run the native
CLI. Ownership, reading, source completeness and selection relevance remain supplied attestations.
Actual source access, passage-use rights, scientific execution, production integration and release
require separate decisions. This offline form grants none of them.

## Native meaning and compatibility

The parent is the accepted negative-grounds development form at
`d77096ed368043be923e07c2ac150600b98f7379`, with released ancestor v0.9.12 at
`bb74c3ee9762624f66182f0729b30640bd14e945`. Native source, converter and per-value checker code are
unchanged, as is `negative_grounds.py`. The existing native format does not accept this sidecar as
an entailment input or verdict file.

| Type | Checked native field | Conditioning retained in the new packet |
| --- | --- | --- |
| `scope` | Sourced `/added/layers/core/scope` | The exact added atom statement and proposed scope, main-source context and supplied restrictions |
| `direction` | Sourced `/added/layers/evidence/lines/N/direction` | The native target statement and line finding, proposed direction and explicit claim/property context roles |
| `indirectness` | Sourced `/added/layers/evidence/lines/N/indirectness` | The same target/finding correspondence with separate system, endpoint, intervention and comparison dimensions |

Native `checked_value` already conditions direction and indirectness on a target statement and the
line quote. This form preserves that exact rendering and adds a separately bound context packet.
It does not declare the parent's one-passage task scientifically invalid. Existing per-value
inputs, their prompts, batches and ledger records retain their original contracts and hashes;
this tool neither reads nor enriches them.

The first form supports added atom anchors only. Native prediction targets, author-zone fields,
PDF/HTML/API locators and arbitrary assessment fields are unsupported here. That limitation does
not invalidate their normal native checks. Lines using `quote_withheld` instead of an exact finding
quote are not packet-ready here; the reader does not fetch or manufacture a quotation. A later adapter needs its own review.

## Prepare the local bundle

1. Pin the exact card bytes. Supply its native ID/version and a main JATS source, with any evidence
   source needed for the selected field. Every source has an explicit typed PMCID or DOI, byte hash,
   retrieval stamp, completeness state, role and the same card-owner binding. The main source must
   match the card's main DOI/hash/retrieval stamp. Other sources must already be named by native
   source records in this card.
2. Describe questions using [question-context.schema.json](question-context.schema.json), root
   `ohf-question-context/1`. Each question names its type, state, exact `target_ref`, added atom
   `anchor_ref`, `context[]`, and `supplied` claims/entities/limits. Empty supplied lists remain
   empty: the reader does not invent missing restrictions from the passages.
3. For each ready question, provide at least two source-bound locators spanning more than one
   actual paragraph and more than one distinct normalized paragraph text. Include both `claim`
   and `property` context roles. The former must use the anchor's source, the latter the checked
   property's source. A third, unrelated work cannot rescue either role.
4. For an authorized invented development bundle, run the standalone reader:

   ```sh
   python scripts/question_context.py bundle/request.json > context-diagnostic.json
   ```

   Exit 0 means every packet has a grounded input contract. Exit 1 means at least one cannot be
   assessed; argument errors return exit 2 as a JSON diagnostic. None is a scientific verdict.
   The reader writes only stdout; the caller chooses whether to save it.

All input paths are explicit pinned relative files beneath a trusted local bundle root. There is
no fallback lookup or global file walk. Shared unchanged readers reject path traversal, symlinks,
hardlink aliases, invalid OS paths, duplicate JSON keys, nonfinite numbers and byte-hash drift.
The local read bounds are 8 MiB per file, 32 MiB total and 64 files. Requests have at most 32 sources,
128 questions and 128 locators per question. Strings in the sidecar and native checked values are
bounded by the supplied schema. These are input limits, not measured scientific performance.

## Exact targets and source ownership

A `target_ref` is typed as `scope_field`, `direction_field` or `indirectness_field`. It binds the
exact card owner, canonical field pointer, hash of the full sourced wrapper, hash of the native
checked-value rendering, and the exact source work/hash/retrieval stamp. Line fields additionally
name the unique native line ID. The `anchor_ref` names one unique added atom by ID, pointer, full
value hash and exact main-source binding. Duplicate IDs across atoms or predictions are ambiguous.

Value hashes use the existing native canonical JSON rule: UTF-8 bytes of
`json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))`. Hashing the checked
rendering as well as the wrapper prevents an isolated value from replacing its target/finding
correspondence. A line's native `target_ref`, whether a legacy string or a sourced wrapper, must
identify this exact atom. A sourced target choice must itself resolve to a native record of the
claim or property work.

The line's evidence items must bind the property's artifact, hash and paragraph locator. Its exact
finding quote must occur in a passage bound by one of those native items. This is a quotation
binding check; it never decides direction or indirectness from substring match or nonmatch.
Scope and added atom statements may be paraphrases; their meaning is not judged by this tool.

Only unnamespaced JATS sources with a main PMCID are supported. The selected typed PMCID/DOI must
occur in that article's front metadata. Source URLs, locators and source records use the exact
native `Document.src()` form, not guessed aliases. Main and evidence documents carry explicit
roles and current versions. An incomplete or unavailable needed source cannot produce a packet.
Multiple aliases, cloned files or competing versions of one work are refused, using both parsed
identifiers and the pinned raw digest; changing a filename does not create a new work.

## Context and native addresses

Each context entry carries `claim` or `property` role, an exact source binding, the native card
source-record key, a paragraph number, selected sentence numbers, paragraph/selection hashes,
state, reading time and a supplied selection reason. Integers are strict: booleans and floats do
not identify paragraphs, sentences or card versions.

Paragraphs follow native JATS document order and native whitespace normalization. An empty
`sentences` list selects the whole paragraph; otherwise the numbers are unique, sorted and within
the exact native sentence split. Nonconsecutive selected sentences are joined with one space and
remain explicitly numbered in the packet. Abbreviations and closing quotation marks use the
pinned native sentence helper, rather than a second regex rule.

Two sentence selections from the same paragraph do not count as two paragraphs. Nor do a full
paragraph plus a sentence of it, duplicate source-record aliases, cloned files or repeated
normalized paragraph text at different indices. This conservative minimum can reject repeated
boilerplate even when it occurs in two physical paragraphs; it does not claim to infer semantic
independence. Context roles and selection reasons are supplied, not authenticated reading events.

Reading times must follow the exact source retrieval time and precede the request time. Unknown,
partial, unavailable and not-supplied question/context states remain explicit `cannot_assess`
reasons. Missing target or second paragraph, stale value/source hashes, wrong owners, ambiguous
IDs and malformed addresses cannot receive a positive structural grade.

## Packet and failure output

`ohf-question-context-diagnostic/1` is closed by the same schema's `diagnostic` definition. It
contains per-question input pointers, status, basis state, issue codes and either a packet or null.
The packet uses a fixed instruction for the chosen assessment type, exact target/atom references,
the native checked value, target statement, supplied claims/entities/limits and selected source
text with its roles and locators. An arbitrary prompt, including an isolated quote-substring
question, is not an accepted replacement for this contract.

Both the input and output shapes reject unknown envelope members. The input pins identify the
bytes actually read; native paragraph/sentence and checked-value helpers are source-hash verified.
Native pure helper code is compiled directly from the pinned source; source fetch constructors,
native commands, inference and ledger mutation are not invoked.

This form establishes no query adequacy, actual reading, source or inventory completeness,
scientific context sufficiency, entails verdict, direction truth, indirectness validity or empirical
quality rate. It has no automatic integration path and is not a replacement for independent
scientific review. Existing frozen extraction inputs remain untouched.
