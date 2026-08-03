from app import pipeline, llm_classifier
from app.models import Paragraph, LLMClassification


def test_pipeline_reproduces_the_outline_example(monkeypatch):
    old_paragraphs = [
        Paragraph(text="Assay acceptance criterion: 95.0% to 105.0%."),
        Paragraph(text="Samples shall be stored at 25°C ± 2°C."),
        Paragraph(text="The Quality Control Manager shall approve the result."),
    ]
    new_paragraphs = [
        Paragraph(text="Assay acceptance criterion: 98.0% to 102.0%."),
        Paragraph(text="Samples shall be stored at 25°C ± 2°C and 60% RH ± 5% RH."),
        Paragraph(text="The Quality Assurance Manager shall approve the result."),
    ]

    def fake_classify(unresolved):
        results = []
        for item in unresolved:
            if "Manager" in item["old_text"]:
                results.append(LLMClassification(
                    change_id=item["change_id"],
                    change_type="role_responsibility_change",
                    reason="Approval responsibility changed from QC Manager to QA Manager.",
                    confidence=0.9,
                ))
            else:
                results.append(LLMClassification(
                    change_id=item["change_id"],
                    change_type="qualitative_specification_change",
                    reason="An additional environmental control requirement (humidity) was added.",
                    confidence=0.85,
                ))
        return results

    monkeypatch.setattr(llm_classifier, "classify_changes_batch", fake_classify)

    result = pipeline.compare_documents(old_paragraphs, new_paragraphs, "SOP_v1.txt", "SOP_v2.txt")

    # 5 rows total: line 1 -> numeric_change (1); line 2 -> unit_change + numeric_change
    # + one AI-classified row for the added humidity clause (3); line 3 -> one AI-classified
    # role_responsibility_change row (1).
    assert result.summary.total_changes == 5
    assert result.summary.high_risk == 4
    assert result.summary.medium_risk == 1

    change_types = {c.change_type for c in result.changes}
    assert "numeric_change" in change_types
    assert "unit_change" in change_types
    assert "role_responsibility_change" in change_types

    # This is the row this whole feature exists to add: line 2 alone must now produce
    # 3 distinct rows instead of 1.
    samples_changes = [c for c in result.changes if c.old_text == "Samples shall be stored at 25°C ± 2°C."]
    assert len(samples_changes) == 3
    assert {c.change_type for c in samples_changes} == {
        "unit_change", "numeric_change", "qualitative_specification_change",
    }

    role_change = next(c for c in result.changes if c.change_type == "role_responsibility_change")
    assert role_change.ai_risk_level == "Medium"
    assert "QA Manager" in role_change.reason


def test_two_regex_detections_on_one_line_produce_two_rows_and_skip_ai(monkeypatch):
    old_paragraphs = [Paragraph(text="Dispense 10 mL of solution.")]
    new_paragraphs = [Paragraph(text="Dispense 20 L of solution.")]

    def fail_if_called(unresolved):
        raise AssertionError("classify_changes_batch should not be called - regex fully explains this line")

    monkeypatch.setattr(llm_classifier, "classify_changes_batch", fail_if_called)

    result = pipeline.compare_documents(old_paragraphs, new_paragraphs, "old.txt", "new.txt")

    assert result.summary.total_changes == 2
    assert {c.change_type for c in result.changes} == {"unit_change", "numeric_change"}


def test_regex_detection_plus_separate_wording_change_produces_two_rows(monkeypatch):
    old_paragraphs = [Paragraph(text="Weigh 50 mg of sample, thoroughly mixed.")]
    new_paragraphs = [Paragraph(text="Weigh 55 mg of sample, completely mixed.")]

    def fake_classify(unresolved):
        assert len(unresolved) == 1
        assert unresolved[0]["already_detected"] == ["numeric_change"]
        return [LLMClassification(
            change_id=unresolved[0]["change_id"],
            change_type="qualitative_specification_change",
            reason="The mixing descriptor was changed from thoroughly to completely.",
            confidence=0.9,
        )]

    monkeypatch.setattr(llm_classifier, "classify_changes_batch", fake_classify)

    result = pipeline.compare_documents(old_paragraphs, new_paragraphs, "old.txt", "new.txt")

    assert result.summary.total_changes == 2
    change_types = {c.change_type for c in result.changes}
    assert change_types == {"numeric_change", "qualitative_specification_change"}


def test_date_and_numeric_change_on_one_line_both_survive_with_independent_risk(monkeypatch):
    old_paragraphs = [Paragraph(text="Sample collected on 01 Jan 2024, weight 50 mg.")]
    new_paragraphs = [Paragraph(text="Sample collected on 15 Mar 2024, weight 55 mg.")]

    def fail_if_called(unresolved):
        raise AssertionError("classify_changes_batch should not be called - regex fully explains this line")

    monkeypatch.setattr(llm_classifier, "classify_changes_batch", fail_if_called)

    result = pipeline.compare_documents(old_paragraphs, new_paragraphs, "old.txt", "new.txt")

    assert result.summary.total_changes == 2
    risks_by_type = {c.change_type: c.ai_risk_level for c in result.changes}
    assert risks_by_type == {"date_change": "Medium", "numeric_change": "High"}


def test_pending_change_never_leaks_when_llm_response_omits_it(monkeypatch):
    old_paragraphs = [
        Paragraph(text="The Quality Control Manager shall approve the result."),
    ]
    new_paragraphs = [
        Paragraph(text="The Quality Assurance Manager shall approve the result."),
    ]

    def fake_classify_returns_nothing(unresolved):
        return []  # simulates a partial/malformed Gemini response that omits this item

    monkeypatch.setattr(llm_classifier, "classify_changes_batch", fake_classify_returns_nothing)

    result = pipeline.compare_documents(old_paragraphs, new_paragraphs, "SOP_v1.txt", "SOP_v2.txt")

    assert result.summary.total_changes == 1
    change = result.changes[0]
    assert change.change_type == "unclassified"
    assert change.change_type != "pending_llm_classification"
    assert change.ai_risk_level == "Medium"
    assert change.confidence == 0.0


def test_table_cell_deletion_gets_table_labeled_change_type():
    old_paragraphs = [Paragraph(text="Old Row Value", from_table=True)]
    new_paragraphs = []

    result = pipeline.compare_documents(old_paragraphs, new_paragraphs, "old.docx", "new.docx")

    assert len(result.changes) == 1
    change = result.changes[0]
    assert change.source == "Table"
    assert change.change_type == "deleted_table_content"
    assert change.reason == "Table content removed."


def test_table_cell_addition_gets_table_labeled_change_type():
    old_paragraphs = []
    new_paragraphs = [Paragraph(text="New Row Value", from_table=True)]

    result = pipeline.compare_documents(old_paragraphs, new_paragraphs, "old.docx", "new.docx")

    assert len(result.changes) == 1
    change = result.changes[0]
    assert change.source == "Table"
    assert change.change_type == "added_table_content"
    assert change.reason == "New table content added."


def test_body_paragraph_addition_keeps_generic_change_type():
    old_paragraphs = []
    new_paragraphs = [Paragraph(text="New body sentence.")]

    result = pipeline.compare_documents(old_paragraphs, new_paragraphs, "old.docx", "new.docx")

    assert len(result.changes) == 1
    change = result.changes[0]
    assert change.source == "Body"
    assert change.change_type == "added_paragraph"
    assert change.reason == "New paragraph added."


def test_table_cell_with_precise_regex_change_keeps_precise_type():
    old_paragraphs = [Paragraph(text="Weigh 10 mg of sample.", from_table=True)]
    new_paragraphs = [Paragraph(text="Weigh 20 mg of sample.", from_table=True)]

    result = pipeline.compare_documents(old_paragraphs, new_paragraphs, "old.docx", "new.docx")

    assert len(result.changes) == 1
    change = result.changes[0]
    assert change.source == "Table"
    assert change.change_type == "numeric_change"


def test_pipeline_detects_renumbering_and_reordering_together():
    old_paragraphs = [
        Paragraph(text="1.0 Scope"),
        Paragraph(text="This procedure applies to testing performed in the QC lab."),
        Paragraph(text="2.0 Acceptance Criteria"),
        Paragraph(text="Results shall conform to the specified limits."),
        Paragraph(text="3.0 Approval"),
        Paragraph(text="The Quality Assurance Manager shall approve results."),
    ]
    new_paragraphs = [
        Paragraph(text="1.0 Scope"),
        Paragraph(text="This procedure applies to testing performed in the QC lab."),
        Paragraph(text="2.0 Approval"),
        Paragraph(text="The Quality Assurance Manager shall approve results."),
        Paragraph(text="3.0 Acceptance Criteria"),
        Paragraph(text="Results shall conform to the specified limits."),
    ]

    result = pipeline.compare_documents(old_paragraphs, new_paragraphs, "SOP_v1.txt", "SOP_v2.txt")

    renumbered = {c.old_text: c for c in result.changes if c.change_type == "section_renumbered"}
    reordered = [c for c in result.changes if c.change_type == "section_reordered"]

    assert set(renumbered.keys()) == {"2.0 Acceptance Criteria", "3.0 Approval"}
    assert renumbered["2.0 Acceptance Criteria"].new_text == "3.0 Acceptance Criteria"
    assert renumbered["2.0 Acceptance Criteria"].reason == "Section renumbered from '2.0' to '3.0'."
    assert renumbered["3.0 Approval"].new_text == "2.0 Approval"
    assert renumbered["3.0 Approval"].reason == "Section renumbered from '3.0' to '2.0'."
    for c in renumbered.values():
        assert c.ai_risk_level == "Informational"
        assert c.source == "Body"

    assert len(reordered) == 1
    assert reordered[0].section == "2.0 Approval"
    assert reordered[0].reason == "Section moved from position 3 to position 2 in the document."
    assert reordered[0].ai_risk_level == "Informational"
