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


class TestDuplicateNames:
    """A name documented twice must be reported when the spec depends on it,
    never resolved silently by whichever heading is read last."""

    def test_duplicate_record_type_used_by_the_process_is_an_error(self, make_docx, docset):
        make_docx("06_More_Data.docx", DATA)
        ds = DocSet.load(make_docx("06_More_Data.docx", DATA).parent)
        with pytest.raises(ExtractionError,
                           match=r"record type 'ACME Orders' is documented more than once "
                                 r"\(D05 ¶\d+–\d+ and D06 ¶\d+–\d+\)"):
            build_spec(ds, approve_supplement())

    def test_duplicate_interface_used_by_the_flow_is_an_error(self, make_docx, docset):
        make_docx("06_More_Interfaces.docx", INTERFACES)
        ds = DocSet.load(make_docx("06_More_Interfaces.docx", INTERFACES).parent)
        with pytest.raises(ExtractionError,
                           match="interface 'ACME_FRM_Review' is documented more than once"):
            build_spec(ds, approve_supplement())

    def test_duplicate_process_model_is_an_error(self, make_docx, docset):
        make_docx("06_More_Workflow.docx", WORKFLOW, image_bytes=IMAGE_BYTES)
        ds = DocSet.load(make_docx("06_More_Workflow.docx", WORKFLOW, image_bytes=IMAGE_BYTES).parent)
        with pytest.raises(ExtractionError,
                           match="process model 'ACME Approve Order' is documented more than once"):
            build_spec(ds, approve_supplement())

    def test_duplicate_name_the_spec_does_not_use_is_ignored(self, make_docx, docset):
        extra = ["# Data Model", "", "## Record Type: ACME Unused", "",
                 "### Fields", "", "| Field Name | Data Type | Nullable | Description |",
                 "|---|---|---|---|", "| `a` | Integer | No | x |"]
        make_docx("06_Extra_A.docx", extra)
        ds = DocSet.load(make_docx("07_Extra_B.docx", extra).parent)
        assert build_spec(ds, approve_supplement()).spec["process"]["id"] == "approveOrder"


class TestHeadingNearMisses:
    @pytest.mark.parametrize("heading", [
        "UI Forms", "UI Form Reference", "Forms", "UI_Interfaces", "UI_Forms",
        "Business Screens"])
    def test_ui_form_heading_keeps_documented_task_inputs(self, make_docx, docset, heading):
        lines = [f"# {heading}"] + INTERFACES[1:]
        f = make_docx("04_Interfaces.docx", lines)
        result = build_spec(DocSet.load(f.parent), approve_supplement())
        task = next(n for n in result.spec["nodes"] if n["id"] == "reviewOrder")
        assert task["inputs"] == ["order", "approved"]
        assert "Inputs: rule inputs at D04 ¶6–10." in task["doc"]
        assert not any(d.code == "interface-not-found" for d in result.diagnostics)

    def test_unrelated_heading_is_not_a_form_scope(self, make_docx):
        from ltm_extract.facts import interfaces

        lines = ["# Transformations"] + [line for line in INTERFACES[1:]
                                       if not line.startswith("**Type:**")]
        f = make_docx("04_Interfaces.docx", lines)
        assert interfaces(DocSet.load(f.parent)) == {}

    def test_explicit_non_interface_type_is_not_mistaken_for_a_form(self, make_docx):
        from ltm_extract.facts import interfaces

        lines = [line.replace("**Type:** Form", "**Type:** Expression Rule")
                 for line in INTERFACES]
        f = make_docx("04_Interfaces.docx", lines)
        assert interfaces(DocSet.load(f.parent)) == {}

    def test_untyped_interface_falls_back_to_normalized_scope(self, make_docx, docset):
        lines = ["# UI_Interfaces"] + [line for line in INTERFACES[1:]
                                      if not line.startswith("**Type:**")]
        f = make_docx("04_Interfaces.docx", lines)
        result = build_spec(DocSet.load(f.parent), approve_supplement())
        task = next(n for n in result.spec["nodes"] if n["id"] == "reviewOrder")
        assert task["inputs"] == ["order", "approved"]

    def test_missing_interface_never_silently_emits_an_inputless_task(self, make_docx, docset):
        lines = ["# Business Components"] + [line for line in INTERFACES[1:]
                                           if not line.startswith("**Type:**")]
        f = make_docx("04_Interfaces.docx", lines)
        with pytest.raises(ExtractionError,
                           match="reviewOrder: interface 'ACME_FRM_Review' is not documented"):
            build_spec(DocSet.load(f.parent), approve_supplement())

    def test_missing_process_points_at_headings_that_mention_it(self, make_docx):
        lines = ["# Workflow", "", "## Process: ACME Approve Order", "", "text"]
        ds = DocSet.load(make_docx("03_Workflow.docx", lines).parent)
        with pytest.raises(ExtractionError) as exc:
            build_spec(ds, approve_supplement())
        joined = " | ".join(exc.value.problems)
        assert "no process model 'ACME Approve Order'" in joined
        assert "D03 ¶2 has a heading 'Process: ACME Approve Order'" in joined
        assert "not shaped 'Process Model: <name>'" in joined

    def test_missing_process_with_no_similar_heading_adds_nothing(self, make_docx):
        ds = DocSet.load(make_docx("03_Workflow.docx", ["# Workflow", "", "text"]).parent)
        with pytest.raises(ExtractionError) as exc:
            build_spec(ds, approve_supplement())
        assert len(exc.value.problems) == 1


OVERVIEW = ["# Application Overview", "", "The ACME Orders application handles order approval and shipping."]


@pytest.fixture
def docset_with_overview(make_docx):
    make_docx("01_Overview.docx", OVERVIEW)
    make_docx("03_Workflow.docx", WORKFLOW, image_bytes=IMAGE_BYTES)
    make_docx("04_Interfaces.docx", INTERFACES)
    f = make_docx("05_Data.docx", DATA)
    return DocSet.load(f.parent)


def with_application(supplement, name="ACME Orders",
                     quote="The ACME Orders application handles order approval"):
    return dict(supplement, application={"name": name,
                                         "support": [{"cite": "D01 ¶2", "quote": quote}]})


class TestApplication:
    def test_name_and_evidence_from_the_quote(self, docset_with_overview):
        spec = build_spec(docset_with_overview, with_application(approve_supplement())).spec
        assert spec["application"] == {"name": "ACME Orders", "evidence": "D01 ¶2"}

    def test_without_application_is_a_diagnostic(self, docset_with_overview):
        result = build_spec(docset_with_overview, approve_supplement())
        assert "application" not in result.spec
        assert any(d.code == "no-application" for d in result.diagnostics)

    def test_quote_must_contain_the_name(self, docset_with_overview):
        sup = with_application(approve_supplement(), name="ACME Shop")
        with pytest.raises(ExtractionError, match="no supporting quote contains the name"):
            build_spec(docset_with_overview, sup)

    def test_part_of_a_word_is_not_the_name(self, docset_with_overview):
        sup = with_application(approve_supplement(), name="ME Orders")
        with pytest.raises(ExtractionError, match="no supporting quote contains the name"):
            build_spec(docset_with_overview, sup)

    @pytest.mark.parametrize("quote", ["The ACME Orders_Internal application handles",
                                       "The ACME Orders\uff12 application handles"])
    def test_longer_identifier_is_not_the_name(self, make_docx, quote):
        make_docx("01_Overview.docx", ["# Application Overview", "", quote + " orders."])
        make_docx("03_Workflow.docx", WORKFLOW, image_bytes=IMAGE_BYTES)
        make_docx("04_Interfaces.docx", INTERFACES)
        docset = DocSet.load(make_docx("05_Data.docx", DATA).parent)
        sup = with_application(approve_supplement(), quote=quote)
        with pytest.raises(ExtractionError, match="no supporting quote contains the name"):
            build_spec(docset, sup)

    def test_name_followed_by_japanese(self, make_docx):
        make_docx("01_Overview.docx", ["# 概要", "", "ACME Ordersは注文を承認するアプリケーションです。"])
        make_docx("03_Workflow.docx", WORKFLOW, image_bytes=IMAGE_BYTES)
        make_docx("04_Interfaces.docx", INTERFACES)
        docset = DocSet.load(make_docx("05_Data.docx", DATA).parent)
        sup = with_application(approve_supplement(), quote="ACME Ordersは注文を承認する")
        assert build_spec(docset, sup).spec["application"]["name"] == "ACME Orders"

    def test_quote_must_be_in_the_cited_paragraph(self, docset_with_overview):
        sup = with_application(approve_supplement(), quote="The ACME Orders application ships rockets")
        with pytest.raises(ExtractionError, match="does not contain the quoted support"):
            build_spec(docset_with_overview, sup)

    def test_support_is_required(self, docset_with_overview):
        sup = dict(approve_supplement(), application={"name": "ACME Orders"})
        with pytest.raises(ExtractionError, match="application.support"):
            build_spec(docset_with_overview, sup)


class TestOutOfScopeDocuments:
    @pytest.fixture
    def docset_without_interfaces(self, make_docx):
        make_docx("03_Workflow.docx", WORKFLOW, image_bytes=IMAGE_BYTES)
        return DocSet.load(make_docx("05_Data.docx", DATA).parent)

    def cites_d04(self):
        sup = approve_supplement()
        sup["assumptions"] = [{"id": "A1", "text": "The form saves the order (D04 ¶6).",
                               "support": [{"cite": "D04 ¶6", "quote": "anything"}]}]
        return sup

    def test_missing_document_is_refused_unless_out_of_scope(self, docset_without_interfaces):
        with pytest.raises(ExtractionError, match="no document D04"):
            build_spec(docset_without_interfaces, self.cites_d04())
        result = build_spec(docset_without_interfaces, self.cites_d04(), ["D04"])
        codes = [d.code for d in result.diagnostics]
        assert "out-of-scope-citation" in codes and "interface-not-supplied" in codes
        task = next(n for n in result.spec["nodes"] if n["id"] == "reviewOrder")
        assert task["inputs"] == []

    def test_supplied_document_is_still_checked(self, docset):
        with pytest.raises(ExtractionError, match="does not contain the quoted support"):
            build_spec(docset, self.cites_d04(), ["D04"])

    def test_renamed_interface_in_a_supplied_document_is_still_refused(self, make_docx, docset):
        lines = [line.replace("ACME_FRM_Review", "ACME_FRM_Renamed") for line in INTERFACES]
        f = make_docx("04_Interfaces.docx", lines)
        with pytest.raises(ExtractionError,
                           match="reviewOrder: interface 'ACME_FRM_Review' is not documented"):
            build_spec(DocSet.load(f.parent), approve_supplement(), ["D07"])

    def test_application_name_quoted_only_from_an_omitted_document_is_refused(self, docset):
        sup = dict(approve_supplement(), application={
            "name": "ACME Orders",
            "support": [{"cite": "D01 ¶2", "quote": "The ACME Orders application"}]})
        with pytest.raises(ExtractionError, match="no supporting quote contains the name"):
            build_spec(docset, sup, ["D01"])
