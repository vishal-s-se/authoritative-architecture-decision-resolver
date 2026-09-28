import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
os.environ["ADR_DB_PATH"] = "/tmp/adr_seed_test.db"
os.environ["ADR_CONFIG_PATH"] = "/tmp/adr_seed_test_config.json"

from app.database import get_conn, reset_db
from app.seed import generate


SCENARIOS = {
    "newer_draft_vs_older_approved",
    "newer_pending_review",
    "newer_rejected",
    "owner_authority_tiebreak",
    "superseded_newest",
    "approval_conflict",
    "restricted_document_for_viewer",
    "manual_override_active",
    "ambiguous_query",
    "missing_metadata",
    "clean_control",
}


def setup_module(_):
    reset_db()
    generate()


def test_seed_meets_dataset_size_contract():
    conn = get_conn()
    assert conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0] >= 50
    assert conn.execute("SELECT COUNT(*) FROM versions").fetchone()[0] >= 200
    assert conn.execute("SELECT COUNT(*) FROM approvals").fetchone()[0] >= 100
    assert conn.execute("SELECT COUNT(*) FROM owners").fetchone()[0] >= 30
    assert conn.execute("SELECT COUNT(*) FROM access_rules").fetchone()[0] >= 20
    assert conn.execute("SELECT COUNT(*) FROM eval_queries").fetchone()[0] >= 100


def test_every_planted_scenario_has_independent_ground_truth():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM eval_queries").fetchall()
    assert SCENARIOS.issubset({row["scenario_type"] for row in rows})
    valid_behaviors = {"SELECT", "FLAG_CONFLICT", "DENY", "AMBIGUOUS"}
    for row in rows:
        assert row["expected_behavior"] in valid_behaviors
        if row["expected_behavior"] != "SELECT":
            assert row["expected_document_id"] is None
            assert row["expected_version_id"] is None
        else:
            version = conn.execute("SELECT content FROM versions WHERE id=?", (row["expected_version_id"],)).fetchone()
            assert version is not None
            assert row["expected_answer"].lower() in version["content"].lower()
            citation = json.loads(conn.execute("SELECT citations_json FROM versions WHERE id=?", (row["expected_version_id"],)).fetchone()[0])[0]
            assert citation["chunk_id"] in row["expected_citation"]


def test_seed_dates_are_reproducible():
    conn = get_conn()
    first = [tuple(row) for row in conn.execute("SELECT id, created_date, modified_date FROM versions ORDER BY id").fetchall()]
    reset_db()
    generate()
    second_conn = get_conn()
    second = [tuple(row) for row in second_conn.execute("SELECT id, created_date, modified_date FROM versions ORDER BY id").fetchall()]
    assert first == second
