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

    st.subheader("Structural Changes")
    # .get with a default so a summary produced before these fields existed
    # renders as zeros instead of taking the whole page down with a KeyError.
    # Every label is prefixed "Sections" because the report below also contains
    # moved paragraphs, moved table content, and added/deleted table rows - a bare
    # "Moved" would be read against any of those. The Cascaded tooltip is required,
    # not decorative: the word is not self-explanatory.
    s1, s2, s3, s4, s5, s6 = st.columns(6)
    s1.metric("Sections Added", summary.get("sections_added", 0),
              help="A section present in the new document only.")
    s2.metric("Sections Deleted", summary.get("sections_deleted", 0),
              help="A section present in the old document only.")
    s3.metric("Sections Renamed", summary.get("sections_renamed", 0),
              help="Heading wording changed.")
    s4.metric("Sections Renumbered", summary.get("sections_renumbered", 0),
              help="Section number changed deliberately.")
    s5.metric("Sections Cascaded", summary.get("sections_cascaded", 0),
              help="Number shifted only because a section above was added or "
                   "removed; wording unchanged.")
    s6.metric("Sections Moved", summary.get("sections_moved", 0),
              help="Section changed position in the document.")
