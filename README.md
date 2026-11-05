# ohf-extractor

Build and check a source-linked [Open Hypothesis Format (OHF)](https://github.com/hypothesis-arena/open-hypothesis-format)
card from one published biology article. The author zone keeps the authors' located words; the
added zone records the converter's attributed reading and typed gaps. A separate entailment pass
checks each added value against its cited passage and records the result in a ledger.

## Project stage

Work in progress. Software checks cover schema, quotations, source bindings, hashes, references and
ledger integrity. Technical cards and successful checks are not scientific acceptance.

The [development native profile](references/native-renderer-profile.md) uses synthetic validation;
its recipe does not establish scientific acceptance.

## Quick start

Use Python 3.12, Git and a POSIX shell. Start from a clean extractor checkout. Setup fetches the pinned
Standard and installs Python dependencies; the smoke test then runs offline.

```sh
set -eu
git clone --no-checkout https://github.com/hypothesis-arena/open-hypothesis-format.git open-hypothesis-format
git -C open-hypothesis-format checkout --detach bf1f582f977c2ac65e5537ebd9f1b1b19ae328d3
test "$(git -C open-hypothesis-format rev-parse HEAD)" = bf1f582f977c2ac65e5537ebd9f1b1b19ae328d3
python3.12 -m venv .venv
.venv/bin/python -m pip install --index-url https://pypi.org/simple -r requirements.txt
. ./examples/config/offline.env.example
.venv/bin/python -m pytest -q -s scripts/tests/test_quickstart.py::test_offline_conversion_and_validation scripts/tests/test_readme_config_examples.py
```

The smoke builds an invented JATS card, supplies explicitly fake checker results, and validates its
schema and content hash. It blocks network/DNS and external process calls during conversion and
validation, and reports `network_attempts=0; model_calls=0`. Its source-verification record is also
invented. This is the offline reproduction check, not an article reading or a model entailment run.

The two [configuration examples](examples/config/) are loaded by the existing shell/environment
interface; they introduce no configuration loader. They contain no credentials. For a real conversion:

```sh
cp examples/config/article.env.example .env
# Edit .env: set OHF_MODEL to the exact model identifier used by the reading executor.
. ./.env
```

The example leaves the model empty, so a real builder refuses until it is supplied. Keep credentials
in the executor's own configuration. `.env` and the private `work/` directory are ignored by Git.

Follow [SKILL.md](SKILL.md) and [the field guide](references/fields.md) to write the article's builder.
It must establish quotation rights from the source and supply an explicit complete budget counter;
the kit does not infer or default model/HTTP totals. Use a private work directory with no other writers.
After building `work/article/card.json` beside its retained sources:

```sh
.venv/bin/python -I scripts/entailment.py input work/article/card.json work/article work/article/in.json
# Run the separate checker on in.json, preserving its response as work/article/out.json.
.venv/bin/python -I scripts/entailment.py merge work/article/card.json work/article work/article/in.json work/article/out.json
.venv/bin/python -I scripts/check_card.py work/article/card.json work/article
```

The merge binds verdicts and notes to the checked values and passages. It retains history and shows
the worst applicable verdict; a later check does not erase an earlier one. `partial` keeps its note.
The final check prints errors and exits non-zero when a required condition fails.

## Components

| Component | Responsibility | Source |
|---|---|---|
| Arena | Cards, dossiers, pairwise comparisons, ratings and the site | [Arena](https://github.com/hypothesis-arena/arena) |
| Open Hypothesis Format (OHF) | Card fields, provenance and validation rules | [OHF](https://github.com/hypothesis-arena/open-hypothesis-format) |
| Extractor | Article-to-card construction and source/ledger checks | This repository: [SKILL.md](SKILL.md), [`scripts/`](scripts/) |
| Judge | Prompt preparation, response validation and evidence receipts | [Judge protocol](https://github.com/hypothesis-arena/arena/blob/main/judge/README-v4.md) |
| Criterion | The question and four aspects examined before one final choice | [Criterion](https://github.com/hypothesis-arena/arena/blob/main/judge/criterion@3.md) |
| Runner | Executes an explicitly prepared comparison and records its lifecycle | [Runner](https://github.com/hypothesis-arena/arena/tree/main/tournament), [judging reference](https://github.com/hypothesis-arena/arena/blob/main/docs/judging.md) |

The extractor produces and checks the card used by the other components. It does not rank hypotheses
or execute comparisons. The [conversion guide](https://github.com/hypothesis-arena/arena/blob/main/docs/converter.md)
describes how a card enters Arena's workflow.

## Reproduce the checks

Check that both example files load without building a card:

```sh
.venv/bin/python -m pytest -q scripts/tests/test_readme_config_examples.py
```

For the complete suite on the quick-start primary, also prepare its pinned research-test companion:

```sh
set -eu
git clone --no-checkout https://github.com/hypothesis-arena/open-hypothesis-format.git standard-research
git -C standard-research checkout --detach 0b6f5ef1003f696220d8bb0b8316260825e4a10c
test "$(git -C standard-research rev-parse HEAD)" = 0b6f5ef1003f696220d8bb0b8316260825e4a10c
export OHF_TEST_PRIMARY_14="$OHF_REPO"
export OHF_RESEARCH_STANDARD="$PWD/standard-research"
.venv/bin/python -m pytest -q scripts/tests
git rev-parse HEAD
```

Record the extractor commit, Standard commit and test output when reporting a result. The
[CI source inventory](.forgejo/standard-test-matrix.json) and [workflow](.forgejo/workflows/check.yml)
name every active primary and companion. CI runs the complete general suite for each active primary;
the separate bounded native-profile job adds synthetic checks.

Pytest reports optional integration skips separately. In particular, evidence export needs an
externally supplied pinned scrubber; without it the actual scrubber/export integration is skipped.
Those skips are not an export test pass.

A card's `added.by.converter_hash` binds the converter rules. On the exact extractor checkout used
for that card, reproduce it with:

```sh
.venv/bin/python -I -c "import sys; sys.path.insert(0, 'scripts'); import ohfkit; print(ohfkit.rules_hash())"
```

The hash uses relative paths and file bytes, not the machine's checkout path.

## Licence and contributions

Code is licensed under [MIT](LICENSE). Article text and other third-party material retain their
source licences; the code licence does not grant quotation rights. The extraction rules are in
[references/rules.md](references/rules.md).

Contributions: contribute@hypothesisarena.com. Security reports: security@hypothesisarena.com.

The files under `scripts/tests/fixtures-cc-by-sa-3.0/` contain ChEMBL data and derivatives licensed under CC-BY-SA 3.0. Their LICENSE and NOTICE apply to that directory. The extractor code is MIT.
