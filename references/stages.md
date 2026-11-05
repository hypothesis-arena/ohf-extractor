# Fixed search step and first draft

Use this workflow when the conversion must stop after search for independent labelling. It records
the current extraction procedure. It does not add a closeout gate, decide which works matter, or
change a card to satisfy an acceptance criterion.

Run the searches and fetch the source documents before closing the step. Then run:

```sh
python scripts/search.py close-step --workdir DIR
```

`step-1.json` records the exact byte hash of `search-log.jsonl`, the number of calls, and the works
with identifiers, titles and publication types. It contains no line-building verdict. A log already
containing such decisions is refused: the stop must precede them. Closing again is refused. Kit
search calls and log writes in that directory stop after closure; a new search needs a new directory.

Hand the fixed log and stop record to the independent labelling process. The extractor does not read
the labelling. Wait for that process's named completion before building lines. The stage files do not
claim that an independent process has completed; the run's coordinator supplies that dependency.

The builder exposes `build(calls, workdir)` and returns its card. Keep its extraction logic as it is;
move it into that function and return the card instead of writing the final file. `calls` is a copy
of the written log, and source documents are read from the work directory. It is not a search client.
Run it with the released kit checkout used to close the step:

```sh
python scripts/stages.py build BUILDER.py --from-log --workdir DIR
python scripts/stages.py check --workdir DIR
```

The build refuses a missing or changed stop record or log, and a different kit version or rules hash.
Its in-process search, urllib opener, HTTP connection and socket transports are replaced with
a stub that raises on a request, including `build_opener().open()`, `http.client` requests and
`socket.create_connection()`. Closure waits for an active kit call in another thread to finish
and write its record; reentrancy belongs to one thread and work directory.
Socket construction and socket factories are blocked as well. Existing sockets have their send
methods blocked, including datagram `sendmsg`, which does not need a preceding connection.
Catching the refusal does not permit saving a draft. This is a workflow guard for cooperating kit
builders, not a Python sandbox or a restriction on hostile child processes.

The first draft obeys the card's licence rules. The main source's licence is derived again from its
own bytes. Documents supplying text must grant a licence the kit accepts. Reference-only works may
be named, but not quoted. Rights must be established before any draft file is saved; an unestablished
licence stops the build rather than producing a draft containing the body or its quotations. This
check establishes neither scientific support nor acceptance, and no entailment pass is required to
record the draft.

The builder's card is copied before `finish` stamps and hashes it. A successful build fixes these
files together under `DIR/first-draft/`:

- `card.json`: the first card, with its `content_hash`.
- `record.json`: the card file's byte hash, `content_hash`, timestamp, kit version and rules hash,
  the builder's byte hash, and the hashes of the stop record and search log.

The command refuses to replace an existing bundle, and its files are marked read-only. `check`
detects altered card, log or stop bytes against that record, including when a later kit inspects the
old draft. These hashes bind recorded bytes; they do not authenticate a malicious writer able to
replace all records. Failed temporary bundles are left under `.first-draft-*` for diagnosis.

Copy `first-draft/card.json` to a separate working card before checks and critics. Keep the original
bundle for the comparison between first extraction and final card. A draft is not an accepted card.
