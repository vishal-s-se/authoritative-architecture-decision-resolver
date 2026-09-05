import os
import json
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, UploadFile, File, Form, Header, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from passlib.hash import bcrypt

from .database import init_db, get_conn, reset_db
from .config import load_config, save_config
from .audit import log_event, get_events
from .authority import resolve_authority, baseline_resolve, manual_override, rollback, get_versions_for_document
from .access import is_allowed, check_access_or_log, ROLE_RANK
from .retrieval import search, build_index
from .ai import answer_question
from .ingestion import ingest_document, ALLOWED_EXTENSIONS
from .seed import generate as seed_generate
from .evaluation import run_evaluation, latest_results

app = FastAPI(title="Authoritative Architecture Decision Resolver")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

TOKENS = {}  # in-memory session token -> user row (simple demo auth)


def ensure_default_users():
    """
    Guarantees the demo accounts always exist and can log in, even on a
    completely fresh database — otherwise there would be no way to obtain
    an ADMIN token to trigger the full synthetic dataset seed in the first
    place (a chicken-and-egg problem). Full document/version/approval data
    is still only populated via the explicit, admin-gated /api/admin/seed
    action described in credentials_login.txt.
    """
    conn = get_conn()
    demo_users = [
        ("admin", "admin123", "ADMIN"),
        ("architect1", "architect123", "ARCHITECT"),
        ("engineer1", "engineer123", "ENGINEER"),
        ("viewer1", "viewer123", "VIEWER"),
    ]
    for uname, pwd, role in demo_users:
        conn.execute(
            "INSERT OR IGNORE INTO users (username, password_hash, role) VALUES (?,?,?)",
            (uname, bcrypt.hash(pwd), role),
        )
    conn.commit()


@app.on_event("startup")
def startup():
    init_db()
    ensure_default_users()
    cfg = load_config()
    save_config(cfg)


# ---------------------------------------------------------------- AUTH ----
class LoginRequest(BaseModel):
    username: str
    password: str


@app.post("/api/auth/login")
def login(body: LoginRequest):
    conn = get_conn()
    row = conn.execute("SELECT * FROM users WHERE username=?", (body.username,)).fetchone()
    if not row or not bcrypt.verify(body.password, row["password_hash"]):
        raise HTTPException(401, "invalid credentials")
    token = str(uuid.uuid4())
    TOKENS[token] = {"username": row["username"], "role": row["role"]}
    log_event(row["username"], "LOGIN")
    return {"token": token, "username": row["username"], "role": row["role"]}


def current_user(authorization: Optional[str] = Header(None)):
    if not authorization:
        return {"username": "anonymous", "role": "VIEWER"}
    token = authorization.replace("Bearer ", "")
    return TOKENS.get(token, {"username": "anonymous", "role": "VIEWER"})


def require_admin(user=Depends(current_user)):
    if user["role"] != "ADMIN":
        raise HTTPException(403, "administrator role required")
    return user


# ------------------------------------------------------------- DASHBOARD --
@app.get("/api/dashboard")
def dashboard():
    conn = get_conn()
    total_docs = conn.execute("SELECT COUNT(*) c FROM documents").fetchone()["c"]
    total_versions = conn.execute("SELECT COUNT(*) c FROM versions").fetchone()["c"]
    approved = conn.execute("SELECT COUNT(*) c FROM versions WHERE status='APPROVED'").fetchone()["c"]
    draft = conn.execute("SELECT COUNT(*) c FROM versions WHERE status='DRAFT'").fetchone()["c"]
    authoritative_count = conn.execute("SELECT COUNT(*) c FROM authoritative").fetchone()["c"]
    overrides = conn.execute("SELECT COUNT(*) c FROM authoritative WHERE is_override=1").fetchone()["c"]
    recent = get_events(limit=10)

    # authority conflicts: versions with both APPROVED and REJECTED decisions
    conflict_rows = conn.execute(
        """SELECT version_id, GROUP_CONCAT(DISTINCT decision) decisions FROM approvals
           GROUP BY version_id HAVING decisions LIKE '%APPROVED%' AND decisions LIKE '%REJECTED%'"""
    ).fetchall()

    return {
        "total_documents": total_docs,
        "total_versions": total_versions,
        "approved_versions": approved,
        "draft_versions": draft,
        "authoritative_documents": authoritative_count,
        "manual_overrides": overrides,
        "recent_audit_events": recent,
        "authority_conflicts": len(conflict_rows),
    }


# ------------------------------------------------------------- DOCUMENTS --
@app.get("/api/documents")
def list_documents(user=Depends(current_user)):
    conn = get_conn()
    docs = conn.execute("SELECT * FROM documents ORDER BY title").fetchall()
    out = []
    for d in docs:
        versions = get_versions_for_document(d["id"])
        auth_row = conn.execute("SELECT * FROM authoritative WHERE document_id=?", (d["id"],)).fetchone()
        out.append({
            "id": d["id"], "title": d["title"], "category": d["category"],
            "version_count": len(versions),
            "accessible": is_allowed(d["id"], user["role"]),
            "authoritative_version": auth_row["version_id"] if auth_row else None,
            "is_override": bool(auth_row["is_override"]) if auth_row else False,
        })
    return out


@app.get("/api/documents/{document_id}")
def get_document(document_id: str, user=Depends(current_user)):
    if not check_access_or_log(document_id, user["role"], user["username"], "VIEW_DOCUMENT"):
        raise HTTPException(403, "access denied")
    conn = get_conn()
    doc = conn.execute("SELECT * FROM documents WHERE id=?", (document_id,)).fetchone()
    if not doc:
        raise HTTPException(404, "document not found")
    versions = get_versions_for_document(document_id)
    for v in versions:
        v["approvals"] = conn.execute(
            """SELECT approvals.*, owners.name as approver_name FROM approvals
               JOIN owners ON approvals.approver_owner_id = owners.id WHERE version_id=?""",
            (v["id"],),
        ).fetchall()
        v["approvals"] = [dict(a) for a in v["approvals"]]
    return {"document": dict(doc), "versions": versions}


@app.post("/api/documents/upload")
async def upload_document(
    file: UploadFile = File(...),
    title: str = Form(...),
    document_id: str = Form(...),
    owner_id: int = Form(...),
    status: str = Form("DRAFT"),
    user=Depends(current_user),
):
    if user["role"] not in ("ADMIN", "ARCHITECT"):
        raise HTTPException(403, "only architects/admins may upload documents")
    contents = await file.read()
    tmp_path = f"/tmp/{uuid.uuid4()}_{file.filename}"
    with open(tmp_path, "wb") as f:
        f.write(contents)
    try:
        result = ingest_document(tmp_path, file.filename, title, document_id, owner_id, status,
                                   user["username"], len(contents))
    except ValueError as e:
        raise HTTPException(400, str(e))
    finally:
        os.remove(tmp_path)
    build_index()
    resolve_authority(document_id, user=user["username"])
    return result


# -------------------------------------------------------------- OWNERS ----
@app.get("/api/owners")
def list_owners():
    conn = get_conn()
    return [dict(r) for r in conn.execute("SELECT * FROM owners ORDER BY authority_level DESC").fetchall()]


# ---------------------------------------------------------- AUTHORITY -----
@app.get("/api/authority/{document_id}")
def get_authority(document_id: str, user=Depends(current_user)):
    if not check_access_or_log(document_id, user["role"], user["username"], "VIEW_AUTHORITY"):
        raise HTTPException(403, "access denied")
    result = resolve_authority(document_id, user=user["username"])
    if not result:
        raise HTTPException(404, "no versions found for document")
    result["version"] = dict(result["version"])
    return result


@app.get("/api/authority/{document_id}/baseline")
def get_baseline(document_id: str):
    result = baseline_resolve(document_id)
    if not result:
        raise HTTPException(404, "no versions found for document")
    result["version"] = dict(result["version"])
    return result


class OverrideRequest(BaseModel):
    version_id: str
    reason: str


@app.post("/api/authority/{document_id}/override")
def override(document_id: str, body: OverrideRequest, user=Depends(require_admin)):
    if not body.reason or len(body.reason.strip()) < 5:
        raise HTTPException(400, "a meaningful reason is required for manual override")
    try:
        return manual_override(document_id, body.version_id, user["username"], body.reason)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/authority/{document_id}/rollback")
def do_rollback(document_id: str, user=Depends(require_admin)):
    try:
        return rollback(document_id, user["username"])
    except ValueError as e:
        raise HTTPException(400, str(e))


# --------------------------------------------------------------- ASK AI ---
class AskRequest(BaseModel):
    question: str


@app.post("/api/ask")
def ask(body: AskRequest, user=Depends(current_user)):
    candidates = search(body.question, top_k=5)
    if not candidates:
        log_event(user["username"], "QUERY_ANSWERED", reason=body.question,
                   metadata={"result": "no_candidates"})
        return {"answer": "No relevant documents were found for this question.", "candidates": []}

    top = candidates[0]
    document_id = top["document_id"]

    if not check_access_or_log(document_id, user["role"], user["username"], "ASK_AI"):
        return {
            "answer": "You do not have permission to access the authoritative source for this question. "
                      "Please request access from an administrator.",
            "access_denied": True,
        }

    conn = get_conn()
    doc = conn.execute("SELECT * FROM documents WHERE id=?", (document_id,)).fetchone()
    result = resolve_authority(document_id, user=user["username"])
    if not result:
        raise HTTPException(404, "could not resolve an authoritative version")

    version = dict(result["version"])
    ai_result = answer_question(body.question, version, doc["title"])

    log_event(user["username"], "QUERY_ANSWERED", document_id=document_id, version_id=version["id"],
               reason=body.question, metadata={"grounded": ai_result["grounded"]})

    return {
        "answer": ai_result["answer"],
        "grounded": ai_result["grounded"],
        "document_title": doc["title"],
        "document_id": document_id,
        "version_number": version["version_number"],
        "version_id": version["id"],
        "status": version["status"],
        "authority_score": result["score"],
        "breakdown": result["breakdown"],
        "conflict": result["conflict"],
        "is_override": result["is_override"],
        "override_reason": result.get("override_reason"),
        "citation": ai_result["citation"],
        "candidates": candidates,
        "relevance_note": "Retrieval selected candidate documents by relevance; the authority resolver "
                           "then independently selected the authoritative VERSION of the top candidate.",
    }


# -------------------------------------------------------------- AUDIT -----
@app.get("/api/audit")
def audit_trail(document_id: Optional[str] = None, limit: int = 200):
    return get_events(limit=limit, document_id=document_id)


# ------------------------------------------------------------- SETTINGS ---
@app.get("/api/settings")
def get_settings():
    return load_config()


class SettingsRequest(BaseModel):
    weights: Optional[dict] = None
    status_scores: Optional[dict] = None
    recency_half_life_days: Optional[int] = None


@app.post("/api/settings")
def update_settings(body: SettingsRequest, user=Depends(require_admin)):
    cfg = load_config()
    if body.weights:
        total = sum(body.weights.values())
        if abs(total - 1.0) > 0.01:
            raise HTTPException(400, f"weights must sum to 1.0 (got {total})")
        cfg["weights"] = body.weights
    if body.status_scores:
        cfg["status_scores"] = body.status_scores
    if body.recency_half_life_days:
        cfg["recency_half_life_days"] = body.recency_half_life_days
    save_config(cfg)
    log_event(user["username"], "SETTINGS_UPDATED", new_value=json.dumps(cfg))
    return cfg


# --------------------------------------------------------------- SEED -----
@app.post("/api/admin/seed")
def admin_seed(user=Depends(require_admin)):
    reset_db()
    stats = seed_generate()
    build_index()
    # resolve authority for every document immediately after seeding
    conn = get_conn()
    for row in conn.execute("SELECT id FROM documents").fetchall():
        resolve_authority(row["id"], user="system")
    return stats


# --------------------------------------------------------------- EVAL -----
@app.post("/api/eval/run")
def eval_run(mode: str, user=Depends(current_user)):
    if mode not in ("baseline", "proposed"):
        raise HTTPException(400, "mode must be 'baseline' or 'proposed'")
    return run_evaluation(mode)


@app.get("/api/eval/results")
def eval_results():
    return latest_results()


@app.get("/api/eval/queries")
def eval_queries():
    conn = get_conn()
    return [dict(r) for r in conn.execute("SELECT * FROM eval_queries LIMIT 100").fetchall()]


# ------------------------------------------------------------ FEEDBACK ----
class FeedbackRequest(BaseModel):
    query: str
    answer_clear: bool
    source_clear: bool
    citation_useful: bool
    increased_trust: bool
    would_use: bool


@app.post("/api/feedback")
def submit_feedback(body: FeedbackRequest):
    conn = get_conn()
    conn.execute(
        """INSERT INTO feedback (query, answer_clear, source_clear, citation_useful, increased_trust, would_use, created_at)
           VALUES (?,?,?,?,?,?,?)""",
        (body.query, body.answer_clear, body.source_clear, body.citation_useful,
         body.increased_trust, body.would_use, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    return {"ok": True}


@app.get("/api/feedback/summary")
def feedback_summary():
    conn = get_conn()
    row = conn.execute(
        """SELECT COUNT(*) n, AVG(answer_clear) a, AVG(source_clear) s,
           AVG(citation_useful) c, AVG(increased_trust) t, AVG(would_use) w FROM feedback"""
    ).fetchone()
    if not row or not row["n"]:
        return {"count": 0}
    return {
        "count": row["n"],
        "answer_clear_pct": round((row["a"] or 0) * 100, 1),
        "source_clear_pct": round((row["s"] or 0) * 100, 1),
        "citation_useful_pct": round((row["c"] or 0) * 100, 1),
        "increased_trust_pct": round((row["t"] or 0) * 100, 1),
        "would_use_pct": round((row["w"] or 0) * 100, 1),
    }


# ------------------------------------------------------------- STATIC -----
frontend_dir = os.path.join(os.path.dirname(__file__), "..", "..", "frontend")
if os.path.isdir(frontend_dir):
    app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")
