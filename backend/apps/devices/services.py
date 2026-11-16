from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied

from apps.audit.services import record_event
from apps.common.exceptions import DomainError
from apps.workspaces.models import WorkspaceMembership
from apps.workspaces.policies import Capability, has_capability, require_capability

from .models import Device, DeviceStatus


@transaction.atomic
def register_device(*, membership: WorkspaceMembership, name: str, platform: str = "") -> Device:
    """Register a device for the member who is using it."""
    require_capability(membership, Capability.DEVICES_USE)
    device = Device.objects.create(
        workspace_id=membership.workspace_id,
        user_id=membership.user_id,
        name=name.strip(),
        platform=platform.strip(),
    )
    record_event(
        action="device.registered",
        target=device,
        actor=membership.user,
        workspace=membership.workspace,
    )
    return device


@transaction.atomic
def revoke_device(*, actor: WorkspaceMembership, device_id) -> Device:
    """Revoke a device. Members revoke their own; device managers revoke any.

    Revocation is permanent and idempotent: revoking twice is not an error.
    """
    try:
        device = Device.objects.select_for_update().get(
            pk=device_id, workspace_id=actor.workspace_id
        )
    except Device.DoesNotExist as exc:
        raise DomainError("Device not found in this workspace.", code="device_not_found") from exc
    if device.user_id != actor.user_id and not has_capability(actor, Capability.DEVICES_MANAGE):
        raise PermissionDenied("You can only revoke your own devices.")
    if device.status == DeviceStatus.REVOKED:
        return device
    device.status = DeviceStatus.REVOKED
    device.revoked_at = timezone.now()
    device.revoked_by = actor.user
    device.save(update_fields=["status", "revoked_at", "revoked_by", "updated_at"])
    record_event(
        action="device.revoked", target=device, actor=actor.user, workspace=actor.workspace
    )
    return device


def touch_device(device: Device) -> None:
    Device.objects.filter(pk=device.pk).update(last_seen_at=timezone.now())
