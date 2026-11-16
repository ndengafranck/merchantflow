from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework.request import Request
from rest_framework.response import Response

from apps.workspaces import device_services
from apps.workspaces.access import WorkspaceAPIView
from apps.workspaces.models import WorkspaceDevice
from apps.workspaces.policies import Capability, has_capability

from .serializers import SyncHandshakeSerializer, WorkspaceDeviceSerializer


class DeviceListView(WorkspaceAPIView):
    """Devices authorised for this workspace: one's own, or all for device managers."""

    required_capability = Capability.DEVICES_USE

    @extend_schema(responses=WorkspaceDeviceSerializer(many=True))
    def get(self, request: Request, workspace_id) -> Response:
        devices = self.workspace_queryset(WorkspaceDevice).select_related("installation")
        if not has_capability(request.membership, Capability.DEVICES_MANAGE):
            devices = devices.filter(installation__user=request.user)
        serializer = WorkspaceDeviceSerializer(devices, many=True, context={"request": request})
        return Response(serializer.data)


class DeviceRevokeView(WorkspaceAPIView):
    # Any member may call this; the service decides whether the device is
    # their own or whether they manage devices.
    required_capability = Capability.DEVICES_USE

    @extend_schema(request=None, responses=WorkspaceDeviceSerializer)
    def post(self, request: Request, workspace_id, device_id) -> Response:
        device = device_services.revoke_workspace_device(
            actor=request.membership, device_id=device_id
        )
        return Response(WorkspaceDeviceSerializer(device, context={"request": request}).data)


class SyncHandshakeView(WorkspaceAPIView):
    """Confirms that this browser may synchronise with this workspace.

    The device is the one the session is bound to; the client cannot name a
    different one. The operation queue is a later milestone.
    """

    required_capability = Capability.DEVICES_USE

    @extend_schema(request=None, responses=SyncHandshakeSerializer)
    def post(self, request: Request, workspace_id) -> Response:
        device_services.touch_workspace_device(request.workspace_device)
        payload = {"device_id": request.workspace_device.id, "server_time": timezone.now()}
        return Response(SyncHandshakeSerializer(payload).data)
