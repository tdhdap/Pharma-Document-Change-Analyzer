from unittest.mock import patch

from streamlit.testing.v1 import AppTest


def test_page_loads_with_no_comparison():
    with patch("bootstrap._backend_is_reachable", return_value=True):
        at = AppTest.from_file("pages/2_Detailed_Changes.py")
        at.run()
    assert not at.exception


def test_page_loads_with_a_comparison():
    with patch("bootstrap._backend_is_reachable", return_value=True):
        at = AppTest.from_file("pages/2_Detailed_Changes.py")
        at.session_state["comparison"] = {
            "changes": [
                {
                    "change_id": "1", "section": "Acceptance Criteria", "change_type": "numeric_change",
                    "old_text": "95%", "new_text": "98%", "ai_risk_level": "High",
                    "reviewer_risk_level": None, "reason": "narrowed",
                },
            ]
        }
        at.run()
    assert not at.exception


def _make_comparison(changes):
    return {"changes": changes}


def _run_page_with(changes):
    with patch("bootstrap._backend_is_reachable", return_value=True):
        at = AppTest.from_file("pages/2_Detailed_Changes.py")
        at.session_state["comparison"] = _make_comparison(changes)
        at.run()
    return at


_ALL_CATEGORY_CHANGES = [
    {
        "change_id": "h1", "section": "Page Header", "source": "Body", "change_type": "section_added",
        "old_text": "", "new_text": "Confidential", "ai_risk_level": "High",
        "reviewer_risk_level": None, "reason": "new header",
    },
    {
        "change_id": "b1", "section": "2.0 Scope", "source": "Body", "change_type": "section_heading_changed",
        "old_text": "2.0 Scope", "new_text": "2.0 Applicability", "ai_risk_level": "Medium",
        "reviewer_risk_level": None, "reason": "heading changed",
    },
    {
        "change_id": "t1", "section": "4.0 Procedure", "source": "Table", "change_type": "numeric_change",
        "old_text": "14.8 kN", "new_text": "15.1 kN", "ai_risk_level": "High",
        "reviewer_risk_level": None, "reason": "value changed",
        "old_table_position": {"table_id": 0, "row": 1, "col": 2},
        "new_table_position": {"table_id": 0, "row": 1, "col": 2},
    },
]


def test_page_renders_four_categories_in_order():
    at = _run_page_with(_ALL_CATEGORY_CHANGES)
    assert not at.exception
    labels = [e.label for e in at.expander]
    header_index = next(i for i, l in enumerate(labels) if "Headers" in l)
    footer_index = next(i for i, l in enumerate(labels) if "Footers" in l)
    body_index = next(i for i, l in enumerate(labels) if "Body" in l)
    tables_index = next(i for i, l in enumerate(labels) if "Tables" in l)
    assert header_index < footer_index < body_index < tables_index


def test_page_shows_all_four_categories_even_when_some_are_empty():
    # Only a Body change - Headers, Footers, and Tables must still render, showing 0 changes.
    at = _run_page_with([_ALL_CATEGORY_CHANGES[1]])
    assert not at.exception
    labels = [e.label for e in at.expander]
    assert any(l == "Headers — 0 changes" for l in labels)
    assert any(l == "Footers — 0 changes" for l in labels)
    assert any(l == "Tables — 0 changes" for l in labels)


def test_page_nests_body_and_tables_by_section():
    at = _run_page_with(_ALL_CATEGORY_CHANGES)
    assert not at.exception
    labels = [e.label for e in at.expander]
    assert any("2.0 Scope" in l for l in labels)
    assert any("4.0 Procedure" in l for l in labels)


def test_page_high_risk_group_defaults_expanded():
    at = _run_page_with(_ALL_CATEGORY_CHANGES)
    assert not at.exception
    header_expander = next(e for e in at.expander if "Headers" in e.label)
    # AppTest's Expander element exposes the expanded flag via .proto.expanded,
    # not a top-level .expanded attribute - verified empirically before writing
    # this plan (a top-level .expanded does not exist on this Streamlit version).
    assert header_expander.proto.expanded is True


def test_page_no_high_risk_group_defaults_collapsed():
    low_risk_change = {
        "change_id": "b2", "section": "6.0 Quality Control Release", "source": "Body",
        "change_type": "section_reordered", "old_text": "6.0", "new_text": "6.0",
        "ai_risk_level": "Informational", "reviewer_risk_level": None, "reason": "moved",
    }
    at = _run_page_with([low_risk_change])
    assert not at.exception
    body_section_expander = next(e for e in at.expander if "6.0 Quality Control Release" in e.label)
    assert body_section_expander.proto.expanded is False


def test_page_table_category_shows_table_id_row_col_columns():
    at = _run_page_with(_ALL_CATEGORY_CHANGES)
    assert not at.exception
    table_values = [t.value for t in at.table]
    matching = [df for df in table_values if "Table ID" in df.columns]
    assert len(matching) == 1
    df = matching[0]
    assert list(df.columns) == ["Table ID", "Row", "Col", "Old Text", "New Text", "Change Type", "Risk", "Reason"]
    assert df.iloc[0]["Row"] == "1"
    assert df.iloc[0]["Col"] == "2"


def test_page_body_category_has_no_table_cell_column():
    at = _run_page_with(_ALL_CATEGORY_CHANGES)
    assert not at.exception
    table_values = [t.value for t in at.table]
    body_style = [df for df in table_values if "Table ID" not in df.columns]
    assert len(body_style) >= 1
    for df in body_style:
        assert "Table Cell" not in df.columns
        assert "Source" not in df.columns


def test_page_filters_narrow_results_within_groups():
    at = _run_page_with(_ALL_CATEGORY_CHANGES)
    risk_selectbox = at.selectbox[0]  # "Filter by risk" is the first selectbox on the page
    risk_selectbox.select("High").run()
    assert not at.exception
    labels = [e.label for e in at.expander]
    # With only High-risk changes surviving the filter, Body's only change (Medium) is filtered
    # out, so Body should show 0 changes while Headers/Tables (both High) still show theirs.
    assert any(l == "Body — 0 changes" for l in labels)


def test_page_headers_category_distinguishes_multiple_variants():
    # Regression test for the exact scenario the final whole-branch review
    # found broken: two different header variants changing independently
    # were rendered as indistinguishable rows with no Section column.
    changes = [
        {
            "change_id": "h1", "section": "Page Header", "source": "Body", "change_type": "numeric_change",
            "old_text": "Confidential - SOP-1234", "new_text": "Confidential - SOP-5678",
            "ai_risk_level": "High", "reviewer_risk_level": None, "reason": "doc number changed",
        },
        {
            "change_id": "h2", "section": "Page Header (First Page)", "source": "Body",
            "change_type": "clarification_no_meaning_change",
            "old_text": "DRAFT - For Review Only", "new_text": "APPROVED - For Distribution",
            "ai_risk_level": "Low", "reviewer_risk_level": None, "reason": "status updated",
        },
    ]
    at = _run_page_with(changes)
    assert not at.exception
    headers_table = next(t.value for t in at.table if "Section" in t.value.columns)
    assert list(headers_table["Section"]) == ["Page Header", "Page Header (First Page)"]
