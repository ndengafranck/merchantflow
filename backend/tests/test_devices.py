"""Workspace-specific device authorisation (R5, decisions 3, 4, 6 and 7)."""

import pytest
from django.db import IntegrityError, transaction
from rest_framework.test import APIClient

from apps.audit.models import AuditEvent
from apps.common.exceptions import NotPermittedError
from apps.workspaces.device_services import ensure_workspace_device, revoke_workspace_device
from apps.workspaces.models import WorkspaceDevice, WorkspaceMembership

from .conftest import sign_in


def ws(shop, suffix: str = "") -> str:
    return f"/api/v1/workspaces/{shop.workspace.id}/{suffix}"


def device_of(client, shop) -> WorkspaceDevice:
    return WorkspaceDevice.objects.get(workspace=shop.workspace, installation=client.installation)


# --- Authorisation is created on first entry ---------------------------------------


def test_first_entry_authorises_the_installation_once(shop, client_for):
    client = client_for(shop.affiliate.user)
    assert not WorkspaceDevice.objects.exists()

    for _ in range(3):
        assert client.get(ws(shop)).status_code == 200

    device = device_of(client, shop)
    assert WorkspaceDevice.objects.count() == 1
    assert device.status == "active"
    event = AuditEvent.objects.get(action="device.authorized")
    assert (event.target_id, event.actor, event.workspace) == (
        device.id,
        shop.affiliate.user,
        shop.workspace,
    )


def test_one_installation_serves_several_workspaces(shop, other_shop, client_for):
    """Decision 3: belonging to two workspaces does not make two devices."""
    user = shop.owner.user
    WorkspaceMembership.objects.create(workspace=other_shop.workspace, user=user, role="affiliate")
    client = client_for(user)

    assert client.get(ws(shop)).status_code == 200
    assert client.get(ws(other_shop)).status_code == 200

    assert user.installations.count() == 1
    devices = WorkspaceDevice.objects.filter(installation=client.installation)
    assert {d.workspace_id for d in devices} == {shop.workspace.id, other_shop.workspace.id}


def test_non_members_never_get_a_workspace_device(shop, make_user, client_for):
    assert client_for(make_user()).get(ws(shop)).status_code == 404
    assert not WorkspaceDevice.objects.exists()


def test_installation_of_another_user_cannot_be_authorised(shop, make_user):
    foreign = sign_in(APIClient(), make_user())
    with pytest.raises(NotPermittedError):
        ensure_workspace_device(installation=foreign, membership=shop.affiliate)
    assert not WorkspaceDevice.objects.exists()


# --- Listing --------------------------------------------------------------------------


def test_members_see_their_own_devices_and_managers_see_all(shop, client_for):
    affiliate = client_for(shop.affiliate.user)
    attendant = client_for(shop.attendant.user)
    attendant.get(ws(shop))

    own = affiliate.get(ws(shop, "devices/")).json()
    assert [(d["id"], d["is_current"]) for d in own] == [(str(device_of(affiliate, shop).id), True)]
    assert own[0]["user_id"] == str(shop.affiliate.user.id)

    for role in ("owner", "manager"):
        everyone = client_for(shop.by_role[role].user).get(ws(shop, "devices/")).json()
        others = {d["user_id"] for d in everyone if not d["is_current"]}
        assert {str(shop.affiliate.user.id), str(shop.attendant.user.id)} <= others
        assert sum(d["is_current"] for d in everyone) == 1


# --- Revocation -----------------------------------------------------------------------


def revoke(client, shop, device):
    return client.post(ws(shop, f"devices/{device.id}/revoke/"))


def test_revoked_workspace_device_closes_that_workspace_only(shop, other_shop, client_for):
    """Decision 6, and the lost-phone scenario of review finding H-01."""
    user = shop.affiliate.user
    WorkspaceMembership.objects.create(workspace=other_shop.workspace, user=user, role="affiliate")
    phone = client_for(user)
    assert phone.get(ws(shop)).status_code == 200
    assert phone.get(ws(other_shop)).status_code == 200

    response = revoke(client_for(shop.owner.user), shop, device_of(phone, shop))
    assert response.status_code == 200 and response.json()["status"] == "revoked"

    for method, suffix in [("get", ""), ("get", "devices/"), ("post", "sync/handshake/")]:
        refused = getattr(phone, method)(ws(shop, suffix))
        assert refused.status_code == 403
        assert refused.json()["code"] == "device_not_authorized"

    assert phone.get("/api/v1/auth/me/").status_code == 200  # still signed in
    assert phone.get(ws(other_shop)).status_code == 200  # other workspace untouched


def test_revoked_browser_cannot_obtain_a_replacement_device(shop, client_for):
    """Decision 7: nothing the revoked browser can send creates a new authorisation."""
    phone = client_for(shop.affiliate.user)
    phone.get(ws(shop))
    revoke(client_for(shop.owner.user), shop, device_of(phone, shop))

    for _ in range(3):
        phone.get(ws(shop))
        phone.get(ws(shop, "devices/"))
        phone.post(ws(shop, "sync/handshake/"))
        phone.post(ws(shop, "devices/"), {"name": "Replacement"})
        phone.put("/api/v1/workspaces/current/", {"workspace_id": str(shop.workspace.id)})

    devices = WorkspaceDevice.objects.filter(installation__user=shop.affiliate.user)
    assert [d.status for d in devices] == ["revoked"]
    assert shop.affiliate.user.installations.count() == 1


def test_signing_out_and_in_again_on_the_same_browser_does_not_lift_the_revocation(shop, make_user):
    from .conftest import PASSWORD

    login = {"email": shop.affiliate.user.email, "password": PASSWORD}
    browser = APIClient()
    assert browser.post("/api/v1/auth/login/", login).status_code == 200
    assert browser.get(ws(shop)).status_code == 200
    device = WorkspaceDevice.objects.get(workspace=shop.workspace)
    revoke_workspace_device(actor=shop.owner, device_id=device.id)

    browser.post("/api/v1/auth/logout/")
    assert browser.post("/api/v1/auth/login/", login).status_code == 200

    assert browser.get(ws(shop)).status_code == 403
    assert WorkspaceDevice.objects.count() == 1


def test_users_other_browser_is_not_affected_by_a_revocation(shop, client_for):
    phone = client_for(shop.affiliate.user)
    laptop = client_for(shop.affiliate.user)
    phone.get(ws(shop))
    laptop.get(ws(shop))
    revoke(client_for(shop.owner.user), shop, device_of(phone, shop))
    assert phone.get(ws(shop)).status_code == 403
    assert laptop.get(ws(shop)).status_code == 200


def test_member_revokes_own_device(shop, client_for):
    client = client_for(shop.affiliate.user)
    client.get(ws(shop))
    device = device_of(client, shop)
    assert revoke(client, shop, device).status_code == 200
    device.refresh_from_db()
    assert (device.status, device.revoked_by) == ("revoked", shop.affiliate.user)
    assert device.revoked_at is not None


def test_member_cannot_revoke_or_detect_someone_elses_device(shop, client_for):
    """Review finding A-03: another member's device is reported as not found."""
    victim = client_for(shop.affiliate.user)
    victim.get(ws(shop))
    device = device_of(victim, shop)
    response = revoke(client_for(shop.attendant.user), shop, device)
    assert response.status_code == 404
    device.refresh_from_db()
    assert device.status == "active"


@pytest.mark.parametrize("role", ["owner", "manager"])
def test_device_managers_can_revoke_any_device(shop, client_for, role):
    member = client_for(shop.affiliate.user)
    member.get(ws(shop))
    response = revoke(client_for(shop.by_role[role].user), shop, device_of(member, shop))
    assert response.status_code == 200
    assert response.json()["status"] == "revoked"


def test_revocation_is_idempotent_and_audited_once(shop, client_for):
    member = client_for(shop.affiliate.user)
    member.get(ws(shop))
    owner = client_for(shop.owner.user)
    first = revoke(owner, shop, device_of(member, shop)).json()
    second = revoke(owner, shop, device_of(member, shop))
    assert second.status_code == 200
    assert second.json()["revoked_at"] == first["revoked_at"]
    assert AuditEvent.objects.filter(action="device.revoked").count() == 1


def test_cannot_revoke_a_device_of_another_workspace(shop, other_shop, client_for):
    foreign_client = client_for(other_shop.affiliate.user)
    foreign_client.get(ws(other_shop))
    foreign = device_of(foreign_client, other_shop)
    assert revoke(client_for(shop.owner.user), shop, foreign).status_code == 404
    foreign.refresh_from_db()
    assert foreign.status == "active"


def test_database_rejects_duplicate_and_inconsistent_workspace_devices(shop, client_for):
    client = client_for(shop.affiliate.user)
    client.get(ws(shop))
    device = device_of(client, shop)
    with pytest.raises(IntegrityError), transaction.atomic():
        WorkspaceDevice.objects.create(workspace=shop.workspace, installation=client.installation)
    with pytest.raises(IntegrityError), transaction.atomic():
        WorkspaceDevice.objects.filter(pk=device.pk).update(status="revoked")


# --- Synchronisation gate ---------------------------------------------------------------


def test_sync_handshake_identifies_the_sessions_own_device(shop, client_for):
    client = client_for(shop.affiliate.user)
    response = client.post(ws(shop, "sync/handshake/"))
    assert response.status_code == 200
    device = device_of(client, shop)
    assert response.json()["device_id"] == str(device.id)
    device.refresh_from_db()
    assert device.last_seen_at is not None


def test_client_cannot_choose_which_device_it_is(shop, client_for):
    """Review finding V-01: a device id supplied by the client is ignored."""
    phone = client_for(shop.affiliate.user)
    laptop = client_for(shop.affiliate.user)
    phone.post(ws(shop, "sync/handshake/"))
    phone_device = device_of(phone, shop)

    response = laptop.post(ws(shop, "sync/handshake/"), HTTP_X_DEVICE_ID=str(phone_device.id))

    assert response.json()["device_id"] == str(device_of(laptop, shop).id)
    assert response.json()["device_id"] != str(phone_device.id)


def test_revoked_device_cannot_synchronise(shop, client_for):
    client = client_for(shop.affiliate.user)
    assert client.post(ws(shop, "sync/handshake/")).status_code == 200
    revoke_workspace_device(actor=shop.owner, device_id=device_of(client, shop).id)
    response = client.post(ws(shop, "sync/handshake/"))
    assert response.status_code == 403
    assert response.json()["code"] == "device_not_authorized"


def test_sync_requires_authentication_and_active_membership(shop, client_for):
    assert APIClient().post(ws(shop, "sync/handshake/")).status_code == 401
    client = client_for(shop.affiliate.user)
    WorkspaceMembership.objects.filter(pk=shop.affiliate.pk).update(status="suspended")
    assert client.post(ws(shop, "sync/handshake/")).status_code == 404
