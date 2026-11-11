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
- Nodes with several incoming flows are reported; no merge gateway is emitted.

## Modules

- `docset.py` — the document set keyed `D01..`, citations, image hashes
- `facts.py` — process models, record types and interfaces with anchors
- `flow_text.py` — text flow diagram parser
- `spec_build.py` — facts + supplement -> spec, with validation
