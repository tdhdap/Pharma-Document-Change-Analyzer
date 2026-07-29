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
}

DEFAULT_RISK = "Medium"


def assign_risk(change_type: str) -> str:
    return RISK_TABLE.get(change_type, DEFAULT_RISK)
