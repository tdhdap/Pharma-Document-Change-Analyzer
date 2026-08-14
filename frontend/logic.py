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


def build_change_update_payload(edited_row: dict, original_row: dict) -> dict:
    payload = {}
    for field in ("reviewer_risk_level", "reviewer_comment", "accepted"):
        if edited_row.get(field) != original_row.get(field):
            payload[field] = edited_row.get(field)
    return payload


def format_table_cell(old_position: dict | None, new_position: dict | None) -> str:
    if old_position is None and new_position is None:
        return ""
    if old_position is not None and new_position is not None and old_position == new_position:
        return f"Table {old_position['table_id']}, Row {old_position['row']}, Col {old_position['col']}"
    if old_position is not None and new_position is not None:
        return (
            f"Table {old_position['table_id']}, Row {old_position['row']}, Col {old_position['col']} -> "
            f"Table {new_position['table_id']}, Row {new_position['row']}, Col {new_position['col']}"
        )
    position = new_position or old_position
    return f"Table {position['table_id']}, Row {position['row']}, Col {position['col']}"
