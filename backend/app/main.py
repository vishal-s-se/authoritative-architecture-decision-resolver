import os
import json
import uuid
import tempfile
import time
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, UploadFile, File, Form, Header, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from passlib.hash import bcrypt
from jose import JWTError, jwt

from .database import init_db, get_conn, reset_db
from .config import load_config, save_config
from .audit import log_event, get_events, verify_chain
from .authority import resolve_authority, baseline_resolve, manual_override, rollback, get_versions_for_document
from .access import is_allowed, check_access_or_log, ROLE_RANK
from .retrieval import search, build_index
from .ai import answer_question
from .ingestion import ingest_document, ALLOWED_EXTENSIONS
from .seed import generate as seed_generate, ensure_default_users
from .evaluation import run_evaluation, latest_results, error_analysis, sensitivity_experiment

app = FastAPI(title="Authoritative Architecture Decision Resolver")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

JWT_SECRET = os.environ.get("ADR_JWT_SECRET")
LOGIN_FAILURES = {}
JWT_ALGORITHM = "HS256"
JWT_MINUTES = 60


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
    if not JWT_SECRET:
        raise HTTPException(500, "ADR_JWT_SECRET is not configured")
    now = time.time()
    recent_failures = [stamp for stamp in LOGIN_FAILURES.get(body.username, []) if now - stamp < 60]
    LOGIN_FAILURES[body.username] = recent_failures
    if len(recent_failures) >= 5:
        raise HTTPException(429, "too many login attempts")
    conn = get_conn()
    row = conn.execute("SELECT * FROM users WHERE username=?", (body.username,)).fetchone()
    if not row or not bcrypt.verify(body.password, row["password_hash"]):
        LOGIN_FAILURES[body.username].append(now)
        log_event(body.username, "LOGIN_FAILED", reason="invalid credentials")
        raise HTTPException(401, "invalid credentials")
    token = jwt.encode({"sub": row["username"], "role": row["role"],
                        "exp": int(now + JWT_MINUTES * 60)}, JWT_SECRET, algorithm=JWT_ALGORITHM)
    log_event(row["username"], "LOGIN")
    return {"token": token, "username": row["username"], "role": row["role"]}


def current_user(authorization: Optional[str] = Header(None)):
    if not authorization or not JWT_SECRET:
        return {"username": "anonymous", "role": "VIEWER"}
    token = authorization.replace("Bearer ", "")
    try:
        claims = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return {"username": claims["sub"], "role": claims["role"]}
    except (JWTError, KeyError):
        return {"username": "anonymous", "role": "VIEWER"}


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
    suffix = os.path.splitext(file.filename or "")[1].lower()
    tmp_file = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    tmp_path = tmp_file.name
    with tmp_file as f:
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
    if result.get("version"):
        result["version"] = dict(result["version"])
    return result


@app.get("/api/authority/{document_id}/baseline")
def get_baseline(document_id: str, user=Depends(current_user)):
    if not check_access_or_log(document_id, user["role"], user["username"], "VIEW_BASELINE"):
        raise HTTPException(403, "access denied")
    result = baseline_resolve(document_id)
    if not result:
        raise HTTPException(404, "no versions found for document")
    result["version"] = dict(result["version"])
    result["version"].pop("content", None)
    return result


class OverrideRequest(BaseModel):
    version_id: str
    reason: str


class ApprovalRequest(BaseModel):
    version_id: str
    decision: str
    reason: str


class RevokeApprovalRequest(BaseModel):
    reason: str


class ChangeReviewRequest(BaseModel):
    decision: str


class RemoveOverrideRequest(BaseModel):
    reason: str


def require_architect_or_admin(user=Depends(current_user)):
    if user["role"] not in ("ADMIN", "ARCHITECT"):
        raise HTTPException(403, "architect or administrator role required")
    return user


@app.post("/api/approvals")
def add_approval(body: ApprovalRequest, user=Depends(require_architect_or_admin)):
    if body.decision not in ("APPROVED", "REJECTED", "PENDING_REVIEW"):
        raise HTTPException(400, "invalid approval decision")
    if not body.reason or len(body.reason.strip()) < 5:
        raise HTTPException(400, "a reason is required")
    conn = get_conn()
    version = conn.execute("SELECT * FROM versions WHERE id=?", (body.version_id,)).fetchone()
    if not version:
        raise HTTPException(404, "version not found")
    before = resolve_authority(version["document_id"], user=user["username"], persist=False)
    owner = conn.execute("SELECT id FROM owners WHERE name=?", (user["username"],)).fetchone()
    approver_id = owner["id"] if owner else conn.execute("SELECT id FROM owners ORDER BY authority_level DESC LIMIT 1").fetchone()["id"]
    conn.execute("INSERT INTO approvals (version_id, approver_owner_id, decision, date, reason) VALUES (?,?,?,?,?)",
                 (body.version_id, approver_id, body.decision, datetime.now(timezone.utc).isoformat(), body.reason))
    conn.commit()
    log_event(user["username"], "APPROVAL_ADDED", document_id=version["document_id"], version_id=body.version_id, reason=body.reason)
    after = resolve_authority(version["document_id"], user=user["username"])
    before_id = before.get("version")["id"] if before and before.get("version") else None
    after_id = after.get("version")["id"] if after and after.get("version") else None
    if before_id != after_id:
        log_event(user["username"], "AUTHORITY_CHANGED", document_id=version["document_id"],
                  previous_value=before_id, new_value=after_id, reason=body.reason)
    return {"ok": True, "version_id": body.version_id, "decision": body.decision}


@app.post("/api/approvals/{approval_id}/revoke")
def revoke_approval(approval_id: int, body: RevokeApprovalRequest, user=Depends(require_architect_or_admin)):
    reason = body.reason
    if len(reason.strip()) < 5:
        raise HTTPException(400, "a reason is required")
    conn = get_conn()
    approval = conn.execute("SELECT * FROM approvals WHERE id=?", (approval_id,)).fetchone()
    if not approval:
        raise HTTPException(404, "approval not found")
    version = conn.execute("SELECT document_id FROM versions WHERE id=?", (approval["version_id"],)).fetchone()
    conn.execute("DELETE FROM approvals WHERE id=?", (approval_id,))
    conn.commit()
    log_event(user["username"], "APPROVAL_REVOKED", document_id=version["document_id"], version_id=approval["version_id"], reason=reason)
    resolve_authority(version["document_id"], user=user["username"])
    return {"ok": True, "approval_id": approval_id}


@app.post("/api/authority/{document_id}/override")
def override(document_id: str, body: OverrideRequest, user=Depends(require_admin)):
    if not body.reason or len(body.reason.strip()) < 5:
        raise HTTPException(400, "a meaningful reason is required for manual override")
    conn = get_conn()
    if not conn.execute("SELECT 1 FROM versions WHERE id=? AND document_id=?", (body.version_id, document_id)).fetchone():
        raise HTTPException(400, "version not found for this document")
    cur = conn.execute("INSERT INTO pending_changes (action, document_id, version_id, requested_by, reason, created_at) VALUES (?,?,?,?,?,?)",
                       ("OVERRIDE", document_id, body.version_id, user["username"], body.reason, datetime.now(timezone.utc).isoformat()))
    conn.commit()
    log_event(user["username"], "CHANGE_REQUESTED", document_id=document_id, version_id=body.version_id, reason=body.reason)
    return {"pending_change_id": cur.lastrowid, "status": "PENDING"}


@app.post("/api/authority/{document_id}/override/remove")
def remove_override(document_id: str, body: RemoveOverrideRequest, user=Depends(require_admin)):
    if len(body.reason.strip()) < 5:
        raise HTTPException(400, "a meaningful reason is required")
    conn = get_conn()
    current = conn.execute("SELECT * FROM authoritative WHERE document_id=?", (document_id,)).fetchone()
    if not current or not current["is_override"]:
        raise HTTPException(400, "no active override exists")
    previous = current["version_id"]
    result = resolve_authority(document_id, user=user["username"], persist=True)
    log_event(user["username"], "OVERRIDE_REMOVED", document_id=document_id, version_id=previous,
              previous_value=previous, new_value=result["version"]["id"] if result and result.get("version") else None,
              reason=body.reason)
    return {"ok": True, "authority": result}


@app.post("/api/authority/{document_id}/rollback")
def do_rollback(document_id: str, user=Depends(require_admin)):
    conn = get_conn()
    if not conn.execute("SELECT 1 FROM authoritative WHERE document_id=? AND previous_version_id IS NOT NULL", (document_id,)).fetchone():
        raise HTTPException(400, "no previous authoritative version to roll back to")
    cur = conn.execute("INSERT INTO pending_changes (action, document_id, requested_by, reason, created_at) VALUES (?,?,?,?,?)",
                       ("ROLLBACK", document_id, user["username"], "Administrator rollback", datetime.now(timezone.utc).isoformat()))
    conn.commit()
    log_event(user["username"], "CHANGE_REQUESTED", document_id=document_id, reason="Administrator rollback")
    return {"pending_change_id": cur.lastrowid, "status": "PENDING"}


@app.get("/api/pending-changes")
def pending_changes(user=Depends(require_admin)):
    conn = get_conn()
    return [dict(row) for row in conn.execute("SELECT * FROM pending_changes WHERE status='PENDING' ORDER BY id").fetchall()]


@app.post("/api/pending-changes/{change_id}/review")
def review_change(change_id: int, body: ChangeReviewRequest, user=Depends(require_admin)):
    if body.decision not in ("APPROVE", "REJECT"):
        raise HTTPException(400, "decision must be APPROVE or REJECT")
    conn = get_conn()
    change = conn.execute("SELECT * FROM pending_changes WHERE id=? AND status='PENDING'", (change_id,)).fetchone()
    if not change:
        raise HTTPException(404, "pending change not found")
    if change["requested_by"] == user["username"]:
        raise HTTPException(400, "a requester cannot approve their own change")
    status = "APPROVED" if body.decision == "APPROVE" else "REJECTED"
    if status == "APPROVED":
        try:
            result = manual_override(change["document_id"], change["version_id"], user["username"], change["reason"]) if change["action"] == "OVERRIDE" else rollback(change["document_id"], user["username"])
        except ValueError as exc:
            raise HTTPException(400, str(exc))
    else:
        result = {"status": status}
    conn.execute("UPDATE pending_changes SET status=?, reviewed_by=?, reviewed_at=? WHERE id=?",
                 (status, user["username"], datetime.now(timezone.utc).isoformat(), change_id))
    conn.commit()
    log_event(user["username"], "CHANGE_APPROVED" if status == "APPROVED" else "CHANGE_REJECTED",
              document_id=change["document_id"], version_id=change["version_id"], reason=change["reason"])
    return {"status": status, "result": result}


# --------------------------------------------------------------- ASK AI ---
class AskRequest(BaseModel):
    question: str


@app.post("/api/ask")
def ask(body: AskRequest, user=Depends(current_user)):
    candidates = search(body.question, top_k=int(os.environ.get("ADR_TOP_K", "5")))
    if not candidates:
        log_event(user["username"], "QUERY_ANSWERED", reason=body.question,
                   metadata={"result": "no_candidates"})
        return {"answer": "No relevant documents were found for this question.", "candidates": []}

    conn = get_conn()
    accessible = [c for c in candidates if check_access_or_log(
        c["document_id"], user["role"], user["username"], "ASK_AI")]
    if not accessible:
        return {"answer": "You do not have permission to access the relevant documents for this question.",
                "access_denied": True, "candidates": []}

    resolved = []
    for candidate in accessible:
        authority_result = resolve_authority(candidate["document_id"], user=user["username"])
        if authority_result:
            resolved.append((candidate, authority_result))
    if not resolved:
        raise HTTPException(404, "could not resolve an authoritative version")

    top, result = resolved[0]
    document_id = top["document_id"]
    if result["status"] == "MANUAL_REVIEW_REQUIRED":
        return {"answer": "Conflicting approval records detected. Automatic authority resolution has been suspended.",
                "conflict": True, "status": result["status"], "candidates": accessible}
    if not result.get("version"):
        return {"answer": "No approved authoritative version is available for this document.",
                "status": result["status"], "candidates": accessible}

    doc = conn.execute("SELECT * FROM documents WHERE id=?", (document_id,)).fetchone()

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
        "candidates": accessible,
        "relevance_note": "Retrieval selected candidate documents by relevance; the authority resolver "
                           "then independently selected the authoritative VERSION of the top candidate.",
    }


# -------------------------------------------------------------- AUDIT -----
@app.get("/api/audit")
def audit_trail(document_id: Optional[str] = None, limit: int = 200, user=Depends(require_admin)):
    return get_events(limit=limit, document_id=document_id)


@app.get("/api/audit/verify")
def audit_verify(user=Depends(require_admin)):
    return verify_chain()


@app.get("/api/citations/{version_id}/{chunk_id}")
def citation(version_id: str, chunk_id: str, user=Depends(current_user)):
    conn = get_conn()
    version = conn.execute("SELECT * FROM versions WHERE id=?", (version_id,)).fetchone()
    if not version:
        raise HTTPException(404, "version not found")
    if not check_access_or_log(version["document_id"], user["role"], user["username"], "VIEW_CITATION"):
        raise HTTPException(403, "access denied")
    chunks = [part.strip() for part in version["content"].replace("Section ", "\nSection ").splitlines() if part.strip()]
    source = next((part for part in chunks if chunk_id in part or part.startswith("Section")), version["content"])
    return {"version_id": version_id, "chunk_id": chunk_id, "source_text": source}


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


@app.get("/api/eval/error-analysis")
def eval_error_analysis(user=Depends(require_admin)):
    return error_analysis()


@app.get("/api/eval/sensitivity")
def eval_sensitivity(user=Depends(require_admin)):
    return sensitivity_experiment()


# ------------------------------------------------------------ FEEDBACK ----
class FeedbackRequest(BaseModel):
    query: str
    answer_clear: int = Field(ge=1, le=5)
    source_clear: int = Field(ge=1, le=5)
    citation_useful: int = Field(ge=1, le=5)
    increased_trust: int = Field(ge=1, le=5)
    would_use: int = Field(ge=1, le=5)


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
        "answer_clear_average": round(row["a"] or 0, 2),
        "source_clear_average": round(row["s"] or 0, 2),
        "citation_useful_average": round(row["c"] or 0, 2),
        "increased_trust_average": round(row["t"] or 0, 2),
        "would_use_average": round(row["w"] or 0, 2),
        "answer_clear_agree_pct": round((row["a"] or 0) * 20, 1),
        "source_clear_agree_pct": round((row["s"] or 0) * 20, 1),
        "citation_useful_agree_pct": round((row["c"] or 0) * 20, 1),
        "increased_trust_agree_pct": round((row["t"] or 0) * 20, 1),
        "would_use_agree_pct": round((row["w"] or 0) * 20, 1),
    }


# ------------------------------------------------------------- STATIC -----
frontend_dir = os.path.join(os.path.dirname(__file__), "..", "..", "frontend")
if os.path.isdir(frontend_dir):
    app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")
