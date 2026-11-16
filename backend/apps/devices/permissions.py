from uuid import UUID

from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import BasePermission

from .models import Device, DeviceStatus

DEVICE_HEADER = "X-Device-Id"


class ActiveDeviceRequired(BasePermission):
    """Gate for synchronisation endpoints.

    Must run after ``WorkspaceAccess``. The request has to name, in the
    ``X-Device-Id`` header, an active device registered by the same user in
    the same workspace. On success the device is on ``request.device``.
    """

    def has_permission(self, request, view) -> bool:
        raw = request.headers.get(DEVICE_HEADER)
        if not raw:
            raise PermissionDenied(
                "A registered device is required for this operation.", code="device_required"
            )
        try:
            device_id = UUID(raw)
        except ValueError:
            device_id = None
        device = (
            Device.objects.filter(
                pk=device_id, workspace=request.workspace, user=request.user
            ).first()
            if device_id
            else None
        )
        if device is None:
            # Someone else's device looks exactly like an unknown one.
            raise PermissionDenied("Unknown device.", code="device_unknown")
        if device.status != DeviceStatus.ACTIVE:
            raise PermissionDenied("This device has been revoked.", code="device_revoked")
        request.device = device
        return True
