"""The workspace a browser session used last.

A convenience so the SPA can send someone back to where they were after
signing in. It is not an authorisation mechanism and it does not decide which
workspace a screen shows: the SPA takes that from its URL, and every
workspace-scoped request is checked by ``access.WorkspaceAccess``.
"""

from uuid import UUID

from .models import WorkspaceMembership
from .selectors import find_active_membership, membership_grants_entry

SESSION_KEY = "current_workspace_id"


def remember_workspace(request, workspace_id: UUID) -> WorkspaceMembership | None:
    """Record the workspace if the user may enter it; ``None`` otherwise."""
    membership = find_active_membership(request.user, workspace_id)
    if not membership_grants_entry(membership):
        return None
    request.session[SESSION_KEY] = str(workspace_id)
    return membership


def last_workspace_id(request) -> str | None:
    """The remembered workspace, if the user may still enter it."""
    stored = request.session.get(SESSION_KEY)
    if stored is None:
        return None
    try:
        allowed = membership_grants_entry(find_active_membership(request.user, UUID(stored)))
    except ValueError:
        allowed = False
    if not allowed:
        del request.session[SESSION_KEY]
        return None
    return stored
