import os

import requests

API_BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8000")


def upload_document(file_name: str, file_bytes: bytes) -> dict:
    response = requests.post(
        f"{API_BASE_URL}/documents",
        files={"file": (file_name, file_bytes)},
    )
    response.raise_for_status()
    return response.json()


def compare_documents(old_document_id: str, new_document_id: str) -> dict:
    response = requests.post(
        f"{API_BASE_URL}/compare",
        json={"old_document_id": old_document_id, "new_document_id": new_document_id},
    )
    response.raise_for_status()
    return response.json()


def get_comparison(comparison_id: str) -> dict:
    response = requests.get(f"{API_BASE_URL}/comparisons/{comparison_id}")
    response.raise_for_status()
    return response.json()


def update_change(change_id: str, **fields) -> dict:
    response = requests.patch(f"{API_BASE_URL}/changes/{change_id}", json=fields)
    response.raise_for_status()
    return response.json()


def export_comparison(comparison_id: str, fmt: str) -> bytes:
    response = requests.get(
        f"{API_BASE_URL}/comparisons/{comparison_id}/export",
        params={"format": fmt},
    )
    response.raise_for_status()
    return response.content
