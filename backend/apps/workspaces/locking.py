"""The one lock order for changes to memberships and device authorisations.

Every service that changes a membership or a workspace device acquires row
locks in this order, and only in this order:

1. the **workspace** row, ``FOR NO KEY UPDATE``. All member and device
   management in one workspace therefore runs one at a time, while inserts
   elsewhere that reference the workspace (they take ``FOR KEY SHARE`` for
   their foreign key) are not blocked;
2. every **membership** the operation needs (the actor and any target), in a
   single statement ordered by primary key, ``FOR UPDATE``;
3. **workspace devices**, ordered by primary key, ``FOR UPDATE``;
4. **user account** rows, ``FOR UPDATE``.

Authorisation is decided only after step 2, on the rows just locked, so a role
or status change that commits first is always seen, and one that starts later
waits for this operation to finish.

Two code paths take a subset without step 1. Neither holds a lock that an
operation following the full order could be waiting for while it waits itself,
so they cannot form a cycle:

* first entry into a workspace (``device_services._authorize_on_first_entry``)
  locks only the member's own membership (step 2, ``FOR NO KEY UPDATE``) and
  then inserts a device row;
* ``accounts.services.deactivate_user`` locks only the account (step 4) and
  reads memberships without locking them.
"""

from uuid import UUID

from django.db import transaction

from apps.common.exceptions import NotPermittedError

from .models import MembershipStatus, Workspace, WorkspaceMembership, WorkspaceStatus
from .policies import Capability, require_capability


def _as_uuid(value) -> UUID | None:
    try:
        return value if isinstance(value, UUID) else UUID(str(value))
    except (TypeError, ValueError):
        return None


def lock_memberships(
    actor: WorkspaceMembership, capability: Capability, member_ids=()
) -> tuple[WorkspaceMembership, dict[UUID, WorkspaceMembership]]:
    """Steps 1 and 2, then authorise the actor on its freshly locked row.

    Returns the fresh actor and every requested membership of the actor's
    workspace that exists (ids from other workspaces are silently left out).
    Must run inside ``transaction.atomic()``; locks are held until commit.
    """
    if not transaction.get_connection().in_atomic_block:
        raise RuntimeError("Membership locks must be taken inside transaction.atomic().")
    list(
        Workspace.objects.select_for_update(no_key=True)
        .filter(pk=actor.workspace_id)
        .values_list("pk", flat=True)
    )
    wanted = {actor.pk} | {i for i in map(_as_uuid, member_ids) if i is not None}
    locked = {
        m.pk: m
        for m in WorkspaceMembership.objects.select_for_update(of=("self",))
        .select_related("workspace", "user")
        .filter(workspace_id=actor.workspace_id, pk__in=wanted)
        .order_by("pk")
    }
    fresh = locked.get(actor.pk)
    if (
        fresh is None
        or fresh.status != MembershipStatus.ACTIVE
        or fresh.workspace.status != WorkspaceStatus.ACTIVE
        or not fresh.user.is_active
    ):
        raise NotPermittedError("You no longer have access to this workspace.")
    require_capability(fresh, capability)
    return fresh, locked


def locked_member(locked: dict, membership_id) -> WorkspaceMembership | None:
    key = _as_uuid(membership_id)
    return locked.get(key) if key is not None else None
