"""The single place that says which role may do what.

Views and services ask about *capabilities*, never about role names, so a
future change (for example owner-granted manager permissions, see
docs/OPEN_DECISIONS.md) is made here and nowhere else.
"""

from enum import StrEnum

from apps.common.exceptions import NotPermittedError

from .models import MembershipRole, WorkspaceMembership


class Capability(StrEnum):
    WORKSPACE_VIEW = "workspace.view"
    MEMBERS_VIEW = "members.view"
    MEMBERS_MANAGE = "members.manage"
    DEVICES_USE = "devices.use"  # register, use and revoke one's own devices
    DEVICES_MANAGE = "devices.manage"  # see and revoke any device in the workspace


_EVERY_MEMBER = frozenset({Capability.WORKSPACE_VIEW, Capability.DEVICES_USE})

ROLE_CAPABILITIES: dict[str, frozenset[Capability]] = {
    MembershipRole.OWNER: frozenset(Capability),
    MembershipRole.MANAGER: _EVERY_MEMBER | {Capability.MEMBERS_VIEW, Capability.DEVICES_MANAGE},
    MembershipRole.ATTENDANT: _EVERY_MEMBER,
    MembershipRole.AFFILIATE: _EVERY_MEMBER,
}


def capabilities_for(membership: WorkspaceMembership) -> frozenset[Capability]:
    return ROLE_CAPABILITIES.get(membership.role, frozenset())


def has_capability(membership: WorkspaceMembership, capability: Capability) -> bool:
    return capability in capabilities_for(membership)


def require_capability(membership: WorkspaceMembership, capability: Capability) -> None:
    if not has_capability(membership, capability):
        raise NotPermittedError("Your role in this workspace does not allow this action.")
