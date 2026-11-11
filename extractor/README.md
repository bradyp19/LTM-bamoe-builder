# Extractor: reader output -> generator spec

Builds the spec JSON the generator consumes (`generator/specs/*.json`) from the
LTM documents plus a small analyst supplement.

```
cd extractor
PYTHONPATH=../reader ../.venv/bin/python -m ltm_extract --docs ../.. \
    --supplement supplements/allocations.json --out ../generator/specs/allocations.json
../.venv/bin/python -m pytest -q
```

Diagnostics go to stderr. If anything would have to be invented, no spec is
written and every problem is listed.

## What comes from where

| Spec content | Source |
|---|---|
| Process name, id, package | Process model heading (`design.process` may override id/package) |
| Variables, types, `required`, per-row evidence | Process Variables table |
| Models and fields | Record Type field tables, in document order |
| Nodes and flows of a text diagram | Parsed from the fenced diagram |
| Nodes and flows of an image-only flow | `figureTranscriptions` in the supplement, pinned to the image's sha256 |
| `<flag> = true/false` gateway conditions | Flow labels (a null flag counts as not true) |
| User-task inputs | Transcription, else the interface's Rule Inputs that are process variables |
| Interface and evidence citations | Computed from paragraph anchors |
| Class names, extra type mappings, service bindings, task outputs, node notes | `design` in the supplement |
| Assumptions and test scenarios | Supplement, verbatim |

The supplement cannot carry or override source facts. Every `Dnn ¶a–b` it
mentions must resolve to content paragraphs, and each `support` entry's quote
must appear in the paragraphs it cites.

## Transformations applied to text diagrams

Each one is added to the spec's assumptions as `T-n`:

- A node with several outgoing branches gets an exclusive gateway
  (`<node>Gateway`), because the spec carries conditions on gateway flows.
- Branches from one node to the same target become one flow without a condition.
- A task with several incoming flows gets a converging exclusive gateway
  (`<node>Merge`) in front of it, because BAMOE rejects a task with more than
  one incoming flow. This applies to image-transcribed flows too.

## Ambiguity is an error

- A process model, record type or interface documented twice is an error when
  the spec uses that name (the first one is never silently kept).
- If the named process model is not found, headings that mention it but are not
  shaped `Process Model: <name>` are listed with their paragraph.

## Test scenarios

`tests` in the supplement are either single-task (`start` / `complete` /
`expect`) or multi-step: `start`, `steps: [{task, complete}]` and
`expect: {status, saves: {Store: n}, savedLists: {Store: size}}`. Tasks,
variables and record fields are validated against the spec at extraction time.

## Modules

- `docset.py` — the document set keyed `D01..`, citations, image hashes
- `facts.py` — process models, record types and interfaces with anchors
- `flow_text.py` — text flow diagram parser
- `spec_build.py` — facts + supplement -> spec, with validation
