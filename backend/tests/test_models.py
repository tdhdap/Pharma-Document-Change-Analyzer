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
