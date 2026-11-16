"""Read-side lookups shared by the HTTP guard, the session context and services."""

from uuid import UUID

from .models import MembershipStatus, WorkspaceMembership, WorkspaceStatus


def find_active_membership(user, workspace_id: UUID) -> WorkspaceMembership | None:
    """The user's active membership of the workspace, or ``None``.

    The workspace itself may still be inactive; callers that need an open
    workspace use ``membership_grants_entry``.
    """
    return (
        WorkspaceMembership.objects.select_related("workspace", "user")
        .filter(workspace_id=workspace_id, user=user, status=MembershipStatus.ACTIVE)
        .first()
    )


def membership_grants_entry(membership: WorkspaceMembership | None) -> bool:
    return membership is not None and membership.workspace.status == WorkspaceStatus.ACTIVE
