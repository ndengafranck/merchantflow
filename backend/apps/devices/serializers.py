from rest_framework import serializers

from .models import Device


class DeviceSerializer(serializers.ModelSerializer):
    user_id = serializers.UUIDField(read_only=True)

    class Meta:
        model = Device
        fields = [
            "id",
            "user_id",
            "name",
            "platform",
            "status",
            "last_seen_at",
            "revoked_at",
            "created_at",
        ]
        read_only_fields = fields


class DeviceRegistrationSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=80)
    platform = serializers.CharField(max_length=120, required=False, allow_blank=True, default="")


class SyncHandshakeSerializer(serializers.Serializer):
    device_id = serializers.UUIDField()
    server_time = serializers.DateTimeField()
