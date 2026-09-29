"""
Role-based access control (RBAC) layer.
Responsibility: Enforces document-level permissions based on user roles.
What it must never do: It must never determine authority or answer questions. It only decides if a document can be viewed.
"""
from .database import get_conn
from .audit import log_event

ROLE_RANK = {"VIEWER": 0, "ENGINEER": 1, "ARCHITECT": 2, "ADMIN": 3}


def is_allowed(document_id, role):
    """
    Check if a specific role is allowed to access a document.
    ADMIN always passes; every other role needs an explicit document rule.
    
    Args:
        document_id (str): The ID of the document (e.g., 'doc-1').
        role (str): The user's role (e.g., 'VIEWER', 'ADMIN').
        
    Returns:
        bool: True if allowed, False otherwise.
        
    Example:
        is_allowed('doc-1', 'VIEWER') -> False
    """
    if role not in ROLE_RANK:
        return False
    if role == "ADMIN":
        return True
    conn = get_conn()
    row = conn.execute(
        "SELECT allowed FROM access_rules WHERE document_id=? AND role=?", (document_id, role)
    ).fetchone()
    if row is None:
        return False
    return bool(row["allowed"])


def check_access_or_log(document_id, role, user, action="QUERY"):
    """
    Check access and log an audit event if access is denied.
    
    Args:
        document_id (str): The ID of the document.
        role (str): The role of the user.
        user (str): The username attempting access.
        action (str): The context of the action being attempted.
        
    Returns:
        bool: True if allowed, False otherwise.
        
    Example:
        check_access_or_log('doc-1', 'VIEWER', 'viewer1') -> False (and logs ACCESS_DENIED)
    """
    allowed = is_allowed(document_id, role)
    if not allowed:
        log_event(user, "ACCESS_DENIED", document_id=document_id, reason=f"role {role} not permitted",
                   metadata={"action": action})
    return allowed
