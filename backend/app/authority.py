"""
Authority Resolver — deterministic, explainable scoring.

This module NEVER calls an LLM. It only uses structured facts
(status, ownership, dates, version numbers, evidence count) to decide
which version of a document is authoritative. The AI layer is only
allowed to *answer questions using* whatever this module selects.
"""
import math
from datetime import datetime, timezone
from .database import get_conn
from .config import load_config
from .audit import log_event

TERMINAL_STATUSES = {"REJECTED", "ARCHIVED"}


def _parse_date(s):
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return datetime.now(timezone.utc)


def get_versions_for_document(document_id):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM versions WHERE document_id=? ORDER BY version_number DESC", (document_id,)
    ).fetchall()
    return [dict(r) for r in rows]


def get_approvals_for_version(version_id):
    conn = get_conn()
    rows = conn.execute(
        """SELECT approvals.*, owners.name as approver_name, owners.authority_level
           FROM approvals JOIN owners ON approvals.approver_owner_id = owners.id
           WHERE version_id=? ORDER BY date DESC""",
        (version_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def detect_conflict(version_id):
    """Return True if a version has both an APPROVED and REJECTED decision on record."""
    approvals = get_approvals_for_version(version_id)
    decisions = {a["decision"] for a in approvals}
    return "APPROVED" in decisions and "REJECTED" in decisions


def _approval_score(version, cfg):
    status = version["status"]
    base = cfg["status_scores"].get(status, 0.0)
    return base, status


def _ownership_score(version, approvals, cfg):
    """Highest authority level among APPROVED decisions; falls back to owner's own level."""
    approver_levels = [a["authority_level"] for a in approvals if a["decision"] == "APPROVED"]
    if approver_levels:
        return max(approver_levels)
    conn = get_conn()
    row = conn.execute("SELECT authority_level FROM owners WHERE id=?", (version["owner_id"],)).fetchone()
    return row["authority_level"] if row else 0.3


def _recency_score(version, cfg):
    half_life = cfg.get("recency_half_life_days", 180)
    modified = _parse_date(version["modified_date"])
    now = datetime.now(timezone.utc)
    if modified.tzinfo is None:
        modified = modified.replace(tzinfo=timezone.utc)
    age_days = max((now - modified).days, 0)
    # exponential decay so very old docs still score >0 but trend to 0
    score = 0.5 ** (age_days / max(half_life, 1))
    return max(0.0, min(1.0, score))


def _version_score(version, all_versions):
    """Rewards being a valid, non-superseded, non-terminal version number."""
    if version["status"] in TERMINAL_STATUSES:
        return 0.1
    max_v = max(v["version_number"] for v in all_versions) if all_versions else version["version_number"]
    if max_v == 0:
        return 1.0
    return 0.5 + 0.5 * (version["version_number"] / max_v)


def _evidence_score(version):
    import json as _json
    try:
        citations = _json.loads(version.get("citations_json") or "[]")
    except Exception:
        citations = []
    n = len(citations)
    return min(1.0, n / 3.0)  # 3+ citations = full score


def score_version(version, cfg=None, all_versions=None):
    cfg = cfg or load_config()
    all_versions = all_versions or get_versions_for_document(version["document_id"])
    approvals = get_approvals_for_version(version["id"])

    approval_raw, status = _approval_score(version, cfg)
    ownership_raw = _ownership_score(version, approvals, cfg)
    recency_raw = _recency_score(version, cfg)
    version_raw = _version_score(version, all_versions)
    evidence_raw = _evidence_score(version)

    w = cfg["weights"]
    weighted = {
        "approval": approval_raw * w["approval"],
        "ownership": ownership_raw * w["ownership"],
        "recency": recency_raw * w["recency"],
        "version": version_raw * w["version"],
        "evidence": evidence_raw * w["evidence"],
    }
    total = sum(weighted.values())  # 0..1

    breakdown = {
        "approval": {"raw": round(approval_raw, 3), "weight": w["approval"],
                     "points": round(weighted["approval"] * 100, 1), "max": round(w["approval"] * 100, 1)},
        "ownership": {"raw": round(ownership_raw, 3), "weight": w["ownership"],
                      "points": round(weighted["ownership"] * 100, 1), "max": round(w["ownership"] * 100, 1)},
        "recency": {"raw": round(recency_raw, 3), "weight": w["recency"],
                    "points": round(weighted["recency"] * 100, 1), "max": round(w["recency"] * 100, 1)},
        "version": {"raw": round(version_raw, 3), "weight": w["version"],
                    "points": round(weighted["version"] * 100, 1), "max": round(w["version"] * 100, 1)},
        "evidence": {"raw": round(evidence_raw, 3), "weight": w["evidence"],
                     "points": round(weighted["evidence"] * 100, 1), "max": round(w["evidence"] * 100, 1)},
    }
    return round(total * 100, 2), breakdown, status


def resolve_authority(document_id, user=None, persist=True):
    """
    Deterministically pick the authoritative version for a document.
    Returns dict with version, score, breakdown, conflict flag, and whether
    a manual override is currently active (overrides always win unless
    explicitly cleared).
    """
    conn = get_conn()
    cfg = load_config()
    versions = get_versions_for_document(document_id)
    if not versions:
        return None

    # Check for an active manual override first — overrides are sticky.
    existing = conn.execute("SELECT * FROM authoritative WHERE document_id=?", (document_id,)).fetchone()
    if existing and existing["is_override"]:
        chosen = next((v for v in versions if v["id"] == existing["version_id"]), None)
        if chosen:
            score, breakdown, status = score_version(chosen, cfg, versions)
            conflict = detect_conflict(chosen["id"])
            return {
                "document_id": document_id,
                "version": chosen,
                "score": existing["score"],
                "breakdown": breakdown,
                "status": status,
                "conflict": conflict,
                "is_override": True,
                "override_reason": existing["override_reason"],
                "override_by": existing["override_by"],
            }

    # Score every non-terminal-by-default candidate, but keep terminal ones
    # in the pool too (transparency) — they will simply score low.
    scored = []
    for v in versions:
        s, breakdown, status = score_version(v, cfg, versions)
        conflict = detect_conflict(v["id"])
        scored.append((s, v, breakdown, status, conflict))

    scored.sort(key=lambda t: (t[0], t[1]["version_number"]), reverse=True)
    best_score, best_version, best_breakdown, best_status, best_conflict = scored[0]

    # Global conflict flag: if the *top* candidate itself has conflicting approvals,
    # do not silently resolve — surface it.
    result = {
        "document_id": document_id,
        "version": best_version,
        "score": best_score,
        "breakdown": best_breakdown,
        "status": best_status,
        "conflict": best_conflict,
        "is_override": False,
        "override_reason": None,
        "override_by": None,
        "all_candidates": [
            {"version_id": v["id"], "version_number": v["version_number"], "status": v["status"], "score": s}
            for s, v, *_ in scored
        ],
    }

    if persist:
        from datetime import datetime as _dt
        now = _dt.now(timezone.utc).isoformat()
        prev = conn.execute("SELECT * FROM authoritative WHERE document_id=?", (document_id,)).fetchone()
        changed = (not prev) or (prev["version_id"] != best_version["id"])
        conn.execute(
            """INSERT INTO authoritative (document_id, version_id, score, breakdown_json, is_override,
                override_reason, override_by, previous_version_id, previous_score, updated_at)
               VALUES (?,?,?,?,0,NULL,NULL,?,?,?)
               ON CONFLICT(document_id) DO UPDATE SET
                 version_id=excluded.version_id, score=excluded.score, breakdown_json=excluded.breakdown_json,
                 is_override=0, override_reason=NULL, override_by=NULL,
                 previous_version_id=excluded.previous_version_id, previous_score=excluded.previous_score,
                 updated_at=excluded.updated_at""",
            (document_id, best_version["id"], best_score, _json_dumps(best_breakdown),
             prev["version_id"] if prev else None, prev["score"] if prev else None, now),
        )
        conn.commit()
        if changed:
            log_event(user or "system", "AUTHORITY_CALCULATED", document_id=document_id,
                       version_id=best_version["id"],
                       previous_value=prev["version_id"] if prev else None,
                       new_value=best_version["id"],
                       reason="Recalculated authority score",
                       metadata={"score": best_score, "breakdown": best_breakdown})

    return result


def _json_dumps(obj):
    import json
    return json.dumps(obj)


def baseline_resolve(document_id):
    """Naive baseline: newest version wins, full stop. No approval/ownership logic."""
    versions = get_versions_for_document(document_id)
    if not versions:
        return None
    newest = max(versions, key=lambda v: (v["version_number"], v["modified_date"]))
    return {"document_id": document_id, "version": newest, "method": "baseline_newest"}


def manual_override(document_id, version_id, admin_user, reason):
    conn = get_conn()
    versions = {v["id"]: v for v in get_versions_for_document(document_id)}
    if version_id not in versions:
        raise ValueError("version not found for this document")

    prev = conn.execute("SELECT * FROM authoritative WHERE document_id=?", (document_id,)).fetchone()
    cfg = load_config()
    score, breakdown, status = score_version(versions[version_id], cfg, list(versions.values()))
    now = datetime.now(timezone.utc).isoformat()

    conn.execute(
        """INSERT INTO authoritative (document_id, version_id, score, breakdown_json, is_override,
            override_reason, override_by, previous_version_id, previous_score, updated_at)
           VALUES (?,?,?,?,1,?,?,?,?,?)
           ON CONFLICT(document_id) DO UPDATE SET
             version_id=excluded.version_id, score=excluded.score, breakdown_json=excluded.breakdown_json,
             is_override=1, override_reason=excluded.override_reason, override_by=excluded.override_by,
             previous_version_id=excluded.previous_version_id, previous_score=excluded.previous_score,
             updated_at=excluded.updated_at""",
        (document_id, version_id, score, _json_dumps(breakdown), reason, admin_user,
         prev["version_id"] if prev else None, prev["score"] if prev else None, now),
    )
    conn.commit()

    log_event(admin_user, "MANUAL_OVERRIDE", document_id=document_id, version_id=version_id,
               previous_value=prev["version_id"] if prev else None, new_value=version_id,
               reason=reason, metadata={"previous_score": prev["score"] if prev else None, "new_score": score})
    return {"document_id": document_id, "version_id": version_id, "score": score, "reason": reason}


def rollback(document_id, admin_user):
    """Restore the previous authoritative version, keeping the override event in history."""
    conn = get_conn()
    row = conn.execute("SELECT * FROM authoritative WHERE document_id=?", (document_id,)).fetchone()
    if not row or not row["previous_version_id"]:
        raise ValueError("no previous authoritative version to roll back to")

    prev_version_id = row["previous_version_id"]
    prev_score = row["previous_score"]
    now = datetime.now(timezone.utc).isoformat()

    conn.execute(
        """UPDATE authoritative SET version_id=?, score=?, is_override=0, override_reason=NULL,
           override_by=NULL, previous_version_id=?, previous_score=?, updated_at=? WHERE document_id=?""",
        (prev_version_id, prev_score, row["version_id"], row["score"], now, document_id),
    )
    conn.commit()

    log_event(admin_user, "ROLLBACK", document_id=document_id, version_id=prev_version_id,
               previous_value=row["version_id"], new_value=prev_version_id,
               reason="Administrator rollback", metadata={"restored_score": prev_score})
    return {"document_id": document_id, "version_id": prev_version_id, "score": prev_score}
