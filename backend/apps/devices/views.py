from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.generics import get_object_or_404
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from apps.workspaces.access import WorkspaceAccess, WorkspaceAPIView
from apps.workspaces.policies import Capability, has_capability

from . import services
from .models import Device
from .permissions import DEVICE_HEADER, ActiveDeviceRequired
from .serializers import DeviceRegistrationSerializer, DeviceSerializer, SyncHandshakeSerializer


class DeviceListView(WorkspaceAPIView):
    required_capability = Capability.DEVICES_USE

    @extend_schema(responses=DeviceSerializer(many=True))
    def get(self, request: Request, workspace_id) -> Response:
        devices = Device.objects.filter(workspace=request.workspace)
        if not has_capability(request.membership, Capability.DEVICES_MANAGE):
            devices = devices.filter(user=request.user)
        return Response(DeviceSerializer(devices, many=True).data)

    @extend_schema(request=DeviceRegistrationSerializer, responses={201: DeviceSerializer})
    def post(self, request: Request, workspace_id) -> Response:
        serializer = DeviceRegistrationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        device = services.register_device(
            membership=request.membership, **serializer.validated_data
        )
        return Response(DeviceSerializer(device).data, status=status.HTTP_201_CREATED)


class DeviceRevokeView(WorkspaceAPIView):
    # Any member may call this; the service decides whether it is their own
    # device or whether they manage devices.
    required_capability = Capability.DEVICES_USE

    @extend_schema(request=None, responses=DeviceSerializer)
    def post(self, request: Request, workspace_id, device_id) -> Response:
        get_object_or_404(Device, pk=device_id, workspace=request.workspace)
        device = services.revoke_device(actor=request.membership, device_id=device_id)
        return Response(DeviceSerializer(device).data)


class SyncHandshakeView(WorkspaceAPIView):
    """Confirms that this device may synchronise with this workspace.

    The first synchronisation endpoint; the operation queue is a later
    milestone and will sit behind the same permission classes.
    """

    permission_classes = [IsAuthenticated, WorkspaceAccess, ActiveDeviceRequired]
    required_capability = Capability.DEVICES_USE

    @extend_schema(
        request=None,
        responses=SyncHandshakeSerializer,
        parameters=[OpenApiParameter(DEVICE_HEADER, str, OpenApiParameter.HEADER, required=True)],
    )
    def post(self, request: Request, workspace_id) -> Response:
        services.touch_device(request.device)
        payload = {"device_id": request.device.id, "server_time": timezone.now()}
        return Response(SyncHandshakeSerializer(payload).data)
