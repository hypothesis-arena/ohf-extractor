# Native relational profile for OHF 1.4

`ohf-native-relational@1`, epoch 2, is an explicitly selected structural and IO
binding profile. This development candidate implements the definition in
`references/native-renderer-profile-4.json`. Conformance of a released extractor
and standard pair requires independent review and CI on that exact pair.

The profile supports one local JATS document and the shapes listed in the
normative definition. It has no source-fetch, provider or process implementation.
The conformance scenario uses an invented document and an injected fake checker;
its result does not establish source faithfulness, completeness or scientific truth.

## Selection and source identity

Selection is external metadata, with exactly these members:

```json
{"id":"ohf-native-relational@1","epoch":2,"definition_sha256":"sha256:c964ce88b31374062cbebf6e801259f3f85533244633d3d5642cc7bab9124db7"}
```

The digest covers the definition's canonical JSON. The file's raw SHA-256 is
`80b8c026c959b415758c1b0d3ccb2d26a62ba78a50888cd8fb25b90e0202cd46`;
it is checked separately. The epoch is an integer, with booleans and floats refused.
Missing, different or additional selector members refuse selection.

The normative source is standard commit
`bf1f582f977c2ac65e5537ebd9f1b1b19ae328d3`, with schema version 1.4,
release metadata 1.4.2 and `ohf-target-projection/1`. The API's version dispatch
requires a 1.4 card. Header relabelling cannot create a full-context proof.
`native-profile-dependencies-4.json` pins the schema, target API, validation helpers,
catalogue, gap policy, mapping, vocabularies and release metadata. Private source
loading verifies all captured bytes before executing helpers. Helper data reads
use those snapshots; ambient helper modules, package initializers and bytecode
are not validator inputs. Python and dependency versions are checked explicitly.

`SKILL.md` defines the converter version; `search.VERSION`, `ohfkit.CONVERTER` and
`added.by.converter_version` agree. The card and original frozen proof name the
current rules hash. The profile contract additionally binds schema/API/definition,
dependency manifest and validation runtime identity. External commit association
is separate from the stable scientific projection digest; it does not introduce
a self-referential rules hash.

## Supported fields and conditioning

The added zone supports core statement, scope, kind and plain-ID atoms with
statement, claim_type, modality and role. Predictions support id, population,
endpoint, direction, horizon and derives_from_atom_refs. Evidence supports id,
target_ref, quote, src, direction, indirectness, sample_size and endpoint_kind.
Mechanism, provenance and appendix are empty; profile.domain is `["none"]`.
The complete author zone must pass the normative scientific-card schema.
The ordinary 1.4.2 producer also admits value-only, child-sourced wrappers for
added uncertainties, alternative_explanations, opens and explains. Those four
shapes remain unsupported by this native profile; selecting definition 4 does
not activate them here. Definitions and dependency records 1–3 remain historical
bytes and are not interchangeable with the selected definition.

Derivation and evidence target references are exact typed card conditions.
Derivation names existing added-zone atoms and contributes no passage item.
Unresolved, ambiguous, author-zone or external targets are refused by this subset;
no counterpart is guessed. `document_from_bytes` constructs the native reader from supplied local XML bytes
and a retrieval stamp, without calling fetch. Build verifies those original bytes
against the document hash, parsed paragraphs and source access stamp.
Every passage has an exact native `.//p[N]` locator,
card-owned source record, local document hash and source text. Multiple documents
or unsupported shapes refuse selection.

Direction retains the complete target projection and evidence conditions plus
`line_quote`. Indirectness retains its own value, the same target and quotation,
and the other evidence conditions, including direction. The assessed value
appears once, outside those other conditions. Sample size retains its native
WITH_QUOTE object; endpoint kind retains WITH_TERM, including term, quotation and
note when supplied. Target digest equality does not imply complete-value equality.

## Complete entrypoint

`native_profile.validate_files(card_path, ledger_path, selector_path, docs)` calls
`validate_bundle`, the complete selected entrypoint. It requires all of:

- full normative schema validation with strict formats;
- content hash, reference consistency and structural gap checks;
- exact supported shape, source bindings, card conditions and complete item roster;
- original selected-profile frozen input/configuration and returned-result proofs;
- current profile/rules/runtime identity, exact frozen source-version/locator/stamp
  bindings and worst eligible history for each item.

The result reports schema and native-binding validity separately. Warnings,
manual gap review and computed completeness are retained. Structural gap checking
does not establish that every applicable omission has been recorded. A schema-only
or ledger-only check cannot produce the complete selected PASS.

Use `freeze`, the injected `native_entailment.run_frozen_checker`, and `merge` for
the selected IO path. `stale_items` verifies the original pair and current items;
it allows the content-hash change caused by merged integrity records, while merge
itself requires the frozen pre-merge envelope. `carry` keeps exact eligible proofs
or returns NEEDS_CHECK. `restore` requires explicit fully validated card/ledger
pairs. `export` uses the complete entrypoint before an exclusive write.

The selected modules are `native_profile`, `native_entailment`, `native_ledger`,
`projection_binding` and `checker_io`. General conversion helpers remain separate;
their low-level results are not selected-profile acceptance. Missing-context,
unbound or different-epoch history cannot become current support through root
rehashing, carry or an archived card alone. The supported source version is fixed. A changed source hash, locator or retrieval
stamp cannot relabel a matching historical verdict, even when the delivered passage
bytes are unchanged. Automatic source-version migration is unsupported; its history
and eligibility policy requires a separate contract. No history reset is provided.
History stays append-only; a later
`entails` cannot hide a `no` for the same complete value and passage.

Writes use exclusive creation and checked file/directory fsync barriers before
a dependent phase. An interrupted or ambiguous dispatch is consumed, with no
automatic replay or cleanup. Durability assumes successful syncs are honoured by
the filesystem/device. IO receipts bind saved bytes; they do not authenticate a
remote checker or protect against coordinated forgery by a trusted operator.

## Deterministic conformance recipe

The extractor CI retains its serial general regression matrix and then runs a
separate `native-profile-1-4` job. It checks out the exact extractor event head
and normative standard commit, verifies both Git identities before importing
producer code, and supplies those commit/tree assertions to the recipe.
The CI driver verifies the normative dependency closure, empty tools package
initializer and prompt before product imports. Its private bytecode namespace
avoids ambient caches. Each serial leaf has one CPU, a 1 GiB address-space
limit, 180 CPU seconds and a 240-second wall timeout, with measured headroom gates
of 90 CPU and 120 wall seconds. Serial aggregate budgets are 480 seconds for the
three four-shard groups and 960 for the sixteen-shard epoch2 group; their half
budget gates are 240 and 480 seconds. Admission requires load per available CPU
below 0.9 (or load below 10 when the CPU count is unavailable), at least 3 GiB available memory and disk; a disk monitor preserves
evidence and stops below that threshold. Network, process, authentication and
unlisted file reads are denied during the invented checks.

The driver accepts only the documented batch names and four full lowercase Git
object identities. Existing output directories refuse reuse. The surrounding
trusted CI remains responsible for verifying the checkout assertions; the driver
does not authenticate an arbitrary caller. A later standard paired job supplies
its actual current checkout and the reviewed extractor/rules pins, including
`--expected-rules`. Its association requires a separate accepted pair.

With a verified checkout of the pinned standard as `OHF_REPO`, run the explicit
synthetic tests in `scripts/tests/test_native_profile14.py`,
`test_native_profile.py`, `test_projection_adapter.py` and
`test_checker_durability.py`, the ordinary source-mode controls in
`test_child_sourced_lists142.py`, plus the closed CI identity/source controls in
`test_native_profile_ci_driver.py`. The two general regression CI lanes do not substitute
for the profile's separate 1.4 lane.

The in-process `scripts/tests/native_profile_ci.run(output_directory, pair)` uses
one normative-schema-valid invented fixture, frozen fake IO, merge, the complete
entrypoint and export. Trusted CI verifies both Git commits/trees before import
and supplies extractor_commit/tree, standard_commit/tree and rules_sha256.
The receipt binds that assertion into the frozen configuration, reports the
actual rules and normative pins and labels the result synthetic. Checkout
verification belongs to the surrounding CI, not to this pure helper.

On that same schema-valid fixture, the unchanged bare standard reader must report
exactly four labelled complete-value mismatches: direction, indirectness,
sample_size and endpoint_kind. Its item roster must match the selected roster.
An exception, extra error, schema failure or unexpected bare PASS fails this
negative control. The bare reader remains unsupported for those native encodings;
no quotation stripping or hash conversion makes it equivalent.

Known zero model/HTTP operations describe only this invented, offline scenario.
Unknown accounting remains unknown; it receives no schema waiver or backfill.
Scientific adequacy, source truth, completeness, real checker execution and
release acceptance require their own evidence and decisions.
