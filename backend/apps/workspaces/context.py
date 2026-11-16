"""The workspace a browser session is currently working in.

This is a convenience so the SPA can restore its place after a reload. It is
not an authorisation mechanism: every workspace-scoped request is checked
again by ``access.resolve_membership``.
"""

from uuid import UUID

from rest_framework.exceptions import APIException

from .access import resolve_membership
from .models import WorkspaceMembership

SESSION_KEY = "current_workspace_id"


def select_workspace(request, workspace_id: UUID) -> WorkspaceMembership:
    membership = resolve_membership(request.user, workspace_id)
    request.session[SESSION_KEY] = str(workspace_id)
    return membership


def current_workspace_id(request) -> str | None:
    """Return the selected workspace if the user may still enter it."""
    stored = request.session.get(SESSION_KEY)
    if stored is None:
        return None
    try:
        resolve_membership(request.user, UUID(stored))
    except (APIException, ValueError):
        del request.session[SESSION_KEY]
        return None
    return stored
