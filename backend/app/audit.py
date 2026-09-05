import json
from datetime import datetime, timezone
from .database import get_conn


def log_event(user, action, document_id=None, version_id=None,
              previous_value=None, new_value=None, reason=None, metadata=None):
    """Append-only audit event. There is no UPDATE/DELETE path exposed for this table."""
    conn = get_conn()
    conn.execute(
        """INSERT INTO audit_log
           (timestamp, user, action, document_id, version_id, previous_value, new_value, reason, metadata_json)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (
            datetime.now(timezone.utc).isoformat(),
            user,
            action,
            document_id,
            version_id,
            json.dumps(previous_value) if previous_value is not None else None,
            json.dumps(new_value) if new_value is not None else None,
            reason,
            json.dumps(metadata) if metadata is not None else None,
        ),
    )
    conn.commit()


def get_events(limit=200, document_id=None):
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
