from app.db import get_connection
from app.models import Change, ComparisonResult, build_summary
from app import repository


def make_conn():
    return get_connection(":memory:")


def test_create_and_get_document():
    conn = make_conn()
    doc_id = repository.create_document(conn, "sop_v1.pdf", "pdf", "/data/sop_v1.pdf")
    doc = repository.get_document(conn, doc_id)
    assert doc["filename"] == "sop_v1.pdf"
    assert doc["file_type"] == "pdf"
    assert doc["storage_path"] == "/data/sop_v1.pdf"


def test_get_document_returns_none_when_missing():
    conn = make_conn()
    assert repository.get_document(conn, "does-not-exist") is None


def test_save_and_get_comparison_round_trip():
    conn = make_conn()
    old_id = repository.create_document(conn, "old.txt", "txt", "/data/old.txt")
    new_id = repository.create_document(conn, "new.txt", "txt", "/data/new.txt")

    changes = [
        Change(
            change_id="ch-1", section="1.0 Scope", change_type="numeric_change",
            old_text="95%", new_text="98%", old_page=1, new_page=1,
            confidence=1.0, ai_risk_level="High", reason="value changed",
        ),
    ]
    comparison = ComparisonResult(
        comparison_id="cmp-1", old_document="old.txt", new_document="new.txt",
        summary=build_summary(changes), changes=changes,
    )

    repository.save_comparison(conn, comparison, old_id, new_id)
    fetched = repository.get_comparison(conn, "cmp-1")

    assert fetched is not None
    assert fetched.old_document == "old.txt"
    assert fetched.new_document == "new.txt"
    assert len(fetched.changes) == 1
    assert fetched.changes[0].change_type == "numeric_change"
    assert fetched.summary.high_risk == 1


def test_update_change_sets_reviewer_fields():
    conn = make_conn()
    old_id = repository.create_document(conn, "old.txt", "txt", "/data/old.txt")
    new_id = repository.create_document(conn, "new.txt", "txt", "/data/new.txt")
    changes = [
        Change(
            change_id="ch-1", section="1.0 Scope", change_type="numeric_change",
            old_text="95%", new_text="98%", old_page=1, new_page=1,
            confidence=1.0, ai_risk_level="High", reason="value changed",
        ),
    ]
    comparison = ComparisonResult(
        comparison_id="cmp-1", old_document="old.txt", new_document="new.txt",
        summary=build_summary(changes), changes=changes,
    )
    repository.save_comparison(conn, comparison, old_id, new_id)

    updated = repository.update_change(conn, "ch-1", reviewer_risk_level="Low", accepted=True)
    assert updated["reviewer_risk_level"] == "Low"
    assert updated["accepted"] == 1

    fetched = repository.get_comparison(conn, "cmp-1")
    assert fetched.changes[0].reviewer_risk_level == "Low"
    assert fetched.changes[0].accepted is True
    assert fetched.changes[0].ai_risk_level == "High"


def test_update_change_returns_none_when_missing():
    conn = make_conn()
    assert repository.update_change(conn, "does-not-exist", accepted=True) is None
