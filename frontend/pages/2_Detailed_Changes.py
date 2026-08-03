import streamlit as st

from logic import filter_changes
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

    st.table([
        {
            "Section": c["section"],
            "Old Text": c["old_text"],
            "New Text": c["new_text"],
            "Change Type": c["change_type"],
            "Risk": c.get("reviewer_risk_level") or c["ai_risk_level"],
            "Reason": c["reason"],
        }
        for c in filtered
    ])
