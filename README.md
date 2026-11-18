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
.venv/bin/python -m pytest -q tools/tests
```

Extractor integration tests use `LTM_DOCS_DIR` (default: the parent directory of
this repository). Without the originals, those tests skip; synthetic tests
still run. Some existing reader integration tests require the originals at
`/Users/bpark/bamoe-appian`.

## Extract and generate

The processes of one application are generated into **one** BAMOE project:
one BPMN per process, the union of the models (a class used by several
processes must have the same fields and types in every spec), one test double
per service class and one test class per process. The runner does every step,
from the repository root, with the originals in `$LTM_DOCS_DIR`:

```sh
.venv/bin/python tools/run_ltm_demo.py --docs "$LTM_DOCS_DIR" --out "$(mktemp -d)/demo"
```

It extracts every supplement in `extractor/supplements/`, writes `specs/`,
`projects/<artifactId>/`, `logs/maven.log` and `manifest.json` (an
application-level build/test result plus one entry per process), runs Maven
once and fails if a source DOCX changed. `--skip-maven` generates only.
`--out` must be new or empty.

From Python, `ltm_gen.emit_application(specs, skeleton_dir, out_dir)` writes
the project. It refuses (`ApplicationError`, listing every problem, nothing
written) on duplicate process ids, different package names or applications,
conflicting model definitions or service signatures. **It deletes `out_dir`
first.** Use a new directory; never point it at a hand-edited project.

### Generated project

- `src/main/resources/<processId>.bpmn` for every process.
- `src/test/java/<package>/<ProcessId>ProcessTest.java`: the spec's scenarios.
  Every step runs in a unit of work; afterwards `StepAudit` reads the
  data-audit record (`/data-audit/q`) and fails the test if nothing was
  recorded, the step's node was not left, or a variable the step sent was not
  recorded with the value sent (e.g. a task output with no data mapping).
  At the end it checks the recorded status, the end event and which service
  tasks ran. The record of every step is written to `logs/<processId>-audit.json`.
- `src/main/resources/META-INF/resources/ui/`: a webpage at
  `http://localhost:8080/ui/` in dev mode. It is generated from the specs
  (`application.json`): start forms from each process's start variables, a
  task inbox across processes with forms from the user tasks' inputs and
  outputs, the spec's scenarios as prefills, and per instance the status, node
  history, variables and user-task states recorded by data-audit. After every
  start or completion it reads the record back and shows mismatches. It uses
  the generated REST resources (`/<processId>`, `/<processId>/<id>/tasks`,
  `/<processId>/<id>/<Task_Name>/<taskId>`) and is denied outside dev
  (`%prod` HTTP permission), since OIDC is not configured for it.

## BAMOE verification

Generated projects need Java 21, Maven and access to the pinned BAMOE
dependencies. From a generated project:

```sh
mvn -Pdevelopment -Dquarkus.test.profile=dev clean package
```

The development profile uses H2 and disables OIDC. A passing generated test
checks the proposed spec and test doubles; it does not establish Appian parity
or production readiness.
