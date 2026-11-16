from rest_framework import serializers

from apps.workspaces.models import WorkspaceDevice


class WorkspaceDeviceSerializer(serializers.ModelSerializer):
    user_id = serializers.UUIDField(source="installation.user_id", read_only=True)
    label = serializers.CharField(source="installation.label", read_only=True)
    is_current = serializers.SerializerMethodField()

    class Meta:
        model = WorkspaceDevice
        fields = [
            "id",
            "user_id",
            "label",
            "status",
            "revocation_reason",
            "is_current",
            "last_seen_at",
            "revoked_at",
            "created_at",
        ]
        read_only_fields = fields

    def get_is_current(self, device: WorkspaceDevice) -> bool:
        return device.pk == self.context["request"].workspace_device.pk


class SyncHandshakeSerializer(serializers.Serializer):
    device_id = serializers.UUIDField()
    server_time = serializers.DateTimeField()
