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


def categorize_change(change: dict) -> str:
    if change.get("source", "Body") == "Table":
        return "Tables"
    section = change["section"]
    if section.startswith("Page Header"):
        return "Headers"
    if section.startswith("Page Footer"):
        return "Footers"
    return "Body"


def group_changes_for_display(changes: list[dict]) -> dict:
    result = {"Headers": [], "Footers": [], "Body": {}, "Tables": {}}
    for change in changes:
        category = categorize_change(change)
        if category in ("Headers", "Footers"):
            result[category].append(change)
        else:
            result[category].setdefault(change["section"], []).append(change)
    return result


_RISK_SEVERITY_ORDER = ["High", "Medium", "Low", "Informational"]
_RISK_EMOJI = {"High": "\U0001f534", "Medium": "\U0001f7e1", "Low": "\U0001f7e2", "Informational": "⚪"}


def _change_risk(change: dict) -> str:
    return change.get("reviewer_risk_level") or change["ai_risk_level"]


def compute_risk_counts(changes: list[dict]) -> dict:
    counts = {}
    for change in changes:
        risk = _change_risk(change)
        counts[risk] = counts.get(risk, 0) + 1
    return {level: counts[level] for level in _RISK_SEVERITY_ORDER if level in counts}


def format_group_label(name: str, changes: list[dict]) -> str:
    total = len(changes)
    risk_counts = compute_risk_counts(changes)
    if not risk_counts:
        return f"{name} — 0 changes"
    top_tier = next(iter(risk_counts))
    emoji = _RISK_EMOJI[top_tier]
    breakdown = ", ".join(f"{count} {level}" for level, count in risk_counts.items())
    plural = "" if total == 1 else "s"
    return f"{emoji} {name} — {total} change{plural} ({breakdown})"


def has_high_risk(changes: list[dict]) -> bool:
    return any(_change_risk(c) == "High" for c in changes)


def table_group_key(change: dict) -> int:
    new_position = change.get("new_table_position")
    old_position = change.get("old_table_position")
    position = new_position if new_position is not None else old_position
    return position["table_id"]


def format_table_coordinates(old_position: dict | None, new_position: dict | None) -> tuple[str, str]:
    if old_position is None and new_position is None:
        return "", ""

    def field(key: str) -> str:
        if old_position is not None and new_position is not None and old_position[key] != new_position[key]:
            return f"{old_position[key] + 1} → {new_position[key] + 1}"
        source = new_position if new_position is not None else old_position
        return str(source[key] + 1)

    return field("row"), field("col")
