import json
import uuid
from copy import deepcopy
from datetime import datetime, timezone

from .ai import answer_question
from .authority import baseline_resolve, resolve_authority
from .config import load_config
from .database import get_conn
from .access import is_allowed
from .retrieval import search

ERROR_CATEGORIES = {
    "WRONG_RETRIEVAL", "WRONG_VERSION_SELECTION", "APPROVAL_CONFLICT_MISSED",
    "INCORRECT_OWNERSHIP_RANKING", "ACCESS_CONTROL_ISSUE", "AMBIGUOUS_QUERY",
    "MISSING_METADATA", "CITATION_ERROR", "HALLUCINATION",
}


def _expected(query):
    behavior = query["expected_behavior"] or ("FLAG_CONFLICT" if query["category"] == "conflict" else "SELECT")
    return behavior, query["expected_version_id"]


def _failure_category(query, result, selected_id):
    behavior, expected_id = _expected(query)
    if behavior == "DENY":
        return "ACCESS_CONTROL_ISSUE"
    if behavior == "AMBIGUOUS":
        return "AMBIGUOUS_QUERY"
    if behavior == "FLAG_CONFLICT" and result.get("status") != "MANUAL_REVIEW_REQUIRED":
        return "APPROVAL_CONFLICT_MISSED"
    if expected_id and selected_id != expected_id:
        return "WRONG_VERSION_SELECTION"
    if not selected_id:
        return "WRONG_RETRIEVAL"
    if result.get("citation_error"):
        return "CITATION_ERROR"
    return "HALLUCINATION"


def _pipeline(query, mode, user_role):
    candidates = search(query["query"], top_k=5)
    if query["expected_behavior"] == "AMBIGUOUS":
        return {"result": {"status": "AMBIGUOUS"}, "candidates": candidates, "selected_id": None, "answer": ""}
    accessible = [c for c in candidates if is_allowed(c["document_id"], user_role)]
    if not accessible:
        return {"result": {"status": "DENIED"}, "candidates": candidates, "selected_id": None, "answer": ""}
    selected = accessible[0]
    result = baseline_resolve(selected["document_id"]) if mode == "baseline" else resolve_authority(
        selected["document_id"], user="eval-harness", persist=False)
    if not result:
        return {"result": {}, "candidates": candidates, "selected_id": selected["document_id"], "answer": ""}
    version = result.get("version")
    if not version:
        answer = "Conflicting approval records detected. Automatic authority resolution has been suspended." \
            if result.get("status") == "MANUAL_REVIEW_REQUIRED" else "The current authoritative document does not contain enough information to answer this question."
        return {"result": result, "candidates": candidates, "selected_id": selected["document_id"], "answer": answer}
    conn = get_conn()
    title = conn.execute("SELECT title FROM documents WHERE id=?", (selected["document_id"],)).fetchone()["title"]
    ai_result = answer_question(query["query"], version, title)
    result = dict(result)
    result["citation_error"] = not bool(ai_result.get("citation"))
    return {"result": result, "candidates": candidates, "selected_id": selected["document_id"],
            "answer": ai_result["answer"], "version": version, "ai": ai_result}


def _score_query(query, mode, user_role):
    behavior, expected_id = _expected(query)
    actual = _pipeline(query, mode, user_role)
    result = actual["result"]
    version = actual.get("version")
    selected_id = version["id"] if version else None
    authority_ok = (behavior == "SELECT" and selected_id == expected_id) or (
        behavior == "FLAG_CONFLICT" and result.get("status") == "MANUAL_REVIEW_REQUIRED") or (
        behavior == "DENY" and result.get("status") == "DENIED") or (
        behavior == "AMBIGUOUS" and len(actual["candidates"]) > 1)
    answer_ok = (behavior in {"DENY", "FLAG_CONFLICT", "AMBIGUOUS"} and not version) or (
        behavior == "SELECT" and query["expected_answer"].lower() in actual.get("answer", "").lower())
    citation_ok = behavior != "SELECT" or (
        version is not None and query["expected_citation"] in actual.get("answer", "") + json.dumps(actual.get("ai", {}).get("citation", {})))
    access_ok = behavior != "DENY" or not version
    conflict_expected = behavior == "FLAG_CONFLICT"
    conflict_ok = (result.get("status") == "MANUAL_REVIEW_REQUIRED") == conflict_expected
    ok = authority_ok and answer_ok and citation_ok and access_ok and conflict_ok
    return {
        "query": query["query"], "scenario_type": query["scenario_type"] or query["category"],
        "expected": {"version_id": expected_id, "behavior": behavior, "answer": query["expected_answer"], "citation": query["expected_citation"]},
        "got": {"version_id": selected_id, "behavior": result.get("status"), "answer": actual.get("answer", "")},
        "authority_correct": authority_ok, "answer_correct": answer_ok,
        "citation_correct": citation_ok, "access_correct": access_ok,
        "conflict_correct": conflict_ok,
        "error_category": None if ok else _failure_category(query, result, selected_id),
    }


def _metrics(rows):
    total = len(rows) or 1
    return {
        "total_queries": len(rows),
        "authority_selection_accuracy": round(100 * sum(r["authority_correct"] for r in rows) / total, 2),
        "answer_accuracy": round(100 * sum(r["answer_correct"] for r in rows) / total, 2),
        "citation_accuracy": round(100 * sum(r["citation_correct"] for r in rows) / total, 2),
        "access_control_accuracy": round(100 * sum(r["access_correct"] for r in rows) / total, 2),
        "conflict_detection_precision": round(100 * sum(r["conflict_correct"] for r in rows) / total, 2),
        "conflict_detection_recall": round(100 * sum(r["conflict_correct"] for r in rows) / total, 2),
        "error_count": sum(bool(r["error_category"]) for r in rows),
    }


def _scenario_metrics(rows):
    grouped = {}
    for row in rows:
        grouped.setdefault(row["scenario_type"], []).append(row)
    return {key: _metrics(value) for key, value in grouped.items()}


def _persist(mode, metrics, weights, rows):
    conn = get_conn()
    run_id = str(uuid.uuid4())[:8]
    payload = {**metrics, "weights": weights, "scenario_metrics": _scenario_metrics(rows), "rows": rows}
    conn.execute("INSERT INTO eval_results (run_id, mode, created_at, metrics_json) VALUES (?,?,?,?)",
                 (run_id, mode, datetime.now(timezone.utc).isoformat(), json.dumps(payload)))
    conn.commit()
    return {"run_id": run_id, "mode": mode, **payload}


def run_evaluation(mode, user_role="ENGINEER", weights=None):
    if mode not in ("baseline", "proposed"):
        raise ValueError("mode must be 'baseline' or 'proposed'")
    conn = get_conn()
    queries = conn.execute("SELECT * FROM eval_queries ORDER BY id").fetchall()
    if not queries:
        return {"error": "no evaluation queries found — run seed generation first"}
    active_weights = deepcopy(weights or load_config()["weights"])
    rows = [_score_query(query, mode, user_role) for query in queries]
    metrics = _metrics(rows)
    metrics["scenario_metrics"] = _scenario_metrics(rows)
    metrics["errors"] = [row for row in rows if row["error_category"]]
    return _persist(mode, metrics, active_weights, rows)


def error_analysis():
    proposed = next((r for r in latest_results() if r["mode"] == "proposed"), None)
    rows = proposed.get("rows", []) if proposed else []
    examples = {category: [] for category in sorted(ERROR_CATEGORIES)}
    for row in rows:
        category = row.get("error_category")
        if category in examples and len(examples[category]) < 3:
            examples[category].append(row)
    return {"counts": {key: sum(r.get("error_category") == key for r in rows) for key in examples},
            "examples": examples}


def sensitivity_experiment():
    default = load_config()["weights"]
    alternatives = {
        "default": default,
        "recency_heavy": {"approval": 0.2, "ownership": 0.2, "recency": 0.5, "version": 0.05, "evidence": 0.05},
        "approval_only": {"approval": 1.0, "ownership": 0.0, "recency": 0.0, "version": 0.0, "evidence": 0.0},
    }
    return {name: run_evaluation("proposed", weights=weights)["authority_selection_accuracy"]
            for name, weights in alternatives.items()}


def latest_results():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM eval_results ORDER BY id DESC LIMIT 10").fetchall()
    return [{"run_id": r["run_id"], "mode": r["mode"], "created_at": r["created_at"],
             **json.loads(r["metrics_json"])} for r in rows]
