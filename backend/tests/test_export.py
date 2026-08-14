import csv
import io

from app.models import Change, ComparisonResult, build_summary, TableCoordinate
from app.export import to_json, to_csv


def make_comparison() -> ComparisonResult:
    changes = [
        Change(
            change_id="ch-1", section="Acceptance Criteria", change_type="numeric_change",
            old_text="Assay: 95.0% to 105.0%", new_text="Assay: 98.0% to 102.0%",
            old_page=4, new_page=5, confidence=0.97, ai_risk_level="High",
            reason="The approved assay acceptance range was narrowed.",
        ),
    ]
    return ComparisonResult(
        comparison_id="CMP-001", old_document="SOP_v1.pdf", new_document="SOP_v2.pdf",
        summary=build_summary(changes), changes=changes,
    )


def test_to_json_matches_expected_schema_shape():
    result = to_json(make_comparison())

    assert result["comparison_id"] == "CMP-001"
    assert result["old_document"] == "SOP_v1.pdf"
    assert result["new_document"] == "SOP_v2.pdf"
    assert result["summary"]["total_changes"] == 1
    assert result["summary"]["high_risk"] == 1

    change = result["changes"][0]
    assert change["change_id"] == "ch-1"
    assert change["change_type"] == "numeric_change"
    assert change["old_text"] == "Assay: 95.0% to 105.0%"
    assert change["new_text"] == "Assay: 98.0% to 102.0%"
    assert change["risk_level"] == "High"
    assert change["old_page"] == 4
    assert change["new_page"] == 5
    assert change["confidence"] == 0.97


def test_reviewer_override_takes_priority_in_risk_level():
    comparison = make_comparison()
    comparison.changes[0].reviewer_risk_level = "Low"
    result = to_json(comparison)
    assert result["changes"][0]["risk_level"] == "Low"
    assert result["changes"][0]["ai_risk_level"] == "High"


def test_to_csv_has_header_and_one_row_per_change():
    csv_text = to_csv(make_comparison())
    rows = list(csv.reader(io.StringIO(csv_text)))
    assert rows[0][:3] == ["change_id", "section", "change_type"]
    assert len(rows) == 2
    assert rows[1][0] == "ch-1"


def test_to_json_includes_source_field():
    comparison = make_comparison()
    comparison.changes[0].source = "Table"
    result = to_json(comparison)
    assert result["changes"][0]["source"] == "Table"


def test_to_json_defaults_source_to_body():
    result = to_json(make_comparison())
    assert result["changes"][0]["source"] == "Body"


def test_to_csv_includes_source_column():
    comparison = make_comparison()
    comparison.changes[0].source = "Table"
    csv_text = to_csv(comparison)
    rows = list(csv.reader(io.StringIO(csv_text)))
    assert "source" in rows[0]
    source_index = rows[0].index("source")
    assert rows[1][source_index] == "Table"


def test_to_csv_correctly_quotes_embedded_newlines():
    comparison = make_comparison()
    comparison.changes[0].new_text = "Heading\nParagraph one.\nParagraph two."
    csv_text = to_csv(comparison)
    rows = list(csv.reader(io.StringIO(csv_text)))
    # Header + 1 data row - embedded newlines inside a quoted field must not be
    # mistaken for row boundaries by a proper CSV reader.
    assert len(rows) == 2
    new_text_index = rows[0].index("new_text")
    assert rows[1][new_text_index] == "Heading\nParagraph one.\nParagraph two."


def test_to_json_includes_table_positions_when_present():
    comparison = make_comparison()
    comparison.changes[0].old_table_position = TableCoordinate(table_id=0, row=1, col=1)
    comparison.changes[0].new_table_position = TableCoordinate(table_id=0, row=1, col=1)
    result = to_json(comparison)
    change = result["changes"][0]
    assert change["old_table_position"] == {"table_id": 0, "row": 1, "col": 1}
    assert change["new_table_position"] == {"table_id": 0, "row": 1, "col": 1}


def test_to_json_table_positions_default_to_null():
    result = to_json(make_comparison())
    change = result["changes"][0]
    assert change["old_table_position"] is None
    assert change["new_table_position"] is None


def test_to_csv_table_cell_column_shows_position_when_identical():
    comparison = make_comparison()
    comparison.changes[0].old_table_position = TableCoordinate(table_id=0, row=1, col=1)
    comparison.changes[0].new_table_position = TableCoordinate(table_id=0, row=1, col=1)
    csv_text = to_csv(comparison)
    rows = list(csv.reader(io.StringIO(csv_text)))
    table_cell_index = rows[0].index("table_cell")
    assert rows[1][table_cell_index] == "Table 0, Row 1, Col 1"


def test_to_csv_table_cell_column_shows_arrow_when_positions_differ():
    comparison = make_comparison()
    comparison.changes[0].old_table_position = TableCoordinate(table_id=0, row=1, col=0)
    comparison.changes[0].new_table_position = TableCoordinate(table_id=1, row=0, col=0)
    csv_text = to_csv(comparison)
    rows = list(csv.reader(io.StringIO(csv_text)))
    table_cell_index = rows[0].index("table_cell")
    assert rows[1][table_cell_index] == "Table 0, Row 1, Col 0 -> Table 1, Row 0, Col 0"


def test_to_csv_table_cell_column_shows_only_populated_side():
    comparison = make_comparison()
    comparison.changes[0].old_table_position = None
    comparison.changes[0].new_table_position = TableCoordinate(table_id=1, row=3, col=0)
    csv_text = to_csv(comparison)
    rows = list(csv.reader(io.StringIO(csv_text)))
    table_cell_index = rows[0].index("table_cell")
    assert rows[1][table_cell_index] == "Table 1, Row 3, Col 0"


def test_to_csv_table_cell_column_is_empty_for_body_changes():
    csv_text = to_csv(make_comparison())
    rows = list(csv.reader(io.StringIO(csv_text)))
    table_cell_index = rows[0].index("table_cell")
    assert rows[1][table_cell_index] == ""
