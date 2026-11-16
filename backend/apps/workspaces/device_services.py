"""Workspace-specific device authorisation."""

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.accounts.models import DeviceInstallation
from apps.audit.services import record_event
from apps.common.exceptions import NotFoundError, NotPermittedError

from .locking import lock_memberships, locked_member
from .models import (
    DeviceRevocationReason,
    MembershipStatus,
    WorkspaceDevice,
    WorkspaceDeviceStatus,
    WorkspaceMembership,
)
from .policies import Capability, has_capability, outranks


def ensure_workspace_device(
    *, installation: DeviceInstallation, membership: WorkspaceMembership
) -> WorkspaceDevice:
    """Return this installation's authorisation for the workspace.

    The first entry by an active member creates it (no owner approval is
    required at present, see OPEN_DECISIONS O-020). A revoked authorisation is
    never recreated here; only ``reauthorize_workspace_device`` lifts it.
    """
    if installation.user_id != membership.user_id or not installation.is_active:
        raise NotPermittedError("This device cannot be used here.", code="device_not_authorized")
    lookup = {"workspace_id": membership.workspace_id, "installation": installation}
    device = WorkspaceDevice.objects.filter(**lookup).first()
    if device is None:
        device = _authorize_on_first_entry(membership, lookup)
    if device.status != WorkspaceDeviceStatus.ACTIVE:
        raise NotPermittedError(
            "This device is no longer authorised for this workspace.",
            code="device_not_authorized",
        )
    return device


def _authorize_on_first_entry(membership: WorkspaceMembership, lookup: dict) -> WorkspaceDevice:
    try:
        with transaction.atomic():
            # Lock the membership so this cannot interleave with its removal:
            # removal holds the row FOR UPDATE until it has revoked every device.
            still_active = (
                WorkspaceMembership.objects.select_for_update(no_key=True)
                .filter(pk=membership.pk, status=MembershipStatus.ACTIVE)
                .exists()
            )
            if not still_active:
                raise NotFoundError("Workspace not found.")
            device = WorkspaceDevice.objects.create(**lookup)
            record_event(
                action="device.authorized",
                target=device,
                actor=membership.user,
                workspace=membership.workspace,
            )
            return device
    except IntegrityError:
        # Another request from the same browser created it first.
        return WorkspaceDevice.objects.get(**lookup)


def _lock_device_and_holder(actor: WorkspaceMembership, capability: Capability, device_id):
    """Lock in the order of ``locking.py``: workspace, then the actor and the
    device holder's memberships together, then the device.

    The holder is looked up first without a lock (a device's installation, and
    so its holder, never changes); the rank decision is then taken on the
    holder's locked, current membership.
    """
    peek = (
        WorkspaceDevice.objects.for_workspace(actor.workspace)
        .select_related("installation")
        .filter(pk=device_id)
        .first()
    )
    holder_id = None
    if peek is not None:
        holder_id = (
            WorkspaceMembership.objects.filter(
                workspace_id=actor.workspace_id, user_id=peek.installation.user_id
            )
            .values_list("pk", flat=True)
            .first()
        )
    actor, locked = lock_memberships(actor, capability, [holder_id] if holder_id else [])
    if peek is None:
        return actor, None, None
    device = (
        WorkspaceDevice.objects.select_for_update(of=("self",))
        .select_related("installation")
        .get(pk=peek.pk)
    )
    return actor, device, locked_member(locked, holder_id)


def _may_act_on(actor: WorkspaceMembership, device, holder) -> bool:
    """Own devices always; others only with devices.manage and a higher rank."""
    if device is None or holder is None:
        return False
    if holder.pk == actor.pk:
        return True
    return has_capability(actor, Capability.DEVICES_MANAGE) and outranks(actor, holder)


def _revoke(device: WorkspaceDevice, *, by, reason: str, workspace, holder_role: str) -> None:
    device.status = WorkspaceDeviceStatus.REVOKED
    device.revoked_at = timezone.now()
    device.revoked_by = by
    device.revocation_reason = reason
    device.save(
        update_fields=["status", "revoked_at", "revoked_by", "revocation_reason", "updated_at"]
    )
    record_event(
        action="device.revoked",
        target=device,
        actor=by,
        workspace=workspace,
        metadata={"reason": reason, "holder_role": holder_role},
    )


@transaction.atomic
def revoke_workspace_device(*, actor: WorkspaceMembership, device_id) -> WorkspaceDevice:
    """Close the workspace to one installation. Idempotent.

    Members revoke their own devices. Holders of ``devices.manage`` revoke
    devices of members ranked below them, so a manager cannot lock out the
    owner or another manager. A device the actor may not touch is reported as
    not found.
    """
    actor, device, holder = _lock_device_and_holder(actor, Capability.DEVICES_USE, device_id)
    if not _may_act_on(actor, device, holder):
        raise NotFoundError("Device not found in this workspace.")
    if device.status == WorkspaceDeviceStatus.ACTIVE:
        _revoke(
            device,
            by=actor.user,
            reason=DeviceRevocationReason.MANUAL,
            workspace=actor.workspace,
            holder_role=holder.role,
        )
    return device


@transaction.atomic
def reauthorize_workspace_device(*, actor: WorkspaceMembership, device_id) -> WorkspaceDevice:
    """Lift a revocation, explicitly. Idempotent for an active device.

    The only way a revoked browser regains access to a workspace, including
    after the member was reinstated. Requires ``devices.manage`` and a higher
    rank than the device's holder; the owner may also re-authorise their own.
    The holder must be an active member and the installation still active.
    """
    actor, device, holder = _lock_device_and_holder(actor, Capability.DEVICES_MANAGE, device_id)
    own_as_owner = holder is not None and holder.pk == actor.pk and actor.is_owner
    if device is None or not (own_as_owner or (holder is not None and outranks(actor, holder))):
        raise NotFoundError("Device not found in this workspace.")
    if device.status == WorkspaceDeviceStatus.ACTIVE:
        return device
    if holder.status != MembershipStatus.ACTIVE:
        raise NotPermittedError(
            "Reinstate the member before re-authorising their device.",
            code="member_not_active",
        )
    if not device.installation.is_active:
        raise NotPermittedError(
            "This browser was signed out everywhere by its owner and cannot be re-authorised.",
            code="installation_revoked",
        )
    previous_reason = device.revocation_reason
    device.status = WorkspaceDeviceStatus.ACTIVE
    device.revoked_at = None
    device.revoked_by = None
    device.revocation_reason = None
    device.save(
        update_fields=["status", "revoked_at", "revoked_by", "revocation_reason", "updated_at"]
    )
    record_event(
        action="device.reauthorized",
        target=device,
        actor=actor.user,
        workspace=actor.workspace,
        metadata={"previous_reason": previous_reason},
    )
    return device


def revoke_devices_of_removed_member(*, membership: WorkspaceMembership, by) -> int:
    """Revoke every active device of a member being removed. Call inside the
    removal transaction, after ``locking.py`` steps 1-2 (step 3 happens here)."""
    devices = (
        WorkspaceDevice.objects.for_workspace(membership.workspace)
        .select_for_update(of=("self",))
        .filter(installation__user_id=membership.user_id, status=WorkspaceDeviceStatus.ACTIVE)
        .order_by("pk")
    )
    count = 0
    for device in devices:
        _revoke(
            device,
            by=by,
            reason=DeviceRevocationReason.MEMBERSHIP_REMOVED,
            workspace=membership.workspace,
            holder_role=membership.role,
        )
        count += 1
    return count


def touch_workspace_device(device: WorkspaceDevice) -> None:
    WorkspaceDevice.objects.filter(pk=device.pk).update(last_seen_at=timezone.now())
