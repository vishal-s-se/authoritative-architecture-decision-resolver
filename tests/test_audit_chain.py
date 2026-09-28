import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
os.environ["ADR_DB_PATH"] = "/tmp/adr_audit_test.db"
os.environ["ADR_CONFIG_PATH"] = "/tmp/adr_audit_config.json"

from app.audit import log_event, verify_chain
from app.database import get_conn, reset_db


def setup_function(_):
    reset_db()


def test_audit_chain_verifies_and_reports_tampering():
    log_event("admin", "FIRST", reason="one", metadata={"source": "test"})
    log_event("admin", "SECOND", reason="two")
    assert verify_chain()["valid"] is True
    conn = get_conn()
    conn.execute("UPDATE audit_log SET reason='tampered' WHERE event_id=1")
    conn.commit()
    result = verify_chain()
    assert result["valid"] is False
    assert result["first_broken_event"] == 1


def test_legacy_hash_columns_are_added_safely():
    conn = get_conn()
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(audit_log)").fetchall()}
    assert {"prev_hash", "event_hash"}.issubset(columns)
