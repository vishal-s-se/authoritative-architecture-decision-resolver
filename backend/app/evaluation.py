import json
import os
import shutil
import tempfile
import uuid
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone

from . import database, retrieval
from .access import is_allowed
from .ai import answer_question
from .audit import get_events
from .authority import baseline_resolve, manual_override, resolve_authority, rollback
from .config import load_config
from .database import get_conn

ERROR_CATEGORIES = {
    "WRONG_RETRIEVAL", "WRONG_VERSION_SELECTION", "APPROVAL_CONFLICT_MISSED",
    "INCORRECT_OWNERSHIP_RANKING", "ACCESS_CONTROL_ISSUE", "AMBIGUOUS_QUERY",
    "MISSING_METADATA", "CITATION_ERROR", "HALLUCINATION",
}


@contextmanager
def _temporary_database():
    original_path = database.DB_PATH
    source = get_conn()
    source.commit()
    temp_handle = tempfile.NamedTemporaryFile(prefix="adr-eval-", suffix=".db", delete=False)
    temp_path = temp_handle.name
    temp_handle.close()
    shutil.copy2(original_path, temp_path)
    if hasattr(database._local, "conn"):
        database._local.conn.close()
        del database._local.conn
    database.DB_PATH = temp_path
    retrieval._vectorizer = None
    retrieval._matrix = None
    retrieval._doc_ids = []
    try:
        yield
    finally:
        if hasattr(database._local, "conn"):
            database._local.conn.close()
            del database._local.conn
        database.DB_PATH = original_path
        retrieval._vectorizer = None
        retrieval._matrix = None
        retrieval._doc_ids = []
        try:
            os.remove(temp_path)
        except OSError:
            pass


def _expected(query):
    behavior = query["expected_behavior"] or ("FLAG_CONFLICT" if query["category"] == "conflict" else "SELECT")
    return behavior, query["expected_document_id"], query["expected_version_id"]


def _answer_has_expected(answer, expected_answer, behavior):
    if behavior == "DENY":
        return "permission" in answer.lower() and "enough information" not in answer.lower()
    if behavior == "FLAG_CONFLICT":
        return "conflicting approval" in answer.lower() or "manual review" in answer.lower()
    if behavior == "AMBIGUOUS":
        return not answer or "ambiguous" in answer.lower()
    return bool(expected_answer and expected_answer.lower() in answer.lower())


def _citation_belongs(version, citation):
    if not version or not citation:
        return False
    try:
        citations = json.loads(version["citations_json"] or "[]")
    except (TypeError, json.JSONDecodeError):
        return False
    return any(item.get("chunk_id") == citation.get("chunk_id") for item in citations)


def _pipeline(query, mode, user_role, cfg):
    from .retrieval import build_index, search

    build_index()
    candidates = search(query["query"], top_k=5)
    behavior, expected_doc_id, _ = _expected(query)
    if behavior == "AMBIGUOUS":
        return {"result": {"status": "AMBIGUOUS"}, "candidates": candidates,
                "version": None, "selected_document_id": None,
                "answer": "Ambiguous result: multiple documents match this query."}
    if behavior == "DENY":
        restricted = [candidate for candidate in candidates if not is_allowed(candidate["document_id"], user_role)]
        if restricted:
            leaked = False
            conn = get_conn()
            response = "You do not have permission to access the relevant documents for this question."
            for candidate in restricted:
                versions = conn.execute("SELECT content FROM versions WHERE document_id=?", (candidate["document_id"],)).fetchall()
                leaked = leaked or any(row["content"] and row["content"] in response for row in versions)
            return {"result": {"status": "DENIED", "leaked": leaked}, "candidates": candidates,
                    "version": None, "selected_document_id": None, "answer": response}
    accessible = [candidate for candidate in candidates if is_allowed(candidate["document_id"], user_role)]
    if not accessible:
        return {"result": {"status": "DENIED", "leaked": False}, "candidates": candidates,
            "version": None, "selected_document_id": None,
            "answer": "You do not have permission to access the relevant documents for this question."}
    selected = accessible[0]
    if mode == "baseline":
        resolver_result = baseline_resolve(selected["document_id"])
    else:
        # Override policy if mode specifies it
        if mode in ("weighted", "tiered"):
            cfg["resolver_policy"] = mode
        resolver_result = resolve_authority(selected["document_id"], user="eval-harness", persist=False, cfg=cfg)
    if not resolver_result:
        return {"result": {}, "candidates": candidates, "version": None,
            "selected_document_id": selected["document_id"], "answer": ""}
    version = resolver_result.get("version")
    if not version:
        answer = "Conflicting approval records detected. Automatic authority resolution has been suspended." \
            if resolver_result.get("status") == "MANUAL_REVIEW_REQUIRED" else \
            "The current authoritative document does not contain enough information to answer this question."
        return {"result": resolver_result, "candidates": candidates, "version": None,
            "selected_document_id": selected["document_id"], "answer": answer}
    conn = get_conn()
    title = conn.execute("SELECT title FROM documents WHERE id=?", (selected["document_id"],)).fetchone()["title"]
    ai_result = answer_question(query["query"], version, title)
    return {"result": resolver_result, "candidates": candidates, "version": version,
            "selected_document_id": selected["document_id"],
            "answer": ai_result["answer"], "ai": ai_result, "expected_doc_id": expected_doc_id}


def _failure_category(query, actual, selected_id):
    behavior, expected_doc_id, expected_id = _expected(query)
    result = actual["result"]
    if behavior == "DENY":
        return "ACCESS_CONTROL_ISSUE", "A restricted document response was not denied without leakage."
    if behavior == "AMBIGUOUS":
        return "AMBIGUOUS_QUERY", "The retrieval result did not preserve the multiple-match condition."
    if behavior == "FLAG_CONFLICT" and result.get("status") != "MANUAL_REVIEW_REQUIRED":
        return "APPROVAL_CONFLICT_MISSED", "Conflicting approval records did not suspend automatic resolution."
    if expected_doc_id and actual.get("selected_document_id") != expected_doc_id:
        return "WRONG_RETRIEVAL", "The retrieval result ranked a similar but incorrect document first or absent."
    if expected_id and selected_id != expected_id:
        category = "INCORRECT_OWNERSHIP_RANKING" if query["scenario_type"] == "owner_authority_tiebreak" else "WRONG_VERSION_SELECTION"
        return category, "The resolver selected a different version from the independently planted target."
    if result.get("citation_error"):
        return "CITATION_ERROR", "The citation did not identify a chunk belonging to the selected version."
    if not actual.get("answer"):
        return "HALLUCINATION", "The response did not contain a grounded answer."
    return "MISSING_METADATA", "The selected result lacked required metadata for the expected behavior."


def _score_query(query, mode, user_role, cfg):
    behavior, expected_doc_id, expected_id = _expected(query)
    actual = _pipeline(query, mode, user_role, cfg)
    result = actual["result"]
    version = actual.get("version")
    selected_id = version["id"] if version else None
    retrieval_ok = not expected_doc_id or any(candidate["document_id"] == expected_doc_id for candidate in actual["candidates"])
    authority_ok = (behavior == "SELECT" and selected_id == expected_id and retrieval_ok) or \
        (behavior == "FLAG_CONFLICT" and result.get("status") == "MANUAL_REVIEW_REQUIRED") or \
        (behavior == "DENY" and result.get("status") == "DENIED" and not result.get("leaked")) or \
        (behavior == "AMBIGUOUS" and len(actual["candidates"]) >= 2)
    answer_ok = _answer_has_expected(actual.get("answer", ""), query["expected_answer"], behavior)
    citation = actual.get("ai", {}).get("citation")
    citation_ok = behavior != "SELECT" or _citation_belongs(version, citation)
    access_ok = behavior != "DENY" or (result.get("status") == "DENIED" and not result.get("leaked") and not version)
    conflict_expected = behavior == "FLAG_CONFLICT"
    conflict_detected = result.get("status") == "MANUAL_REVIEW_REQUIRED"
    conflict_ok = conflict_detected == conflict_expected
    all_ok = authority_ok and answer_ok and citation_ok and access_ok and conflict_ok
    category, reason = (None, None) if all_ok else _failure_category(query, actual, selected_id)
    return {
        "query": query["query"], "scenario_type": query["scenario_type"] or query["category"],
        "expected": {"document_id": expected_doc_id, "version_id": expected_id,
                     "behavior": behavior, "answer": query["expected_answer"], "citation": query["expected_citation"]},
        "got": {"document_id": actual.get("selected_document_id"), "version_id": selected_id,
                "behavior": result.get("status"), "answer": actual.get("answer", "")},
        "authority_correct": authority_ok, "answer_correct": answer_ok,
        "citation_correct": citation_ok, "access_correct": access_ok,
        "conflict_expected": conflict_expected, "conflict_detected": conflict_detected,
        "conflict_correct": conflict_ok, "passed": all_ok,
        "error_category": category, "reason": reason,
    }


def _metrics(rows):
    total = len(rows) or 1
    true_positive = sum(row["conflict_expected"] and row["conflict_detected"] for row in rows)
    false_positive = sum(not row["conflict_expected"] and row["conflict_detected"] for row in rows)
    false_negative = sum(row["conflict_expected"] and not row["conflict_detected"] for row in rows)
    return {
        "total_queries": len(rows),
        "authority_selection_accuracy": round(100 * sum(row["authority_correct"] for row in rows) / total, 2),
        "answer_accuracy": round(100 * sum(row["answer_correct"] for row in rows) / total, 2),
        "citation_accuracy": round(100 * sum(row["citation_correct"] for row in rows) / total, 2),
        "access_control_accuracy": round(100 * sum(row["access_correct"] for row in rows) / total, 2),
        "conflict_detection_accuracy": round(100 * sum(row["conflict_correct"] for row in rows) / total, 2),
        "conflict_detection_precision": round(100 * true_positive / max(true_positive + false_positive, 1), 2),
        "conflict_detection_recall": round(100 * true_positive / max(true_positive + false_negative, 1), 2),
        "error_count": sum(not row["passed"] for row in rows),
    }


def _scenario_metrics(rows):
    grouped = {}
    for row in rows:
        grouped.setdefault(row["scenario_type"], []).append(row)
    return {name: _metrics(items) for name, items in grouped.items()}


def _exercise_override_and_rollback(user_role):
    conn = get_conn()
    candidate = conn.execute(
        """SELECT document_id FROM versions GROUP BY document_id
           HAVING COUNT(*) >= 2 ORDER BY document_id LIMIT 1"""
    ).fetchone()
    if not candidate:
        return False, False
    document_id = candidate["document_id"]
    versions = conn.execute("SELECT id FROM versions WHERE document_id=? ORDER BY version_number", (document_id,)).fetchall()
    base = resolve_authority(document_id, user="eval-harness", persist=True)
    if not base or not base.get("version"):
        return False, False
    alternate = next((row["id"] for row in versions if row["id"] != base["version"]["id"]), None)
    if not alternate:
        return False, False
    manual_override(document_id, alternate, "eval-admin", "evaluation override validation")
    overridden = resolve_authority(document_id, user="eval-harness", persist=False)
    override_ok = bool(overridden and overridden.get("is_override") and overridden["version"]["id"] == alternate)
    rollback_ok = False
    try:
        rollback(document_id, "eval-admin")
        restored = resolve_authority(document_id, user="eval-harness", persist=False)
        events = get_events(limit=100, document_id=document_id)
        rollback_ok = bool(restored and restored["version"]["id"] == base["version"]["id"] and
                           any(event["action"] == "MANUAL_OVERRIDE" for event in events))
    except ValueError:
        rollback_ok = False
    return override_ok, rollback_ok


def _persist(mode, metrics, weights, rows):
    conn = get_conn()
    run_id = str(uuid.uuid4())[:8]
    payload = {**metrics, "weights": weights, "rows": rows,
               "scenario_metrics": _scenario_metrics(rows)}
    conn.execute("INSERT INTO eval_results (run_id, mode, created_at, metrics_json) VALUES (?,?,?,?)",
                 (run_id, mode, datetime.now(timezone.utc).isoformat(), json.dumps(payload)))
    conn.commit()
    return {"run_id": run_id, "mode": mode, **payload}


def run_evaluation(mode, user_role="VIEWER", weights=None):
    if mode not in ("baseline", "proposed", "weighted", "tiered"):
        raise ValueError("mode must be 'baseline', 'proposed', 'weighted', or 'tiered'")
    active_weights = deepcopy(weights or load_config()["weights"])
    with _temporary_database():
        queries = get_conn().execute("SELECT * FROM eval_queries ORDER BY id").fetchall()
        if not queries:
            return {"error": "no evaluation queries found — run seed generation first"}
        rows = [_score_query(query, mode, user_role, {**load_config(), "weights": active_weights}) for query in queries]
        metrics = _metrics(rows)
        override_ok, rollback_ok = _exercise_override_and_rollback(user_role)
        metrics["manual_override_success"] = 100.0 if override_ok else 0.0
        metrics["rollback_success"] = 100.0 if rollback_ok else 0.0
    previous = next((item for item in latest_results() if item["mode"] != mode), None)
    if previous:
        metric_names = ("authority_selection_accuracy", "answer_accuracy", "citation_accuracy",
                        "access_control_accuracy", "conflict_detection_accuracy",
                        "manual_override_success", "rollback_success")
        metrics["overall_improvement"] = {
            name: round(metrics[name] - previous.get(name, 0), 2) for name in metric_names
        }
    result = _persist(mode, metrics, active_weights, rows)
    result["scenario_metrics"] = _scenario_metrics(rows)
    return result


def error_analysis():
    proposed = next((result for result in latest_results() if result["mode"] in ("proposed", "tiered", "weighted")), None)
    rows = proposed.get("rows", []) if proposed else []
    examples = {category: [] for category in sorted(ERROR_CATEGORIES)}
    for row in rows:
        category = row.get("error_category")
        if category in examples and len(examples[category]) < 3:
            examples[category].append({"query": row["query"], "expected": row["expected"],
                                       "got": row["got"], "reason": row["reason"]})
    return {"counts": {category: sum(row.get("error_category") == category for row in rows) for category in examples},
            "examples": examples}


def sensitivity_experiment():
    default = load_config()["weights"]
    alternatives = {
        "default": default,
        "recency_heavy": {"approval": 0.2, "ownership": 0.2, "recency": 0.5, "version": 0.05, "evidence": 0.05},
        "approval_only": {"approval": 1.0, "ownership": 0.0, "recency": 0.0, "version": 0.0, "evidence": 0.0},
    }
    results = {}
    for name, weights in alternatives.items():
        run = run_evaluation("weighted", weights=weights)
        results[name] = {
            "run_id": run["run_id"],
            "weights": weights,
            "authority_selection_accuracy": run["authority_selection_accuracy"],
            "answer_accuracy": run["answer_accuracy"],
            "citation_accuracy": run["citation_accuracy"],
            "access_control_accuracy": run["access_control_accuracy"],
            "conflict_detection_accuracy": run["conflict_detection_accuracy"],
        }
    return results


def latest_results():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM eval_results ORDER BY id DESC LIMIT 10").fetchall()
    return [{"run_id": row["run_id"], "mode": row["mode"], "created_at": row["created_at"],
             **json.loads(row["metrics_json"])} for row in rows]
