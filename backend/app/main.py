import shutil
import uuid
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from app import config, db, repository, extraction, pipeline, export

app = FastAPI(title="Pharma Document Change Analyzer")

SUPPORTED_TYPES = {"pdf", "docx", "txt"}


def _get_conn():
    return db.get_connection(config.DB_PATH)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/documents")
async def upload_document(file: UploadFile = File(...)):
    suffix = Path(file.filename).suffix.lower().lstrip(".")
    if suffix not in SUPPORTED_TYPES:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {suffix}")

    upload_dir = Path(config.UPLOAD_DIR)
    upload_dir.mkdir(parents=True, exist_ok=True)
    temp_name = f"{uuid.uuid4()}_{file.filename}"
    storage_path = str(upload_dir / temp_name)
    with open(storage_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    conn = _get_conn()
    document_id = repository.create_document(conn, file.filename, suffix, storage_path)
    paragraphs = extraction.extract_text(storage_path, suffix)

    return {
        "document_id": document_id,
        "filename": file.filename,
        "extracted_text": [p.text for p in paragraphs],
    }


class ComparePayload(BaseModel):
    old_document_id: str
    new_document_id: str


@app.post("/compare")
def compare(payload: ComparePayload):
    conn = _get_conn()
    old_doc = repository.get_document(conn, payload.old_document_id)
    new_doc = repository.get_document(conn, payload.new_document_id)
    if not old_doc or not new_doc:
        raise HTTPException(status_code=404, detail="Document not found")

    old_paragraphs = extraction.extract_text(old_doc["storage_path"], old_doc["file_type"])
    new_paragraphs = extraction.extract_text(new_doc["storage_path"], new_doc["file_type"])

    result = pipeline.compare_documents(old_paragraphs, new_paragraphs, old_doc["filename"], new_doc["filename"])
    repository.save_comparison(conn, result, payload.old_document_id, payload.new_document_id)
    return export.to_json(result)


@app.get("/comparisons/{comparison_id}")
def get_comparison_endpoint(comparison_id: str):
    conn = _get_conn()
    result = repository.get_comparison(conn, comparison_id)
    if not result:
        raise HTTPException(status_code=404, detail="Comparison not found")
    return export.to_json(result)


class ChangeUpdate(BaseModel):
    reviewer_risk_level: Optional[str] = None
    reviewer_comment: Optional[str] = None
    accepted: Optional[bool] = None


@app.patch("/changes/{change_id}")
def patch_change(change_id: str, payload: ChangeUpdate):
    conn = _get_conn()
    updated = repository.update_change(
        conn, change_id,
        reviewer_risk_level=payload.reviewer_risk_level,
        reviewer_comment=payload.reviewer_comment,
        accepted=payload.accepted,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Change not found")
    return updated


@app.get("/comparisons/{comparison_id}/export")
def export_comparison(comparison_id: str, format: str = "json"):
    conn = _get_conn()
    result = repository.get_comparison(conn, comparison_id)
    if not result:
        raise HTTPException(status_code=404, detail="Comparison not found")
    if format == "csv":
        return PlainTextResponse(export.to_csv(result), media_type="text/csv")
    return export.to_json(result)
