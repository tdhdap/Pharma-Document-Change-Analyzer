def filter_changes(
    changes: list[dict],
    risk: str | None,
    section: str | None,
    change_type: str | None,
) -> list[dict]:
    result = changes
    if risk:
        result = [c for c in result if (c.get("reviewer_risk_level") or c["ai_risk_level"]) == risk]
    if section:
        result = [c for c in result if c["section"] == section]
    if change_type:
        result = [c for c in result if c["change_type"] == change_type]
    return result
