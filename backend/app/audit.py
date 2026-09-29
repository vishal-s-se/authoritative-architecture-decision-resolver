"""
Immutable cryptographic audit log layer.
Responsibility: Records every state-changing action in the system securely.
What it must never do: It must never provide an API or function to delete or update an event. It is strictly append-only.
"""
import json
import hashlib
from datetime import datetime, timezone
from .database import get_conn


def log_event(user, action, document_id=None, version_id=None,
              previous_value=None, new_value=None, reason=None, metadata=None):
    """
    Append an event to the secure audit log with a cryptographic hash chain.
    There is no UPDATE/DELETE path exposed for this table.
    
    Args:
        user (str): Username initiating the action.
        action (str): Action type (e.g., 'MANUAL_OVERRIDE').
        document_id (str, optional): Target document ID.
        version_id (str, optional): Target version ID.
        previous_value (any, optional): State before change.
        new_value (any, optional): State after change.
        reason (str, optional): Justification for the action.
        metadata (dict, optional): Extra event data.
        
    Returns:
        None
        
    Example:
        log_event("admin", "MANUAL_OVERRIDE", "doc-1", "doc-1-v2", reason="Emergency")
    """
    conn = get_conn()
    timestamp = datetime.now(timezone.utc).isoformat()
    previous = conn.execute("SELECT event_hash FROM audit_log ORDER BY event_id DESC LIMIT 1").fetchone()
    prev_hash = previous["event_hash"] if previous and previous["event_hash"] else ""
    payload = json.dumps({"timestamp": timestamp, "user": user, "action": action,
                          "document_id": document_id, "version_id": version_id,
                          "previous_value": previous_value, "new_value": new_value,
                          "reason": reason, "metadata": metadata}, sort_keys=True, default=str)
    event_hash = hashlib.sha256((prev_hash + payload).encode()).hexdigest()
    conn.execute(
        """INSERT INTO audit_log
           (timestamp, user, action, document_id, version_id, previous_value, new_value, reason, metadata_json, prev_hash, event_hash)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (
            timestamp,
            user,
            action,
            document_id,
            version_id,
            json.dumps(previous_value) if previous_value is not None else None,
            json.dumps(new_value) if new_value is not None else None,
            reason,
            json.dumps(metadata) if metadata is not None else None,
            prev_hash,
            event_hash,
        ),
    )
    conn.commit()


def get_events(limit=200, document_id=None):
    """
    Retrieve recent audit events.
    
    Args:
        limit (int): Max number of events to return.
        document_id (str, optional): Filter by document ID.
        
    Returns:
        list[dict]: List of audit log records.
        
    Example:
        get_events(10, "doc-1") -> [{"event_id": 1, "action": "CREATE", ...}]
    """
    conn = get_conn()
    if document_id:
        rows = conn.execute(
            "SELECT * FROM audit_log WHERE document_id=? ORDER BY event_id DESC LIMIT ?",
            (document_id, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM audit_log ORDER BY event_id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def verify_chain():
    """
    Verify the cryptographic hash chain of all audit events.
    
    Returns:
        dict: {"valid": bool, "first_broken_event": int or None, "events_checked": int}
        
    Example:
        verify_chain() -> {"valid": True, "first_broken_event": None, "events_checked": 50}
    """
    conn = get_conn()
    rows = conn.execute("SELECT * FROM audit_log ORDER BY event_id").fetchall()
    previous_hash = ""
    for row in rows:
        metadata = json.loads(row["metadata_json"]) if row["metadata_json"] else None
        payload = json.dumps({"timestamp": row["timestamp"], "user": row["user"], "action": row["action"],
                              "document_id": row["document_id"], "version_id": row["version_id"],
                              "previous_value": json.loads(row["previous_value"]) if row["previous_value"] else None,
                              "new_value": json.loads(row["new_value"]) if row["new_value"] else None,
                              "reason": row["reason"], "metadata": metadata}, sort_keys=True, default=str)
        expected = hashlib.sha256((previous_hash + payload).encode()).hexdigest()
        if row["prev_hash"] != previous_hash or row["event_hash"] != expected:
            return {"valid": False, "first_broken_event": row["event_id"]}
        previous_hash = row["event_hash"]
    return {"valid": True, "first_broken_event": None, "events_checked": len(rows)}
