import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    filename TEXT NOT NULL,
    file_type TEXT NOT NULL,
    storage_path TEXT NOT NULL,
    uploaded_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS comparisons (
    id TEXT PRIMARY KEY,
    old_document_id TEXT NOT NULL,
    new_document_id TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS changes (
    id TEXT PRIMARY KEY,
    comparison_id TEXT NOT NULL,
    section TEXT,
    change_type TEXT,
    old_text TEXT,
    new_text TEXT,
    old_page INTEGER,
    new_page INTEGER,
    confidence REAL,
    ai_risk_level TEXT,
    reviewer_risk_level TEXT,
    reason TEXT,
    reviewer_comment TEXT,
    accepted INTEGER DEFAULT 0,
    source TEXT DEFAULT 'Body',
    old_table_id INTEGER,
    old_table_row INTEGER,
    old_table_col INTEGER,
    new_table_id INTEGER,
    new_table_row INTEGER,
    new_table_col INTEGER
);
"""


def _ensure_changes_source_column(conn: sqlite3.Connection) -> None:
    # CREATE TABLE IF NOT EXISTS above only applies to brand-new databases - it does
    # not add columns to a changes table that already exists from before this field
    # was introduced. Any pre-existing database (including the real backend/app.db
    # file already in use) needs this explicit, idempotent migration instead.
    columns = {row[1] for row in conn.execute("PRAGMA table_info(changes)").fetchall()}
    if "source" not in columns:
        conn.execute("ALTER TABLE changes ADD COLUMN source TEXT DEFAULT 'Body'")
        conn.commit()


def _ensure_changes_table_position_columns(conn: sqlite3.Connection) -> None:
    # Same rationale as _ensure_changes_source_column above - a pre-existing changes
    # table (including the real backend/app.db file) needs these added explicitly.
    columns = {row[1] for row in conn.execute("PRAGMA table_info(changes)").fetchall()}
    new_columns = [
        "old_table_id", "old_table_row", "old_table_col",
        "new_table_id", "new_table_row", "new_table_col",
    ]
    for column in new_columns:
        if column not in columns:
            conn.execute(f"ALTER TABLE changes ADD COLUMN {column} INTEGER")
    conn.commit()


def get_connection(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    _ensure_changes_source_column(conn)
    _ensure_changes_table_position_columns(conn)
    return conn
