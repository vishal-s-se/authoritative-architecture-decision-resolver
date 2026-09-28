import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
os.environ["ADR_DB_PATH"] = "/tmp/adr_ingestion_test.db"
os.environ["ADR_CONFIG_PATH"] = "/tmp/adr_ingestion_config.json"

from app.database import get_conn, reset_db
from app.ingestion import ingest_document, split_into_chunks


def setup_module(_):
    reset_db()
    conn = get_conn()
    conn.execute("INSERT INTO owners (name, authority_level) VALUES ('Architecture Board', 1.0)")
    conn.commit()


def test_split_sections_has_real_metadata():
    chunks = split_into_chunks("Section 1: Overview\nfirst\nSection 2: Decision\nsecond", "doc-v1")
    assert [chunk["chunk_id"] for chunk in chunks] == ["doc-v1-c1", "doc-v1-c2"]
    assert chunks[1]["section"] == "Section 2"
    assert chunks[1]["source_text"].endswith("second")


def test_ingestion_persists_chunks_and_citations(tmp_path: Path):
    source = tmp_path / "decision.txt"
    source.write_text("Section 1: Overview\nOAuth\nSection 2: Decision\nUse OAuth.", encoding="utf-8")
    owner_id = get_conn().execute("SELECT id FROM owners").fetchone()[0]
    ingest_document(str(source), "decision.txt", "Decision", "doc-chunks", owner_id, "APPROVED", "admin", source.stat().st_size)
    conn = get_conn()
    version = conn.execute("SELECT * FROM versions WHERE id='doc-chunks-v1'").fetchone()
    citations = json.loads(version["citations_json"])
    assert len(citations) == 2
    assert conn.execute("SELECT COUNT(*) FROM version_chunks WHERE version_id='doc-chunks-v1'").fetchone()[0] == 2
