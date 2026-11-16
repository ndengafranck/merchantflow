"""Runs every workspace endpoint through the tenant-isolation contract."""

import pytest
from rest_framework.test import APIClient

from apps.workspaces.device_services import ensure_workspace_device, revoke_workspace_device
from apps.workspaces.models import WorkspaceDevice, WorkspaceMembership

from .conftest import sign_in
from .isolation import WORKSPACE_ENDPOINTS, build_url


@pytest.fixture
def records(shop, other_shop):
    """Sample record ids inside ``shop`` and, for the swap test, inside ``other_shop``."""
    device = ensure_workspace_device(
        installation=sign_in(APIClient(), shop.attendant.user), membership=shop.attendant
    )
    foreign_device = ensure_workspace_device(
        installation=sign_in(APIClient(), other_shop.affiliate.user),
        membership=other_shop.affiliate,
    )
    return {
        "own": {"membership_id": shop.attendant.id, "device_id": device.id},
        "foreign": {"membership_id": other_shop.affiliate.id, "device_id": foreign_device.id},
    }


def call(client, endpoint, url):
    return getattr(client, endpoint.method)(url, endpoint.body)


def snapshot():
    return (
        sorted(WorkspaceMembership.objects.values_list("id", "role", "status")),
        sorted(WorkspaceDevice.objects.values_list("id", "status")),
    )


@pytest.mark.parametrize("endpoint", WORKSPACE_ENDPOINTS, ids=lambda e: f"{e.method} {e.route}")
class TestIsolationContract:
    def test_owner_is_served(self, endpoint, shop, records, client_for):
        url = build_url(endpoint.route, shop.workspace.id, **records["own"])
        assert call(client_for(shop.owner.user), endpoint, url).status_code in endpoint.ok

    def test_outsiders_are_refused_and_nothing_changes(
        self, endpoint, shop, other_shop, records, client_for, make_user
    ):
        url = build_url(endpoint.route, shop.workspace.id, **records["own"])
        WorkspaceMembership.objects.filter(pk=shop.manager.pk).update(status="suspended")
        before = snapshot()

        assert call(APIClient(), endpoint, url).status_code == 401  # anonymous

        no_device = APIClient()
        no_device.force_login(shop.owner.user)  # a session not bound to any installation
        assert call(no_device, endpoint, url).status_code == 401

        assert call(client_for(make_user()), endpoint, url).status_code == 404  # no membership
        # The most privileged role of another tenant is still an outsider here.
        assert call(client_for(other_shop.owner.user), endpoint, url).status_code == 404
        assert call(client_for(shop.manager.user), endpoint, url).status_code == 404  # suspended

        assert snapshot() == before

    def test_own_workspace_id_with_foreign_record_ids_finds_nothing(
        self, endpoint, shop, records, client_for
    ):
        if "<uuid:" not in endpoint.route.replace("<uuid:workspace_id>", ""):
            pytest.skip("endpoint takes no record id")
        url = build_url(endpoint.route, shop.workspace.id, **records["foreign"])
        client = client_for(shop.owner.user)
        # The first entry authorises this browser; do it before the snapshot.
        assert client.get(f"/api/v1/workspaces/{shop.workspace.id}/").status_code == 200
        before = snapshot()
        assert call(client, endpoint, url).status_code == 404
        assert snapshot() == before

    def test_revoked_workspace_device_is_refused(self, endpoint, shop, records, client_for):
        client = client_for(shop.owner.user)
        own_device = ensure_workspace_device(
            installation=client.installation, membership=shop.owner
        )
        revoke_workspace_device(actor=shop.owner, device_id=own_device.id)
        url = build_url(endpoint.route, shop.workspace.id, **records["own"])
        response = call(client, endpoint, url)
        assert response.status_code == 403
        assert response.json()["code"] == "device_not_authorized"
