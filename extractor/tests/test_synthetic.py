"""End-to-end on a made-up application, so the extractor is not NSSOL-specific
and these tests run without the LTM originals."""

import hashlib

import pytest

from conftest import IMAGE
from ltm_extract import DocSet, ExtractionError, build_spec

IMAGE_BYTES = b"\x89PNG-acme-figure"

WORKFLOW = """# Workflow and Process Models

## Process Model: ACME Approve Order

| Attribute | Value |
|---|---|
| UUID | `0001` |

### Process Variables

| Variable | Type | Parameter | Required | Description |
|---|---|---|---|---|
| `approved` | Boolean | Yes | No | Reviewer decision |
| `order` | ACME Orders record | Yes | **Yes** | The order under review |

### Process Flow

```
START
  │
  ▼
[User Task: Review Order]
  │   Interface: ACME_FRM_Review
  │
  ├──[approved = true]──▶
  │     │
  │     ▼
  │   [Service Task: Save Order]
  │     │
  │     ▼
  │    END
  │
  └──[approved = false]──▶ END
```

---

## Process Model: ACME Ship Order

### Process Variables

| Variable | Type | Parameter | Required | Description |
|---|---|---|---|---|
| `order` | ACME Orders record | Yes | No | The order to ship |

### Process Flow
""".split("\n") + [IMAGE, "Figure 7. BPMN flow for ACME Ship Order."]

INTERFACES = """# UI Interfaces

### 1. ACME_FRM_Review
**Type:** Form

#### Rule Inputs
| Input | Type | Description |
|---|---|---|
| `ri!order` | ACME Orders | Order to review |
| `ri!approved` | Boolean | Decision |
| `ri!hint` | Text | Not a process variable |

---
""".split("\n")

DATA = """# Data Model

## Record Type: ACME Orders

**Primary Key:** `orderId`

### Fields

| Field Name | Data Type | Nullable | Description |
|---|---|---|---|
| `orderId` | Integer | No | Key |
| `total` | Decimal | Yes | Order total |
| `placedOn` | DateTime | Yes | Timestamp |
""".split("\n")


@pytest.fixture
def docset(make_docx):
    make_docx("03_Workflow.docx", WORKFLOW, image_bytes=IMAGE_BYTES)
    make_docx("04_Interfaces.docx", INTERFACES)
    f = make_docx("05_Data.docx", DATA)
    return DocSet.load(f.parent)


def approve_supplement():
    return {
        "process": "ACME Approve Order",
        "design": {
            "typeMap": {"DateTime": "java.time.OffsetDateTime"},
            "nodes": {
                "reviewOrder": {"outputs": ["approved", "order"]},
                "saveOrder": {"service": {"class": "acme.service.OrderStore", "operation": "save"},
                              "inputs": ["order"], "outputs": ["order"]},
            },
        },
    }


def ship_supplement(sha256):
    return {
        "process": "ACME Ship Order",
        "figureTranscriptions": [{
            "cite": "D03 ¶47", "image": "media/image1.png", "sha256": sha256,
            "inspected": "2026-01-02",
            "nodes": [
                {"id": "start", "type": "start", "name": "Start"},
                {"id": "ship", "type": "serviceTask", "name": "Ship"},
                {"id": "done", "type": "end", "name": "Shipped"},
            ],
            "flows": [{"from": "start", "to": "ship"}, {"from": "ship", "to": "done"}],
        }],
        "design": {
            "typeMap": {"DateTime": "java.time.OffsetDateTime"},
            "nodes": {"ship": {"service": {"class": "acme.service.Shipper", "operation": "ship"},
                               "inputs": ["order"], "outputs": ["order"]}},
        },
    }


class TestTextFlow:
    def test_spec(self, docset):
        spec = build_spec(docset, approve_supplement()).spec
        assert spec["process"] == {
            "id": "approveOrder", "name": "ACME Approve Order", "packageName": "acme",
            "evidence": "D03 ¶17–33, D03 ¶10–13, D04 ¶2–10"}
        assert spec["variables"] == [
            {"name": "approved", "type": "java.lang.Boolean", "evidence": "D03 ¶12"},
            {"name": "order", "type": "acme.model.Orders", "required": True,
             "evidence": "D03 ¶13"},
        ]
        assert spec["models"] == {"Orders": {
            "fields": [{"name": "orderId", "type": "Integer"},
                       {"name": "total", "type": "java.math.BigDecimal"},
                       {"name": "placedOn", "type": "java.time.OffsetDateTime"}],
            "evidence": "D05 ¶8–12"}}
        assert [(n["id"], n["type"]) for n in spec["nodes"]] == [
            ("start", "start"), ("reviewOrder", "userTask"),
            ("reviewOrderGateway", "xor"), ("saveOrder", "serviceTask"),
            ("end1", "end"), ("end2", "end")]
        assert spec["flows"] == [
            {"from": "start", "to": "reviewOrder"},
            {"from": "reviewOrder", "to": "reviewOrderGateway"},
            {"from": "reviewOrderGateway", "to": "saveOrder", "name": "approved = true",
             "condition": "return approved != null && approved;"},
            {"from": "saveOrder", "to": "end1"},
            {"from": "reviewOrderGateway", "to": "end2", "name": "approved = false",
             "condition": "return approved == null || !approved;"},
        ]
        assert spec["tests"] == []

    def test_rule_inputs_that_are_not_process_variables_are_not_task_inputs(self, docset):
        result = build_spec(docset, approve_supplement())
        review = next(n for n in result.spec["nodes"] if n["id"] == "reviewOrder")
        assert review["inputs"] == ["order", "approved"]
        assert "rule-input-not-a-variable" in [d.code for d in result.diagnostics]

    def test_unmapped_type_is_reported_with_its_anchor(self, docset):
        supplement = approve_supplement()
        supplement["design"]["typeMap"] = {}
        with pytest.raises(ExtractionError, match=r"DateTime.*D05 ¶12"):
            build_spec(docset, supplement)

    def test_all_problems_are_reported_together(self, docset):
        supplement = approve_supplement()
        supplement["design"]["typeMap"] = {}
        del supplement["design"]["nodes"]["saveOrder"]["service"]
        with pytest.raises(ExtractionError) as exc:
            build_spec(docset, supplement)
        assert len(exc.value.problems) == 2


class TestImageFlow:
    def test_transcribed_flow(self, docset):
        sha = hashlib.sha256(IMAGE_BYTES).hexdigest()
        result = build_spec(docset, ship_supplement(sha))
        assert result.spec["process"]["id"] == "shipOrder"
        assert result.spec["process"]["evidence"] == (
            "D03 Figure 7 (image-inspected 2026-01-02), D03 ¶41–43")
        assert [n["id"] for n in result.spec["nodes"]] == ["start", "ship", "done"]

    def test_stale_transcription(self, docset):
        with pytest.raises(ExtractionError, match="sha256"):
            build_spec(docset, ship_supplement("ab" * 32))

    def test_missing_transcription(self, docset):
        supplement = ship_supplement("")
        supplement["figureTranscriptions"] = []
        with pytest.raises(ExtractionError, match=r"image-only.*D03 ¶47"):
            build_spec(docset, supplement)


class TestDocSet:
    def test_load_ignores_non_ltm_files(self, docset, tmp_path):
        (tmp_path / "notes.docx").write_bytes(b"not a document")
        (tmp_path / "03_Workflow.pdf").write_bytes(b"review copy")
        assert list(DocSet.load(tmp_path).documents) == ["D03", "D04", "D05"]

    def test_empty_directory_is_an_error(self, tmp_path):
        with pytest.raises(ExtractionError, match="no LTM documents"):
            DocSet.load(tmp_path / "missing")
