import os
import zipfile

from lxml import etree

from app import llm_classifier, pipeline
from app.extraction import extract_text

_DOCS = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "test-documents", "docx",
)
_V1 = os.path.join(_DOCS, "FullCoverageDemo_v1.docx")
_V2 = os.path.join(_DOCS, "FullCoverageDemo_v2.docx")

# The 22 change types a document pair can be authored to produce. Deliberately
# excluded: the six LLM-derived types, whose label is the model's choice and not
# reproducible across runs or model versions; and "unclassified" /
# "pending_llm_classification", which no document content can cause - the first
# comes from an LLM call failing, the second is an internal placeholder.
DETERMINISTIC_CHANGE_TYPES = {
    "numeric_change", "unit_change", "date_change",
    "section_added", "section_deleted", "section_heading_changed",
    "section_renumbered", "section_renumbered_cascade", "section_reordered",
    "moved_paragraph", "moved_table_content",
    "added_paragraph", "deleted_paragraph",
    "added_table_content", "deleted_table_content",
    "table_row_added", "table_row_deleted", "table_row_moved",
    "table_column_added", "table_column_deleted", "table_column_moved",
    "table_cell_merge_changed",
}


def _compare(monkeypatch):
    # Stubbed so the suite spends no API quota and stays deterministic. The stub
    # makes a few rows fall back to "unclassified"; that is an artifact of the stub,
    # not of the fixture, and nothing here asserts on it.
    monkeypatch.setattr(llm_classifier, "classify_changes_batch", lambda items, *a, **k: [])
    old = extract_text(_V1, "docx")
    new = extract_text(_V2, "docx")
    return pipeline.compare_documents(old, new, "FullCoverageDemo_v1.docx", "FullCoverageDemo_v2.docx")


def test_pair_produces_every_deterministic_change_type(monkeypatch):
    result = _compare(monkeypatch)

    produced = {c.change_type for c in result.changes}
    missing = DETERMINISTIC_CHANGE_TYPES - produced

    assert not missing, f"fixture no longer produces: {sorted(missing)}"


def test_each_table_structure_type_fires_exactly_once(monkeypatch):
    # Every table in the fixture changes in exactly ONE way. A count above one means
    # a table started doing two things - most likely a row edit large enough to drop
    # the row below the 0.85 match threshold, which turns it into a delete+add pair.
    result = _compare(monkeypatch)

    for change_type in (
        "table_row_added", "table_row_deleted", "table_row_moved",
        "table_column_added", "table_column_deleted", "table_column_moved",
        "table_cell_merge_changed",
    ):
        count = sum(1 for c in result.changes if c.change_type == change_type)
        assert count == 1, f"{change_type} fired {count} times, expected exactly 1"


def test_moved_section_still_reports_its_content_edit(monkeypatch):
    # The central false-negative guard: relocation must never hide an edit. The
    # Procedure section both moves and has its compression force changed.
    result = _compare(monkeypatch)

    assert any(c.change_type == "section_reordered" for c in result.changes)
    assert any("20 kN" in (c.new_text or "") for c in result.changes)


def test_cascading_and_deliberate_renumbering_are_distinguished(monkeypatch):
    # The one type no other document in the corpus produces. The insertion sits
    # above the cascade sections and the deletion below them, so the net shift is
    # exactly +1; Records (+2) exceeds it and stays deliberate.
    result = _compare(monkeypatch)

    cascaded = [c for c in result.changes if c.change_type == "section_renumbered_cascade"]
    deliberate = [c for c in result.changes if c.change_type == "section_renumbered"]

    assert cascaded, "no cascade - check the insertion is above and the deletion below"
    assert deliberate, "no deliberate renumber"


def test_structural_summary_counts_are_all_non_zero(monkeypatch):
    result = _compare(monkeypatch)
    summary = result.summary

    assert summary.sections_added > 0
    assert summary.sections_deleted > 0
    assert summary.sections_renamed > 0
    assert summary.sections_renumbered > 0
    assert summary.sections_cascaded > 0
    assert summary.sections_moved > 0


def test_text_boxes_anchor_to_different_sections():
    # Two boxes, not one: a single box would only prove a label exists, not that the
    # anchor varies with location.
    labels = [p.text for p in extract_text(_V1, "docx")
              if p.is_heading and p.text.startswith("Text Box")]

    assert len(labels) == 2
    anchors = {label.split("(", 1)[1] for label in labels}
    assert len(anchors) == 2, f"both boxes report the same anchor: {labels}"


def test_footnote_label_names_its_section_and_paragraph():
    labels = [p.text for p in extract_text(_V1, "docx")
              if p.is_heading and p.text.startswith("Footnote")]

    assert labels == ["Footnote 1 (5.0 Procedure, paragraph 1)"]


def test_anchors_follow_their_section_when_it_moves():
    # Procedure moves from 5.0 to 10.0, so anything anchored to it must say so.
    v1 = [p.text for p in extract_text(_V1, "docx") if p.is_heading and p.text.startswith("Footnote")]
    v2 = [p.text for p in extract_text(_V2, "docx") if p.is_heading and p.text.startswith("Footnote")]

    assert "5.0 Procedure" in v1[0]
    assert "10.0 Procedure" in v2[0]


def test_both_documents_keep_sectpr_last_in_the_body():
    # A body child after <w:sectPr> makes Word refuse to open the file while
    # python-docx parses it happily, so nothing else in the suite would notice.
    w = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    for path in (_V1, _V2):
        with zipfile.ZipFile(path) as archive:
            body = etree.fromstring(archive.read("word/document.xml")).find(w + "body")
        assert etree.QName(body[-1]).localname == "sectPr", f"{os.path.basename(path)}"


def test_comparing_a_document_with_itself_reports_nothing(monkeypatch):
    monkeypatch.setattr(llm_classifier, "classify_changes_batch", lambda items, *a, **k: [])
    paragraphs = extract_text(_V1, "docx")

    result = pipeline.compare_documents(paragraphs, extract_text(_V1, "docx"), "a", "b")

    assert result.changes == []
