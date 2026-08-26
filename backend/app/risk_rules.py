RISK_TABLE = {
    "numeric_change": "High",
    "unit_change": "High",
    "process_sequence_change": "High",
    "qualitative_specification_change": "High",
    "role_responsibility_change": "Medium",
    "reference_document_change": "Medium",
    "date_change": "Medium",
    "clarification_no_meaning_change": "Low",
    "formatting_only": "Informational",
    "section_renumbered": "Informational",
    "section_renumbered_cascade": "Informational",
    "section_reordered": "Informational",
    "section_added": "High",
    "section_deleted": "High",
    "section_heading_changed": "Medium",
    "table_row_added": "Medium",
    "table_row_deleted": "Medium",
    "table_row_moved": "Informational",
    "table_column_added": "Medium",
    "table_column_deleted": "Medium",
    "table_column_moved": "Informational",
}

DEFAULT_RISK = "Medium"


def assign_risk(change_type: str) -> str:
    return RISK_TABLE.get(change_type, DEFAULT_RISK)
