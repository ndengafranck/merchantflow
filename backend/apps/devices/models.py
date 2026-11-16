from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.common.models import TimestampedModel, UUIDModel


class DeviceStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    REVOKED = "revoked", "Revoked"


class Device(UUIDModel, TimestampedModel):
    """A browser installation registered by one user for one workspace.

    Offline operations will be attributed to the device that captured them.
    A device is an *identifier*, not a credential: requests are authenticated
    by the user's session and additionally name their device.
    """

    workspace = models.ForeignKey(
        "workspaces.Workspace", on_delete=models.PROTECT, related_name="devices"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="devices"
    )
    name = models.CharField(max_length=80)
    platform = models.CharField(max_length=120, blank=True)
    status = models.CharField(
        max_length=16, choices=DeviceStatus.choices, default=DeviceStatus.ACTIVE
    )
    last_seen_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="revoked_devices",
    )

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=Q(status__in=DeviceStatus.values), name="device_status_valid"
            ),
            models.CheckConstraint(
                condition=(
                    Q(status="active", revoked_at__isnull=True, revoked_by__isnull=True)
                    | Q(status="revoked", revoked_at__isnull=False, revoked_by__isnull=False)
                ),
                name="device_revocation_consistent",
            ),
        ]
        indexes = [
            models.Index(fields=["workspace", "user"], name="device_ws_user_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.status})"
