import streamlit as st

from logic import filter_changes, group_changes_for_display, format_group_label, has_high_risk, format_table_coordinates
from bootstrap import ensure_backend_running

st.set_page_config(layout="wide")

ensure_backend_running()

st.title("Detailed Changes")

comparison = st.session_state.get("comparison")

if not comparison:
    st.info("Upload and compare two documents on the 'Upload & Compare' page first.")
else:
    changes = comparison["changes"]
    sections = sorted({c["section"] for c in changes})
    change_types = sorted({c["change_type"] for c in changes})

    risk_filter = st.selectbox("Filter by risk", ["All", "High", "Medium", "Low", "Informational"])
    section_filter = st.selectbox("Filter by section", ["All"] + sections)
    type_filter = st.selectbox("Filter by change type", ["All"] + change_types)

    filtered = filter_changes(
        changes,
        risk=None if risk_filter == "All" else risk_filter,
        section=None if section_filter == "All" else section_filter,
        change_type=None if type_filter == "All" else type_filter,
    )

    grouped = group_changes_for_display(filtered)

    def render_body_rows(group_changes):
        st.table([
            {
                "Old Text": c["old_text"],
                "New Text": c["new_text"],
                "Change Type": c["change_type"],
                "Risk": c.get("reviewer_risk_level") or c["ai_risk_level"],
                "Reason": c["reason"],
            }
            for c in group_changes
        ])

    def render_table_rows(group_changes):
        rows = []
        for c in group_changes:
            table_id, row, col = format_table_coordinates(c.get("old_table_position"), c.get("new_table_position"))
            rows.append({
                "Table ID": table_id,
                "Row": row,
                "Col": col,
                "Old Text": c["old_text"],
                "New Text": c["new_text"],
                "Change Type": c["change_type"],
                "Risk": c.get("reviewer_risk_level") or c["ai_risk_level"],
                "Reason": c["reason"],
            })
        st.table(rows)

    for category in ("Headers", "Footers"):
        category_changes = grouped[category]
        with st.expander(format_group_label(category, category_changes), expanded=has_high_risk(category_changes)):
            if category_changes:
                render_body_rows(category_changes)
            else:
                st.caption("No changes.")

    for category, render_rows in (("Body", render_body_rows), ("Tables", render_table_rows)):
        sections_for_category = grouped[category]
        all_category_changes = [c for section_changes in sections_for_category.values() for c in section_changes]
        with st.expander(format_group_label(category, all_category_changes), expanded=has_high_risk(all_category_changes)):
            if not sections_for_category:
                st.caption("No changes.")
            for section_name, section_changes in sections_for_category.items():
                with st.expander(format_group_label(section_name, section_changes), expanded=has_high_risk(section_changes)):
                    render_rows(section_changes)
