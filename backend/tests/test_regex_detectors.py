from app.regex_detectors import detect_regex_change


def test_numeric_change_when_only_numbers_differ():
    result = detect_regex_change(
        "Assay acceptance criterion: 95.0% to 105.0%.",
        "Assay acceptance criterion: 98.0% to 102.0%.",
    )
    assert result is not None
    assert result.change_type == "numeric_change"
    assert "95.0" in result.reason and "98.0" in result.reason


def test_unit_change_when_unit_token_differs():
    result = detect_regex_change("Weigh 10 mg of sample.", "Weigh 10 g of sample.")
    assert result is not None
    assert result.change_type == "unit_change"


def test_date_change_takes_priority_over_numeric():
    result = detect_regex_change(
        "Effective date: 01 Jan 2024.",
        "Effective date: 15 Mar 2024.",
    )
    assert result is not None
    assert result.change_type == "date_change"


def test_no_detection_when_text_has_no_numbers_units_or_dates():
    result = detect_regex_change(
        "The Quality Control Manager shall approve the result.",
        "The Quality Assurance Manager shall approve the result.",
    )
    assert result is None
