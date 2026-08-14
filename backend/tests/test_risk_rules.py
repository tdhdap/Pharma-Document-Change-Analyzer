from app.risk_rules import assign_risk


def test_high_risk_change_types():
    for change_type in ["numeric_change", "unit_change", "process_sequence_change", "qualitative_specification_change"]:
        assert assign_risk(change_type) == "High"


def test_medium_risk_change_types():
    for change_type in ["role_responsibility_change", "reference_document_change", "date_change"]:
        assert assign_risk(change_type) == "Medium"


def test_low_risk_change_type():
    assert assign_risk("clarification_no_meaning_change") == "Low"


def test_informational_risk_change_type():
    assert assign_risk("formatting_only") == "Informational"


def test_structural_and_unknown_types_default_to_medium():
    for change_type in ["added_paragraph", "deleted_paragraph", "moved_paragraph", "unclassified", "something_new"]:
        assert assign_risk(change_type) == "Medium"


def test_section_renumbered_is_informational_risk():
    assert assign_risk("section_renumbered") == "Informational"


def test_section_reordered_is_informational_risk():
    assert assign_risk("section_reordered") == "Informational"


def test_section_added_is_high_risk():
    assert assign_risk("section_added") == "High"


def test_section_deleted_is_high_risk():
    assert assign_risk("section_deleted") == "High"


def test_section_heading_changed_is_medium_risk():
    assert assign_risk("section_heading_changed") == "Medium"
