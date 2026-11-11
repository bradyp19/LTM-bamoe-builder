# Register Project — hand-built BAMOE 9.6 reference

Reference implementation of the LTM-documented **NSSOL Register Project** process.
This is the target output the document-to-BAMOE generator must reproduce.

- BAMOE `9.6.0-ibm-0004`, Quarkus + Maven accelerator skeleton (pinned branch `9.6.0-ibm-0004-workflows-quarkus-maven`)
- Java 21 required: `JAVA_HOME=$(/usr/libexec/java_home -v 21)`
- Build & test: `mvn -Pdevelopment -Dquarkus.test.profile=dev clean test`
- Dev run (H2 in-memory, no external services): `mvn -Pdevelopment quarkus:dev`

## What is documented vs assumed

| Element | Status |
|---|---|
| Flow (start → form → Cancel? → save/cancelled end) | Documented — D03 Figure 1 (image-inspected 2026-11-09) |
| Variables `cancel`, `isUpdate`, `projectRegistration` | Documented — D03 ¶24–28 |
| Form interface + fields | Documented — D04 ¶24–79 |
| Task assignee | **ASSUMPTION: none set** — unassigned draft task (SR-3, open) |
| Confirmation step | **CONFLICT C1 open** — model follows Figure 1 (no confirmation node); D04 ¶353–358 describes one |
| Status required | **CONFLICT C2 open** — no enforcement coded |
| `ProjectStore` save service | **TEST DOUBLE** — write semantics unspecified (SR-4) |
| Start permissions | **CONFLICT C3 open** — dev profile has auth disabled |
| `cancel=null` gateway behaviour | **ASSUMPTION** — treated as not-cancelled (SR-5) |

## Files

- `src/main/resources/RegisterProject.bpmn` — process model (opens in BAMOE Developer Tools)
- `src/main/java/nssol/model/ProjectRegistration.java` — NSSOL Projects fields (D05 ¶48–76)
- `src/main/java/nssol/service/ProjectStore.java` — demo save service (explicit test double)
- `src/test/java/nssol/RegisterProjectProcessTest.java` — create / update / cancel paths

## Lessons for the generator (verified on 9.6.0)

- Java service tasks bind the single input as `Parameter` / output as `Result`; the implementation class must be a CDI bean (`@ApplicationScoped`).
- Process-variable classes need `is<Field>` getters for `is*` fields (e.g. `isIsActive()`).
- `%dev` profile (H2, OIDC off) is required for tests: `-Pdevelopment -Dquarkus.test.profile=dev`.
- Gateway conditions use `language="http://www.java.com/java"` with `return` statements.
