from rest_framework import serializers

from .models import MembershipRole, MembershipStatus, Workspace, WorkspaceMembership
from .policies import capabilities_for


class WorkspaceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Workspace
        fields = ["id", "name", "slug", "status", "currency"]
        read_only_fields = fields


class MyMembershipSerializer(serializers.ModelSerializer):
    """The requesting user's own membership, with what it allows."""

    workspace = WorkspaceSerializer(read_only=True)
    capabilities = serializers.SerializerMethodField()

    class Meta:
        model = WorkspaceMembership
        fields = ["id", "role", "status", "workspace", "capabilities"]
        read_only_fields = fields

    def get_capabilities(self, membership: WorkspaceMembership) -> list[str]:
        return sorted(capabilities_for(membership))


class MyWorkspacesSerializer(serializers.Serializer):
    current_workspace_id = serializers.UUIDField(allow_null=True)
    memberships = MyMembershipSerializer(many=True)


class SelectWorkspaceSerializer(serializers.Serializer):
    workspace_id = serializers.UUIDField()


class MemberSerializer(serializers.ModelSerializer):
    user_id = serializers.UUIDField(read_only=True)
    email = serializers.EmailField(source="user.email", read_only=True)
    full_name = serializers.CharField(source="user.full_name", read_only=True)

    class Meta:
        model = WorkspaceMembership
        fields = ["id", "user_id", "email", "full_name", "role", "status", "created_at"]
        read_only_fields = fields


class MemberUpdateSerializer(serializers.Serializer):
    role = serializers.ChoiceField(choices=MembershipRole.choices, required=False)
    status = serializers.ChoiceField(choices=MembershipStatus.choices, required=False)

    def validate(self, attrs: dict) -> dict:
        if not attrs:
            raise serializers.ValidationError("Provide a role or a status to change.")
        return attrs
