from app.models import Section, Paragraph, SectionMatch
from app.section_structure import detect_section_renumbering, detect_section_reordering


def test_pure_renumber_is_detected():
    old_sections = [Section(heading="2.0 Acceptance Criteria", paragraphs=[Paragraph(text="body")])]
    new_sections = [Section(heading="3.0 Acceptance Criteria", paragraphs=[Paragraph(text="body")])]
    matches = [SectionMatch(old_index=0, new_index=0, score=1.0)]

    changes = detect_section_renumbering(matches, old_sections, new_sections)

    assert len(changes) == 1
    c = changes[0]
    assert c.change_type == "section_renumbered"
    assert c.section == "3.0 Acceptance Criteria"
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


def test_number_and_wording_both_changing_is_not_flagged_as_pure_renumbering():
    old_sections = [Section(heading="2.0 Acceptance Criteria", paragraphs=[])]
    new_sections = [Section(heading="3.0 Acceptance Criteria for Assay", paragraphs=[])]
    matches = [SectionMatch(old_index=0, new_index=0, score=1.0)]

    assert detect_section_renumbering(matches, old_sections, new_sections) == []


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
