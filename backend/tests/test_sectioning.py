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


def test_does_not_misdetect_numeral_leading_body_text_as_heading():
    paragraphs = [
        Paragraph(text="5.2 Sample Preparation"),
        Paragraph(text="10 mg of sample was weighed and diluted."),
        Paragraph(text="2 hours later, the reaction was stopped."),
        Paragraph(text="5.3 Sample Analysis"),
        Paragraph(text="1234 units were tested."),
    ]

    sections = split_into_sections(paragraphs)

    assert len(sections) == 2
    assert sections[0].heading == "5.2 Sample Preparation"
    assert [p.text for p in sections[0].paragraphs] == [
        "10 mg of sample was weighed and diluted.",
        "2 hours later, the reaction was stopped.",
    ]
    assert sections[1].heading == "5.3 Sample Analysis"
    assert [p.text for p in sections[1].paragraphs] == ["1234 units were tested."]


def test_prefers_is_heading_flag_over_text_pattern():
    paragraphs = [
        Paragraph(text="Sample Preparation", is_heading=True),
        Paragraph(text="Weigh 10 mg of sample."),
        Paragraph(text="Sample Analysis", is_heading=True),
        Paragraph(text="Inject into the HPLC system."),
    ]

    sections = split_into_sections(paragraphs)

    assert len(sections) == 2
    assert sections[0].heading == "Sample Preparation"
    assert sections[1].heading == "Sample Analysis"


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


def test_structural_signal_does_not_block_numbered_pattern_elsewhere():
    paragraphs = [
        Paragraph(text="Introduction", is_heading=True),
        Paragraph(text="This document describes the procedure."),
        Paragraph(text="5.2 Sample Preparation"),
        Paragraph(text="Weigh 10 mg of sample."),
    ]

    sections = split_into_sections(paragraphs)

    assert len(sections) == 2
    assert sections[0].heading == "Introduction"
    assert sections[1].heading == "5.2 Sample Preparation"


def test_all_caps_heading_without_numbering_is_detected():
    paragraphs = [
        Paragraph(text="SCOPE"),
        Paragraph(text="This procedure applies to all lab testing."),
        Paragraph(text="MATERIALS AND METHODS"),
        Paragraph(text="Use validated equipment only."),
    ]

    sections = split_into_sections(paragraphs)

    assert len(sections) == 2
    assert sections[0].heading == "SCOPE"
    assert sections[1].heading == "MATERIALS AND METHODS"


def test_all_caps_sentence_ending_in_period_is_not_a_heading():
    paragraphs = [
        Paragraph(text="1.0 Warnings"),
        Paragraph(text="DO NOT USE IF SEAL IS BROKEN."),
    ]

    sections = split_into_sections(paragraphs)

    assert len(sections) == 1
    assert sections[0].heading == "1.0 Warnings"
    assert [p.text for p in sections[0].paragraphs] == ["DO NOT USE IF SEAL IS BROKEN."]
