"""Business operations on workspaces and memberships.

All writes go through these functions. Each one runs in a transaction, locks
the rows it reasons about, and records an audit event. The acting membership
passed in by the caller is treated only as an identifier: ``authorize_actor``
re-reads and locks it, so authority is always judged on current data.
"""

import secrets

from django.db import transaction
from django.utils.text import slugify

from apps.accounts.models import User
from apps.audit.services import record_event
from apps.common.exceptions import ConflictError, DomainError, NotPermittedError

from .locking import lock_memberships, locked_member
from .models import (
    MembershipRole,
    MembershipStatus,
    Workspace,
    WorkspaceMembership,
)
from .policies import Capability


def _unique_slug(name: str) -> str:
    base = slugify(name)[:120] or "workspace"
    slug = base
    while Workspace.objects.filter(slug=slug).exists():
        slug = f"{base}-{secrets.token_hex(3)}"
    return slug


@transaction.atomic
def create_workspace(*, name: str, owner: User) -> Workspace:
    """Create a workspace together with its owner membership, or neither."""
    name = name.strip()
    if not name:
        raise DomainError("A workspace name is required.", code="name_required")
    if not owner.is_active:
        raise DomainError("An inactive user cannot own a workspace.", code="owner_inactive")
    workspace = Workspace.objects.create(name=name, slug=_unique_slug(name))
    WorkspaceMembership.objects.create(workspace=workspace, user=owner, role=MembershipRole.OWNER)
    record_event(action="workspace.created", target=workspace, actor=owner, workspace=workspace)
    return workspace


def authorize_actor(actor: WorkspaceMembership, capability: Capability) -> WorkspaceMembership:
    """Lock the workspace and the acting membership (``locking.py`` steps 1-2),
    then check, on the fresh row, that the actor may do this.

    Must be called inside a transaction. The locks are held until commit, so
    the actor cannot be demoted, suspended or removed while the operation runs.
    Returns the fresh row; callers must use it instead of the one passed in.
    """
    fresh, _ = lock_memberships(actor, capability)
    return fresh


def _lock_actor_and_target(actor, capability, membership_id):
    """Steps 1-2 for an operation on another member of the actor's workspace."""
    fresh, locked = lock_memberships(actor, capability, [membership_id])
    target = locked_member(locked, membership_id)
    if target is None:
        raise DomainError("Member not found in this workspace.", code="member_not_found")
    return fresh, target


@transaction.atomic
def add_member(*, actor: WorkspaceMembership, user: User, role: str) -> WorkspaceMembership:
    actor = authorize_actor(actor, Capability.MEMBERS_MANAGE)
    if role not in MembershipRole.values:
        raise DomainError("Unknown role.", code="invalid_role")
    if role == MembershipRole.OWNER:
        raise DomainError(
            "A workspace has one owner. Transfer ownership instead.", code="owner_role_reserved"
        )
    if WorkspaceMembership.objects.filter(workspace_id=actor.workspace_id, user=user).exists():
        raise ConflictError("This user is already a member.", code="already_member")
    membership = WorkspaceMembership.objects.create(
        workspace_id=actor.workspace_id, user=user, role=role
    )
    record_event(
        action="membership.added",
        target=membership,
        actor=actor.user,
        workspace=actor.workspace,
        metadata={"role": role},
    )
    return membership


@transaction.atomic
def change_member_role(
    *, actor: WorkspaceMembership, membership_id, role: str
) -> WorkspaceMembership:
    actor, membership = _lock_actor_and_target(actor, Capability.MEMBERS_MANAGE, membership_id)
    if role not in MembershipRole.values:
        raise DomainError("Unknown role.", code="invalid_role")
    if membership.is_owner or role == MembershipRole.OWNER:
        raise DomainError(
            "The owner role only changes through an ownership transfer.",
            code="owner_role_reserved",
        )
    if membership.role != role:
        previous = membership.role
        membership.role = role
        membership.save(update_fields=["role", "updated_at"])
        record_event(
            action="membership.role_changed",
            target=membership,
            actor=actor.user,
            workspace=actor.workspace,
            metadata={"from": previous, "to": role},
        )
    return membership


@transaction.atomic
def set_member_status(
    *, actor: WorkspaceMembership, membership_id, status: str
) -> WorkspaceMembership:
    actor, membership = _lock_actor_and_target(actor, Capability.MEMBERS_MANAGE, membership_id)
    if status not in MembershipStatus.values:
        raise DomainError("Unknown status.", code="invalid_status")
    if membership.is_owner:
        raise DomainError(
            "The owner cannot be suspended or removed. Transfer ownership first.",
            code="owner_status_locked",
        )
    if membership.status != status:
        previous = membership.status
        membership.status = status
        membership.save(update_fields=["status", "updated_at"])
        record_event(
            action="membership.status_changed",
            target=membership,
            actor=actor.user,
            workspace=actor.workspace,
            metadata={"from": previous, "to": status},
        )
        if status == MembershipStatus.REMOVED:
            # Removal ends this member's device authorisations. Reinstatement
            # does not restore them: see device_services.reauthorize_workspace_device.
            from .device_services import revoke_devices_of_removed_member

            revoke_devices_of_removed_member(membership=membership, by=actor.user)
    return membership


@transaction.atomic
def transfer_ownership(*, actor: WorkspaceMembership, new_owner_id) -> WorkspaceMembership:
    """Make another active member the owner; the previous owner becomes a manager."""
    # locking.py steps 1-2: workspace, then current owner and successor together.
    current, locked = lock_memberships(actor, Capability.MEMBERS_MANAGE, [new_owner_id])
    if not current.is_owner:
        raise NotPermittedError("Only the owner can transfer ownership.", code="not_owner")
    successor = locked_member(locked, new_owner_id)
    if successor is None:
        raise DomainError("Member not found in this workspace.", code="member_not_found")
    # Lock the successor's account too, so a concurrent deactivation of that
    # account either finishes first (and is seen here) or waits and then sees
    # the new ownership (and is refused): accounts.services.deactivate_user.
    successor_user = User.objects.select_for_update().get(pk=successor.user_id)
    if successor.pk == current.pk:
        raise ConflictError("This member already owns the workspace.", code="already_owner")
    if successor.status != MembershipStatus.ACTIVE or not successor_user.is_active:
        raise DomainError("The new owner must be an active member.", code="successor_inactive")

    # Demote before promoting: the single-owner constraint is checked per statement.
    current.role = MembershipRole.MANAGER
    current.save(update_fields=["role", "updated_at"])
    successor.role = MembershipRole.OWNER
    successor.save(update_fields=["role", "updated_at"])
    record_event(
        action="workspace.ownership_transferred",
        target=successor,
        actor=current.user,
        workspace=current.workspace,
        metadata={"previous_owner_membership": str(current.pk)},
    )
    return successor
