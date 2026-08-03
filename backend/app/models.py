from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Paragraph:
    text: str
    page: Optional[int] = None
    paragraph_index: Optional[int] = None
    is_heading: bool = False
    allow_text_pattern_heading: bool = True
    from_table: bool = False


@dataclass
class Section:
    heading: str
    paragraphs: list[Paragraph]


@dataclass
class SectionMatch:
    old_index: int
    new_index: int
    score: float


@dataclass
class SectionMatchResult:
    matches: list[SectionMatch]
    deleted_indices: list[int]
    inserted_indices: list[int]


@dataclass
class MovedParagraph:
    old_paragraph: Paragraph
    new_paragraph: Paragraph
    old_section: str
    new_section: str
    score: float


@dataclass
class RegexDetection:
    change_type: str
    reason: str
    confidence: float = 1.0
    old_values: list[str] = field(default_factory=list)
    new_values: list[str] = field(default_factory=list)
    old_spans: list[tuple[int, int]] = field(default_factory=list)
    new_spans: list[tuple[int, int]] = field(default_factory=list)


@dataclass
class LLMClassification:
    change_id: str
    change_type: str
    reason: str
    confidence: float


@dataclass
class Change:
    change_id: str
    section: str
    change_type: str
    old_text: str
    new_text: str
    old_page: Optional[int]
    new_page: Optional[int]
    confidence: float
    ai_risk_level: str
    reason: str
    reviewer_risk_level: Optional[str] = None
    reviewer_comment: Optional[str] = None
    accepted: bool = False
    source: str = "Body"


@dataclass
class ComparisonSummary:
    total_changes: int
    high_risk: int
    medium_risk: int
    low_risk: int
    informational: int


@dataclass
class ComparisonResult:
    comparison_id: str
    old_document: str
    new_document: str
    summary: ComparisonSummary
    changes: list[Change]


def build_summary(changes: list[Change]) -> ComparisonSummary:
    return ComparisonSummary(
        total_changes=len(changes),
        high_risk=sum(1 for c in changes if c.ai_risk_level == "High"),
        medium_risk=sum(1 for c in changes if c.ai_risk_level == "Medium"),
        low_risk=sum(1 for c in changes if c.ai_risk_level == "Low"),
        informational=sum(1 for c in changes if c.ai_risk_level == "Informational"),
    )
