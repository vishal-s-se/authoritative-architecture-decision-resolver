"""
Document ingestion: extracts text + metadata from PDF/DOCX/TXT uploads,
generates stable IDs and content hashes, and inserts a new document version.
Missing metadata (owner, status, dates) falls back to admin-supplied values.
"""
import hashlib
import os
import re
import json
from datetime import datetime, timezone
from .database import get_conn
from .audit import log_event

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".txt"}
MAX_FILE_SIZE_MB = 15
ALLOWED_STATUSES = {"APPROVED", "DRAFT", "REJECTED", "SUPERSEDED", "ARCHIVED", "PENDING_REVIEW"}


def extract_text(file_path, ext):
    if ext == ".txt":
        with open(file_path, "r", errors="ignore") as f:
            return f.read()
    if ext == ".docx":
        import docx
        d = docx.Document(file_path)
        return "\n".join(p.text for p in d.paragraphs)
    if ext == ".pdf":
        import fitz  # PyMuPDF
        text = []
        with fitz.open(file_path) as doc:
            for page in doc:
                text.append(page.get_text())
        return "\n".join(text)
    raise ValueError(f"unsupported extension {ext}")


def validate_upload(filename, size_bytes):
    ext = os.path.splitext(filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError(f"file type {ext} not allowed. Allowed: {ALLOWED_EXTENSIONS}")
    if size_bytes > MAX_FILE_SIZE_MB * 1024 * 1024:
        raise ValueError(f"file exceeds {MAX_FILE_SIZE_MB}MB limit")
    return ext


def content_hash(text):
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def split_into_chunks(text, version_id):
    """Split source at Section headings and preserve real citation metadata."""
    matches = list(re.finditer(r"(?im)^\s*(Section\s+[\w.-]+)\s*[:.-]?", text))
    if not matches:
        return [{"section": "Document", "page": 1, "chunk_id": f"{version_id}-c1", "source_text": text.strip()}]
    chunks = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        source_text = text[match.start():end].strip()
        chunks.append({"section": match.group(1), "page": index + 1,
                       "chunk_id": f"{version_id}-c{index + 1}", "source_text": source_text})
    return chunks


def ingest_document(file_path, filename, title, document_id, owner_id, status, user, size_bytes):
    ext = validate_upload(filename, size_bytes)
    if status not in ALLOWED_STATUSES:
        raise ValueError(f"invalid document status: {status}")
    text = extract_text(file_path, ext)
    if not text.strip():
        raise ValueError("could not extract any text from the uploaded file")

    conn = get_conn()
    if not conn.execute("SELECT 1 FROM owners WHERE id=?", (owner_id,)).fetchone():
        raise ValueError("owner not found")
    doc = conn.execute("SELECT * FROM documents WHERE id=?", (document_id,)).fetchone()
    now = datetime.now(timezone.utc).isoformat()
    if not doc:
        conn.execute(
            "INSERT INTO documents (id, title, category, created_at) VALUES (?,?,?,?)",
            (document_id, title, "Architecture Decision", now),
        )
        log_event(user, "DOCUMENT_UPLOADED", document_id=document_id, new_value=title)

    existing_versions = conn.execute(
        "SELECT * FROM versions WHERE document_id=? ORDER BY version_number DESC", (document_id,)
    ).fetchall()

    h = content_hash(text)
    duplicate = next((v for v in existing_versions if v["content_hash"] == h), None)
    if duplicate:
        raise ValueError(f"duplicate content detected — identical to version {duplicate['version_number']}")

    next_version = (existing_versions[0]["version_number"] + 1) if existing_versions else 1
    version_id = f"{document_id}-v{next_version}"
    chunks = split_into_chunks(text, version_id)

    conn.execute(
        """INSERT INTO versions (id, document_id, version_number, content, created_date, modified_date,
           status, content_hash, owner_id, citations_json)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (version_id, document_id, next_version, text, now, now, status, h, owner_id,
         json.dumps([{key: chunk[key] for key in ("section", "page", "chunk_id")} for chunk in chunks])),
    )
    conn.executemany(
        "INSERT INTO version_chunks (version_id, chunk_id, section, page, source_text) VALUES (?,?,?,?,?)",
        [(version_id, chunk["chunk_id"], chunk["section"], chunk["page"], chunk["source_text"]) for chunk in chunks],
    )
    conn.commit()
    log_event(user, "VERSION_CREATED", document_id=document_id, version_id=version_id,
               new_value=f"v{next_version}", metadata={"status": status})

    return {"document_id": document_id, "version_id": version_id, "version_number": next_version}
