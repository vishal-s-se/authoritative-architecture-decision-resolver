"""
Tests for the tiered resolver policy.
"""
import os
import sys
import json
import threading

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
os.environ["ADR_DB_PATH"] = "/tmp/adr_test_tiered.db"
os.environ["ADR_CONFIG_PATH"] = "/tmp/adr_test_config.json"

from app.database import reset_db, get_conn
from app import authority

def setup_module(_):
    reset_db()
    conn = get_conn()
    conn.execute("INSERT INTO owners (name, authority_level) VALUES ('Architecture Board', 1.0)")
    conn.execute("INSERT INTO owners (name, authority_level) VALUES ('Developer', 0.5)")
    conn.execute("INSERT INTO documents (id, title, category, created_at) VALUES ('doc-t','Tiered Test','arch','2026-01-01T00:00:00+00:00')")
    conn.commit()


def _owner_id(name):
    return get_conn().execute("SELECT id FROM owners WHERE name=?", (name,)).fetchone()["id"]


def _add_version(doc_id, vnum, status, owner_name, modified_date):
    conn = get_conn()
    vid = f"{doc_id}-v{vnum}"
    conn.execute(
        """INSERT INTO versions (id, document_id, version_number, content, created_date, modified_date,
           status, content_hash, owner_id, citations_json) VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (vid, doc_id, vnum, f"content v{vnum}", modified_date, modified_date, status,
         f"hash{vnum}", _owner_id(owner_name), "[]"),
    )
    conn.commit()
    return vid

def _add_approval(version_id, owner_name, decision, date, reason=""):
    conn = get_conn()
    conn.execute(
        "INSERT INTO approvals (version_id, approver_owner_id, decision, date, reason) VALUES (?,?,?,?,?)",
        (version_id, _owner_id(owner_name), decision, date, reason),
    )
    conn.commit()

def _resolve(doc_id):
    cfg = {
        "resolver_policy": "tiered", 
        "weights": {"approval": 0.40, "ownership": 0.25, "recency": 0.20, "version": 0.10, "evidence": 0.05}, 
        "status_scores": {"APPROVED": 1.0, "DRAFT": 0.2, "REJECTED": 0}, 
        "recency_half_life_days": 180
    }
    return authority.resolve_authority(doc_id, user="test", persist=False, cfg=cfg)

def _reset():
    conn = get_conn()
    conn.execute("DELETE FROM approvals")
    conn.execute("DELETE FROM authoritative")
    conn.execute("DELETE FROM versions")
    conn.commit()

def test_older_board_vs_newer_developer():
    _reset()
    v1 = _add_version("doc-t", 1, "APPROVED", "Architecture Board", "2020-01-01T00:00:00+00:00")
    v2 = _add_version("doc-t", 2, "APPROVED", "Developer", "2026-01-01T00:00:00+00:00")
    _add_approval(v1, "Architecture Board", "APPROVED", "2020-01-01T00:00:00+00:00")
    _add_approval(v2, "Developer", "APPROVED", "2026-01-01T00:00:00+00:00")
    result = _resolve("doc-t")
    assert result["version"]["id"] == v1

def test_equal_recency_approver_authority():
    _reset()
    v1 = _add_version("doc-t", 1, "APPROVED", "Developer", "2026-01-01T00:00:00+00:00")
    v2 = _add_version("doc-t", 2, "APPROVED", "Developer", "2026-01-01T00:00:00+00:00")
    _add_approval(v1, "Developer", "APPROVED", "2026-01-01T00:00:00+00:00")
    _add_approval(v2, "Architecture Board", "APPROVED", "2026-01-01T00:00:00+00:00")
    result = _resolve("doc-t")
    assert result["version"]["id"] == v2

def test_ancient_vs_new_conflicting_rejection():
    _reset()
    v1 = _add_version("doc-t", 1, "APPROVED", "Architecture Board", "2020-01-01T00:00:00+00:00")
    _add_approval(v1, "Architecture Board", "APPROVED", "2020-01-01T00:00:00+00:00")
    _add_approval(v1, "Developer", "REJECTED", "2026-01-01T00:00:00+00:00")
    result = _resolve("doc-t")
    assert result["status"] == "MANUAL_REVIEW_REQUIRED"

def test_revoked_newest_approval():
    _reset()
    v1 = _add_version("doc-t", 1, "APPROVED", "Architecture Board", "2025-01-01T00:00:00+00:00")
    v2 = _add_version("doc-t", 2, "DRAFT", "Architecture Board", "2026-01-01T00:00:00+00:00")
    _add_approval(v1, "Architecture Board", "APPROVED", "2025-01-01T00:00:00+00:00")
    _add_approval(v2, "Architecture Board", "APPROVED", "2026-01-01T00:00:00+00:00")
    _add_approval(v2, "Architecture Board", "REJECTED", "2026-02-01T00:00:00+00:00") # Revoked
    result = _resolve("doc-t")
    assert result["version"]["id"] == v1

def test_override_removed_reresolved():
    _reset()
    v1 = _add_version("doc-t", 1, "APPROVED", "Architecture Board", "2025-01-01T00:00:00+00:00")
    v2 = _add_version("doc-t", 2, "APPROVED", "Developer", "2026-01-01T00:00:00+00:00")
    _add_approval(v1, "Architecture Board", "APPROVED", "2025-01-01T00:00:00+00:00")
    _add_approval(v2, "Developer", "APPROVED", "2026-01-01T00:00:00+00:00")
    
    authority.resolve_authority("doc-t", user="test", persist=True)
    authority.manual_override("doc-t", v2, "admin", "test override")
    authority.rollback("doc-t", "admin")
    
    result = _resolve("doc-t")
    assert result["version"]["id"] == v1
