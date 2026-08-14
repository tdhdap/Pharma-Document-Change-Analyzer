from app.models import Section, Paragraph, SectionMatch
from app.section_structure import (
    detect_section_renumbering, detect_section_reordering,
    detect_section_added, detect_section_deleted, detect_section_heading_changed,
)


def test_pure_renumber_is_detected():
    old_sections = [Section(heading="2.0 Acceptance Criteria", paragraphs=[Paragraph(text="body")])]
    new_sections = [Section(heading="3.0 Acceptance Criteria", paragraphs=[Paragraph(text="body")])]
    matches = [SectionMatch(old_index=0, new_index=0, score=1.0)]

    changes = detect_section_renumbering(matches, old_sections, new_sections)

    assert len(changes) == 1
    c = changes[0]
    assert c.change_type == "section_renumbered"
    assert c.section == "2.0 Acceptance Criteria"
    assert c.old_text == "2.0 Acceptance Criteria"
    assert c.new_text == "3.0 Acceptance Criteria"
    assert c.reason == "Section renumbered from '2.0' to '3.0'."
    assert c.ai_risk_level == "Informational"
    assert c.source == "Body"
    assert c.confidence == 1.0
    assert c.old_page is None
    assert c.new_page is None


def test_unchanged_number_is_not_flagged():
    old_sections = [Section(heading="1.0 Scope", paragraphs=[])]
    new_sections = [Section(heading="1.0 Scope", paragraphs=[])]
    matches = [SectionMatch(old_index=0, new_index=0, score=1.0)]

    assert detect_section_renumbering(matches, old_sections, new_sections) == []


def test_reworded_heading_with_same_number_is_not_flagged():
    old_sections = [Section(heading="2.0 Acceptance Criteria", paragraphs=[])]
    new_sections = [Section(heading="2.0 Acceptance Criteria for Assay", paragraphs=[])]
    matches = [SectionMatch(old_index=0, new_index=0, score=1.0)]

    assert detect_section_renumbering(matches, old_sections, new_sections) == []


def test_number_and_wording_both_changing_flags_renumbering_too():
    old_sections = [Section(heading="2.0 Acceptance Criteria", paragraphs=[])]
    new_sections = [Section(heading="3.0 Acceptance Criteria for Assay", paragraphs=[])]
    matches = [SectionMatch(old_index=0, new_index=0, score=1.0)]

    changes = detect_section_renumbering(matches, old_sections, new_sections)

    assert len(changes) == 1
    assert changes[0].change_type == "section_renumbered"
    assert changes[0].reason == "Section renumbered from '2.0' to '3.0'."


def test_headings_without_a_leading_number_are_not_flagged():
    old_sections = [Section(heading="SCOPE", paragraphs=[])]
    new_sections = [Section(heading="PURPOSE", paragraphs=[])]
    matches = [SectionMatch(old_index=0, new_index=0, score=1.0)]

    assert detect_section_renumbering(matches, old_sections, new_sections) == []


def test_only_the_side_with_a_leading_number_removed_is_not_flagged():
    old_sections = [Section(heading="2.0 Acceptance Criteria", paragraphs=[])]
    new_sections = [Section(heading="Acceptance Criteria", paragraphs=[])]
    matches = [SectionMatch(old_index=0, new_index=0, score=1.0)]

    assert detect_section_renumbering(matches, old_sections, new_sections) == []


def test_only_renumbered_matches_are_flagged_among_several():
    old_sections = [
        Section(heading="1.0 Scope", paragraphs=[]),
        Section(heading="2.0 Acceptance Criteria", paragraphs=[]),
    ]
    new_sections = [
        Section(heading="1.0 Scope", paragraphs=[]),
        Section(heading="3.0 Acceptance Criteria", paragraphs=[]),
    ]
    matches = [
        SectionMatch(old_index=0, new_index=0, score=1.0),
        SectionMatch(old_index=1, new_index=1, score=1.0),
    ]

    changes = detect_section_renumbering(matches, old_sections, new_sections)

    assert len(changes) == 1
    assert changes[0].old_text == "2.0 Acceptance Criteria"


def test_empty_matches_returns_no_changes():
    assert detect_section_reordering([], [], []) == []


def test_matches_with_unchanged_relative_order_produce_no_changes():
    sections = [Section(heading=f"{n}", paragraphs=[]) for n in ["A", "B", "C"]]
    matches = [
        SectionMatch(old_index=0, new_index=0, score=1.0),
        SectionMatch(old_index=1, new_index=1, score=1.0),
        SectionMatch(old_index=2, new_index=2, score=1.0),
    ]

    assert detect_section_reordering(matches, sections, sections) == []


def test_insertion_elsewhere_does_not_cause_a_false_positive():
    # Old: A, B, C. New: X, A, B, C (X inserted at the front, unmatched).
    # Every matched section's raw index shifts by +1, but their relative
    # order to each other is unchanged, so nothing should be flagged.
    old_sections = [Section(heading=n, paragraphs=[]) for n in ["A", "B", "C"]]
    new_sections = [Section(heading=n, paragraphs=[]) for n in ["X", "A", "B", "C"]]
    matches = [
        SectionMatch(old_index=0, new_index=1, score=1.0),
        SectionMatch(old_index=1, new_index=2, score=1.0),
        SectionMatch(old_index=2, new_index=3, score=1.0),
    ]

    assert detect_section_reordering(matches, old_sections, new_sections) == []


def test_synthetic_headings_are_not_flagged_as_reordered():
    # Old: A, Paragraph 1, Paragraph 2, B (A, B are real headings).
    # New: Paragraph 2, Paragraph 1, A, B.
    # By plain LIS logic, A and B (positions 0 and 3 in old order) form the
    # longest increasing subsequence and are kept, while Paragraph 1 and
    # Paragraph 2 fall outside it and would normally be flagged as
    # reordered. Since both carry synthetic headings with no real document
    # text, they must be suppressed instead.
    old_sections = [
        Section(heading="A", paragraphs=[]),
        Section(heading="Paragraph 1", paragraphs=[]),
        Section(heading="Paragraph 2", paragraphs=[]),
        Section(heading="B", paragraphs=[]),
    ]
    new_sections = [
        Section(heading="Paragraph 2", paragraphs=[]),
        Section(heading="Paragraph 1", paragraphs=[]),
        Section(heading="A", paragraphs=[]),
        Section(heading="B", paragraphs=[]),
    ]
    matches = [
        SectionMatch(old_index=0, new_index=2, score=1.0),  # A
        SectionMatch(old_index=1, new_index=1, score=1.0),  # Paragraph 1
        SectionMatch(old_index=2, new_index=0, score=1.0),  # Paragraph 2
        SectionMatch(old_index=3, new_index=3, score=1.0),  # B
    ]

    assert detect_section_reordering(matches, old_sections, new_sections) == []


def test_synthetic_heading_on_either_side_alone_suppresses_the_flag():
    # Old: A, B, C, Paragraph 1, Y. New: M, Paragraph 9, A, B, C.
    # A, B, C keep their relative order to each other (kept by LIS).
    # "Paragraph 1" (old side synthetic, new side real heading "M") and "Y"
    # (old side real, new side synthetic heading "Paragraph 9") both jump
    # to the front and would normally be flagged by plain LIS - proven by
    # the fact that without the synthetic guard, only A/B/C form the
    # longest increasing subsequence of new_index positions. Both must be
    # suppressed because a synthetic heading appears on at least one side.
    old_sections = [
        Section(heading="A", paragraphs=[]),
        Section(heading="B", paragraphs=[]),
        Section(heading="C", paragraphs=[]),
        Section(heading="Paragraph 1", paragraphs=[]),
        Section(heading="Y", paragraphs=[]),
    ]
    new_sections = [
        Section(heading="M", paragraphs=[]),
        Section(heading="Paragraph 9", paragraphs=[]),
        Section(heading="A", paragraphs=[]),
        Section(heading="B", paragraphs=[]),
        Section(heading="C", paragraphs=[]),
    ]
    matches = [
        SectionMatch(old_index=0, new_index=2, score=1.0),  # A
        SectionMatch(old_index=1, new_index=3, score=1.0),  # B
        SectionMatch(old_index=2, new_index=4, score=1.0),  # C
        SectionMatch(old_index=3, new_index=0, score=1.0),  # Paragraph 1 -> M (synthetic old side only)
        SectionMatch(old_index=4, new_index=1, score=1.0),  # Y -> Paragraph 9 (synthetic new side only)
    ]

    assert detect_section_reordering(matches, old_sections, new_sections) == []


def test_section_that_jumps_ahead_of_others_is_flagged():
    # Old: A, B, C, D. New: D, A, B, C (D jumps to the front; A, B, C keep
    # their relative order to each other, so only D should be flagged).
    old_sections = [Section(heading=n, paragraphs=[]) for n in ["A", "B", "C", "D"]]
    new_sections = [Section(heading=n, paragraphs=[]) for n in ["D", "A", "B", "C"]]
    matches = [
        SectionMatch(old_index=0, new_index=1, score=1.0),  # A
        SectionMatch(old_index=1, new_index=2, score=1.0),  # B
        SectionMatch(old_index=2, new_index=3, score=1.0),  # C
        SectionMatch(old_index=3, new_index=0, score=1.0),  # D
    ]

    changes = detect_section_reordering(matches, old_sections, new_sections)

    assert len(changes) == 1
    c = changes[0]
    assert c.change_type == "section_reordered"
    assert c.section == "D"
    assert c.old_text == "D"
    assert c.new_text == "D"
    assert c.reason == "Section moved from position 4 to position 1 in the document."
    assert c.ai_risk_level == "Informational"
    assert c.source == "Body"
    assert c.confidence == 1.0
    assert c.old_page is None
    assert c.new_page is None


def test_new_section_with_body_is_detected():
    new_sections = [
        Section(heading="1.0 Scope", paragraphs=[Paragraph(text="existing", page=1)]),
        Section(heading="5.0 Environmental Monitoring", paragraphs=[
            Paragraph(text="Environmental monitoring of the manufacturing area shall be performed weekly.", page=3),
            Paragraph(text="Settle plates shall be used at each critical location.", page=3),
        ]),
    ]

    changes = detect_section_added([1], new_sections)

    assert len(changes) == 1
    c = changes[0]
    assert c.change_type == "section_added"
    assert c.section == "5.0 Environmental Monitoring"
    assert c.old_text == ""
    assert c.new_text == (
        "5.0 Environmental Monitoring\n"
        "Environmental monitoring of the manufacturing area shall be performed weekly.\n"
        "Settle plates shall be used at each critical location."
    )
    assert c.reason == "New section added: '5.0 Environmental Monitoring'."
    assert c.ai_risk_level == "High"
    assert c.source == "Body"
    assert c.confidence == 1.0
    assert c.old_page is None
    assert c.new_page == 3


def test_heading_only_new_section_is_still_detected():
    new_sections = [Section(heading="9.0 Reserved", paragraphs=[])]

    changes = detect_section_added([0], new_sections)

    assert len(changes) == 1
    c = changes[0]
    assert c.old_text == ""
    assert c.new_text == "9.0 Reserved"
    assert c.new_page is None


def test_synthetic_heading_new_section_is_not_flagged():
    new_sections = [Section(heading="Paragraph 1", paragraphs=[Paragraph(text="body")])]

    assert detect_section_added([0], new_sections) == []


def test_table_sourced_new_section_is_labeled_table():
    new_sections = [Section(heading="4.0 Limits", paragraphs=[Paragraph(text="cell value", from_table=True)])]

    changes = detect_section_added([0], new_sections)

    assert len(changes) == 1
    assert changes[0].source == "Table"


def test_only_inserted_indices_are_flagged_among_several_sections():
    new_sections = [
        Section(heading="1.0 Scope", paragraphs=[Paragraph(text="unchanged")]),
        Section(heading="2.0 New Section", paragraphs=[Paragraph(text="added content")]),
    ]

    changes = detect_section_added([1], new_sections)

    assert len(changes) == 1
    assert changes[0].section == "2.0 New Section"


def test_deleted_section_with_body_is_detected():
    old_sections = [
        Section(heading="7.0 Storage", paragraphs=[Paragraph(text="unchanged", page=5)]),
        Section(heading="8.0 Deviation Handling", paragraphs=[
            Paragraph(text="Any deviation from this procedure shall be documented.", page=6),
        ]),
    ]

    changes = detect_section_deleted([1], old_sections)

    assert len(changes) == 1
    c = changes[0]
    assert c.change_type == "section_deleted"
    assert c.section == "8.0 Deviation Handling"
    assert c.old_text == "8.0 Deviation Handling\nAny deviation from this procedure shall be documented."
    assert c.new_text == ""
    assert c.reason == "Section deleted: '8.0 Deviation Handling'."
    assert c.ai_risk_level == "High"
    assert c.source == "Body"
    assert c.confidence == 1.0
    assert c.old_page == 6
    assert c.new_page is None


def test_heading_only_deleted_section_is_still_detected():
    old_sections = [Section(heading="9.0 Reserved", paragraphs=[])]

    changes = detect_section_deleted([0], old_sections)

    assert len(changes) == 1
    c = changes[0]
    assert c.old_text == "9.0 Reserved"
    assert c.new_text == ""
    assert c.old_page is None


def test_synthetic_heading_deleted_section_is_not_flagged():
    old_sections = [Section(heading="Paragraph 3", paragraphs=[Paragraph(text="body")])]

    assert detect_section_deleted([0], old_sections) == []


def test_table_sourced_deleted_section_is_labeled_table():
    old_sections = [Section(heading="4.0 Limits", paragraphs=[Paragraph(text="cell value", from_table=True)])]

    changes = detect_section_deleted([0], old_sections)

    assert len(changes) == 1
    assert changes[0].source == "Table"


def test_excluded_paragraph_ids_are_omitted_from_added_section_text():
    p1 = Paragraph(text="This paragraph relocated from elsewhere.", page=2)
    p2 = Paragraph(text="This paragraph is genuinely new.", page=2)
    new_sections = [Section(heading="5.0 New Section", paragraphs=[p1, p2])]

    changes = detect_section_added([0], new_sections, excluded_paragraph_ids={id(p1)})

    assert len(changes) == 1
    assert changes[0].new_text == "5.0 New Section\nThis paragraph is genuinely new."


def test_excluded_paragraph_ids_are_omitted_from_deleted_section_text():
    p1 = Paragraph(text="This paragraph relocated elsewhere.", page=2)
    p2 = Paragraph(text="This paragraph is genuinely removed.", page=2)
    old_sections = [Section(heading="8.0 Old Section", paragraphs=[p1, p2])]

    changes = detect_section_deleted([0], old_sections, excluded_paragraph_ids={id(p1)})

    assert len(changes) == 1
    assert changes[0].old_text == "8.0 Old Section\nThis paragraph is genuinely removed."


def test_pure_rewording_is_detected():
    old_sections = [Section(heading="8.0 Deviation Handling", paragraphs=[])]
    new_sections = [Section(heading="8.0 Non-Conformance Management", paragraphs=[])]
    matches = [SectionMatch(old_index=0, new_index=0, score=1.0)]

    changes = detect_section_heading_changed(matches, old_sections, new_sections)

    assert len(changes) == 1
    c = changes[0]
    assert c.change_type == "section_heading_changed"
    assert c.section == "8.0 Deviation Handling"
    assert c.old_text == "8.0 Deviation Handling"
    assert c.new_text == "8.0 Non-Conformance Management"
    assert c.reason == "Section heading changed from '8.0 Deviation Handling' to '8.0 Non-Conformance Management'."
    assert c.ai_risk_level == "Medium"
    assert c.source == "Body"
    assert c.confidence == 1.0
    assert c.old_page is None
    assert c.new_page is None


def test_pure_renumber_does_not_flag_heading_changed():
    old_sections = [Section(heading="2.0 Acceptance Criteria", paragraphs=[])]
    new_sections = [Section(heading="3.0 Acceptance Criteria", paragraphs=[])]
    matches = [SectionMatch(old_index=0, new_index=0, score=1.0)]

    assert detect_section_heading_changed(matches, old_sections, new_sections) == []


def test_number_and_wording_both_changing_flags_heading_changed_too():
    old_sections = [Section(heading="2.0 Acceptance Criteria", paragraphs=[])]
    new_sections = [Section(heading="3.0 Acceptance Criteria for Assay", paragraphs=[])]
    matches = [SectionMatch(old_index=0, new_index=0, score=1.0)]

    changes = detect_section_heading_changed(matches, old_sections, new_sections)

    assert len(changes) == 1
    assert changes[0].old_text == "2.0 Acceptance Criteria"
    assert changes[0].new_text == "3.0 Acceptance Criteria for Assay"


def test_reworded_heading_with_no_leading_number_is_detected():
    old_sections = [Section(heading="SCOPE", paragraphs=[])]
    new_sections = [Section(heading="PURPOSE", paragraphs=[])]
    matches = [SectionMatch(old_index=0, new_index=0, score=1.0)]

    changes = detect_section_heading_changed(matches, old_sections, new_sections)

    assert len(changes) == 1
    assert changes[0].old_text == "SCOPE"
    assert changes[0].new_text == "PURPOSE"


def test_identical_headings_are_not_flagged():
    old_sections = [Section(heading="1.0 Scope", paragraphs=[])]
    new_sections = [Section(heading="1.0 Scope", paragraphs=[])]
    matches = [SectionMatch(old_index=0, new_index=0, score=1.0)]

    assert detect_section_heading_changed(matches, old_sections, new_sections) == []


def test_synthetic_heading_is_not_flagged_as_heading_changed():
    old_sections = [Section(heading="Paragraph 1", paragraphs=[])]
    new_sections = [Section(heading="Paragraph 2", paragraphs=[])]
    matches = [SectionMatch(old_index=0, new_index=0, score=1.0)]

    assert detect_section_heading_changed(matches, old_sections, new_sections) == []


def test_internal_whitespace_only_difference_is_not_flagged_on_unnumbered_heading():
    old_sections = [Section(heading="SCOPE  OF WORK", paragraphs=[])]
    new_sections = [Section(heading="SCOPE OF WORK", paragraphs=[])]
    matches = [SectionMatch(old_index=0, new_index=0, score=1.0)]

    assert detect_section_heading_changed(matches, old_sections, new_sections) == []
