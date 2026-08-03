from app.models import Section, Paragraph, SectionMatch
from app.section_structure import detect_section_renumbering


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
