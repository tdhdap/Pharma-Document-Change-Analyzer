import sqlite3

from app.db import get_connection
from app.models import Change, ComparisonResult, build_summary, TableCoordinate
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


def test_save_and_get_comparison_round_trip_preserves_source():
    conn = make_conn()
    old_id = repository.create_document(conn, "old.txt", "txt", "/data/old.txt")
    new_id = repository.create_document(conn, "new.txt", "txt", "/data/new.txt")

    changes = [
        Change(
            change_id="ch-1", section="2.0 Acceptance Criteria", change_type="added_table_content",
            old_text="", new_text="Microbial Limits", old_page=None, new_page=1,
            confidence=1.0, ai_risk_level="Medium", reason="New table content added.",
            source="Table",
        ),
    ]
    comparison = ComparisonResult(
        comparison_id="cmp-2", old_document="old.txt", new_document="new.txt",
        summary=build_summary(changes), changes=changes,
    )

    repository.save_comparison(conn, comparison, old_id, new_id)
    fetched = repository.get_comparison(conn, "cmp-2")

    assert fetched.changes[0].source == "Table"


def test_save_and_get_comparison_defaults_source_to_body():
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
        comparison_id="cmp-3", old_document="old.txt", new_document="new.txt",
        summary=build_summary(changes), changes=changes,
    )

    repository.save_comparison(conn, comparison, old_id, new_id)
    fetched = repository.get_comparison(conn, "cmp-3")

    assert fetched.changes[0].source == "Body"


def test_existing_database_missing_source_column_gets_migrated(tmp_path):
    db_path = str(tmp_path / "legacy.db")
    # Simulate a database created before the `source` column existed - this is
    # exactly the shape of the real backend/app.db file found during planning.
    legacy_conn = sqlite3.connect(db_path)
    legacy_conn.execute("""
        CREATE TABLE changes (
            id TEXT PRIMARY KEY, comparison_id TEXT NOT NULL, section TEXT, change_type TEXT,
            old_text TEXT, new_text TEXT, old_page INTEGER, new_page INTEGER, confidence REAL,
            ai_risk_level TEXT, reviewer_risk_level TEXT, reason TEXT, reviewer_comment TEXT,
            accepted INTEGER DEFAULT 0
        )
    """)
    legacy_conn.commit()
    legacy_conn.close()

    conn = get_connection(db_path)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(changes)").fetchall()}

    assert "source" in columns


def test_save_and_get_comparison_round_trip_preserves_table_positions():
    conn = make_conn()
    old_id = repository.create_document(conn, "old.docx", "docx", "/data/old.docx")
    new_id = repository.create_document(conn, "new.docx", "docx", "/data/new.docx")

    old_pos = TableCoordinate(table_id=0, row=1, col=1)
    new_pos = TableCoordinate(table_id=0, row=1, col=1)
    changes = [
        Change(
            change_id="ch-1", section="2.0 Acceptance Criteria", change_type="numeric_change",
            old_text="95%", new_text="98%", old_page=1, new_page=1,
            confidence=1.0, ai_risk_level="High", reason="value changed", source="Table",
            old_table_position=old_pos, new_table_position=new_pos,
        ),
    ]
    comparison = ComparisonResult(
        comparison_id="cmp-table-1", old_document="old.docx", new_document="new.docx",
        summary=build_summary(changes), changes=changes,
    )

    repository.save_comparison(conn, comparison, old_id, new_id)
    fetched = repository.get_comparison(conn, "cmp-table-1")

    assert fetched.changes[0].old_table_position == old_pos
    assert fetched.changes[0].new_table_position == new_pos


def test_save_and_get_comparison_defaults_table_positions_to_none():
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
        comparison_id="cmp-table-2", old_document="old.txt", new_document="new.txt",
        summary=build_summary(changes), changes=changes,
    )

    repository.save_comparison(conn, comparison, old_id, new_id)
    fetched = repository.get_comparison(conn, "cmp-table-2")

    assert fetched.changes[0].old_table_position is None
    assert fetched.changes[0].new_table_position is None


def test_save_and_get_comparison_round_trip_with_only_new_table_position():
    conn = make_conn()
    old_id = repository.create_document(conn, "old.docx", "docx", "/data/old.docx")
    new_id = repository.create_document(conn, "new.docx", "docx", "/data/new.docx")

    new_pos = TableCoordinate(table_id=1, row=3, col=0)
    changes = [
        Change(
            change_id="ch-1", section="2.0 Acceptance Criteria", change_type="added_table_content",
            old_text="", new_text="Microbial Limits", old_page=None, new_page=1,
            confidence=1.0, ai_risk_level="Medium", reason="New table content added.", source="Table",
            old_table_position=None, new_table_position=new_pos,
        ),
    ]
    comparison = ComparisonResult(
        comparison_id="cmp-table-3", old_document="old.docx", new_document="new.docx",
        summary=build_summary(changes), changes=changes,
    )

    repository.save_comparison(conn, comparison, old_id, new_id)
    fetched = repository.get_comparison(conn, "cmp-table-3")

    assert fetched.changes[0].old_table_position is None
    assert fetched.changes[0].new_table_position == new_pos


def test_existing_database_missing_table_position_columns_gets_migrated(tmp_path):
    db_path = str(tmp_path / "legacy_table.db")
    # Simulate a database created before the table-position columns existed - this
    # is exactly the shape of the real backend/app.db file found during planning
    # for the earlier `source` column migration, now missing these 6 columns too.
    legacy_conn = sqlite3.connect(db_path)
    legacy_conn.execute("""
        CREATE TABLE changes (
            id TEXT PRIMARY KEY, comparison_id TEXT NOT NULL, section TEXT, change_type TEXT,
            old_text TEXT, new_text TEXT, old_page INTEGER, new_page INTEGER, confidence REAL,
            ai_risk_level TEXT, reviewer_risk_level TEXT, reason TEXT, reviewer_comment TEXT,
            accepted INTEGER DEFAULT 0, source TEXT DEFAULT 'Body'
        )
    """)
    legacy_conn.commit()
    legacy_conn.close()

    conn = get_connection(db_path)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(changes)").fetchall()}

    for column in ("old_table_id", "old_table_row", "old_table_col", "new_table_id", "new_table_row", "new_table_col"):
        assert column in columns
