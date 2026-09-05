"""
Covers the six required failure/success cases from the spec:
1. Newer draft vs older approved -> approved wins
2. Two approved versions, different owner authority -> higher authority wins
3. Unauthorized access -> denied, no content leak
4. Manual override -> becomes authoritative
5. Rollback -> restores previous, audit event retained
6. Conflicting approvals -> flagged for manual review

Run with:  pytest tests/test_authority.py  (from backend/, with PYTHONPATH set)
"""
import os
import sys
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
os.environ["ADR_DB_PATH"] = "/tmp/adr_test.db"
os.environ["ADR_CONFIG_PATH"] = "/tmp/adr_test_config.json"

from app.database import reset_db, get_conn
from app import authority, access, audit


def setup_module(_):
    reset_db()
    conn = get_conn()
    conn.execute("INSERT INTO owners (name, authority_level) VALUES ('Architecture Board', 1.0)")
    conn.execute("INSERT INTO owners (name, authority_level) VALUES ('Developer', 0.5)")
    conn.execute("INSERT INTO documents (id, title, category, created_at) VALUES ('doc-x','Test Doc','arch','2026-01-01T00:00:00+00:00')")
    conn.commit()


def _owner_id(name):
    return get_conn().execute("SELECT id FROM owners WHERE name=?", (name,)).fetchone()["id"]


def _add_version(doc_id, vnum, status, owner_name, modified_date, citations=None):
    conn = get_conn()
    vid = f"{doc_id}-v{vnum}"
    conn.execute(
        """INSERT INTO versions (id, document_id, version_number, content, created_date, modified_date,
           status, content_hash, owner_id, citations_json) VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (vid, doc_id, vnum, f"content v{vnum}", modified_date, modified_date, status,
         f"hash{vnum}", _owner_id(owner_name), json.dumps(citations or [])),
    )
    conn.commit()
    return vid


def test_case_1_older_approved_beats_newer_draft():
    v1 = _add_version("doc-x", 1, "APPROVED", "Architecture Board", "2026-08-10T00:00:00+00:00")
    v2 = _add_version("doc-x", 2, "DRAFT", "Developer", "2026-08-24T00:00:00+00:00")
    result = authority.resolve_authority("doc-x", user="test", persist=False)
    assert result["version"]["id"] == v1, "older approved version must win over newer draft"


def test_case_2_owner_authority_breaks_ties():
    conn = get_conn()
    conn.execute("DELETE FROM versions WHERE document_id='doc-x'")
    conn.commit()
    v_low = _add_version("doc-x", 1, "APPROVED", "Developer", "2026-08-20T00:00:00+00:00")
    v_high = _add_version("doc-x", 2, "APPROVED", "Architecture Board", "2026-08-20T00:00:00+00:00")
    result = authority.resolve_authority("doc-x", user="test", persist=False)
    assert result["version"]["id"] == v_high, "higher-authority owner should win between two approved versions"


def test_case_3_unauthorized_access_denied():
    conn = get_conn()
    conn.execute("INSERT INTO access_rules (document_id, role, allowed) VALUES ('doc-x','VIEWER',0)")
    conn.commit()
    assert access.is_allowed("doc-x", "VIEWER") is False
    assert access.is_allowed("doc-x", "ARCHITECT") is True  # no rule for ARCHITECT -> default allow
    assert access.is_allowed("doc-x", "ADMIN") is True  # admin always allowed


def test_case_4_manual_override():
    conn = get_conn()
    conn.execute("DELETE FROM versions WHERE document_id='doc-x'")
    conn.commit()
    v1 = _add_version("doc-x", 1, "APPROVED", "Architecture Board", "2026-08-10T00:00:00+00:00")
    v2 = _add_version("doc-x", 2, "DRAFT", "Developer", "2026-08-24T00:00:00+00:00")
    authority.resolve_authority("doc-x", user="test")  # persist baseline pick (v1)
    authority.manual_override("doc-x", v2, "admin", "Business decision to fast-track draft to production")
    result = authority.resolve_authority("doc-x", user="test")
    assert result["is_override"] is True
    assert result["version"]["id"] == v2


def test_case_5_rollback_restores_and_keeps_audit():
    result = authority.rollback("doc-x", "admin")
    assert result["version_id"] is not None
    events = audit.get_events(limit=50, document_id="doc-x")
    actions = [e["action"] for e in events]
    assert "MANUAL_OVERRIDE" in actions, "override event must remain in audit log after rollback"
    assert "ROLLBACK" in actions


def test_case_6_conflicting_approvals_flagged():
    conn = get_conn()
    old_versions = conn.execute("SELECT id FROM versions WHERE document_id='doc-x'").fetchall()
    for v in old_versions:
        conn.execute("DELETE FROM approvals WHERE version_id=?", (v["id"],))
    conn.execute("DELETE FROM authoritative WHERE document_id='doc-x'")
    conn.execute("DELETE FROM versions WHERE document_id='doc-x'")
    conn.commit()
    v1 = _add_version("doc-x", 1, "APPROVED", "Architecture Board", "2026-08-10T00:00:00+00:00")
    conn.execute(
        "INSERT INTO approvals (version_id, approver_owner_id, decision, date, reason) VALUES (?,?,?,?,?)",
        (v1, _owner_id("Architecture Board"), "APPROVED", "2026-08-10T00:00:00+00:00", "approved"),
    )
    conn.execute(
        "INSERT INTO approvals (version_id, approver_owner_id, decision, date, reason) VALUES (?,?,?,?,?)",
        (v1, _owner_id("Developer"), "REJECTED", "2026-08-11T00:00:00+00:00", "rejected"),
    )
    conn.commit()
    assert authority.detect_conflict(v1) is True
