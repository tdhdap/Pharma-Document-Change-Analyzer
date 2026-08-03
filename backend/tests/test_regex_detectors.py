from app.regex_detectors import detect_regex_change, _extract_numbers


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


def test_numeric_change_does_not_absorb_trailing_sentence_period():
    result = detect_regex_change(
        "This procedure is effective from 2024-01-15.",
        "This procedure is effective from 2024-03-20.",
    )
    assert result is not None
    assert result.change_type == "numeric_change"


def test_extract_numbers_excludes_a_bare_trailing_period():
    # The sentence-ending period right after "15" must not be absorbed into
    # the number - previously "-?\d+\.?\d*" would greedily consume it.
    assert _extract_numbers("Effective from 2024-01-15.") == ["2024", "-01", "-15"]
    # A real decimal point followed by digits must still parse correctly.
    assert _extract_numbers("Assay range: 95.0% to 105.0%.") == ["95.0", "105.0"]


from app.regex_detectors import detect_all_regex_changes, strip_detected_values


def test_detect_all_regex_changes_finds_both_unit_and_numeric_on_one_line():
    detections = detect_all_regex_changes("Dispense 10 mL of solution.", "Dispense 20 L of solution.")
    change_types = {d.change_type for d in detections}
    assert change_types == {"unit_change", "numeric_change"}


def test_detect_all_regex_changes_returns_empty_list_when_nothing_matches():
    detections = detect_all_regex_changes(
        "The Quality Control Manager shall approve the result.",
        "The Quality Assurance Manager shall approve the result.",
    )
    assert detections == []


def test_regex_detection_carries_raw_matched_values():
    detections = detect_all_regex_changes(
        "Assay acceptance criterion: 95.0% to 105.0%.",
        "Assay acceptance criterion: 98.0% to 102.0%.",
    )
    assert len(detections) == 1
    assert detections[0].old_values == ["95.0", "105.0"]
    assert detections[0].new_values == ["98.0", "102.0"]


def test_strip_detected_values_leaves_no_residual_when_regex_explains_everything():
    old_text = "Dispense 10 mL of solution."
    new_text = "Dispense 20 L of solution."
    detections = detect_all_regex_changes(old_text, new_text)
    stripped_old, stripped_new = strip_detected_values(old_text, new_text, detections)
    assert stripped_old == stripped_new


def test_strip_detected_values_leaves_a_residual_when_something_else_also_changed():
    old_text = "Weigh 50 mg of sample, thoroughly mixed."
    new_text = "Weigh 55 mg of sample, completely mixed."
    detections = detect_all_regex_changes(old_text, new_text)
    stripped_old, stripped_new = strip_detected_values(old_text, new_text, detections)
    assert stripped_old != stripped_new


def test_detect_all_regex_changes_no_longer_hides_a_higher_risk_change_behind_a_lower_risk_one():
    # Regression guard for the first-match-wins severity-masking bug: date_change (Medium
    # risk) is checked before numeric_change (High risk) in detect_regex_change's fixed
    # order, so a line with both used to silently report only the Medium-risk one. Verified
    # directly while writing this plan: both genuinely fire on this exact pair.
    detections = detect_all_regex_changes(
        "Sample collected on 01 Jan 2024, weight 50 mg.",
        "Sample collected on 15 Mar 2024, weight 55 mg.",
    )
    change_types = {d.change_type for d in detections}
    assert change_types == {"date_change", "numeric_change"}
