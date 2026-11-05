# Negative-claim grounds: isolated offline form

This development form checks the evidence contract behind a negative claim. Its strongest result is
`grounded_contract_only`. Every diagnostic sets `scientific_absence_verified: false`, including a
successful contract check. Neither exit 0 nor complete paragraph coverage establishes scientific
absence, entailment, exhaustive search, inventory completeness or whole-card consistency.

This form is separate from the conversion workflow. It reads explicit local inputs and emits a
sidecar diagnostic; it never changes a card, budget, search log or stop record. Production use,
integration and empirical qualification need separate decisions. It invokes no network or model client; its reused native query-rendering helpers are pure.

## Existing terminology and compatibility

The inspected native inputs are the released kit v0.9.12 at
`bb74c3ee9762624f66182f0729b30640bd14e945`, its inventory and fixed-search-step formats, and the
OHF 1.1.4 `Gap` definition.
The native search, converter, coverage and stage implementations remain unchanged.

| Existing form | Meaning retained | Sidecar relationship |
| --- | --- | --- |
| Gap `searched_not_found` | Search did not find the answer within stated bounds | A `not_found_by_agent` claim may point here. Query ID strings alone do not validate its grounds. |
| Gap `not_supplied`; map `not_in_source` | The source does not supply an answer | An `absent_from_the_article` claim may point here. These terms alone do not establish semantic absence. |
| Gap `blocked` / `budget_exhausted`; map `not_yet_checked` | Work remains undone | No automatic conversion into not-found or absence. |
| `search-log.jsonl` | Native calls, outcomes, requests and returned identifiers | Each call needs an explicit owner and run binding in the new sidecar. |
| `ohf-search-step/1` | Exact log hash, call count and work metadata | Does not certify per-run completion or supply negative judgements. |
| Native `inventory.json` | Article ID/hash, reading time and items with paragraph addresses and quotes | Used without changing its fields; paragraph coverage is a separate attestation. |
| Universal literature absence | No native gap disposition with this meaning | Retained as `absent_from_the_literature`, always unsupported as a universal conclusion. |

There is no schema migration, inferred alias mapping or automatic conversion of existing gap prose.
The three claim kinds live in `ohf-negative-grounds/1`, not in the OHF card schema. Unknown members
or aliases fail the sidecar contract. A native gap target whose disposition contradicts the chosen
bounded claim kind is rejected. A pointer to another existing card value is an explicit sidecar
association; this tool does not judge whether that value expresses the proposition.

## Prepare inputs before checking

1. Pin the exact card bytes and main source bytes. Supply a nonempty proposition, a stated scope,
   a claim ID and an existing JSON Pointer into that card. All paths are explicit relative paths
   beneath one trusted local bundle directory. Symlinks, hardlink aliases and path traversal are
   refused. The directory and supplied attestations must come from the coordinator; this is not a
   sandbox against an operator replacing its ancestors or fabricating all input evidence.
2. Use the JSON contract in [negative-grounds.schema.json](negative-grounds.schema.json). The root
   holds `schema`, timezone-qualified `made_at`, `card`, `source` and nonempty `claims`. Each artifact
   reference contains `file` and a SHA-256 of its exact bytes. `source` additionally names a typed ID
   and the exact `retrieved_at` string from the card's main source. An explicit source `state`
   keeps `complete`, `partial`, `unavailable` and `unknown` apart; only a declared complete source
   can receive a positive grounds grade. This declaration is an attestation, not proof of full acquisition.
3. Prepare the grounds below. No state is upgraded merely because a top-level object says
   `completed`. Required run IDs must be supplied explicitly; every required run is checked.
4. For an authorized synthetic development bundle, call the standalone reader:

   ```sh
   python scripts/negative_grounds.py bundle/request.json > diagnostic.json
   ```

   The only write in this command is the caller's output redirection. The reader does not fetch a
   missing input or discover an alternative copy. Exit 0 means all claims have grounded evidence
   contracts. It is not a scientific or OHF-schema acceptance flag. Other outcomes return exit 1.

The sidecar schema documents object shapes. The Python checker additionally verifies hashes,
identity, time order, referenced IDs, source paragraphs and call outcomes. JSON syntax validation
alone does not perform those checks. Duplicate JSON keys and nonfinite numbers are rejected,
including exponent overflow such as `1e9999`; ordinary finite floats remain supported. Invalid OS
paths, including NUL or unencodable surrogate characters, return structured issues. CLI JSON uses
ASCII escapes so even an echoed invalid path remains printable without changing its value.

## Accepted source and identifier forms

This first form supports an unnamespaced JATS XML main article with an exact DOI binding to
`author.source.doi`, `source_text_sha256` and `retrieved_at`. Other source formats are unavailable
for this contract. DTDs and entities are unsupported: the XML parser rejects a doctype before
entity expansion, independent of the source byte encoding. Ordinary UTF-8 and UTF-16 inputs use
the same check; declaration text inside a comment is not a doctype. Paragraphs are all `p` elements in document
order, with whitespace collapsed, matching the native XML reader's address convention.

Source IDs are explicit `{namespace, value}` objects: `pmcid` with `PMC` plus a positive number, or
`doi` with a literal DOI. The selected ID must occur in the main article's front metadata. For the
JATS `pmc` field only, a numeric ID gains the `PMC` prefix. DOI URLs, `PMID:` strings in a numeric
field and inferred cross-namespace equivalences are not aliases accepted by this form. A DOI must
match literally; no case or version substitution is guessed. Native returned works support only
`MED:<number>`, `PMC:PMC<number>` and `DOI:<literal DOI>`, mapped explicitly to `pmid`, `pmcid`, `doi`.
Other namespaces need a later reviewed adapter.

Inventory `article.id` must equal the selected source ID's value, with the exact source hash. If an
inventory uses a different identifier, this tool refuses it rather than silently mapping identifiers.
Source hashes and exact retrieval stamps identify a version; a timestamp alone is not a version pin.

## Search grounds

`search` contains references to the native log, its native stop record, `ohf-negative-runs/1`, and
`required_run_ids`. Only native v0.9.12 `literature` calls from Europe PMC or PubMed are supported.
The native stop's kit/rules identity, log hash/count and work projection must match these calls.
No unrelated log rows or unbound global pool is accepted. This restrictive initial contract may
refuse a historical log containing other native tools; it does not rewrite that log into compliance.

The new run sidecar has an exact owner binding: card ID/version/byte hash, typed source ID, source
hash, retrieval stamp and declared complete state. The envelope, each run and each call binding must agree. Explicit native
call owners, if present, must also agree. Ownership is a supplied attestation, not an authenticated
observation of who made a native call that has no owner field.

Each run names its scope (`query`, `service`, `as_of`), native call references `call:<id>`, start,
finish, stop reason/time, conclusion and assessment time. Each local call belongs to exactly one
required run. A positive contract needs `completed`, an `exhausted` stop, a declared `not_found`
conclusion and all successful named calls. Native query/service/cutoff, actual response URL/query,
counts, response statuses/hashes and time order must agree. The native `ask.query` is the original
query; `ask.variant` selects `as_given` or `no_reviews`. Native `ask.sent` is present only when that
variant or `as_of` cutoff changes the sent query. The checker renders the exact native variant and
cutoff, checks optional `sent`, and binds the response URL to those sent words. A fabricated
`sent_query` field, missing transformation or changed cutoff is rejected; no log is rewritten.
Truncation, a cap, failed or missing
responses, contradictory counts, or a non-OK call cannot support not-found.

Every returned work occurrence needs an explicit `not_matching` judgement with its own typed work
ID, call reference, nonblank reason and assessment time. Zero native hits need no work judgement,
but still require all run/call/stop evidence. The machine checks these bindings, not whether the
judgement or query strategy is scientifically correct. It checks all declared required runs; it
cannot infer an omitted search family from natural-language scope.

Events use timezone-qualified RFC 3339 timestamps with at most six fractional digits. Unknown
`-00:00` offsets and out-of-range offsets are refused. Events must be ordered: source retrieval precedes the run; calls and their
responses lie within it; the run ends before its stop and native log closure; run assessments are
after closure and no later than sidecar recording; the request comes last. A completed envelope
cannot rescue a missing or failed individual run.

For example, an empty log is insufficient, a missing pinned log is unavailable, and a capped run is
partial. None is not-found. A missing search block is `not_searched`. Declared `unknown`,
`unavailable`, `not_searched` and `partial` are retained without upgrading or inspecting a claimed
positive basis. They still require the shared card/source envelope to bind correctly.

## Article grounds

`article` references the native inventory and `ohf-negative-article-coverage/1`. The coverage sidecar
binds the same owner, source, inventory hash, proposition hash and scope. It names every existing
native paragraph exactly once, with its text hash, reading time, inventory item IDs, disposition and
reason. Each inventory item has an existing paragraph (and valid `also_in` addresses), a nonblank
text/quote and a quote present in one of its bound source paragraphs. No item IDs from another
inventory can fill a missing row.

A paragraph with items uses `items_recorded`. A paragraph without items uses
`inspected_no_inventory_item` with an explicit reason. Empty inventory, partial coverage, a missing
paragraph or a stale paragraph hash cannot receive a positive contract grade. Dates must follow
source retrieval, precede inventory completion and remain within the coverage/request sequence.

The reading times and dispositions are attestations. Matching quotes and paragraph hashes do not
prove an inventory exhaustive or a reader attentive. The contract covers native paragraphs, not
all scientific obligations in tables, figures or other non-paragraph content. A proposition may
even occur literally in the source and still have a grounded *coverage contract*: this checker
never uses substring match or nonmatch to decide semantic absence. Independent semantic review is
still required.

## Diagnostic and limits

`ohf-negative-grounds-diagnostic/1` records each original kind and state, card/input pointers,
evidence references, checked basis status and issue codes. Shared input failures invalidate every
claim and retain its input pointer. Input pins identify the bytes actually read. For universal
literature absence, `status` is `unsupported_universal`; `basis_status` separately describes any
bounded search grounds. The original claim is never silently renamed into a weaker one.

The reader snapshots at most 64 explicit files, 8 MiB per file and 32 MiB in total, with at most
128 claims and 2,048 native calls. Exceeding a cap is unavailable, not not-found. Inputs are read once
per path into the pinned snapshot; there is no global directory walk, fallback search or requery.
No historical model/HTTP budget is inferred or filled. Synthetic regression evidence is not an
estimate of empirical extraction quality, and this development form does not authorize a real run.
