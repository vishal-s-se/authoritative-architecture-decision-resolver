from .database import get_conn
from .audit import log_event

ROLE_RANK = {"VIEWER": 0, "ENGINEER": 1, "ARCHITECT": 2, "ADMIN": 3}


def is_allowed(document_id, role):
    """ADMIN always passes. Otherwise consult access_rules; default-allow if no rule exists."""
    if role == "ADMIN":
        return True
    conn = get_conn()
    row = conn.execute(
        "SELECT allowed FROM access_rules WHERE document_id=? AND role=?", (document_id, role)
    ).fetchone()
    if row is None:
        return True  # no explicit rule -> default allow
    return bool(row["allowed"])


def check_access_or_log(document_id, role, user, action="QUERY"):
    allowed = is_allowed(document_id, role)
    if not allowed:
        log_event(user, "ACCESS_DENIED", document_id=document_id, reason=f"role {role} not permitted",
                   metadata={"action": action})
    return allowed
