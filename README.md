# LTM → BAMOE builder

Python tooling for an evidence-linked pipeline:

```
LTM DOCX documents → reader → extractor + analyst supplement → spec JSON
                                                           ↓
                                            generator → BAMOE project
```

The examples target BAMOE `9.6.0-ibm-0004` on Quarkus. Generated services are
explicit **test doubles**, not production persistence implementations.
The original LTM documents are not distributed in this repository.

## Layout

- `reader/` — read-only DOCX intake, paragraph anchors, sections and tables.
- `extractor/` — document facts, flow parsing and validated analyst supplements.
  See [the extractor guide](extractor/README.md).
- `generator/` — spec JSON → BPMN, Java models, service test doubles and
  multi-step process tests; `generator/specs/` holds the examples.
- `register-project/` — hand-built BAMOE reference and build skeleton.
- `register-project-generated/` — checked-in generated Register Project example.
- `docs/allocations-decisions.md` — open business decisions, not approvals.

Three examples are included: Register Project, Allocations and Update Language
Toggle. Specs retain unresolved assumptions and conflicts rather than presenting
them as approved requirements.

## Python tests

Python 3.10+ and `pytest` are required. Run each sibling package's tests from
that package directory:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install pytest
(cd reader && ../.venv/bin/python -m pytest -q)
(cd extractor && ../.venv/bin/python -m pytest -q)
(cd generator && ../.venv/bin/python -m pytest -q)
```

Extractor integration tests use `LTM_DOCS_DIR` (default: the parent directory of
this repository). Without the originals, those tests skip; synthetic tests
still run. Some existing reader integration tests require the originals at
`/Users/bpark/bamoe-appian`.

## Extract and generate

From the repository root, with originals in `$LTM_DOCS_DIR`:

```sh
export PYTHONPATH="$PWD/reader:$PWD/extractor:$PWD/generator"
OUT=$(mktemp -d)
.venv/bin/python -m ltm_extract --docs "$LTM_DOCS_DIR" \
  --supplement extractor/supplements/allocations.json --out "$OUT/spec.json"
.venv/bin/python - "$OUT" <<'PY'
import json
import sys
from pathlib import Path
from ltm_gen import emit_project

out = Path(sys.argv[1])
emit_project(json.loads((out / "spec.json").read_text()),
             Path("register-project"), out / "allocations-generated")
PY
```

**`emit_project` deletes its output directory first.** Use a new directory;
never point it at a hand-edited project.

## BAMOE verification

Generated projects need Java 21, Maven and access to the pinned BAMOE
dependencies. From a generated project:

```sh
mvn -Pdevelopment -Dquarkus.test.profile=dev clean test
```

The development profile uses H2 and disables OIDC. A passing generated test
checks the proposed spec and test doubles; it does not establish Appian parity
or production readiness.
