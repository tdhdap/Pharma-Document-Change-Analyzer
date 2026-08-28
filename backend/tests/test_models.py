# backend/tests/test_models.py
from app.models import (
    Paragraph, Section, SectionMatch, SectionMatchResult, MovedParagraph,
    RegexDetection, LLMClassification, Change, ComparisonSummary,
    ComparisonResult, build_summary, TableCoordinate,
)


def test_paragraph_defaults():
    p = Paragraph(text="hello")
    assert p.text == "hello"
    assert p.page is None
    assert p.paragraph_index is None
    assert p.is_heading is False


def test_section_holds_paragraphs():
    s = Section(heading="1.0 Scope", paragraphs=[Paragraph(text="a"), Paragraph(text="b")])
    assert s.heading == "1.0 Scope"
    assert len(s.paragraphs) == 2


def test_change_defaults_for_reviewer_fields():
    c = Change(
        change_id="c1", section="1.0 Scope", change_type="numeric_change",
        old_text="95%", new_text="98%", old_page=1, new_page=1,
        confidence=1.0, ai_risk_level="High", reason="value changed",
    )
    assert c.reviewer_risk_level is None
    assert c.reviewer_comment is None
    assert c.accepted is False


def test_build_summary_counts_by_risk():
    changes = [
        Change("1", "s", "t", "o", "n", None, None, 1.0, "High", "r"),
        Change("2", "s", "t", "o", "n", None, None, 1.0, "High", "r"),
        Change("3", "s", "t", "o", "n", None, None, 1.0, "Medium", "r"),
        Change("4", "s", "t", "o", "n", None, None, 1.0, "Informational", "r"),
    ]
    summary = build_summary(changes)
    assert summary.total_changes == 4
    assert summary.high_risk == 2
    assert summary.medium_risk == 1
    assert summary.low_risk == 0
    assert summary.informational == 1


def test_paragraph_table_position_defaults_to_none():
    p = Paragraph(text="hello")
    assert p.table_position is None


def test_table_coordinate_holds_id_row_and_column():
    coord = TableCoordinate(table_id=2, row=1, col=3)
    assert coord.table_id == 2
    assert coord.row == 1
    assert coord.col == 3


def test_paragraph_can_carry_a_table_position():
    coord = TableCoordinate(table_id=0, row=0, col=0)
    p = Paragraph(text="cell text", from_table=True, table_position=coord)
    assert p.table_position is coord


def test_change_table_positions_default_to_none():
    c = Change(
        change_id="c1", section="1.0 Scope", change_type="numeric_change",
        old_text="95%", new_text="98%", old_page=1, new_page=1,
        confidence=1.0, ai_risk_level="High", reason="value changed",
    )
    assert c.old_table_position is None
    assert c.new_table_position is None


def test_change_can_carry_table_positions():
    old_pos = TableCoordinate(table_id=0, row=1, col=1)
    new_pos = TableCoordinate(table_id=0, row=1, col=1)
    c = Change(
        change_id="c1", section="2.0 Acceptance Criteria", change_type="numeric_change",
        old_text="95%", new_text="98%", old_page=1, new_page=1,
        confidence=1.0, ai_risk_level="High", reason="value changed",
        old_table_position=old_pos, new_table_position=new_pos,
    )
    assert c.old_table_position is old_pos
    assert c.new_table_position is new_pos


def test_build_summary_counts_structural_changes():
    changes = [
        Change("1", "s", "section_added", "", "n", None, None, 1.0, "High", "r"),
        Change("2", "s", "section_added", "", "n", None, None, 1.0, "High", "r"),
        Change("3", "s", "section_deleted", "o", "", None, None, 1.0, "High", "r"),
        Change("4", "s", "section_heading_changed", "o", "n", None, None, 1.0, "Medium", "r"),
        Change("5", "s", "section_renumbered", "o", "n", None, None, 1.0, "Informational", "r"),
        Change("6", "s", "section_reordered", "o", "n", None, None, 1.0, "Informational", "r"),
        Change("7", "s", "numeric_change", "95%", "98%", None, None, 1.0, "High", "r"),
    ]

    summary = build_summary(changes)

    assert summary.sections_added == 2
    assert summary.sections_deleted == 1
    assert summary.sections_renamed == 1
    assert summary.sections_renumbered == 1
    assert summary.sections_moved == 1
    assert summary.sections_cascaded == 0


def test_build_summary_does_not_count_a_cascade_as_a_deliberate_renumber():
    # "section_renumbered_cascade" starts with "section_renumbered", so a prefix
    # match would count every cascade in BOTH metrics - inflating the exact number
    # the split exists to clarify. This is the single most likely implementation
    # error, and no corpus document exercises the cascade path.
    changes = [
        Change("1", "s", "section_renumbered_cascade", "o", "n", None, None, 1.0, "Informational", "r"),
        Change("2", "s", "section_renumbered_cascade", "o", "n", None, None, 1.0, "Informational", "r"),
    ]

    summary = build_summary(changes)

    assert summary.sections_cascaded == 2
    assert summary.sections_renumbered == 0


def test_build_summary_does_not_count_content_moves_as_moved_sections():
    # Content moving BETWEEN sections is not a section moving. The real SOP pair
    # has one moved_paragraph and no section_reordered; counting it here would
    # report a relocated section for a document in which none moved.
    changes = [
        Change("1", "s", "moved_paragraph", "o", "n", None, None, 1.0, "Informational", "r"),
        Change("2", "s", "moved_table_content", "o", "n", None, None, 1.0, "Informational", "r"),
    ]

    summary = build_summary(changes)

    assert summary.sections_moved == 0


def test_build_summary_reports_zero_structural_counts_when_there_are_none():
    changes = [Change("1", "s", "numeric_change", "95%", "98%", None, None, 1.0, "High", "r")]

    summary = build_summary(changes)

    assert summary.sections_added == 0
    assert summary.sections_deleted == 0
    assert summary.sections_renamed == 0
    assert summary.sections_renumbered == 0
    assert summary.sections_cascaded == 0
    assert summary.sections_moved == 0
