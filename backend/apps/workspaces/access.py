"""Workspace isolation for HTTP requests.

A workspace identifier in a URL is only a *claim*. It becomes trusted when
the guard finds an active membership linking it to the authenticated user and
an unrevoked authorisation for the browser installation making the request.

The guard is structural, not a convention:

* ``WorkspaceAPIView`` always runs ``IsAuthenticated`` and ``WorkspaceAccess``
  first. ``permission_classes`` on a subclass only *adds* checks, and a
  subclass that tries to replace the guard machinery fails at import time.
* A system check (``checks.py``) refuses to start the application if a route
  that takes a ``workspace_id`` is served by anything else, or if a handler
  has no declared capability.
"""

from django.core.exceptions import ImproperlyConfigured
from rest_framework.exceptions import MethodNotAllowed, NotFound, PermissionDenied
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.views import APIView

from apps.accounts.models import DeviceInstallation

from .device_services import ensure_workspace_device
from .models import WorkspaceStatus
from .policies import Capability, has_capability
from .selectors import find_active_membership


class WorkspaceAccess(BasePermission):
    """Membership, device authorisation and capability, in that order."""

    def has_permission(self, request, view) -> bool:
        # A missing workspace and one the user does not belong to are
        # indistinguishable (404), so identifiers cannot be probed.
        membership = find_active_membership(request.user, view.kwargs["workspace_id"])
        if membership is None:
            raise NotFound("Workspace not found.")
        if membership.workspace.status != WorkspaceStatus.ACTIVE:
            raise PermissionDenied("This workspace is not active.", code="workspace_inactive")
        if not isinstance(request.auth, DeviceInstallation):
            # Only the device-bound session authenticator may reach workspaces.
            raise PermissionDenied("A device-bound session is required.")
        # Raises NotPermittedError (403 device_not_authorized) if revoked.
        request.workspace_device = ensure_workspace_device(
            installation=request.auth, membership=membership
        )
        request.membership = membership
        request.workspace = membership.workspace
        if request.method == "OPTIONS":
            return True
        return has_capability(membership, required_capability_for(view, request.method))


def required_capability_for(view, method: str) -> Capability:
    required = getattr(view, "required_capability", None)
    if isinstance(required, dict):
        if method not in required:
            raise MethodNotAllowed(method)
        required = required[method]
    if not isinstance(required, Capability):
        # Fail closed: an endpoint without a declared policy is a bug.
        raise ImproperlyConfigured(f"{type(view).__name__} declares no capability for {method}.")
    return required


class WorkspaceAPIView(APIView):
    """Base class for every endpoint under ``/workspaces/<workspace_id>/``.

    Subclasses set ``required_capability`` to a ``Capability`` or to a
    ``{"GET": ..., "POST": ...}`` mapping, and query tenant data only through
    ``self.workspace_queryset(Model)``.
    """

    #: Checks that run *after* the mandatory workspace guard.
    permission_classes: list = []
    required_capability: Capability | dict[str, Capability] | None = None

    _GUARD_MACHINERY = (
        "get_permissions",
        "check_permissions",
        "initial",
        "get_authenticators",
        "perform_authentication",
        "authentication_classes",
    )

    def __init_subclass__(cls, **kwargs) -> None:
        super().__init_subclass__(**kwargs)
        replaced = [name for name in cls._GUARD_MACHINERY if name in cls.__dict__]
        if replaced:
            raise TypeError(
                f"{cls.__name__} must not override {', '.join(replaced)}: "
                "the workspace guard cannot be replaced. Add checks with permission_classes."
            )

    def get_permissions(self) -> list[BasePermission]:
        extra = [permission() for permission in self.permission_classes]
        return [IsAuthenticated(), WorkspaceAccess(), *extra]

    def workspace_queryset(self, model):
        """Rows of ``model`` that belong to the request's workspace."""
        return model.objects.for_workspace(self.request.workspace)
