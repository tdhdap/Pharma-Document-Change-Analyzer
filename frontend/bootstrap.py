import os
import subprocess
import sys
import time

import requests
import streamlit as st

API_BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8000")

_BACKEND_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend")


def _backend_is_reachable() -> bool:
    try:
        requests.get(f"{API_BASE_URL}/health", timeout=1)
        return True
    except requests.exceptions.RequestException:
        return False


def ensure_backend_running() -> None:
    """Start the FastAPI backend as a background process if it isn't already
    reachable. This lets the whole app (frontend + backend) run inside a
    single Streamlit Community Cloud deployment, which only runs one process
    natively. Safe to call from every page - it's a no-op once the backend
    is already up."""
    if _backend_is_reachable():
        return

    try:
        os.environ["GEMINI_API_KEY"] = st.secrets["GEMINI_API_KEY"]
    except Exception:
        pass

    subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"],
        cwd=_BACKEND_DIR,
    )

    with st.spinner("Starting backend service (first load only)..."):
        for _ in range(60):
            if _backend_is_reachable():
                return
            time.sleep(1)

    st.error("Backend did not start in time. Try refreshing the page.")
