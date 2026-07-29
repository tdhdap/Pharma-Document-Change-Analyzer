import streamlit as st

from api_client import upload_document, compare_documents

st.title("Upload & Compare")

old_file = st.file_uploader("Previous document", type=["pdf", "docx", "txt"], key="old_file")
new_file = st.file_uploader("Revised document", type=["pdf", "docx", "txt"], key="new_file")

if old_file is not None and st.session_state.get("old_filename") != old_file.name:
    st.session_state["old_document"] = upload_document(old_file.name, old_file.getvalue())
    st.session_state["old_filename"] = old_file.name

if new_file is not None and st.session_state.get("new_filename") != new_file.name:
    st.session_state["new_document"] = upload_document(new_file.name, new_file.getvalue())
    st.session_state["new_filename"] = new_file.name

if st.session_state.get("old_document"):
    st.subheader(f"Previous: {st.session_state['old_document']['filename']}")
    st.text_area(
        "Extracted text (previous)",
        "\n\n".join(st.session_state["old_document"]["extracted_text"]),
        height=200,
    )

if st.session_state.get("new_document"):
    st.subheader(f"Revised: {st.session_state['new_document']['filename']}")
    st.text_area(
        "Extracted text (revised)",
        "\n\n".join(st.session_state["new_document"]["extracted_text"]),
        height=200,
    )

if st.session_state.get("old_document") and st.session_state.get("new_document"):
    if st.button("Compare"):
        with st.spinner("Comparing documents..."):
            comparison = compare_documents(
                st.session_state["old_document"]["document_id"],
                st.session_state["new_document"]["document_id"],
            )
        st.session_state["comparison"] = comparison
        st.session_state["comparison_id"] = comparison["comparison_id"]
        st.success(f"Comparison complete: {comparison['summary']['total_changes']} changes found.")
