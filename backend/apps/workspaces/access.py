"""Workspace isolation for HTTP requests.

A workspace identifier in a URL is only a *claim*. It becomes trusted when
``resolve_membership`` finds an active membership linking it to the
authenticated user. Workspace-scoped views must extend ``WorkspaceAPIView``
and build every query from ``request.workspace``, never from raw input.
"""

from uuid import UUID

from django.core.exceptions import ImproperlyConfigured
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.views import APIView

from .models import MembershipStatus, WorkspaceMembership, WorkspaceStatus
from .policies import Capability, has_capability


def resolve_membership(user, workspace_id: UUID) -> WorkspaceMembership:
    """Return the user's active membership of the workspace or refuse.

    A missing workspace and a workspace the user does not belong to are
    indistinguishable (404), so identifiers cannot be probed.
    """
    membership = (
        WorkspaceMembership.objects.select_related("workspace", "user")
        .filter(workspace_id=workspace_id, user=user, status=MembershipStatus.ACTIVE)
        .first()
    )
    if membership is None:
        raise NotFound("Workspace not found.")
    if membership.workspace.status != WorkspaceStatus.ACTIVE:
        raise PermissionDenied("This workspace is not active.", code="workspace_inactive")
    return membership


class WorkspaceAccess(BasePermission):
    """Resolves the membership and enforces the view's required capability."""

    def has_permission(self, request, view) -> bool:
        membership = resolve_membership(request.user, view.kwargs["workspace_id"])
        request.membership = membership
        request.workspace = membership.workspace
        if request.method == "OPTIONS":
            return True
        return has_capability(membership, self._required_capability(request, view))

    @staticmethod
    def _required_capability(request, view) -> Capability:
        required = getattr(view, "required_capability", None)
        if isinstance(required, dict):
            required = required.get(request.method)
        if not isinstance(required, Capability):
            # Fail closed: an endpoint without a declared policy is a bug.
            raise ImproperlyConfigured(
                f"{type(view).__name__} declares no capability for {request.method}."
            )
        return required


class WorkspaceAPIView(APIView):
    """Base class for every endpoint under ``/workspaces/<workspace_id>/``.

    Subclasses set ``required_capability`` to a ``Capability`` or to a
    ``{"GET": ..., "POST": ...}`` mapping. Subclasses that add permission
    classes must keep these two first.
    """

    permission_classes = [IsAuthenticated, WorkspaceAccess]
    required_capability: Capability | dict[str, Capability] | None = None
