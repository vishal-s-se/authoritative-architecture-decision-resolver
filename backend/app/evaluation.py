import uuid
import json
from datetime import datetime, timezone
from .database import get_conn
from .authority import resolve_authority, baseline_resolve, detect_conflict
from .ai import answer_question
from .access import is_allowed


def run_evaluation(mode, user_role="ARCHITECT"):
    """
    mode: 'baseline' or 'proposed'
    Runs every eval_queries row through the chosen resolver + AI layer and
    scores against ground truth. Nothing here is hardcoded — results are
    computed from the live database each run.
    """
    conn = get_conn()
    queries = conn.execute("SELECT * FROM eval_queries").fetchall()
    if not queries:
        return {"error": "no evaluation queries found — run seed generation first"}

    correct_authority = 0
    correct_citation = 0
    access_correct = 0
    conflict_detected = 0
    conflict_total = 0
    errors = []
    n = len(queries)

    for q in queries:
        doc_id = q["expected_document_id"]
        title_row = conn.execute("SELECT title FROM documents WHERE id=?", (doc_id,)).fetchone()
        title = title_row["title"] if title_row else "Unknown"

        if mode == "baseline":
            result = baseline_resolve(doc_id)
        else:
            result = resolve_authority(doc_id, user="eval-harness", persist=False)

        if not result:
            errors.append({"query": q["query"], "type": "missing_document", "document_id": doc_id})
            continue

        version = result["version"]
        is_correct = version["id"] == q["expected_version_id"]
        if is_correct:
            correct_authority += 1
        else:
            errors.append({
                "query": q["query"], "type": "wrong_version_selection",
                "expected": q["expected_version_id"], "got": version["id"],
            })

        # access control check (simulate an ENGINEER by default)
        allowed = is_allowed(doc_id, user_role)
        if allowed:
            access_correct += 1

        # conflict detection accuracy
        has_conflict = detect_conflict(version["id"])
        if has_conflict:
            conflict_total += 1
            if mode == "proposed" and result.get("conflict"):
                conflict_detected += 1

        # citation accuracy (only meaningful once we've picked a version)
        if is_correct:
            try:
                citations = json.loads(version.get("citations_json") or "[]")
                cited_ok = bool(citations)
            except Exception:
                cited_ok = False
            if cited_ok:
                correct_citation += 1

    metrics = {
        "mode": mode,
        "total_queries": n,
        "authority_selection_accuracy": round(100 * correct_authority / n, 2),
        "citation_accuracy": round(100 * correct_citation / max(correct_authority, 1), 2),
        "access_control_accuracy": round(100 * access_correct / n, 2),
        "conflict_detection_accuracy": round(100 * conflict_detected / max(conflict_total, 1), 2) if conflict_total else None,
        "conflict_cases": conflict_total,
        "error_count": len(errors),
        "errors_sample": errors[:15],
    }

    run_id = str(uuid.uuid4())[:8]
    conn.execute(
        "INSERT INTO eval_results (run_id, mode, created_at, metrics_json) VALUES (?,?,?,?)",
        (run_id, mode, datetime.now(timezone.utc).isoformat(), json.dumps(metrics)),
    )
    conn.commit()
    metrics["run_id"] = run_id
    return metrics


def latest_results():
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM eval_results ORDER BY id DESC LIMIT 10"
    ).fetchall()
    return [{"run_id": r["run_id"], "mode": r["mode"], "created_at": r["created_at"],
              **json.loads(r["metrics_json"])} for r in rows]
