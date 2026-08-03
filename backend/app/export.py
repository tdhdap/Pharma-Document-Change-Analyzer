import csv
import io

from app.models import ComparisonResult


def _effective_risk(change) -> str:
    return change.reviewer_risk_level or change.ai_risk_level


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
            }
            for c in comparison.changes
        ],
    }


def to_csv(comparison: ComparisonResult) -> str:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "change_id", "section", "change_type", "source", "old_text", "new_text",
        "risk_level", "reason", "old_page", "new_page", "confidence",
        "reviewer_comment", "accepted",
    ])
    for c in comparison.changes:
        writer.writerow([
            c.change_id, c.section, c.change_type, c.source, c.old_text, c.new_text,
            _effective_risk(c), c.reason, c.old_page, c.new_page,
            c.confidence, c.reviewer_comment or "", c.accepted,
        ])
    return output.getvalue()
