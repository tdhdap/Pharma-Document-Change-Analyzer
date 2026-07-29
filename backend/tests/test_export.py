import csv
import io

from app.models import Change, ComparisonResult, build_summary
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
