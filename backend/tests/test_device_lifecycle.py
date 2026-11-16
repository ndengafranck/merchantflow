"""F-04 (rank rule for devices) and F-05 (device lifecycle on membership changes)."""

import threading

import pytest
from django.db import connection, transaction
from django.db.migrations.executor import MigrationExecutor
from rest_framework.test import APIClient

from apps.accounts import installations
from apps.audit.models import AuditEvent
from apps.common.exceptions import NotFoundError, NotPermittedError
from apps.workspaces import device_services, services
from apps.workspaces.models import WorkspaceDevice, WorkspaceMembership

from .conftest import sign_in


def ws(shop, suffix=""):
    return f"/api/v1/workspaces/{shop.workspace.id}/{suffix}"


def enter(shop, membership):
    """A signed-in browser of this member that has entered the workspace."""
    client = APIClient()
    sign_in(client, membership.user)
    assert client.get(ws(shop)).status_code == 200
    client.device = WorkspaceDevice.objects.get(
        workspace=shop.workspace, installation=client.installation
    )
    return client


def revoke(actor_client, shop, device):
    return actor_client.post(ws(shop, f"devices/{device.id}/revoke/"))


def reauthorize(actor_client, shop, device):
    return actor_client.post(ws(shop, f"devices/{device.id}/reauthorize/"))


# --- F-04: rank rule -------------------------------------------------------------------------


def test_manager_cannot_revoke_the_owners_device(shop):
    """Assessment probe S4: a manager locked the owner's browser out."""
    owner = enter(shop, shop.owner)
    manager = enter(shop, shop.manager)
    response = revoke(manager, shop, owner.device)
    assert response.status_code == 404
    owner.device.refresh_from_db()
    assert owner.device.status == "active"
    assert owner.get(ws(shop)).status_code == 200


def test_manager_cannot_revoke_another_managers_device(shop, make_member):
    other_manager = enter(shop, make_member(shop.workspace, "manager"))
    assert revoke(enter(shop, shop.manager), shop, other_manager.device).status_code == 404
    other_manager.device.refresh_from_db()
    assert other_manager.device.status == "active"


@pytest.mark.parametrize("role", ["attendant", "affiliate"])
def test_manager_can_revoke_devices_of_lower_roles(shop, role):
    member = enter(shop, shop.by_role[role])
    assert revoke(enter(shop, shop.manager), shop, member.device).status_code == 200
    assert member.get(ws(shop)).status_code == 403


def test_owner_can_revoke_a_managers_device(shop):
    manager = enter(shop, shop.manager)
    assert revoke(enter(shop, shop.owner), shop, manager.device).status_code == 200


def test_attendant_cannot_revoke_an_affiliates_device(shop):
    affiliate = enter(shop, shop.affiliate)
    assert revoke(enter(shop, shop.attendant), shop, affiliate.device).status_code == 404


@pytest.mark.parametrize("role", ["owner", "manager", "attendant", "affiliate"])
def test_everyone_can_revoke_their_own_device(shop, role):
    member = enter(shop, shop.by_role[role])
    assert revoke(member, shop, member.device).status_code == 200


def test_manager_cannot_reauthorize_the_owners_device(shop):
    owner = enter(shop, shop.owner)
    device_services.revoke_workspace_device(actor=shop.owner, device_id=owner.device.id)
    assert reauthorize(enter(shop, shop.manager), shop, owner.device).status_code == 404
    owner.device.refresh_from_db()
    assert owner.device.status == "revoked"


@pytest.mark.parametrize("role", ["attendant", "affiliate"])
def test_lower_roles_cannot_reauthorize_anything(shop, role):
    target = enter(shop, shop.by_role["affiliate" if role == "attendant" else "attendant"])
    device_services.revoke_workspace_device(actor=shop.owner, device_id=target.device.id)
    response = reauthorize(enter(shop, shop.by_role[role]), shop, target.device)
    assert response.status_code == 403


def test_owner_may_reauthorize_their_own_device_through_the_service(shop):
    owner = enter(shop, shop.owner)
    device_services.revoke_workspace_device(actor=shop.owner, device_id=owner.device.id)
    device_services.reauthorize_workspace_device(actor=shop.owner, device_id=owner.device.id)
    assert owner.get(ws(shop)).status_code == 200


# --- F-05: removal, suspension and reinstatement ------------------------------------------------


def test_removal_revokes_the_members_devices_in_that_workspace_only(shop, other_shop):
    """Assessment probe S5: the device stayed active after removal."""
    user = shop.affiliate.user
    there = WorkspaceMembership.objects.create(
        workspace=other_shop.workspace, user=user, role="affiliate"
    )
    phone, laptop = enter(shop, shop.affiliate), enter(shop, shop.affiliate)
    assert phone.get(f"/api/v1/workspaces/{other_shop.workspace.id}/").status_code == 200
    colleague = enter(shop, shop.attendant)

    services.set_member_status(actor=shop.owner, membership_id=shop.affiliate.id, status="removed")

    for client in (phone, laptop):
        client.device.refresh_from_db()
        assert (client.device.status, client.device.revocation_reason) == (
            "revoked",
            "membership_removed",
        )
    elsewhere = WorkspaceDevice.objects.get(workspace=other_shop.workspace)
    assert elsewhere.status == "active" and there.status == "active"
    colleague.device.refresh_from_db()
    assert colleague.device.status == "active"
    events = AuditEvent.objects.filter(action="device.revoked", workspace=shop.workspace)
    assert events.count() == 2
    assert {e.metadata["reason"] for e in events} == {"membership_removed"}
    assert {e.actor for e in events} == {shop.owner.user}


def test_removal_through_the_api_revokes_devices(shop):
    member = enter(shop, shop.affiliate)
    owner = enter(shop, shop.owner)
    response = owner.patch(ws(shop, f"members/{shop.affiliate.id}/"), {"status": "removed"})
    assert response.status_code == 200
    member.device.refresh_from_db()
    assert member.device.status == "revoked"


def test_reinstatement_does_not_restore_device_access(shop):
    member = enter(shop, shop.affiliate)
    services.set_member_status(actor=shop.owner, membership_id=shop.affiliate.id, status="removed")
    services.set_member_status(actor=shop.owner, membership_id=shop.affiliate.id, status="active")

    response = member.get(ws(shop))
    assert response.status_code == 403
    assert response.json()["code"] == "device_not_authorized"
    member.device.refresh_from_db()
    assert member.device.status == "revoked"
    assert WorkspaceDevice.objects.filter(installation=member.installation).count() == 1


def test_access_returns_only_after_explicit_reauthorization(shop):
    member = enter(shop, shop.affiliate)
    owner = enter(shop, shop.owner)
    services.set_member_status(actor=shop.owner, membership_id=shop.affiliate.id, status="removed")

    refused = reauthorize(owner, shop, member.device)
    assert refused.status_code == 403 and refused.json()["code"] == "member_not_active"

    services.set_member_status(actor=shop.owner, membership_id=shop.affiliate.id, status="active")
    response = reauthorize(owner, shop, member.device)
    assert response.status_code == 200
    assert response.json()["status"] == "active"
    assert response.json()["revocation_reason"] is None
    assert member.get(ws(shop)).status_code == 200
    event = AuditEvent.objects.get(action="device.reauthorized")
    assert event.metadata == {"previous_reason": "membership_removed"}
    assert event.actor == shop.owner.user
    # Idempotent.
    assert reauthorize(owner, shop, member.device).status_code == 200
    assert AuditEvent.objects.filter(action="device.reauthorized").count() == 1


def test_a_browser_signed_out_everywhere_cannot_be_reauthorized(shop):
    member = enter(shop, shop.affiliate)
    device_services.revoke_workspace_device(actor=shop.owner, device_id=member.device.id)
    installations.revoke_installation(
        user=shop.affiliate.user, installation_id=member.installation.id
    )
    with pytest.raises(NotPermittedError) as excinfo:
        device_services.reauthorize_workspace_device(actor=shop.owner, device_id=member.device.id)
    assert excinfo.value.code == "installation_revoked"


def test_suspension_blocks_access_but_keeps_devices(shop):
    """Default agreed in the assessment (Q9): devices are revoked on removal only."""
    member = enter(shop, shop.affiliate)
    services.set_member_status(
        actor=shop.owner, membership_id=shop.affiliate.id, status="suspended"
    )
    assert member.get(ws(shop)).status_code == 404
    member.device.refresh_from_db()
    assert member.device.status == "active"
    services.set_member_status(actor=shop.owner, membership_id=shop.affiliate.id, status="active")
    assert member.get(ws(shop)).status_code == 200


# --- Race: first entry against removal ------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_first_entry_cannot_slip_in_while_the_member_is_being_removed(shop):
    installation = sign_in(APIClient(), shop.affiliate.user)
    membership = WorkspaceMembership.objects.select_related("workspace", "user").get(
        pk=shop.affiliate.pk
    )
    outcome = {}

    def first_entry():
        try:
            device_services.ensure_workspace_device(
                installation=installation, membership=membership
            )
            outcome["result"] = "authorized"
        except NotFoundError:
            outcome["result"] = "refused"
        finally:
            connection.close()

    worker = threading.Thread(target=first_entry)
    with transaction.atomic():
        services.set_member_status(
            actor=shop.owner, membership_id=shop.affiliate.id, status="removed"
        )
        worker.start()
        worker.join(timeout=1.0)
        assert worker.is_alive(), "first entry should wait for the removal to finish"
    worker.join(timeout=10)

    assert outcome == {"result": "refused"}
    assert not WorkspaceDevice.objects.filter(installation=installation).exists()


# --- Migration --------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_existing_revocations_are_backfilled_as_manual():
    before = [("workspaces", "0003_migrate_legacy_devices")]
    after = [("workspaces", "0004_device_revocation_reason")]
    executor = MigrationExecutor(connection)
    try:
        executor.migrate(before)
        old = executor.loader.project_state(before).apps
        user = old.get_model("accounts", "User").objects.create(
            email="mig@example.test", full_name="Mig", password="!"
        )
        workspace = old.get_model("workspaces", "Workspace").objects.create(
            name="Mig Shop", slug="mig-shop"
        )
        installation = old.get_model("accounts", "DeviceInstallation").objects.create(
            user=user, label="x"
        )
        from django.utils import timezone

        old.get_model("workspaces", "WorkspaceDevice").objects.create(
            workspace=workspace,
            installation=installation,
            status="revoked",
            revoked_at=timezone.now(),
            revoked_by=user,
        )
        executor = MigrationExecutor(connection)
        executor.migrate(after)
        new = executor.loader.project_state(after).apps
        device = new.get_model("workspaces", "WorkspaceDevice").objects.get()
        assert device.revocation_reason == "manual"
        executor = MigrationExecutor(connection)
        executor.migrate(before)  # reversible
    finally:
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
