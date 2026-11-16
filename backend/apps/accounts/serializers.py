from rest_framework import serializers

from .models import DeviceInstallation, User


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(trim_whitespace=False, write_only=True)


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "email", "full_name", "phone"]
        read_only_fields = fields


class InstallationSerializer(serializers.ModelSerializer):
    is_current = serializers.SerializerMethodField()

    class Meta:
        model = DeviceInstallation
        fields = [
            "id",
            "label",
            "status",
            "is_current",
            "created_at",
            "last_login_at",
            "revoked_at",
        ]
        read_only_fields = fields

    def get_is_current(self, installation: DeviceInstallation) -> bool:
        current = getattr(self.context["request"], "auth", None)
        return current is not None and current.pk == installation.pk
