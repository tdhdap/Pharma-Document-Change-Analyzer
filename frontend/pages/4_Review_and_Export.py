import streamlit as st

from api_client import update_change, export_comparison
from logic import build_change_update_payload

st.title("Review & Export")

comparison = st.session_state.get("comparison")

if not comparison:
    st.info("Upload and compare two documents on the 'Upload & Compare' page first.")
else:
    changes_by_id = {c["change_id"]: c for c in comparison["changes"]}

    editable_rows = [
        {
            "change_id": c["change_id"],
            "section": c["section"],
            "reason": c["reason"],
            "reviewer_risk_level": c.get("reviewer_risk_level") or c["ai_risk_level"],
            "reviewer_comment": c.get("reviewer_comment") or "",
            "accepted": c.get("accepted", False),
        }
        for c in comparison["changes"]
    ]

    edited_rows = st.data_editor(
        editable_rows,
        column_config={
            "reviewer_risk_level": st.column_config.SelectboxColumn(
                options=["High", "Medium", "Low", "Informational"]
            ),
        },
        disabled=["change_id", "section", "reason"],
        hide_index=True,
        key="review_editor",
    )

    if st.button("Save reviewer edits"):
        for edited in edited_rows:
            original = changes_by_id[edited["change_id"]]
            original_row = {
                "reviewer_risk_level": original.get("reviewer_risk_level"),
                "reviewer_comment": original.get("reviewer_comment"),
                "accepted": original.get("accepted", False),
            }
            payload = build_change_update_payload(edited, original_row)
            if payload:
                update_change(edited["change_id"], **payload)
        st.success("Reviewer edits saved.")

    st.divider()
    st.subheader("Export")
    export_format = st.radio("Format", ["json", "csv"], horizontal=True)
    if st.button("Download report"):
        content = export_comparison(comparison["comparison_id"], export_format)
        st.download_button(
            "Save file",
            data=content,
            file_name=f"comparison_{comparison['comparison_id']}.{export_format}",
        )
