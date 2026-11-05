# Conversion rules

These rules hold for every card this skill produces. Each rule says why, so that an edge
case can be decided by the reason rather than by the letter.

## 1. Rights come from the full text, not from metadata

The author zone republishes the authors' words. The licence statement in the bytes you
hashed decides whether that is allowed:

- CC BY 4.0 or CC BY 3.0, or public domain: convert. `author.source.license` is
  `CC-BY-4.0`, `CC-BY-3.0`, `CC0-1.0` or `public-domain`, with `rights_basis: "license"`.
- NC, ND, SA, no licence, or full text not obtainable automatically: stop and report. Do not
  convert from the abstract or from search metadata, and do not obtain the text by
  getting around a download block. Why: an abstract-only card is shorter and thinner
  than the others, which biases any comparison of cards; and a blocked download is not
  a licence to fetch the file another way.

Search metadata (Crossref, Unpaywall) can say "cc-by" for a version that is not the one
you read. Only the block in the bytes you hashed counts.

The kit reads the licence; the builder does not type it. `ohfkit.skeleton()` derives it,
`check_card.py` derives it again from the downloaded bytes and fails if
`author.source.license` differs, and a `licence=` argument that disagrees is an error.

- **Europe PMC XML**: the `permissions` block of the main document — its text and the licence
  URLs in it. The version of a Creative Commons licence is often only in a link (Wiley writes
  "the terms of the <ext-link xlink:href=.../licenses/by/4.0/>Creative Commons Attribution</ext-link>
  License"), so a reading of the prose alone refuses a block that states the licence plainly. Every
  href inside the block is read with the prose; this cannot loosen the check, because a restriction
  marker is searched first and a link is where a by-nc, by-nd or by-sa URL would stand too.
- **PDF or HTML page**: there is no permissions block. Give `skeleton()`
  `licence_statement=(n, text)`: the exact licence statement and the page (PDF) or `<p>`
  number (HTML) it is on. The kit checks that the text is in that page or paragraph and
  records it as `added.sources["rights"]`, whose locator names the page or paragraph and
  quotes the statement; `check_card.py` reads it back from there.
- **A record of a structured API** (`RecordDocument`, kind `record` in `docs.json`): the
  record's own `license` member, which must name an allowed licence; a record without one
  stops the conversion. Each string field is cited by its JSON Pointer, and an author-zone
  value is the whole field, unchanged and untranslated. The members in
  `ohfkit.RECORD_EXCLUDED` (the publisher's own assessment, labels a model made without a
  recorded model and time, and the response time) are not fields and cannot be cited.
  The `license` member (`ohfkit.RECORD_METADATA`) can be cited as the source of the
  licence, never as an author value. The source is the record in RFC 8785 canonical form
  without the members that change on every request (`ohfkit.RECORD_VOLATILE`, the response
  time): the kit writes it as `<name>.canonical.json`, and `source_text_sha256`, the
  refetch hash and every artifact hash are of that form, so anyone can reproduce them from a
  new download. How a given API's fields map to card paths is a separate, versioned mapping
  that the card names.
- **An old work with no licence statement** (a scanned book or journal volume): give
  `skeleton()` `public_domain` instead: the publication year, the imprint (the page and
  the exact text that names that year, usually the title page), the year the author died
  and where that year is recorded. The kit refuses the work unless every copyright term in
  `ohfkit.COPYRIGHT_TERMS` has ended: in the United Kingdom 70 years from the end of the
  year the author died (Copyright, Designs and Patents Act 1988, s. 12(2)), in the United
  States at most 95 years from publication for a work published before 1978 (17 U.S.C.
  304(b)). With several authors, or for a translation, give `deaths` instead of `author_died`
  and `death_source`: one entry per person whose work is in the text read (`person`,
  `role` `author` or `translator`, `died`, `death_source`); the term runs from the latest
  death. The imprint may give the year in digits or in Roman numerals (MDCCCLXXI). The licence is then
  `public-domain`; `added.sources["rights"]` records the imprint, the years and the terms
  checked, and `check_card.py` checks them again. A scan's catalogue status ("out of
  copyright") is metadata and does not count. A work with no DOI gives `url`, the address
  of the copy read, and `kind` (`book` for a book).
- **A submitted text** (`SubmittedText`, kind `submitted` in `docs.json`): an answer of a model,
  a note or a text by a person, with no publication behind it. There is no licence in it to
  read. The rights are the submitter's statement in the submission manifest beside the text,
  `<file>.manifest.json`: who submits (`submitter`), on what basis (`basis`) and under which
  terms they give the card (`card_licence`, "unknown" if they did not say). The card records
  that as `rights_basis: "submitter_statement"` and `added.sources["rights"]`, never as a
  licence the kit read. Who generated the text (`author_kind`: human, ai_system, hybrid or
  unknown), the system, its version, the model and the prompt come only from the manifest;
  what it does not give is null. The model is named in `author.generator.model` and the
  interface it ran in (a CLI, a chat app) in `author.generator.system`, never one in place of
  the other. The manifest gives each model with `model_basis`, how the submitter knows it:
  `"observed_in_output"`, or for example "declared in the CLI configuration, not seen in the
  output"; the basis is kept in `added.sources["generation"]`, so a declared model is not read
  as one the output shows. A `reasoning_effort`, with its `reasoning_effort_basis`, is kept
  there too: the generator has no member for it. The language is the manifest's, or else
  read from the text's frequent words, or `und`.
  **Where the basis and the setting stand in the layers.** The schema fixes `author.generator` at
  `kind`, `system`, `system_version` and `model`, so neither the interface nor a setting gets a field
  of its own there: the interface is the `system`, and a setting such as `reasoning_effort` is a
  configuration reference, which belongs in `provenance.transformation` ("converter versions, prompt
  or configuration references") with the record in `added.sources["generation"]` behind it. A
  declared model may also be carried in `provenance.model`, whose vocabulary is "provider report or
  explicitly client-declared identity": there the model and its attestation basis stand together as
  one sourced value, which `author.generator` cannot do, because it has no `src`. So the card names
  the model where the owner's decision puts it, and a reader who reads only the layers still finds
  how it is known.
  **`provenance.author_type` and `author.generator.kind` are two vocabularies, not one.**
  `author_type` is a `Term` declared by the source, so it carries the word the source uses
  (`machine`); `generator.kind` is an enumeration the schema fixes at `human`, `ai_system`,
  `hybrid`, `unknown`, so a text a model wrote is `ai_system` there. The card may hold both without
  contradiction, and the report names each with its vocabulary rather than choosing one word and
  hiding the other.
  The submitter gives the card only **their own** text. A paragraph that carries a reference
  (a link, a DOI, a PMID or PMCID, an author-year citation) may quote or retell the cited work:
  it is marked `third_party_candidate`, a hint to judge it, not a verdict, because such a
  paragraph often holds the submitter's own claim beside the retelling. The converter judges
  it sentence by sentence, `doc.decide(n, sentence, "own" | "third_party", reason)`, and the
  decisions, each with its reason, model and time, go into the card as
  `added.sources["ownership"]` (`doc.ownership()`). A sentence that is only a list marker ("1.", "-") states
  nothing and needs no decision. `doc.author()` takes a sentence of a marked
  paragraph only when it is judged `own`, and never a sentence judged `third_party`, marked or
  not; `check_card.py` checks the same against the record in the card. Quote another work's
  words only as that work, under its own licence, or cite it by reference. The report lists
  every marked paragraph with its references and the decision on each sentence
  (`doc.third_party_candidates()`). Why: a model's answer that retells four papers is four
  papers' words in part, and the submitter cannot license them; nor should the submitter's own
  claim be lost because it stands next to a link.
  **The marking is a floor, not a guarantee.** It finds references, not borrowed wording: a
  paragraph that retells a work and names none is not marked, and its words may still be that
  work's. So the converter's own judgement stands above the check - nothing goes into the author
  zone that the converter believes to be another work's wording, marked or not. This is a judged
  condition, and the report says on what the judgement rested.
  **What `card_licence` decides.** It is the terms under which the submitter gives *the card*, and
  it governs publication, not conversion. The card is published only where those terms allow it;
  `"unknown"`, or terms that forbid redistribution (NC, ND, share-alike against the collection's
  own licence), mean the conversion may be made and kept but the card is not published.
  There is no middle course in which the text is merely not quoted. A work that may not be
  reproduced cannot be the `src` of any value at all: the entailment pass carries the paragraph of
  every sourced value into its input, so a restricted text would travel into the artefacts whatever
  the card itself shows. (The same rule as for a source cited by reference only - see
  `reference_only` and the acceptance of 2026-10-21.) So a submitted text whose `card_licence` does
  not permit publication yields a card for the submitter and for the record, and nothing for the
  public set, and the report says which of the two it is.

Both are parsed by `ohfkit.licence_of`. It accepts a statement that names CC BY 4.0 or
3.0 (the URL `creativecommons.org/licenses/by/4.0` or `/3.0`, "Creative Commons
Attribution 4.0" or "3.0", "CC BY 4.0"), or else CC0 or public domain. It refuses: any
NC, ND or SA marker (for PDF and HTML, anywhere in the page or paragraph that holds the
statement); "Creative Commons Attribution" with no version; another CC BY version; two
different CC BY versions; an empty or missing statement. A CC0 waiver for the data next
to a CC BY licence for the article (BioMed Central) does not make the licence ambiguous:
the article's licence is the CC BY one.

## 2. Author zone: exact text

Every value in `author.layers` is an exact passage of one paragraph, after tags are
removed and whitespace collapsed (`ohfkit.norm`), and it is made of whole sentences of
that paragraph (fields.md, Author zone, says where a sentence starts and ends). Its locator names that paragraph:
`XML .//p[N] (1-based document order)`. The SHA-256 of the XML is in
`author.source.source_text_sha256`. Fill only what the authors state: usually
`core.statement`, `core.explanandum`, and `mechanism.summary` when the article has one.
Why: the author zone is evidence of what the authors said; a trimmed or merged passage
is no longer that. A cut that is needed (a clause that is not the claim) goes through
`doc.author_part(n, text, reason)`, which writes the cut and its reason into the locator.

The locator of a PDF page is `PDF page N (...)`; of an HTML page read by `<p>` element
(`HtmlDocument`), `HTML <p> N (...)`; of an HTML page read by block (`HtmlBlocksDocument`),
`HTML block N (...)`. The last two are different numberings of the same page and are never mixed:
a source is read by one of them, named in `WORKDIR/docs.json` (kind `html` or `html-blocks`).

### HTML blocks

Use the block reading for a page whose text is not all in `<p>` elements: a blog post written in
`<div>`s, a box in a table cell, a reference list split by `<br>`. Read by `<p>`, such a page loses
the text outside `<p>` without an error. A reader reproduces the block numbers from the bytes as
follows:

1. Decode the page as UTF-8. Drop comments, and the text inside `script`, `style`, `template` and
   `noscript` (their tags included).
2. A **block boundary** is a start tag, end tag or self-closing tag of one of these elements, and
   only these (a closed list; the tag name is matched in lower case): `address article aside
   blockquote body br caption dd details dialog div dl dt fieldset figcaption figure footer form
   h1 h2 h3 h4 h5 h6 head header hgroup hr html legend li main menu nav ol p pre search section
   summary table tbody td tfoot th thead title tr ul`. The tags of any other element (`a`, `em`,
   `span`, `img`, ...) are inline and split nothing.
3. Cut the page at every block boundary. Each piece's text, with character references decoded
   and whitespace runs collapsed to one space and trimmed, is a **block** if it is not empty.
4. A piece whose boundary before it is the start tag of `h1`-`h4` is not numbered: it is the
   section title of the blocks after it (the first page block before any heading has the section
   `(none)`).
5. The other blocks are numbered 1, 2, ... in document order. That is N in `HTML block N`.

This is the rule "a block element with its own text outside the blocks nested in it is a
paragraph", made exact: `<div>A<p>B</p>C</div>` gives three blocks, A, B and C, because B cuts the
`<div>`'s own text in two. No nesting is needed to count, so a misnested or unclosed tag cannot move
a number.

The price, stated so that it is paid knowingly:
- **Every** block of the page is numbered: the page title (`title`), menus and navigation (`nav`,
  `li`), sidebars, related posts, share buttons, comments and the footer become blocks too.
  `HtmlBlocksDocument` therefore needs `work`, the one element that holds the work (`div.entry`,
  `article#post-1`; `docs.json` key `work`), and each locator says `work: inside <work>` or
  `framing: outside <work>`; `report()` lists the numbers as runs of work and framing. The
  licence statement of a page is often framing (the footer); it is still quoted by its block.
- `<br>` is a boundary, so a reference list split by `<br>` gives one block per line, and an entry
  that runs over two lines is two blocks; a sentence broken by `<br>` cannot be quoted whole.
- Each `<li>` is its own block, in the work and in the menus alike.

## 3. Added zone: the converter's reading, each value with its passage

Atoms, mechanism, predictions, evidence, and what the hypothesis explains, reinterprets
and opens are the converter's reading. Each value names its passage through `src`, a key
of `added.sources`. Choose the paragraph that holds the content of the value, not the
one that first mentions the topic: the entailment pass sees only that paragraph. A value
that restates the authors in other words also carries `paraphrase: true` and the short
quotation it rests on in `basis_quote`.

## 4. Other works: quote only what their licence allows

The example set lifts the old rule "evidence only from the article". An evidence line
may come from a cited work or from a work that answers the article:

- CC BY full text in Europe PMC: open it as its own `Document`, quote it exactly, and
  give the line its own `added.sources` record. The quotation is checked against that
  work, not the article.
- NC, ND or closed work, or a work whose public-domain status could not be checked: record
  it by reference only, with no quotation. If the article reports the result, `src` is the
  article paragraph that reports it; otherwise the line carries the reference and no
  `src`-checked text. When the work has its own `added.sources` record, write it with
  `ohfkit.reference_only(record, reason)`: the reason it is not quoted is then in the card,
  and `check_card.py` fails on any quotation whose `src` names that record.

Why: the article's licence does not cover the works it cites.

## 5. Assessments are attributed, grounded and timed

`core.testability`, `predictions[].discrimination`, `evidence.lines[].indirectness` and
`evidence.lines[].risk_of_bias` are the converter's judgements. Each carries
`assessment` with the assessor, the clock time when the judgement was made and the hash
of the text it was made from (`ohfkit.assessment(doc, ohfkit.now())`). Keep an
assessment only where the cited passage gives grounds for it; otherwise the field is a
`not_supplied` gap. Why: an unattributed judgement reads as a fact about the study.

## 6. Nothing is invented

A field the sources do not support stays empty or becomes a typed gap in `added.gaps`
(see `spec/README.md#gaps` for the dispositions). Do not add a line against, an
alternative, a prediction or an opened question to meet a criterion of the example
plan. If a criterion cannot be met honestly, the report says so.

## 7. Times are real

Every timestamp is the clock time of the step it records: `retrieved_at` when the file
was downloaded, `assessed_at` when the judgement was made, `checked_at` when the
entailment pass ran, `added.at` no earlier than the last value written in the added zone.
An assessment made before its check is checked after it; an assessment changed after its
check is checked again. Why: a placeholder time is an invented fact, and a reviewer uses
these times to see which value was checked in which state.

## 8. Cut-off date and profile

Set `added.cutoff_date` to the date up to which the converter considered evidence
(the latest publication date among the works it read). Select `profile.domain`:
`ohf:intervention-pharmacology@1` only for a claim about a drug or other intervention
given to an organism; otherwise `none`.

## 9. Source check

Give `skeleton(citation_title=...)` the work's title separately from its citation, as one nonempty
explicit argument read from the article itself (for JATS, its own `article-title`), never from
Crossref or Europe PMC metadata. Do not join title and journal fields.
`verify_source` compares only this title with the registry's title; it never parses the
citation. A missing title is a mismatch. Run verification before `finish`, which removes the
build-only `citation_title` field before hashing and writing the OHF card. Do not fill it from the
registry response being checked: that would compare the response with itself.
Save the returned run record separately from the card. It keeps the raw `citation_title` and
`registry_title`, `metadata_check`, `title_difference`, the source text hash and the converter rules
hash. After export, repeat `title_match(record['registry_title'], record['citation_title'])` and
compare its result with `metadata_check.title_match` and `title_difference` in that record. No new
registry call or reconstruction from citation text is needed.

Before handing over, `ohfkit.verify_source` downloads the source again, compares its hash,
and looks the DOI up in Crossref. `retracted: false` means only that the Crossref record
listed no retraction or withdrawal notice at that time. A work with no DOI is looked up in
the catalogue that holds the copy read, `verify_source(card, doc, catalogue=(name, item id))`
with a name from `ohfkit.CATALOGUES`; a catalogue records no retractions, so `retracted`
is `"unknown"`.
