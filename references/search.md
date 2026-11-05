# Searching the literature

The card's evidence against, the works that answer the article, and the article's own status are
found by search, not by memory. [scripts/search.py](../scripts/search.py) does the searching and keeps
the record; the converter still reads every work it cites.

## The rule

The conversion report says what was searched and what was found: each search, the service, the
date, and the count. "No evidence against", "no responses" and "not retracted" are claims about a
search, and are accepted only with the search behind them. A search that failed is reported as failed;
it is never reported as one that found nothing.

## Other search tools find; the kit fetches

An agent may use any other search tool (an MCP server, a library such as BioMCP or PaperQA, a web
search) to find candidate works. What it found there is a lead, not a source. A work, an identifier,
a status or a passage enters the card only after it is fetched again through a kit script, with the
call recorded in the search log: `search.py` for a search or a status, `ohfkit` for the text. A
summary, quotation or citation produced by another tool is never copied into the card, and the
report does not count another tool's search as a search unless the kit repeated it.

## What to run

With `--workdir` the work directory of the conversion (the log and the raw responses go there):

1. `search.py status ID` — retracted, partially retracted, corrected, or under a concern. Reads Crossref
   `updated-by` (which includes the notices Crossref takes from Retraction Watch) and the Europe PMC
   links and publication types. `none_found` means these sources record no notice; a retracted
   article stops the conversion until the task says how to treat it.
2. `search.py responses ID` — works that answer the article: comments, replies, letters, errata and
   notices linked to it by Europe PMC, Crossref relations, and citing works whose type is a comment or
   reply. It runs `cited-by` first.
3. `search.py similar ID` — PubMed's related articles, in its order with its score: earlier and
   non-citing work on the same question. `search.py terms ID` — the MeSH headings and keywords of the
   article, to widen a query (see "Searching by meaning").
4. `search.py cited-by ID` — every work that cites the article, from Europe PMC citations, PubMed
   "cited in" and OpenAlex, merged by identifier. OpenAlex reads the reference lists publishers
   deposit and sees citing works the other two do not (on PMC8755536, 67 of 263, among them a paper
   explaining carnivores' higher cancer prevalence by their age in zoos). It is used without a key:
   one free daily budget per network address, plain paging; if it fails, the call stands on the other
   two and records why. A study that disagrees is usually here, as a research article,
   not among the responses: read the citing works whose titles bear on the claim.
5. `search.py literature QUERY` — Europe PMC and PubMed search, for disagreement that does not cite
   the article. Record the exact query; Europe PMC and PubMed syntax differ. Each query is sent twice,
   as given and without reviews (Europe PMC `NOT PUB_TYPE:review`, PubMed `NOT review[pt]`), and both
   answers are logged: reviews push the primary works off the first page, and a primary study against
   the claim is the work a search must not miss (on "rapamycin mTORC2 glucose", 4 467 of Europe PMC's
   8 513 hits are reviews). The report flags a query that has no successful run without reviews.

A trial the article names is read with `search.py trial NCT` (see "Trials").

Each of these but `terms` takes `--as-of YYYY-MM-DD`, for a conversion that must not see what came
after a date; see "A cutoff date".

`ID` is a PMID, a PMCID or a DOI. `search.py report` prints the search section of the report.

## Searching by meaning, not by title

A search for the article's title finds the article and those who repeat it. Disagreement uses other
words: another field's terms, the opposite claim, the data source, the alternative mechanism. And it
need not cite the article. So the search runs from the claim, in families of queries, each recorded.

1. **Split the claim** into what can be searched: the relation (what changes what), the scope (species,
   population, conditions), the predictions, and the alternatives the authors name. Written before
   searching, with paragraph numbers, as step 2 of `SKILL.md` already asks.
2. **Collect the terms** for each concept: the article's own words; `search.py terms ID`, the MeSH
   headings (major topics marked) and keywords the article is indexed under; the words that the
   citing and related works use for the same thing (`cited-by`, `similar`: read the titles); gene names
   resolved by `biodb.py gene`, whose aliases and former symbols are search terms; the other names of
   a drug, complex, process or organism from `biodb.py mesh`, `go` and `taxonomy` (MeSH entry terms
   give the PubMed `[MeSH Terms]` heading for a word, `search.py terms` the headings of one article).
   Example from the pilot: "cancer risk" in the article is "neoplasia prevalence", "cancer mortality"
   and "tumour incidence" elsewhere; "body mass" is also "body size".
3. **Run the families**, each in Europe PMC and PubMed, with `search.py literature`:
   - *the claim*: concept AND concept, with the synonyms joined by OR;
   - *the opposite*: the concepts with the words of disagreement: "no evidence", "does not support",
     "contrary to", "reanalysis", "re-examination", "revisited", "confound", "bias";
   - *the prediction*: what would be observed if the claim were false, in the terms of step 2;
   - *the alternatives*: each alternative the article names, and each mechanism a citing work offers;
   - *the method*: the data source or design and "bias", "limitation", "reanalysis" (pilot: zoo
     records of captive animals).
   Then the neighbours: `status`, `responses`, `cited-by` (all citing works, not only the typed
   answers) and `similar` (PubMed's related articles, which include earlier and non-citing work).
4. **Syntax.** Europe PMC: quoted phrases, `AND`/`OR`/`NOT`, fields `TITLE:`, `ABSTRACT:`, `MESH:`
   (`MESH:"Body Size" AND MESH:"Neoplasms"`). PubMed: `[tiab]`, `[MeSH Terms]`. The two parse
   differently; the log keeps each exact query, so a family is repeated as it was run. Put the
   concepts in fields (`ABSTRACT:"body mass"`), not in the whole text: in the pilot the claim family
   over the whole text gave 2,888 hits, mostly clinical, and over abstracts 74, all recorded. A query
   whose reported hits are far above the recorded ones is too broad: narrow it rather than raise
   `--limit`, because the works past the limit are lost in the service's order, not by relevance.
   Then run each family twice: as it comes (both services put the most recent works first) and with
   `--sort cited` (Europe PMC by citations, PubMed by Best Match), which brings up the established
   work on the question. Both runs are in the log, each with the order it asked for.

   **One `OR` group, one field.** In Europe PMC an `OR` that mixes field qualifiers is not the union
   of its parts and depends on the order of its operands, because the query is reparsed rather than
   combined. Measured on 2026-10-21: `ABSTRACT:"rapamycin"` 44,391 hits, `MESH:"Sirolimus"` 2,471,
   and `(ABSTRACT:"rapamycin" OR MESH:"Sirolimus")` 97,372 — which is not a union of 44,391 and 2,471
   but exactly the count of the bare whole-text term `Sirolimus`, so the first operand was dropped
   and the `MESH:` qualifier stripped. Written the other way round,
   `(MESH:"Sirolimus" OR ABSTRACT:"rapamycin")` gives 597,769. An `OR` of terms in the **same** field
   behaves: `(ABSTRACT:"rapamycin" OR ABSTRACT:"sirolimus")` gives 52,518, a plausible union.
   So: join synonyms with `OR` inside one field, combine different fields with `AND`, and where both
   a word and a MeSH heading are wanted, run them as two recorded queries and merge the works in the
   log. A count from a mixed-field `OR` is not evidence of anything and must not be reported as the
   size of a search.
5. **Screen, then read.** Every title a family returns is screened by reading the title and type, not
   by a keyword filter: in the pilot a filter on "cancer risk", "body size" and "Peto" missed a 2026
   study of bias in zoo cancer records that cites the article. A candidate counts as a work against only
   after its text is read. The report gives three numbers: found and screened in, read, and judged
   against, with the works against named.
6. **Stop** when two families in a row add no new candidate that bears on the claim, or when the budget
   the task sets is spent. The report says which, with the date of the last search: "nothing further
   against" holds only up to that date and within those families.

Another tool (an MCP server, a library, a web search) may suggest terms or works for any step; what
it suggests enters the log only when a kit command repeats the search.

## References inside a submitted text

A submitted text (an answer of a model, a note) often cites works, and a model may cite works that do
not exist or say of a real work what it does not say. `search.py check-refs FILE` reads every
reference (a Markdown link, a DOI, PMID or PMCID, an "Author et al., *Journal*, year", or an entry
of a numbered reference list under a "References" heading, cited in the text as [3], [3,4] or [62-64])
and answers three separate questions for each:

- `exists`: is there such a work? It is found by the identifier the reference gives (Europe PMC,
  then Crossref for a DOI). With no identifier, it is found by its description:
  - with a title, by first author and title in Europe PMC, then by Crossref's bibliographic search,
    kept only where title and first author agree. The year is left out of the query, because a work's
    online year can come before the year cited.
  - without a title, by author, year and journal.

  The answer is `verified`, `not_found`, `ambiguous` (several candidates, none chosen) or
  `not_checked` (too little to search by). A work found by description under another title (a précis
  of a cited book, a longer title that contains the words) is `not_found`, with the closest record
  kept.
- `matches`: does the reference describe that work? Its title, first author, year and journal,
  where it gives them, are compared with the record: `match`, `mismatch` with each difference, or
  `not_checked`. In the comparison:
  - names are compared without diacritics ("Jablonski" is "Jabłoński");
  - a cited year matches any of the work's dates;
  - a title read from a list up to its "?" matches the record's title that goes on with a subtitle.
- `relevance`: does the work bear on the sentence that cites it? `not_assessed` from the tool. A
  separate checker judges it (see below), and it is never inferred from `exists` or `matches`: a real,
  correctly cited paper may say nothing about the claim.

Only a reference that is `verified` and `match` names a work the card may then fetch and read as a
source; an unverified one is never a source of the card and stays visible in the report. A work that
does not support a claim does not refute it, and a reference that is `not_found` says nothing about
whether the claim is true: it says the submitted text cited something that could not be found.

## Attribution: which search found what the card cites

`search.py attribute CARD` reads the card's `added.sources` and the search log, and says for each work
the card cites which logged calls found it (by `call_id`, tool and the exact query), which calls found
nothing the card cites, and which cited works no logged call found. Identifiers are matched across
PMID, PMCID and DOI as the logged records give them together. Put its output in the report.

A cited work "NOT found by a logged search" was known to the converter or found with another tool; it
is still cited, and the report says so. A call that found nothing cited is reported too: a search that
contributed nothing is a measurement, not a failure.

## Relevance of a reference in a submitted text

`check-refs` says whether each work cited by a submitted text exists and is described correctly. Whether
the work says what the text attaches it to is judged by a separate checker, never by the converter that
extracts the card. `relevance-input` and `relevance-merge` carry that judgement into the log, with an
outcome from a closed list and a locator. See [relevance.md](relevance.md).

## Accepted cards that may state the same hypothesis

`search.py similar-cards TEXT --cards DIR` compares a submission with the accepted cards in DIR. The
score is the cosine of the two texts' words, each weighted by how few cards state it; the text's
reference list is left out. A long text shares common words with every card, so a card is a candidate
only when it stands out: its score is at least twice the median of all cards and it shares two or more
words, or it shares a cited work. The candidates are logged with:
- the words both state, rarest first;
- the works both cite;
- the score and the median.

It is a record for the reader, who decides whether the submission is a duplicate (the card's
`identity.duplicate_cluster_ref`). Nothing is filtered or refused. Words are matched within one
language, so a hypothesis translated with no shared term or work is missed. Gene and protein symbols
(mTORC1, Akt) are usually shared across languages.

## Read and not cited

A work that was read against the card and is not cited is logged with the reason:

`search.py not-cited ID --reason REASON --locator WHERE [--atom KEY]`

REASON is one of a closed list:
- `other_species`;
- `other_endpoint`;
- `other_intervention`;
- `subgroup_only` (the result holds only in a subgroup);
- `background_or_review` (no result of its own);
- `licence_refuses_quotation` (the work's own rights refuse quotation);
- `retracted` (the publisher withdrew the result, established by its publication types);
- `off_topic`.

WHERE is where in the work the reason shows: a section, table or figure, not its text. A reason
outside the list or a blank locator is refused, and nothing is logged.
The reading attestation for a valid reason survives a failed metadata lookup. `retracted` additionally
requires a successful lookup showing full withdrawal; a corrected or partially withdrawn work cannot
take that reason. `screen` and `closeout` use the same attestation check.

The report lists each such work with its reason and counts them by reason. The critic reading for
disagreement gets the list, so a work against the claim cannot be dropped without a trace.
`attribute` lists them too, and marks a CONFLICT when the card cites a work logged as not cited.

## Closing the search and reading partial notices

`search.py closeout CARD` lists the answering works and their recorded dispositions. A missing
disposition keeps the gate open. A partial retraction requires a separate reading of its specific
notice before a disposition that uses the work can close it. The scientific question of whether the
line relies on withdrawn results remains a reading judgement.

`status` discovers metadata. It never establishes that the notice body was read. After reading the
identified partial notice, record an attestation:

```sh
python scripts/search.py notice-read WORK_ID --workdir DIR \
  --status-call DISCOVERY_CALL_ID --notice NOTICE_ID \
  --notice-sha256 sha256:HASH_OF_THE_NOTICE_READ --locator 'paragraph or page' --reader READER
```

The discovery record must identify that partial notice for that work. A publication-type flag with
no notice ID, an ordinary correction or a notice for another work cannot bind the attestation. It
records the discovery call's hash, notice ID, declared hash of the document read, locator, reader
and time. The command fetches and retains no body. The hash and reading are the reader's assertion;
the kit checks the binding, not the truth of that assertion or which results were withdrawn.

If several partial notices were identified for the work, each needs a bound reading. The closeout
lists the required notices and reading records. Metadata alone cannot close it, and changing the
bound discovery record invalidates its reading attestation. A work recorded as unavailable needs no
reading because the card does not rest on it. Reading a notice does not supply a missing disposition
of the work itself.

A work found and never read needs no record; "read" means the reader looked at the work for the atom.

## What a record holds

The tool, the question, start and end times, every URL with its time, HTTP status and SHA-256, the
count the service reported, and the works found: PMID, PMCID, DOI, title, year, publication type, and
the licence **as the source states it** (`licence_from` names the field). PubMed states no licence;
Europe PMC states one for open-access works. A work with no stated licence has `licence: null`: its
text is not quoted until its own permissions say it may be ([rules.md](rules.md) §1).

Records hold no abstract or article text. An API that serves text grants access, not a licence to
republish it; only identifiers, titles, locators and hashes leave the search.

## Limits

- Europe PMC citations come from reference lists it has indexed; PubMed "cited in" only from PMC. A
  work missing from both is not found by `cited-by`. The two counts are kept apart in the record.
- A citing work Europe PMC lists without a record it can return is kept, marked with a `note`.
- Crossref relations are deposited by publishers and are sparse.
- Europe PMC and PubMed return a query's works most recent first unless asked otherwise (checked
  2026-10-21). `--sort cited` asks Europe PMC for `CITED desc` and PubMed for `relevance`; Europe PMC
  answered 503 to a `sort` value it does not accept. When `hit_count` exceeds `found`, the report says
  so and the query is narrowed.
- Requests are spaced per host (NCBI 3 a second without a key, Europe PMC and Crossref 2 a second),
  and a 429 or 5xx is retried after the wait the service asks, at most three times. Set `OHF_CONTACT`
  to give Crossref and NCBI a contact address; the kit has none.
- A service that takes its query only by POST (GraphQL) gets a JSON body: `Searcher.json(url,
  responses, body=...)`. The body is kept with the responses and its hash is `request_sha256` in the
  record, so the request repeats as a URL does.
- A response sent compressed though not asked to be (the Internet Archive's `id_` form sends gzip) is
  decoded before it is kept: its `sha256` is of the decoded bytes and the record says `decoded_from`.
  An encoding the kit cannot undo fails the call, with `content_encoding` and `kept: false`; no body
  that reads as nothing is kept.

## Where to read a full text

`search.py text ID` (a PMID, PMCID, DOI or arXiv id) lists the places a work's full text can be read
openly, each with the licence that place states and where the statement comes from:

- a PMC article: its Europe PMC JATS XML (what `ohfkit` reads), and its PMC BioC JSON when it is in the
  open-access subset;
- the free copies Europe PMC lists for it (a publisher page, a PDF, a repository copy found by
  Unpaywall), without a licence of their own;
- a bioRxiv or medRxiv preprint: the JATS XML of its latest version and the licence the server
  records, the version and, when there is one, the DOI of the published paper;
- an arXiv paper: its PDF and the licence arXiv records (OAI-PMH);
- with `OHF_CONTACT` set, the open copies Unpaywall knows (it asks for an address; without one the
  record says it was skipped).

It finds; it downloads nothing and records no text. A card takes text only from a copy the kit reads
itself through `docs.json`, under the licence rule of `rules.md`. A place that refuses access is
recorded as refused and not tried another way.

## Trials

`search.py trial NCT` reads one study from the [ClinicalTrials.gov API v2](https://clinicaltrials.gov/data-api/api):
its status, phases, enrollment, the start and completion dates with their type (anticipated or
actual), conditions, interventions by type and name, primary outcomes by measure and time frame, and
the record's own dates: registered, results first posted, last updated. The registry's descriptions
are not recorded. `search.py trials QUERY` searches the registry, which matches synonyms of conditions
and interventions itself. A subgroup or secondary outcome reported as support is checked against the
registered primary outcome here, by the NCT number the article gives.

The API gives the current version of a record, not its history. For a cutoff, a record last updated
by T is the version of T and every field stands; a record updated after T may have changed, and each
field that changes as a trial goes on is null, with the reason and the day of the last update. Results
count only if first posted by T; a study registered after T was not known on T (`trials` asks only
for studies registered by then). The registry's version history is on its website, not in the API,
and the kit does not read it: a trial updated after T has an unknown status, never today's.

## A cutoff date: what was known by T

A conversion that must not see what came after a date T (a cutoff, OHF `added.cutoff_date`) gives T as
a day, `YYYY-MM-DD`, inclusive; not a time. Two things leak past it, and `search.py` has one rule for
each, for literature and databases alike.

- **A work's date** is the earliest of its online, print and database-record dates
  (`search.earliest`): a work online a month before print was known from the online date. Every
  found work carries its `dates`, read from the service's record: from Europe PMC (`work_dates`) the
  electronic, first and print publication dates and the day it was first indexed; from PubMed
  (`work_dates_pubmed`) the electronic and print dates and the day the record entered PubMed. A
  received or accepted date is not a date the work was public and is not read. The indexing day
  matters: a work published 2025-01-01 may have been in both services since October 2024.
- **A field that changes with time** (a trial's status, a compound's phase) is read as it is now. Its
  value counts for T only when it is known to hold by T: `search.as_of(value, dated, cutoff, release)`
  keeps it when its own date (`dated`, the date from which the source says it holds) is on or before T,
  or, with no date of its own, when the state read was released on or before T. Otherwise the value is
  null, with the reason (`undated`, `after_cutoff`, `straddles_cutoff` for a year or month containing
  T) and the source's release date in the same record of the search log; the value as stated is kept
  there too, as evidence, and never enters a card as the value on T.

`--as-of YYYY-MM-DD` applies both to the search commands `literature`, `cited-by`, `responses`,
`similar`, `status`, `trial` and `trials` (see "Trials" for what a registry record holds on T):

- `literature` asks each service only for what it had by T (Europe PMC: first indexed or first
  published by T; PubMed: entered or published by T); the record keeps the query as given and the
  query `sent`.
- Every work found is then judged by its own dates (`search.cut`). A work dated after T is left out
  and named in the record's `left_out` with the date that dropped it; a work with no date, or with a
  year or month that contains T, is kept and marked `cutoff.before: null`, to be judged by reading,
  not dropped unseen.
- `status` counts only notices dated by T. A notice with no date (Europe PMC's links and publication
  types carry none) may be later: it is listed as `undetermined` and not counted, so a status "as
  of" T can only miss a notice, never import one from after T.
- `similar`: PubMed computes its related articles today, over later works too; the cut removes the
  later works, not their influence on the order.

The order of a search is named in the report. With none asked, both services return the most recent
works first, which is repeatable. PubMed's Best Match (`--sort cited`) is not: the service retrains
it, so the same query may rank differently next month; each work's rank is kept in the log.

## Databases

The genes, targets and interventions a card names are looked up in databases by
[scripts/biodb.py](../scripts/biodb.py). It imports `search.Searcher`: the same log, the same kept
responses, the same waits per host. A lookup is a search and is reported like one. In one process,
pass the one Searcher to every call, of either script; the waits are kept per Searcher.

1. `biodb.py gene NAME ...` — a gene by any name the card uses. HGNC gives the approved symbol; NCBI
   Gene and UniProt are then read by the identifiers HGNC gives. Run it first: the other databases are
   asked by the approved symbol or identifier, and the synonyms it returns widen a literature search.
   A name HGNC holds for several genes stops there, with all of them (`ambiguous`): choose by reading.
2. `biodb.py hgnc NAME ...` — [HGNC](https://www.genenames.org): the approved human gene symbol for a
   symbol, a former symbol or an alias, in that order, regardless of case (`resolved_by` says which
   matched). Records the approved name, the aliases and former symbols and names, the gene groups (a
   protein complex is a group: "MTOR complex 1"), the location and the NCBI Gene, UniProt and Ensembl
   identifiers. CC0.
3. `biodb.py ncbi-gene ID ...` — [NCBI Gene](https://www.ncbi.nlm.nih.gov/gene): symbol, name, aliases,
   other designations, organism and map location, and the id that replaced a retired one. The gene
   summary is not recorded: NCBI places no restriction on its molecular data but cannot license
   material others submitted, and the summary may draw on it.
4. `biodb.py uniprot ACCESSION ...` — [UniProtKB](https://www.uniprot.org): the protein's name, genes,
   entry version and keywords, and its function, subunit and activity regulation as UniProt states
   them, each with the PMIDs of the studies behind it; those studies are listed once each as leads.
   CC BY 4.0: a card that quotes it gives the record's `attribution` (the consortium, the accession and
   the entry version).
5. `biodb.py genage SYMBOL ...` — [HAGR GenAge](https://genomics.senescence.info/genes/): is the gene
   an ageing gene in humans (and why: mammal, model, cell, functional, putative), and how its
   orthologs in model organisms change lifespan (effect, pro- or anti-longevity, the largest change).
   The symbol matches regardless of case, so MTOR finds the mouse Mtor too.
6. `biodb.py drugage COMPOUND ...` — [HAGR DrugAge](https://genomics.senescence.info/drugs/): every
   cohort in which the compound was tested for lifespan: species, strain, sex, dose and regimen, age at
   start, duration, mean and maximum lifespan change with significance, whether it was an ITP study,
   and the study by PMID, listed once each as a lead.
7. `biodb.py hagr-fetch DATASET` — downloads a HAGR build (`genage_human`, `genage_models`, `drugage`)
   as HAGR offers it, and records its build number, release date and SHA-256. HAGR asks that many
   queries go to its downloads, not its site: `genage` and `drugage` search the build fetched last in
   the work directory, fetching it first if there is none, and each record names the build and hash
   it was read from. A kept archive whose hash no longer matches is refused. HAGR says most of its
   content is public domain, but the data sheets of its databases (GenAge descriptions, AnAge
   observations) are copyrighted and under CC BY 3.0: hence the licence on each database record. A card
   that quotes HAGR gives the record's `attribution`, and the report its `citation`.
8. `biodb.py reactome ACCESSION ...` — [Reactome](https://reactome.org): the human pathways a UniProt
   protein takes part in, each with its stable id and the Reactome release. CC0.
9. `biodb.py reactome-pathway ID ...` — a Reactome pathway or reaction: its versioned id, its summary
   and the studies it cites by PMID, listed once each as leads. CC0.
10. `biodb.py target ENSEMBL|SYMBOL ...` — [Open Targets](https://platform.opentargets.org): the diseases
    associated with a target, the first 25 by score and how many there are (Open Targets' own data,
    CC0, with the attribution and the citation Open Targets asks for); and the drugs and clinical
    candidates acting on it, by ChEMBL id and link only.
11. `biodb.py drug NAME|CHEMBL ...` — Open Targets: a drug's ChEMBL id, preferred name and links, and how
    many mechanisms and indications Open Targets holds for it. A name is found by Open Targets' search:
    "rapamycin" finds sirolimus, and the record says which name it matched (`matched`). Link only.

### Drug data from ChEMBL: link only

Open Targets marks its data CC0, but its drugs, mechanisms, clinical stages and indications come from
ChEMBL, whose data are CC BY-SA 3.0 ([ChEMBL, about](https://chembl.gitbook.io/chembl-interface-documentation/about)).
ShareAlike does not fit a card under CC BY, and an aggregator's mark does not lift the terms of the
source it took the data from; where the two statements differ, the kit takes the stricter. Those fields
are recorded by identifier, link and count only (`withheld` names them), and the record names their
origin and licence beside them (`data_licence`, `drugs_licence`), never under the record's CC0; a card that needs a mechanism or a stage reads
it in the drug label or the study, not in Open Targets or ChEMBL. Open Targets' own data, the
target-disease associations and their scores, are recorded under its licence.
12. `biodb.py opengenes SYMBOL ...` — [Open Genes](https://open-genes.com), human genes associated with
   ageing. Answers: is this gene in Open Genes and with what confidence level, which ageing mechanisms
   and selection criteria Open Genes gives it, and which studies, by DOI or PMID, stand behind each kind
   of evidence (lifespan change, age-related change, intervention effects, regulation, longevity
   associations), with Open Genes' row for each: organism, line, sex, intervention, result, the values
   and its comment. A symbol Open Genes does not hold is a search that found nothing, not a failure.

What a database record holds: the entry's identifiers, a link to its page, the values the database's licence allows, the cited
studies' identifiers, and the licence with `licence_from`: where the licence is stated. `withheld`
lists the fields left out and why.

### Open Genes: CC BY 4.0, attributed

Open Genes data are under CC BY 4.0 by permission of the rights holder, Open Longevity (2026-10-21),
kept in the kit as [permissions/open-genes.md](permissions/open-genes.md). The site and the API do not
state a licence, so `licence_from` names that note and its SHA-256. A kit without the note records
Open Genes link only: identifiers, page and counts, no value or text (`withheld` says so). A card that
quotes Open Genes attributes it as the record's `attribution` gives. The licence covers Open Genes' rows, not the studies they summarise: a
study's `licence` is its own and is not known from Open Genes (`evidence_licence` is Open Genes'). A
finding the card states as a study's is read in the study; Open Genes' row says what Open Genes
recorded. Text Open Genes repeats from UniProt, NCBI Gene and the Human Protein Atlas is not recorded.

### Terms: widening a search

A disagreement may use other words than the card: another name of the drug, the complex, the process or
the organism. These lookups give the other words; the search with them is still `search.py
literature`, recorded as usual, with the query that used them.

13. `biodb.py mesh TERM ...` — [MeSH](https://meshb.nlm.nih.gov) (NLM): the headings and supplementary
    concepts a term finds, the heading it maps to first (`"TERM"[MH]`), then those whose terms include
    it: the preferred heading, its entry terms (`synonyms`), tree numbers, scope note, and for a
    heading a PubMed query (`"Sirolimus"[MeSH Terms]`) that finds what is indexed under it whatever
    words the article used. NLM provides MeSH freely and asks to be acknowledged as the source
    (`attribution`) and the version used to be named: `release` is the NCBI MeSH build read and
    `release_date` its update (MeSH may have changed since).
14. `biodb.py taxonomy NAME|ID ...` (or `taxon`; an id as `9031` or `NCBITaxon:9031`) — [NCBI
    Taxonomy](https://www.ncbi.nlm.nih.gov/taxonomy): an organism's scientific name, rank, lineage with
    the id and rank of each node (`lineage_ids`) and other names (common names, synonyms, former names;
    not the strains it includes, nor misspellings). And its rung of closeness to humans, the taxon's part
    of OHF `human_proximity`, by node id, the first that holds: Homo sapiens (9606) `human`, Mammalia
    (40674) `mammal`, Vertebrata (7742) `non_mammal_vertebrate`, Metazoa (33208) `invertebrate`;
    outside Metazoa (yeast, plants, bacteria) none (`proximity_by: "not an animal"`). For the sixteen
    taxa of `ohf:terms@1` it gives the pinned rung; for any other taxon it is the rung the table would
    have. Under `--as-of` the lineage and the rung stand from the taxon's last update.
    `--taxa taxa.json` writes the rows of the taxa asked beside the card, each a row of `ohf:terms@1`
    taxa (`id`, `label`, `proximity`) with where it comes from (`by`, `rank`, `call_id`,
    `taxonomy_updated`), for `check_refs` to check a rung outside its table (`check_refs.py CARD --taxa
    taxa.json`: a row only adds an id the table lacks, never overrides one; a null rung is not derived);
    a common name of several taxa ("mouse": Mus musculus and Mus) is listed in `ambiguous`, not chosen.
    `biodb.py taxon-ids CARD --reading FILE` places a 1.1 card's `system.taxon_id` from a reading of
    its lines, any rank but one taxon only, each with its call as the source, or a gap ([fields.md](fields.md)).
    `biodb.py proximity CARD --standard DIR` places a 1.1 card's `human_proximity` from those ids:
    the derivation is the standard's (`check_refs` of the checkout DIR, run in its own tools), not
    this table's, and makes no request ([fields.md](fields.md), Evidence).
15. `biodb.py go TERM|GO:ID ...` — [Gene Ontology](https://geneontology.org) through QuickGO: a term's
    name, aspect, definition and synonyms with their type (exact, narrow, broad, related; a related
    synonym widens a search and loosens it). A text search reads its first five terms. CC BY 4.0;
    `release` is the GO release read, which GO asks to be mentioned with what is taken from it.

Every record of these three, and of HGNC, carries `synonyms`: the words to add to a query, with the
record they came from. Which of them a query used is in that query, in the search log.

### Compounds and datasets: links, not content

16. `biodb.py chembl NAME|CHEMBL ...` — [ChEMBL](https://www.ebi.ac.uk/chembl/) itself, link only as
    above: a compound's id and preferred name (a name finds it through its synonyms: rapamycin finds
    SIROLIMUS, CHEMBL413), its link, how many mechanisms, indications and activity records ChEMBL holds
    for it, and the release read (`release`, `release_date`). A name search reads the first three
    compounds. What the counts point to is read in ChEMBL by a person, or in the study it cites.
17. `biodb.py geo QUERY|GSE ...` — [GEO](https://www.ncbi.nlm.nih.gov/geo/) expression and other
    high-throughput series: accession, title, organism, type, number of samples, platforms, release
    date, the PubMed ids that describe the series, and links to its page and files. Not the data, and
    not the submitters' summary (`withheld`), as with NCBI Gene. A series is a lead: what it shows is
    read in the paper that reports it, or not claimed. The query is Entrez syntax (`rapamycin AND
    "Mus musculus"[ORGN]`); the first twenty series are read, in GEO's order.
18. `biodb.py pubchem NAME ...` — [PubChem](https://pubchem.ncbi.nlm.nih.gov/): the compound a name
    stands for, by its parent: a salt or a hydrate is the compound (metformin hydrochloride is metformin,
    CID 4091; quercetin dihydrate is quercetin). Where a metal is the active part, the name keeps its own
    compound: PubChem's parent of zinc acetate is acetic acid (the rule of hyp-arena's `compounds.py`,
    MIT). A record holds the CID, the preferred name, the InChIKey, the formula and up to fifty short
    synonyms, the CIDs the name found (`collapsed_from`) and how the parent was chosen (`parent_by`);
    NCBI's terms. DrugAge (item 6) and `entities.py` match compounds by it.

### Hallmarks of ageing: hints, never assigned

19. `biodb.py hallmarks GENE ... [--hints FILE]` — which of the twelve hallmarks of ageing (López-Otín
    2023; OHF 1.1 `profile.aging_hallmarks`) a gene's database terms suggest. HGNC resolves the gene;
    Open Genes gives its ageing mechanisms (CC BY 4.0, attributed in each hint) and QuickGO counts its
    GO annotations that map, by is_a, part_of, occurs_in or regulates, to the GO processes of the table.
    The table is pinned in `references/hallmarks-map.json`, by its hash in `biodb.py`: each row a term (an Open Genes mechanism by
    id, a GO process), its hallmark, its source and the basis. A hint (`ohf-extractor:hallmark-hints@1`)
    gives the hallmark, the term, the reason, the row's source, a link and the call it rests on; a term
    in no row gives no hallmark and is listed in `not_mapped` (ELN's extracellular matrix). A hint
    assigns nothing: the converter sets a card's hallmark from the card's text, with its atoms, or not at
    all. A compound (CHEBI, CID) gets no hint of its own: no open source files a compound under a
    hallmark; with `--via GENE`, the target the card names, it gets the gene's, each marked `via`. The
    twelve hallmarks are the standard's `ohf:hallmarks@1`, pinned in the table by its hash.

### Dates: what a database said on a cutoff

A database answers as it is now, and a conversion with a cutoff T must not take from it what came
later. Every record of `biodb.py` carries `dates`: `since`, the day the entry was made public;
`release_date`, the day of the release read; and `fields`, for each value that changes with time, the
date since which it has stood unchanged, as the source states it, or null. Identifiers, links,
licences and the version read are not dated. Deciding is `search.as_of`'s, one rule for every source:
a field's date is its `dated`, the record's `release_date` its `release`.

| Source | `since` | each value since | release |
|---|---|---|---|
| HGNC | approved | the symbol and the name since their own change, the rest since the entry's last | none |
| UniProtKB | first public | the last annotation update | none |
| NCBI Taxonomy | public | the last update | none |
| MeSH | none: the year introduced is recorded, not taken (absent for some headings, not always the first) | none (MeSH's own dates read 1/01/01) | the NCBI build |
| Reactome | the pathway's first release | none: not its changes, nor a protein's place in it | none |
| GEO | released | none: a later change (a PubMed id added) is not dated | none |
| GO, ChEMBL | none | none | the release |
| HAGR GenAge, DrugAge | none | none | the build |
| NCBI Gene, Open Targets, Open Genes | none | none | none |

`biodb.py ... --as-of T` (T as `added.cutoff_date`) applies it to every call: an entry made public after
T is left out (`as_of.left_out`), each value is kept or null, and the record keeps each decision whole,
the value as stated with it (`as_of.fields`, by `source_id`); the card takes only the value. The hit
count stays the source's count today. A study a database cites (Open Genes, UniProt, Reactome,
DrugAge) is dated by the work itself: its Europe PMC record, found by PMID or DOI in the same call, and
the earliest of its dates (`search.earliest`; `dates.work`, `dates.since_by`). A study published after
T is left out, and so is one Europe PMC does not find: undated. A DrugAge cohort is one study's result
as DrugAge curated it: it takes its study's date, for itself and each value (`since_by: study MED:...`),
and without a dated study it is left out. On MTOR at 2014-06-01: Open Genes keeps 7 of its 13
studies, UniProt (RPTOR) 13 of 29; DrugAge rapamycin 9 of 18 studies and 18 of 37 cohorts. A renamed
gene: HGNC's TENT5C was FAM46C until 2018-04-20, so at 2017-01-01 its symbol is null (`after_cutoff`).

`entities.py link ... --as-of T` keeps every link: a link identifies what the source names, and an
entity is not newer than the entry made for it later. Each link and candidate says whether its entry
was public on T (`at_cutoff`: `public`, or `search.as_of`'s reason), and `cutoff.links_not_public`
counts the links that were not shown to be. On the intermittent-rapamycin card at 2014-06-01: 10 exact
as without a cutoff; Mus musculus public, nine undated. MeSH's year introduced would have dated four
of the eight MeSH links, but it is absent for some headings (mTORC1, T cells, Insulin) and not always
the first (Osteoarthritis reads 2013): a date that cannot be trusted reads as none. With the dates as the sources give them,
a past cutoff keeps little: at T = 2014-06-01, RICTOR's HGNC symbol and GSE53980's existence stand;
its HGNC aliases, its UniProt function and the mouse's taxonomy names changed after T and are
unknown, though they may have read the same then.

### Entities: what the card names, linked, with how

`entities.py` links the genes, proteins, complexes, processes, organisms and compounds a card or a
submitted text names to the databases above, and writes `entities.json` beside the card. OHF has no
place yet for how a link was made (a status, the call behind it), so the file stands beside the card.

1. **Read the mentions.** The converter writes `mentions.json`: each mention's words exactly as they
   stand, its kind (`gene`, `protein`, `complex`, `component`, `process`, `organism`, `compound`,
   `other`) and where it stands (a JSON pointer into the card, or `p1`, `p2`... for a submitted text's
   paragraphs). `query` only where the words to look up differ (a translation: "аутофагии" →
   `autophagy`), `taxon` only where the source says which organism a gene is meant in.
   `entities.py tokens SOURCE` lists the symbol-like words of the source as a check on the reading.
2. **Link.** `entities.py link SOURCE mentions.json`. A mention whose words do not stand where it says
   is rejected and listed, not linked. Each kind is looked up in its databases, each call logged:
   genes and proteins in HGNC and MeSH, or first in NCBI Gene for the mention's taxon when it is not
   human; complexes, components and processes in GO and MeSH; organisms in NCBI Taxonomy; compounds in
   MeSH and PubChem (one parent compound is a link, several are candidates); the rest in MeSH.
3. **Status, by rule.** `exact`: a database has exactly one entry whose own name, symbol or equivalent
   term is the query; one link per such database. `ambiguous`: several, or only entries that carry it
   as an alias or not at all; the candidates are listed and none is chosen. `not_found`: nothing came
   back. Each entity names the calls (`established_by`, by `call_id`).
4. **Read the file.** `unlisted`: symbol-like words no mention covers, each a word the converter read
   past or should name. `rejected`. `card_ids`: the identifiers the card already holds, against the
   links (`linked_by`) or only the candidates (`candidate_of`: the card's entry is broader, narrower or
   another one than the mention's).

Pilot, 21.10: case 7 (a model's answer in Russian) 9 exact, 8 ambiguous, 1 not found; the
intermittent-rapamycin card 10 exact, 1 ambiguous, 1 not found. In the card, "mTORC1" is linked to
the MeSH heading, and the card's GO:0031931 is a candidate only: GO lists "mTORC1" as a narrow synonym
of "TORC1 complex".

### Limits

- Entities: a gene's alias is not an identity (PI3K is an HGNC alias of PIK3CA alone; the text means
  the family), so a match by alias is ambiguous: p16, p21, S6K, Akt and 4E-BP1 stay so until the
  source names the gene. A gene of another species not found in its taxon has the human gene of the same
  name as a candidate (`scope: ortholog`), never as a link: a shared name does not establish orthology.
  A common name ("mouse") is the name of more than one taxon. A query is looked up as given: "lung
  fibroblasts" finds no MeSH entry, though "Fibroblasts" and "Lung" are two. A gene's taxon includes the
  taxa below it (rice genes are filed under Oryza sativa Japonica Group). Letter case decides where it
  can: in Arabidopsis RPS4 is the immune receptor and rps4 the chloroplast ribosomal proteins; the
  entries it set aside stay among the candidates (`set_aside_by: "letter case"`). From the plant case
  (PMC4246468): RRS1 is two NCBI Gene entries of that symbol (AT5G45260, AT5G45270); rice RGA4
  and RGA5 are aliases of LOC genes; popP2 is one entry per Ralstonia strain; MeSH names a concept with
  its organism ("AvrRps4 protein, Pseudomonas syringae"), which a bare name does not match; GO names the
  hypersensitive response "plant-type hypersensitive response" and has no "effector-triggered immunity".
  All stay ambiguous, with the candidates.
- Waits between requests are kept per Searcher, in one process. Two processes calling the same host
  (two conversions at once, or `search.py` and `biodb.py` run separately) are not spaced against each
  other.
- Human genes. HGNC names human genes only; another species' gene is not resolved, and `uniprot_gene`
  is asked for human unless told otherwise.
- A name is resolved as HGNC holds it, not as the card means it: "AKT" is an alias of AKT1 alone, though
  a card may mean the AKT family; a complex ("mTORC1") is no gene and is found nothing. Read the gene
  groups and choose.
- Open Genes is looked up by the approved symbol (run `gene` first); an ortholog's name is not resolved.
  A search by ageing mechanism, intervention or disease is not offered.
- UniProt: only function, subunit and activity regulation are recorded as text; other comments,
  features, sequence and cross-references are not. Its CC BY 4.0 covers the copyrightable parts of its
  databases, and UniProt says some data may be covered by patents or other rights: stronger than NCBI's
  terms, not unconditional.
- Open Targets files a drug under the target of its mechanism as ChEMBL records it: sirolimus is filed
  under FKBP1A, its binding partner, so MTOR's drugs do not include it. A drug acting through a partner
  protein is found from the drug, not from the target it finally inhibits.
- Open Targets is a GraphQL service: each call is a POST whose body is kept and hashed with the
  responses. Its schema changes between releases; a query the release no longer answers is a failed
  call, not an empty one.
- Terms are found as each service matches text: NCBI Taxonomy does not expand an abbreviation ("C.
  elegans" finds nothing; "Caenorhabditis elegans" does), and a MeSH or GO text search returns its own
  order, of which the first five are read. A complex the card names ("mTORC1") is a MeSH heading
  ("Mechanistic Target of Rapamycin Complex 1"), though no gene.
- NCBI states a MeSH build and date, not the MeSH year: the record names the build, and a MeSH text
  carried into a card names it with the date. A record without `release` (written before it was
  kept) is used for search words only, not for a definition or scope note.
- HAGR: one build per dataset per work directory; a newer build is used only after `hagr-fetch` is run
  again. DrugAge files a compound under one name, sometimes as a salt: a row is matched by its name or
  by its PubChem parent (`matched_by`), so sirolimus finds the 37 rapamycin cohorts and promethazine the
  ones filed as promethazine hydrochloride. The build's 1 046 names are mapped once per build
  (`pubchem_drugage` in the log; about 1 300 lookups, 17 minutes on 22.10): 727 to a parent, 28 kept by
  their metal, 21 with no parent, 270 to nothing (combinations, extracts, and names PubChem does not
  carry: "lead acetate", only "lead(II) acetate"; "butylated hydroxytoluene"); those match by name only.
  GenAge model genes are matched by symbol: an ortholog named otherwise (the worm let-363 for
  MTOR) is not found. HAGR's terms ask for advance contact before many queries: the clients query the
  site only to fetch a build.
- Open Genes evidence rows without a DOI or PMID are counted (`rows_without_study_id`), not listed.
- ChEMBL: a name search returns, after the named compound, unnamed analogues that share the word in
  their synonyms (rapamycin: 39 compounds); the first three are read, each with three counts. GEO
  returns the newest series first; a query past twenty series is narrowed (`[ORGN]`, `[DESC]`), not
  read further. A series without `pmids` has no paper GEO knows of.
