import uuid
from datetime import datetime, timezone
from typing import Optional

from app.models import Change, ComparisonResult, build_summary


def create_document(conn, filename: str, file_type: str, storage_path: str) -> str:
    doc_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO documents (id, filename, file_type, storage_path, uploaded_at) VALUES (?, ?, ?, ?, ?)",
        (doc_id, filename, file_type, storage_path, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    return doc_id


def get_document(conn, doc_id: str) -> Optional[dict]:
    row = conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
    return dict(row) if row else None


def save_comparison(conn, comparison: ComparisonResult, old_document_id: str, new_document_id: str) -> None:
    conn.execute(
        "INSERT INTO comparisons (id, old_document_id, new_document_id, created_at) VALUES (?, ?, ?, ?)",
        (comparison.comparison_id, old_document_id, new_document_id, datetime.now(timezone.utc).isoformat()),
    )
    for c in comparison.changes:
        conn.execute(
            """INSERT INTO changes
               (id, comparison_id, section, change_type, old_text, new_text, old_page, new_page,
                confidence, ai_risk_level, reviewer_risk_level, reason, reviewer_comment, accepted)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                c.change_id, comparison.comparison_id, c.section, c.change_type, c.old_text, c.new_text,
                c.old_page, c.new_page, c.confidence, c.ai_risk_level, c.reviewer_risk_level, c.reason,
                c.reviewer_comment, int(c.accepted),
            ),
        )
    conn.commit()


def _row_to_change(row) -> Change:
    return Change(
        change_id=row["id"], section=row["section"], change_type=row["change_type"],
        old_text=row["old_text"], new_text=row["new_text"], old_page=row["old_page"],
        new_page=row["new_page"], confidence=row["confidence"], ai_risk_level=row["ai_risk_level"],
        reason=row["reason"], reviewer_risk_level=row["reviewer_risk_level"],
        reviewer_comment=row["reviewer_comment"], accepted=bool(row["accepted"]),
    )


def get_comparison(conn, comparison_id: str) -> Optional[ComparisonResult]:
    comp_row = conn.execute("SELECT * FROM comparisons WHERE id = ?", (comparison_id,)).fetchone()
    if not comp_row:
        return None
    old_doc = get_document(conn, comp_row["old_document_id"])
    new_doc = get_document(conn, comp_row["new_document_id"])
    change_rows = conn.execute("SELECT * FROM changes WHERE comparison_id = ?", (comparison_id,)).fetchall()
    changes = [_row_to_change(r) for r in change_rows]
    return ComparisonResult(
        comparison_id=comparison_id,
        old_document=old_doc["filename"] if old_doc else "",
        new_document=new_doc["filename"] if new_doc else "",
        summary=build_summary(changes),
        changes=changes,
    )


def update_change(
    conn,
    change_id: str,
    reviewer_risk_level: Optional[str] = None,
    reviewer_comment: Optional[str] = None,
    accepted: Optional[bool] = None,
) -> Optional[dict]:
    existing = conn.execute("SELECT * FROM changes WHERE id = ?", (change_id,)).fetchone()
    if not existing:
        return None

    fields, values = [], []
    if reviewer_risk_level is not None:
        fields.append("reviewer_risk_level = ?")
        values.append(reviewer_risk_level)
    if reviewer_comment is not None:
        fields.append("reviewer_comment = ?")
        values.append(reviewer_comment)
    if accepted is not None:
        fields.append("accepted = ?")
        values.append(int(accepted))

    if fields:
        values.append(change_id)
        conn.execute(f"UPDATE changes SET {', '.join(fields)} WHERE id = ?", values)
        conn.commit()

    updated = conn.execute("SELECT * FROM changes WHERE id = ?", (change_id,)).fetchone()
    return dict(updated)
