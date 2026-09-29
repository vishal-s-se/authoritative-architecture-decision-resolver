"""
SQLite database layer for the Authoritative Architecture Decision Resolver.
Responsibility: Provides ANSI-SQL data storage and connection lifecycle management.
What it must never do: It must never encode business rules like authority scoring.
Designed so migration to PostgreSQL only requires swapping the connection
layer (all SQL is standard ANSI SQL, no SQLite-only syntax used except
AUTOINCREMENT which has a direct Postgres equivalent).
"""
import sqlite3
import os
import threading

DB_PATH = os.environ.get("ADR_DB_PATH", os.path.join(os.path.dirname(__file__), "..", "..", "data", "adr.db"))
DB_PATH = os.path.abspath(DB_PATH)

_local = threading.local()
_connections = set()
_connections_lock = threading.Lock()


def get_conn():
    if hasattr(_local, "conn"):
        try:
            _local.conn.execute("SELECT 1")
        except sqlite3.ProgrammingError:
            del _local.conn
    if not hasattr(_local, "conn"):
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        _local.conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _local.conn.row_factory = sqlite3.Row
        _local.conn.execute("PRAGMA foreign_keys = ON")
        with _connections_lock:
            _connections.add(_local.conn)
    return _local.conn


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('ADMIN','ARCHITECT','ENGINEER','VIEWER'))
);

CREATE TABLE IF NOT EXISTS owners (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    authority_level REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    category TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS versions (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents(id),
    version_number INTEGER NOT NULL,
    content TEXT NOT NULL,
    created_date TEXT NOT NULL,
    modified_date TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('APPROVED','DRAFT','REJECTED','SUPERSEDED','ARCHIVED','PENDING_REVIEW')),
    content_hash TEXT NOT NULL,
    owner_id INTEGER REFERENCES owners(id),
    citations_json TEXT
);

CREATE TABLE IF NOT EXISTS version_chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    version_id TEXT NOT NULL REFERENCES versions(id),
    chunk_id TEXT NOT NULL UNIQUE,
    section TEXT,
    page INTEGER,
    source_text TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS approvals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    version_id TEXT NOT NULL REFERENCES versions(id),
    approver_owner_id INTEGER NOT NULL REFERENCES owners(id),
    decision TEXT NOT NULL CHECK(decision IN ('APPROVED','REJECTED','PENDING_REVIEW')),
    date TEXT NOT NULL,
    reason TEXT
);

CREATE TABLE IF NOT EXISTS access_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id TEXT NOT NULL REFERENCES documents(id),
    role TEXT NOT NULL,
    allowed INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS authoritative (
    document_id TEXT PRIMARY KEY REFERENCES documents(id),
    version_id TEXT NOT NULL REFERENCES versions(id),
    score REAL NOT NULL,
    breakdown_json TEXT,
    is_override INTEGER NOT NULL DEFAULT 0,
    override_reason TEXT,
    override_by TEXT,
    previous_version_id TEXT,
    previous_score REAL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_log (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    user TEXT,
    action TEXT NOT NULL,
    document_id TEXT,
    version_id TEXT,
    previous_value TEXT,
    new_value TEXT,
    reason TEXT,
    metadata_json TEXT,
    prev_hash TEXT,
    event_hash TEXT
);

CREATE TABLE IF NOT EXISTS pending_changes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action TEXT NOT NULL,
    document_id TEXT,
    version_id TEXT,
    requested_by TEXT NOT NULL,
    reason TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('PENDING','APPROVED','REJECTED')) DEFAULT 'PENDING',
    reviewed_by TEXT,
    created_at TEXT NOT NULL,
    reviewed_at TEXT
);

CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    query TEXT,
    answer_clear INTEGER,
    source_clear INTEGER,
    citation_useful INTEGER,
    increased_trust INTEGER,
    would_use INTEGER,
    comment TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS eval_queries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    query TEXT NOT NULL,
    expected_document_id TEXT,
    expected_version_id TEXT,
    expected_answer TEXT,
    expected_citation TEXT,
    category TEXT,
    scenario_type TEXT,
    expected_behavior TEXT
);

CREATE TABLE IF NOT EXISTS eval_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    mode TEXT NOT NULL,
    created_at TEXT NOT NULL,
    metrics_json TEXT NOT NULL
);
"""


def init_db():
    conn = get_conn()
    conn.executescript(SCHEMA)
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(eval_queries)").fetchall()}
    if "scenario_type" not in columns:
        conn.execute("ALTER TABLE eval_queries ADD COLUMN scenario_type TEXT")
    if "expected_behavior" not in columns:
        conn.execute("ALTER TABLE eval_queries ADD COLUMN expected_behavior TEXT")
    audit_columns = {row["name"] for row in conn.execute("PRAGMA table_info(audit_log)").fetchall()}
    if "prev_hash" not in audit_columns:
        conn.execute("ALTER TABLE audit_log ADD COLUMN prev_hash TEXT")
    if "event_hash" not in audit_columns:
        conn.execute("ALTER TABLE audit_log ADD COLUMN event_hash TEXT")
    feedback_columns = {row["name"] for row in conn.execute("PRAGMA table_info(feedback)").fetchall()}
    if "comment" not in feedback_columns:
        conn.execute("ALTER TABLE feedback ADD COLUMN comment TEXT")
    conn.commit()


def reset_db():
    with _connections_lock:
        connections = list(_connections)
        _connections.clear()
    for conn in connections:
        conn.close()
    if hasattr(_local, "conn"):
        del _local.conn
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    if hasattr(_local, "conn"):
        del _local.conn
    init_db()
