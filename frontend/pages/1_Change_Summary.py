import streamlit as st

from bootstrap import ensure_backend_running

ensure_backend_running()

st.title("Change Summary")

comparison = st.session_state.get("comparison")

if not comparison:
    st.info("Upload and compare two documents on the 'Upload & Compare' page first.")
else:
    summary = comparison["summary"]
    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Total Changes", summary["total_changes"])
    col2.metric("High Risk", summary["high_risk"])
    col3.metric("Medium Risk", summary["medium_risk"])
    col4.metric("Low Risk", summary["low_risk"])
    col5.metric("Informational", summary["informational"])
