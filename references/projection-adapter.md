# Native projection and checker IO

The explicitly selected OHF 1.4 native relational profile uses the pinned
`ohf-target-projection/1` API and retains native direction, indirectness,
line-quotation, quote-term and resolver conditioning. Its complete public
validation contract is [native-renderer-profile.md](native-renderer-profile.md).

`native_entailment` and `native_ledger` contain the selected producer's low-level
rendering and history operations. They are separate from general conversion
helpers. Copying a native reader into the standard's tools directory is unsupported:
the native complete values and proof requirements are declared by the profile,
and the standard's normative API remains unchanged.

Checker-visible bytes are the pinned prompt, two LF bytes and frozen item JSON.
Configuration is explicit. Exclusive read-only files retain the request, item
manifest, configuration and input binding. A durable consumed dispatch record is
committed before an injected callback. Returned bytes must match the original
request/configuration digests before output and receipt publication.

File and parent-directory fsync are checked barriers. Failures preserve evidence
and refuse dependent phases; partial or ambiguous dispatch is not replayed.
Caller-provisioned ancestors and an honest filesystem/device are required. The
injected seam has no default provider, model, source fetch or process execution.

Projected ledger entries retain target, complete-value and passage identities,
checker/configuration identity and hash-linked original input/result manifests.
Selected check, carry, restore and export require those proofs. Root metadata,
a reformatted value or an archived card alone cannot manufacture original context.
Worst eligible history remains visible for the same complete value and passage.

Budget-only metadata may preserve scientific target identity while changing the
whole-card envelope. It does not create unknown counters or repair missing proofs.
Receipts prove the saved IO binding, not that an authenticated remote service read
the bytes or that a scientific claim is true. The conformance fixture uses an
explicit fake checker and never constitutes scientific acceptance.

For ordinary 1.4.2 child-sourced lists, the adapter reuses the exact pinned
Standard reader's admission rule. Both reader code and source-mode schema are
verified before a cold or cached use. The rule reads the captured schema bytes;
other existing data reads retain their repository-root semantics. A value-only
wrapper contributes its independently sourced children and no parent item.
A wrapper with a parent source still contributes the complete stored list plus
its independently sourced children. Old or unknown release labels cannot select
the new form. This ordinary rule does not enlarge the native profile's subset.
