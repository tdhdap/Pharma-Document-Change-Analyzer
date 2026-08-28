import csv
import io

from app.models import ComparisonResult


def _effective_risk(change) -> str:
    return change.reviewer_risk_level or change.ai_risk_level


def _table_position_to_dict(position):
    if position is None:
        return None
    return {"table_id": position.table_id, "row": position.row, "col": position.col}


def to_json(comparison: ComparisonResult) -> dict:
    return {
        "comparison_id": comparison.comparison_id,
        "old_document": comparison.old_document,
        "new_document": comparison.new_document,
        "summary": {
            "total_changes": comparison.summary.total_changes,
            "high_risk": comparison.summary.high_risk,
            "medium_risk": comparison.summary.medium_risk,
            "low_risk": comparison.summary.low_risk,
            "informational": comparison.summary.informational,
            "sections_added": comparison.summary.sections_added,
            "sections_deleted": comparison.summary.sections_deleted,
            "sections_renamed": comparison.summary.sections_renamed,
            "sections_renumbered": comparison.summary.sections_renumbered,
            "sections_cascaded": comparison.summary.sections_cascaded,
            "sections_moved": comparison.summary.sections_moved,
        },
        "changes": [
            {
                "change_id": c.change_id,
                "section": c.section,
                "change_type": c.change_type,
                "source": c.source,
                "old_text": c.old_text,
                "new_text": c.new_text,
                "risk_level": _effective_risk(c),
                "ai_risk_level": c.ai_risk_level,
                "reviewer_risk_level": c.reviewer_risk_level,
                "reason": c.reason,
                "old_page": c.old_page,
                "new_page": c.new_page,
                "confidence": c.confidence,
                "reviewer_comment": c.reviewer_comment,
                "accepted": c.accepted,
                "old_table_position": _table_position_to_dict(c.old_table_position),
                "new_table_position": _table_position_to_dict(c.new_table_position),
            }
            for c in comparison.changes
        ],
    }


def _format_table_cell(old_position, new_position) -> str:
    if old_position is None and new_position is None:
        return ""
    if old_position is not None and new_position is not None and old_position == new_position:
        return f"Table {old_position.table_id}, Row {old_position.row}, Col {old_position.col}"
    if old_position is not None and new_position is not None:
        return (
            f"Table {old_position.table_id}, Row {old_position.row}, Col {old_position.col} -> "
            f"Table {new_position.table_id}, Row {new_position.row}, Col {new_position.col}"
        )
    position = new_position or old_position
    return f"Table {position.table_id}, Row {position.row}, Col {position.col}"


def to_csv(comparison: ComparisonResult) -> str:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "change_id", "section", "change_type", "source", "old_text", "new_text",
        "risk_level", "reason", "old_page", "new_page", "confidence",
        "reviewer_comment", "accepted", "table_cell",
    ])
    for c in comparison.changes:
        writer.writerow([
            c.change_id, c.section, c.change_type, c.source, c.old_text, c.new_text,
            _effective_risk(c), c.reason, c.old_page, c.new_page,
            c.confidence, c.reviewer_comment or "", c.accepted,
            _format_table_cell(c.old_table_position, c.new_table_position),
        ])
    return output.getvalue()
