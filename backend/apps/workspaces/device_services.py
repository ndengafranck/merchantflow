"""Workspace-specific device authorisation."""

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.accounts.models import DeviceInstallation
from apps.audit.services import record_event
from apps.common.exceptions import NotFoundError, NotPermittedError

from .models import WorkspaceDevice, WorkspaceDeviceStatus, WorkspaceMembership
from .policies import Capability, has_capability
from .services import authorize_actor


def ensure_workspace_device(
    *, installation: DeviceInstallation, membership: WorkspaceMembership
) -> WorkspaceDevice:
    """Return this installation's authorisation for the workspace.

    The first entry by an active member creates it (no owner approval is
    required at present, see OPEN_DECISIONS O-020). A revoked authorisation is
    final for that installation: it is never recreated here.
    """
    if installation.user_id != membership.user_id or not installation.is_active:
        raise NotPermittedError("This device cannot be used here.", code="device_not_authorized")
    lookup = {"workspace_id": membership.workspace_id, "installation": installation}
    device = WorkspaceDevice.objects.filter(**lookup).first()
    if device is None:
        try:
            with transaction.atomic():
                device = WorkspaceDevice.objects.create(**lookup)
                record_event(
                    action="device.authorized",
                    target=device,
                    actor=membership.user,
                    workspace=membership.workspace,
                )
        except IntegrityError:
            # Another request from the same browser created it first.
            device = WorkspaceDevice.objects.get(**lookup)
    if device.status != WorkspaceDeviceStatus.ACTIVE:
        raise NotPermittedError(
            "This device is no longer authorised for this workspace.",
            code="device_not_authorized",
        )
    return device


@transaction.atomic
def revoke_workspace_device(*, actor: WorkspaceMembership, device_id) -> WorkspaceDevice:
    """Close the workspace to one installation. Idempotent.

    Members revoke their own; holders of ``devices.manage`` revoke any. A
    device the actor may not touch is reported as not found.
    """
    actor = authorize_actor(actor, Capability.DEVICES_USE)
    device = (
        WorkspaceDevice.objects.for_workspace(actor.workspace)
        .select_for_update(of=("self",))
        .select_related("installation")
        .filter(pk=device_id)
        .first()
    )
    is_own = device is not None and device.installation.user_id == actor.user_id
    if device is None or not (is_own or has_capability(actor, Capability.DEVICES_MANAGE)):
        raise NotFoundError("Device not found in this workspace.")
    if device.status == WorkspaceDeviceStatus.REVOKED:
        return device
    device.status = WorkspaceDeviceStatus.REVOKED
    device.revoked_at = timezone.now()
    device.revoked_by = actor.user
    device.save(update_fields=["status", "revoked_at", "revoked_by", "updated_at"])
    record_event(
        action="device.revoked", target=device, actor=actor.user, workspace=actor.workspace
    )
    return device


def touch_workspace_device(device: WorkspaceDevice) -> None:
    WorkspaceDevice.objects.filter(pk=device.pk).update(last_seen_at=timezone.now())
