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
    accepted INTEGER DEFAULT 0
);
"""


def get_connection(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn
