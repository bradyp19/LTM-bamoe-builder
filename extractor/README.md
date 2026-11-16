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
written. Validation runs in stages (supplement shape/citations, source facts
and flow, structure, then rulings/scenarios); a failed stage reports its
problems before stopping.

## What comes from where

| Spec content | Source |
|---|---|
| Process name, id, package | Process model heading (`design.process` may override id/package) |
| Variables, types, `required`, per-row evidence | Process Variables tables |
| Models and fields | Record Type field tables, in document order |
| Nodes and flows of a text diagram | Parsed from the fenced diagram |
| Nodes and flows of an image-only flow | `figureTranscriptions` in the supplement, pinned to the image's sha256 |
| `<flag> = true/false` gateway conditions | Exact flow labels, optionally `Yes /` or `No /` prefixed; compound labels need a design ruling |
| User-task inputs | Transcription, else the interface's Rule Inputs that are process variables |
| Interface and evidence citations | Computed from paragraph anchors |
| Class names, extra type mappings, service bindings, task outputs, node notes | `design` in the supplement |
| Assumptions and test scenarios | Supplement, verbatim |

The supplement cannot override derived fields, rule inputs, declared node
types, built-in type mappings, or a derivable condition. Every key and value
shape is validated. Each `Dnn ¶a–b` must resolve to content paragraphs, and
cited notes/assumptions need supporting quotes. Quote presence is checked,
not semantic entailment; free prose still needs analyst review. Figure and
section references are reported as unchecked.

Register Project matches its hand-written spec except for model-field order:
the extractor preserves D05 document order.

## Transformations applied to text diagrams

Each one is added to the spec's assumptions as `T-n`:

- A node with several outgoing branches gets an exclusive gateway
  (`<node>Gateway`), because the spec carries conditions on gateway flows.
- Branches from one node to the same target become one flow. If that flow
  leaves a branching gateway it needs an explicit `design.conditions` ruling.
- A task with several incoming flows gets a converging exclusive gateway
  (`<node>Merge`) in front of it, because BAMOE rejects a task with more than
  one incoming flow. This applies to image-transcribed flows too.
- Null-flag routing, single guarded exits emitted without a condition, and
  design-supplied conditions/defaults are disclosed. Process attributes and
  variable columns the spec does not carry are reported as diagnostics.

## Ambiguity is an error

- A process model, record type or interface documented twice is an error when
  the spec uses that name (the first one is never silently kept).
- If the named process model is not found, headings that mention it but are not
  shaped `Process Model: <name>` are listed with their paragraph.

## Test scenarios

`tests` in the supplement are either single-task (`start` / `complete` /
`expect`) or multi-step: `start`, `steps: [{task, complete}]` and
`expect: {status, saves: {Store: n}, savedLists: {Store: size}, savedValues: {Store: value}}`
(`savedValues` is for a service task that saves a plain value such as a Boolean).
A process without user tasks uses `"steps": []`. Tasks, variables and record
fields are validated against the spec at extraction time.
Record-list elements, scalar types, task/store references, and expected store
counts are checked too. Unsupported literal types are refused instead of
emitting invalid Java.

## Modules

- `docset.py` — the document set keyed `D01..`, citations, image hashes
- `facts.py` — process models, record types and interfaces with anchors
- `flow_text.py` — text flow diagram parser
- `supplement.py` — loading, key/type validation and scenario shape checks
- `spec_build.py` — facts + supplement -> spec, with validation
