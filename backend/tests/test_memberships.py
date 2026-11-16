"""Ownership and membership invariants: database constraints and services."""

import pytest
from django.db import IntegrityError, transaction

from apps.audit.models import AuditEvent
from apps.common.exceptions import ConflictError, DomainError, NotPermittedError
from apps.workspaces import services
from apps.workspaces.models import (
    MembershipRole,
    MembershipStatus,
    Workspace,
    WorkspaceMembership,
)

# --- Workspace creation -------------------------------------------------------


def test_create_workspace_creates_exactly_one_active_owner(make_user):
    owner = make_user()
    workspace = services.create_workspace(name="  Akwa Phones ", owner=owner)
    assert workspace.name == "Akwa Phones"
    assert workspace.currency == "XAF"
    membership = WorkspaceMembership.objects.get(workspace=workspace)
    assert (membership.user, membership.role, membership.status) == (owner, "owner", "active")
    assert AuditEvent.objects.filter(action="workspace.created", target_id=workspace.id).exists()


def test_workspaces_with_the_same_name_get_distinct_slugs(make_user):
    a = services.create_workspace(name="Akwa Phones", owner=make_user())
    b = services.create_workspace(name="Akwa Phones", owner=make_user())
    assert a.slug != b.slug


def test_create_workspace_refuses_blank_name_and_inactive_owner(make_user):
    with pytest.raises(DomainError):
        services.create_workspace(name="   ", owner=make_user())
    with pytest.raises(DomainError):
        services.create_workspace(name="Shop", owner=make_user(is_active=False))
    assert not Workspace.objects.exists()


# --- Database constraints (hold even if application code is bypassed) ----------


def test_database_rejects_a_second_owner(shop, make_user):
    with pytest.raises(IntegrityError), transaction.atomic():
        WorkspaceMembership.objects.create(
            workspace=shop.workspace, user=make_user(), role=MembershipRole.OWNER
        )


@pytest.mark.parametrize("status", [MembershipStatus.SUSPENDED, MembershipStatus.REMOVED])
def test_database_rejects_an_inactive_owner(shop, status):
    with pytest.raises(IntegrityError), transaction.atomic():
        WorkspaceMembership.objects.filter(pk=shop.owner.pk).update(status=status)


def test_database_rejects_duplicate_membership(shop):
    with pytest.raises(IntegrityError), transaction.atomic():
        WorkspaceMembership.objects.create(
            workspace=shop.workspace, user=shop.affiliate.user, role=MembershipRole.ATTENDANT
        )


def test_database_rejects_unknown_role_and_status(shop):
    with pytest.raises(IntegrityError), transaction.atomic():
        WorkspaceMembership.objects.filter(pk=shop.affiliate.pk).update(role="admin")
    with pytest.raises(IntegrityError), transaction.atomic():
        WorkspaceMembership.objects.filter(pk=shop.affiliate.pk).update(status="banned")


# --- Services ----------------------------------------------------------------


def test_add_member(shop, make_user):
    user = make_user()
    membership = services.add_member(actor=shop.owner, user=user, role=MembershipRole.AFFILIATE)
    assert membership.workspace == shop.workspace
    assert membership.status == MembershipStatus.ACTIVE
    event = AuditEvent.objects.get(action="membership.added", target_id=membership.id)
    assert event.actor == shop.owner.user and event.workspace == shop.workspace

    with pytest.raises(ConflictError):
        services.add_member(actor=shop.owner, user=user, role=MembershipRole.ATTENDANT)


def test_add_member_cannot_create_a_second_owner(shop, make_user):
    with pytest.raises(DomainError) as excinfo:
        services.add_member(actor=shop.owner, user=make_user(), role=MembershipRole.OWNER)
    assert excinfo.value.code == "owner_role_reserved"


@pytest.mark.parametrize("role", ["manager", "attendant", "affiliate"])
def test_services_recheck_the_actors_authority(shop, make_user, role):
    actor = shop.by_role[role]
    with pytest.raises(NotPermittedError):
        services.add_member(actor=actor, user=make_user(), role=MembershipRole.AFFILIATE)
    with pytest.raises(NotPermittedError):
        services.change_member_role(
            actor=actor, membership_id=shop.attendant.id, role=MembershipRole.MANAGER
        )
    with pytest.raises(NotPermittedError):
        services.set_member_status(
            actor=actor, membership_id=shop.attendant.id, status=MembershipStatus.SUSPENDED
        )


def test_services_do_not_reach_into_other_workspaces(shop, other_shop):
    with pytest.raises(DomainError) as excinfo:
        services.set_member_status(
            actor=shop.owner,
            membership_id=other_shop.affiliate.id,
            status=MembershipStatus.REMOVED,
        )
    assert excinfo.value.code == "member_not_found"


def test_owner_membership_cannot_be_demoted_suspended_or_removed(shop):
    with pytest.raises(DomainError):
        services.change_member_role(
            actor=shop.owner, membership_id=shop.owner.id, role=MembershipRole.MANAGER
        )
    with pytest.raises(DomainError):
        services.set_member_status(
            actor=shop.owner, membership_id=shop.owner.id, status=MembershipStatus.REMOVED
        )
    with pytest.raises(DomainError):
        services.change_member_role(
            actor=shop.owner, membership_id=shop.manager.id, role=MembershipRole.OWNER
        )
    shop.owner.refresh_from_db()
    assert (shop.owner.role, shop.owner.status) == ("owner", "active")


def test_transfer_ownership_swaps_roles_atomically(shop):
    services.transfer_ownership(actor=shop.owner, new_owner_id=shop.manager.id)
    shop.owner.refresh_from_db()
    shop.manager.refresh_from_db()
    assert shop.manager.role == MembershipRole.OWNER
    assert shop.owner.role == MembershipRole.MANAGER
    owners = WorkspaceMembership.objects.filter(workspace=shop.workspace, role="owner")
    assert owners.count() == 1
    assert AuditEvent.objects.filter(action="workspace.ownership_transferred").count() == 1


def test_transfer_ownership_guards(shop, other_shop):
    with pytest.raises(NotPermittedError):  # not the owner
        services.transfer_ownership(actor=shop.manager, new_owner_id=shop.attendant.id)
    with pytest.raises(DomainError):  # other tenant's member
        services.transfer_ownership(actor=shop.owner, new_owner_id=other_shop.affiliate.id)
    with pytest.raises(ConflictError):  # to self
        services.transfer_ownership(actor=shop.owner, new_owner_id=shop.owner.id)
    WorkspaceMembership.objects.filter(pk=shop.attendant.pk).update(status="suspended")
    with pytest.raises(DomainError):  # inactive successor
        services.transfer_ownership(actor=shop.owner, new_owner_id=shop.attendant.id)
    shop.owner.refresh_from_db()
    assert shop.owner.role == MembershipRole.OWNER


# --- Member API ---------------------------------------------------------------


def member_url(shop, membership) -> str:
    return f"/api/v1/workspaces/{shop.workspace.id}/members/{membership.id}/"


def test_owner_changes_role_and_status_through_the_api(shop, client_for):
    client = client_for(shop.owner.user)
    response = client.patch(
        member_url(shop, shop.attendant), {"role": "manager", "status": "suspended"}
    )
    assert response.status_code == 200
    assert (response.json()["role"], response.json()["status"]) == ("manager", "suspended")
    actions = set(
        AuditEvent.objects.filter(target_id=shop.attendant.id).values_list("action", flat=True)
    )
    assert actions == {"membership.role_changed", "membership.status_changed"}


def test_api_refuses_to_touch_the_owner_membership(shop, client_for):
    response = client_for(shop.owner.user).patch(
        member_url(shop, shop.owner), {"status": "removed"}
    )
    assert response.status_code == 400
    assert response.json()["code"] == "owner_status_locked"


def test_api_change_is_all_or_nothing(shop, client_for):
    """A valid role plus a refused status change must not half-apply."""
    response = client_for(shop.owner.user).patch(
        member_url(shop, shop.manager), {"role": "owner", "status": "suspended"}
    )
    assert response.status_code == 400
    shop.manager.refresh_from_db()
    assert (shop.manager.role, shop.manager.status) == ("manager", "active")


def test_api_validates_member_update(shop, client_for):
    client = client_for(shop.owner.user)
    assert client.patch(member_url(shop, shop.attendant), {}).status_code == 400
    assert client.patch(member_url(shop, shop.attendant), {"role": "admin"}).status_code == 400


def test_audit_events_are_immutable(shop):
    event = AuditEvent.objects.first()
    event.action = "tampered"
    with pytest.raises(TypeError):
        event.save()
    with pytest.raises(TypeError):
        event.delete()
