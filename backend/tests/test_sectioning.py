from app.models import Paragraph
from app.sectioning import split_into_sections


def test_splits_on_numbered_headings():
    paragraphs = [
        Paragraph(text="5.2 Sample Preparation"),
        Paragraph(text="Weigh 10 mg of sample."),
        Paragraph(text="5.3 Sample Analysis"),
        Paragraph(text="Inject into the HPLC system."),
    ]

    sections = split_into_sections(paragraphs)

    assert len(sections) == 2
    assert sections[0].heading == "5.2 Sample Preparation"
    assert [p.text for p in sections[0].paragraphs] == ["Weigh 10 mg of sample."]
    assert sections[1].heading == "5.3 Sample Analysis"
    assert [p.text for p in sections[1].paragraphs] == ["Inject into the HPLC system."]


def test_paragraphs_before_first_heading_become_preamble():
    paragraphs = [
        Paragraph(text="This document describes the sampling procedure."),
        Paragraph(text="1.0 Scope"),
        Paragraph(text="This applies to all raw materials."),
    ]

    sections = split_into_sections(paragraphs)

    assert sections[0].heading == "Preamble"
    assert [p.text for p in sections[0].paragraphs] == [
        "This document describes the sampling procedure."
    ]
    assert sections[1].heading == "1.0 Scope"


def test_no_headings_falls_back_to_one_section_per_paragraph():
    paragraphs = [
        Paragraph(text="Assay acceptance criterion: 95.0% to 105.0%."),
        Paragraph(text="Samples shall be stored at 25°C ± 2°C."),
        Paragraph(text="The Quality Control Manager shall approve the result."),
    ]

    sections = split_into_sections(paragraphs)

    assert len(sections) == 3
    assert sections[0].heading == "Paragraph 1"
    assert sections[0].paragraphs == [paragraphs[0]]
    assert sections[2].heading == "Paragraph 3"
