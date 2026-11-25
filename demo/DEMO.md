# Demo: documents in, one running BAMOE application out

Prerequisites: Java 21, Maven 3.9.11+ with the BAMOE 9.6 repository
(`quay.io/bamoe/maven-repository:9.6.0-ibm-0004` on `127.0.0.1:9999`), Python 3.11+.
`--out` must not exist yet.

## 1. NSSOL from its documents

```
python3 tools/run_ltm_demo.py --docs <folder with 01_..07_*.docx> --out /tmp/nssol-run
```

Expect `NSSOL POC: 3 processes ...; build pass, 8 tests, 0 failed`. The manifest is at
`/tmp/nssol-run/manifest.json`, and each process's per-step audit is in
`/tmp/nssol-run/projects/<artifact>/logs/`.

## 2. A different application, same command

ACME Expenses is a made-up application with two processes (Submit Expense Claim,
Review Expense Claim) sharing one record type. Its documents are the Markdown files in
`demo/acme-expenses/docs/`, built into DOCX files in the LTM layout. Nothing in
the generator or extractor is specific to NSSOL.

```
python3 demo/acme-expenses/make_docs.py /tmp/acme-docs
python3 tools/run_ltm_demo.py --docs /tmp/acme-docs \
    --supplements demo/acme-expenses/supplements --out /tmp/acme-run
```

Expect `ACME Expenses: 2 processes ...; build pass, 4 tests, 0 failed`.

What came from where:

- **From the documents:** variables, the record and its fields, the flows, and the form inputs.
- **From the analyst supplement** (`demo/acme-expenses/supplements/`): the
  application name (quoted from D01), the task outputs, the service bindings and the test
  scenarios. Each of these is backed by a quote from the documents.

## 3. Run the generated webpage

```
cd /tmp/acme-run/projects/acme-expenses
mvn -Pdevelopment -Dquarkus.profile=dev -DskipTests clean package
java -Dquarkus.profile=dev -Dquarkus.http.host=127.0.0.1 -jar target/quarkus-app/quarkus-run.jar
```

Open http://localhost:8080/ui/, start a process, complete its task in the inbox, and
check that every step's audit check shows OK. Use the packaged jar rather than
`mvn quarkus:dev`, which cannot handle processes with list variables.

## 4. It refuses instead of guessing

```
demo/refusal_demo.sh
```

Each case breaks one thing in a copy of the ACME supplements: a missing service
binding, an application name the documents never state, a quote that is not in the
cited paragraph, and a process name that is not documented. Each run stops with
"No project written" and names the problem and the paragraph it concerns.

## What a new application needs

- **Documents in the LTM layout:** `NN_*.docx` files with `Process Model: X` and
  `Record Type: X` headings, `Process Variables` and field tables, numbered interface
  headings with `**Type:**`, and `├─▶` text flows. A flow that is only an image needs a
  transcription in the supplement, pinned to the image's sha256.
- **One supplement per process:** the application name, task outputs, service
  bindings, any unclear rules, and test scenarios.
- **Supported flow elements:** start, end, user task, service task and exclusive
  gateway. A parallel gateway, timer, subprocess or script task is refused.
- **Values a scenario can set:** Boolean, Integer and String only.
