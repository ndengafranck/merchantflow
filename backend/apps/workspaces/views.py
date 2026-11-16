from django.db import transaction
from drf_spectacular.utils import extend_schema
from rest_framework.exceptions import NotFound
from rest_framework.generics import get_object_or_404
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from . import context, services
from .access import WorkspaceAPIView
from .models import MembershipStatus, WorkspaceMembership, WorkspaceStatus
from .policies import Capability
from .serializers import (
    MemberSerializer,
    MemberUpdateSerializer,
    MyMembershipSerializer,
    MyWorkspacesSerializer,
    SelectWorkspaceSerializer,
)


class MyWorkspacesView(APIView):
    """The workspaces the signed-in user can enter, and the selected one."""

    @extend_schema(operation_id="workspaces_list_mine", responses=MyWorkspacesSerializer)
    def get(self, request: Request) -> Response:
        memberships = (
            WorkspaceMembership.objects.select_related("workspace")
            .filter(
                user=request.user,
                status=MembershipStatus.ACTIVE,
                workspace__status=WorkspaceStatus.ACTIVE,
            )
            .order_by("workspace__name")
        )
        payload = {
            "current_workspace_id": context.last_workspace_id(request),
            "memberships": memberships,
        }
        return Response(MyWorkspacesSerializer(payload).data)


class CurrentWorkspaceView(APIView):
    """Remember the workspace this browser session used last (a UI hint)."""

    @extend_schema(request=SelectWorkspaceSerializer, responses=MyMembershipSerializer)
    def put(self, request: Request) -> Response:
        serializer = SelectWorkspaceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        membership = context.remember_workspace(request, serializer.validated_data["workspace_id"])
        if membership is None:
            raise NotFound("Workspace not found.")
        return Response(MyMembershipSerializer(membership).data)


class WorkspaceDetailView(WorkspaceAPIView):
    required_capability = Capability.WORKSPACE_VIEW

    @extend_schema(responses=MyMembershipSerializer)
    def get(self, request: Request, workspace_id) -> Response:
        return Response(MyMembershipSerializer(request.membership).data)


class MemberListView(WorkspaceAPIView):
    required_capability = Capability.MEMBERS_VIEW

    @extend_schema(responses=MemberSerializer(many=True))
    def get(self, request: Request, workspace_id) -> Response:
        members = self.workspace_queryset(WorkspaceMembership).select_related("user")
        return Response(MemberSerializer(members, many=True).data)


class MemberDetailView(WorkspaceAPIView):
    required_capability = Capability.MEMBERS_MANAGE

    @extend_schema(request=MemberUpdateSerializer, responses=MemberSerializer)
    def patch(self, request: Request, workspace_id, membership_id) -> Response:
        # Scoped lookup: a membership of another workspace is simply not found.
        members = self.workspace_queryset(WorkspaceMembership)
        get_object_or_404(members, pk=membership_id)
        serializer = MemberUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        changes = serializer.validated_data
        with transaction.atomic():
            if "role" in changes:
                services.change_member_role(
                    actor=request.membership, membership_id=membership_id, role=changes["role"]
                )
            if "status" in changes:
                services.set_member_status(
                    actor=request.membership, membership_id=membership_id, status=changes["status"]
                )
        member = members.select_related("user").get(pk=membership_id)
        return Response(MemberSerializer(member).data)
