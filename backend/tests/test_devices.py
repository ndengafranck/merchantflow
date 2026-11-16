import uuid

import pytest
from django.db import IntegrityError, transaction

from apps.audit.models import AuditEvent
from apps.devices import services
from apps.devices.models import Device, DeviceStatus
from apps.workspaces.models import MembershipStatus, WorkspaceMembership


def devices_url(shop) -> str:
    return f"/api/v1/workspaces/{shop.workspace.id}/devices/"


def handshake(client, shop, device_id=None):
    headers = {"HTTP_X_DEVICE_ID": str(device_id)} if device_id else {}
    return client.post(f"/api/v1/workspaces/{shop.workspace.id}/sync/handshake/", **headers)


@pytest.fixture
def affiliate_device(shop) -> Device:
    return services.register_device(membership=shop.affiliate, name="Tecno Spark")


# --- Registration and listing ---------------------------------------------------


def test_member_registers_a_device(shop, client_for):
    response = client_for(shop.affiliate.user).post(
        devices_url(shop), {"name": " Tecno Spark ", "platform": "Android Chrome"}
    )
    assert response.status_code == 201
    body = response.json()
    assert (body["name"], body["status"]) == ("Tecno Spark", "active")
    device = Device.objects.get(pk=body["id"])
    assert (device.user, device.workspace) == (shop.affiliate.user, shop.workspace)
    assert AuditEvent.objects.filter(action="device.registered", target_id=device.id).exists()


def test_device_registration_validates_input(shop, client_for):
    response = client_for(shop.affiliate.user).post(devices_url(shop), {"name": ""})
    assert response.status_code == 400
    assert "name" in response.json()["errors"]


def test_members_see_their_own_devices_and_managers_see_all(shop, client_for, affiliate_device):
    services.register_device(membership=shop.attendant, name="Counter PC")

    own = client_for(shop.affiliate.user).get(devices_url(shop)).json()
    assert [d["id"] for d in own] == [str(affiliate_device.id)]

    for role in ("owner", "manager"):
        everyone = client_for(shop.by_role[role].user).get(devices_url(shop)).json()
        assert len(everyone) == 2


# --- Revocation -------------------------------------------------------------------


def revoke_url(shop, device_id) -> str:
    return f"{devices_url(shop)}{device_id}/revoke/"


def test_member_revokes_own_device(shop, client_for, affiliate_device):
    response = client_for(shop.affiliate.user).post(revoke_url(shop, affiliate_device.id))
    assert response.status_code == 200
    affiliate_device.refresh_from_db()
    assert affiliate_device.status == DeviceStatus.REVOKED
    assert affiliate_device.revoked_by == shop.affiliate.user
    assert affiliate_device.revoked_at is not None


def test_member_cannot_revoke_someone_elses_device(shop, client_for, affiliate_device):
    response = client_for(shop.attendant.user).post(revoke_url(shop, affiliate_device.id))
    assert response.status_code == 403
    affiliate_device.refresh_from_db()
    assert affiliate_device.status == DeviceStatus.ACTIVE


@pytest.mark.parametrize("role", ["owner", "manager"])
def test_device_managers_can_revoke_any_device(shop, client_for, affiliate_device, role):
    response = client_for(shop.by_role[role].user).post(revoke_url(shop, affiliate_device.id))
    assert response.status_code == 200
    assert response.json()["status"] == "revoked"


def test_revocation_is_idempotent_and_audited_once(shop, client_for, affiliate_device):
    client = client_for(shop.owner.user)
    first = client.post(revoke_url(shop, affiliate_device.id)).json()
    second = client.post(revoke_url(shop, affiliate_device.id))
    assert second.status_code == 200
    assert second.json()["revoked_at"] == first["revoked_at"]
    assert AuditEvent.objects.filter(action="device.revoked").count() == 1


def test_cannot_revoke_a_device_of_another_workspace(shop, other_shop, client_for):
    foreign = services.register_device(membership=other_shop.affiliate, name="Foreign")
    response = client_for(shop.owner.user).post(revoke_url(shop, foreign.id))
    assert response.status_code == 404
    foreign.refresh_from_db()
    assert foreign.status == DeviceStatus.ACTIVE


def test_database_rejects_inconsistent_revocation_state(affiliate_device):
    with pytest.raises(IntegrityError), transaction.atomic():
        Device.objects.filter(pk=affiliate_device.pk).update(status="revoked")


# --- Synchronisation gate -----------------------------------------------------------


def test_active_device_passes_the_sync_handshake(shop, client_for, affiliate_device):
    response = handshake(client_for(shop.affiliate.user), shop, affiliate_device.id)
    assert response.status_code == 200
    assert response.json()["device_id"] == str(affiliate_device.id)
    affiliate_device.refresh_from_db()
    assert affiliate_device.last_seen_at is not None


def test_revoked_device_cannot_synchronise(shop, client_for, affiliate_device):
    client = client_for(shop.affiliate.user)
    assert handshake(client, shop, affiliate_device.id).status_code == 200

    services.revoke_device(actor=shop.owner, device_id=affiliate_device.id)

    response = handshake(client, shop, affiliate_device.id)
    assert response.status_code == 403
    assert response.json()["code"] == "device_revoked"


def test_sync_requires_a_device(shop, client_for):
    response = handshake(client_for(shop.affiliate.user), shop)
    assert response.status_code == 403
    assert response.json()["code"] == "device_required"


@pytest.mark.parametrize("bogus", ["not-a-uuid", str(uuid.uuid4())])
def test_sync_rejects_unknown_device(shop, client_for, bogus):
    response = handshake(client_for(shop.affiliate.user), shop, bogus)
    assert response.status_code == 403
    assert response.json()["code"] == "device_unknown"


def test_sync_rejects_another_users_device(shop, client_for, affiliate_device):
    """Even the owner cannot synchronise as somebody else's device."""
    response = handshake(client_for(shop.owner.user), shop, affiliate_device.id)
    assert response.status_code == 403
    assert response.json()["code"] == "device_unknown"


def test_sync_rejects_a_device_registered_for_another_workspace(
    shop, other_shop, client_for, make_user
):
    user = make_user()
    here = WorkspaceMembership.objects.create(workspace=shop.workspace, user=user, role="affiliate")
    there = WorkspaceMembership.objects.create(
        workspace=other_shop.workspace, user=user, role="affiliate"
    )
    device_there = services.register_device(membership=there, name="Phone")
    assert here.status == MembershipStatus.ACTIVE
    response = handshake(client_for(user), shop, device_there.id)
    assert response.status_code == 403
    assert response.json()["code"] == "device_unknown"


def test_sync_requires_authentication_and_active_membership(shop, client_for, affiliate_device):
    assert handshake(client_for(), shop, affiliate_device.id).status_code == 401
    WorkspaceMembership.objects.filter(pk=shop.affiliate.pk).update(status="suspended")
    response = handshake(client_for(shop.affiliate.user), shop, affiliate_device.id)
    assert response.status_code == 404
