"""Tenant isolation and role enforcement at the HTTP boundary."""

import uuid

import pytest
from django.core.exceptions import ImproperlyConfigured
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.workspaces.access import WorkspaceAPIView
from apps.workspaces.models import (
    MembershipRole,
    MembershipStatus,
    WorkspaceMembership,
    WorkspaceStatus,
)
from apps.workspaces.policies import ROLE_CAPABILITIES, Capability


def url(workspace, suffix: str = "") -> str:
    return f"/api/v1/workspaces/{workspace.id}/{suffix}"


# --- Membership is required ------------------------------------------------


def test_owner_can_access_their_workspace(shop, client_for):
    response = client_for(shop.owner.user).get(url(shop.workspace))
    assert response.status_code == 200
    body = response.json()
    assert body["role"] == "owner"
    assert body["workspace"]["id"] == str(shop.workspace.id)
    assert body["workspace"]["currency"] == "XAF"
    assert set(body["capabilities"]) == {c.value for c in Capability}


def test_anonymous_request_is_401(shop, client_for):
    assert client_for().get(url(shop.workspace)).status_code == 401


def test_user_without_membership_gets_404(shop, make_user, client_for):
    response = client_for(make_user()).get(url(shop.workspace))
    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


def test_nonexistent_workspace_looks_the_same_as_a_forbidden_one(shop, make_user, client_for):
    client = client_for(make_user())
    forbidden = client.get(url(shop.workspace))
    missing = client.get(f"/api/v1/workspaces/{uuid.uuid4()}/")
    assert forbidden.status_code == missing.status_code == 404
    assert forbidden.json() == missing.json()


# --- Changing identifiers in the URL ------------------------------------------


@pytest.mark.parametrize("suffix", ["", "members/", "devices/"])
def test_owner_of_one_workspace_cannot_read_another_by_changing_the_url(
    shop, other_shop, client_for, suffix
):
    client = client_for(shop.owner.user)
    assert client.get(url(shop.workspace, suffix)).status_code == 200
    assert client.get(url(other_shop.workspace, suffix)).status_code == 404


def test_member_list_only_contains_own_workspace(shop, other_shop, client_for):
    response = client_for(shop.owner.user).get(url(shop.workspace, "members/"))
    listed = {m["id"] for m in response.json()}
    assert listed == {str(m.id) for m in shop.by_role.values()}
    assert str(other_shop.affiliate.id) not in listed


def test_cannot_modify_another_workspaces_member_through_own_workspace_url(
    shop, other_shop, client_for
):
    """Own workspace id (authorised) + a foreign record id must not match."""
    response = client_for(shop.owner.user).patch(
        url(shop.workspace, f"members/{other_shop.affiliate.id}/"), {"status": "removed"}
    )
    assert response.status_code == 404
    other_shop.affiliate.refresh_from_db()
    assert other_shop.affiliate.status == MembershipStatus.ACTIVE


def test_cannot_write_to_another_workspace(shop, other_shop, client_for):
    client = client_for(shop.owner.user)
    response = client.patch(
        url(other_shop.workspace, f"members/{other_shop.affiliate.id}/"), {"status": "removed"}
    )
    assert response.status_code == 404
    assert client.post(url(other_shop.workspace, "devices/"), {"name": "x"}).status_code == 404


def test_my_workspaces_lists_only_my_active_memberships(shop, other_shop, make_user, client_for):
    user = make_user()
    WorkspaceMembership.objects.create(
        workspace=shop.workspace, user=user, role=MembershipRole.AFFILIATE
    )
    WorkspaceMembership.objects.create(
        workspace=other_shop.workspace,
        user=user,
        role=MembershipRole.MANAGER,
        status=MembershipStatus.SUSPENDED,
    )
    body = client_for(user).get("/api/v1/workspaces/").json()
    assert [m["workspace"]["id"] for m in body["memberships"]] == [str(shop.workspace.id)]
    assert body["memberships"][0]["role"] == "affiliate"
    assert body["current_workspace_id"] is None


def test_user_with_several_workspaces_has_a_role_in_each(shop, other_shop, client_for):
    WorkspaceMembership.objects.create(
        workspace=other_shop.workspace, user=shop.owner.user, role=MembershipRole.AFFILIATE
    )
    client = client_for(shop.owner.user)
    assert client.get(url(shop.workspace)).json()["role"] == "owner"
    assert client.get(url(other_shop.workspace)).json()["role"] == "affiliate"
    # Owner powers do not travel with the user into the other workspace.
    assert client.get(url(other_shop.workspace, "members/")).status_code == 403


# --- Roles ----------------------------------------------------------------

ROLE_MATRIX = [
    # (role, method, suffix, body, expected status)
    ("owner", "get", "", None, 200),
    ("manager", "get", "", None, 200),
    ("attendant", "get", "", None, 200),
    ("affiliate", "get", "", None, 200),
    ("owner", "get", "members/", None, 200),
    ("manager", "get", "members/", None, 200),
    ("attendant", "get", "members/", None, 403),
    ("affiliate", "get", "members/", None, 403),
    ("owner", "patch", "members/{attendant}/", {"role": "manager"}, 200),
    ("manager", "patch", "members/{attendant}/", {"role": "manager"}, 403),
    ("attendant", "patch", "members/{attendant}/", {"role": "manager"}, 403),
    ("affiliate", "patch", "members/{affiliate}/", {"role": "owner"}, 403),
]


@pytest.mark.parametrize(("role", "method", "suffix", "body", "expected"), ROLE_MATRIX)
def test_role_matrix(shop, client_for, role, method, suffix, body, expected):
    suffix = suffix.format(attendant=shop.attendant.id, affiliate=shop.affiliate.id)
    client = client_for(shop.by_role[role].user)
    response = getattr(client, method)(url(shop.workspace, suffix), body)
    assert response.status_code == expected
    if expected == 403:
        assert response.json()["code"] == "permission_denied"


def test_denied_role_change_leaves_data_untouched(shop, client_for):
    client_for(shop.affiliate.user).patch(
        url(shop.workspace, f"members/{shop.affiliate.id}/"), {"role": "manager"}
    )
    shop.affiliate.refresh_from_db()
    assert shop.affiliate.role == MembershipRole.AFFILIATE


def test_every_role_has_a_policy_and_only_owner_manages_members():
    assert set(ROLE_CAPABILITIES) == set(MembershipRole.values)
    holders = [r for r, caps in ROLE_CAPABILITIES.items() if Capability.MEMBERS_MANAGE in caps]
    assert holders == [MembershipRole.OWNER]


def test_workspace_view_without_declared_capability_fails_closed(shop):
    class Forgotten(WorkspaceAPIView):
        def get(self, request, workspace_id):  # pragma: no cover - must not run
            raise AssertionError("handler reached without a policy")

    request = APIRequestFactory().get("/")
    force_authenticate(request, user=shop.owner.user)
    with pytest.raises(ImproperlyConfigured):
        Forgotten.as_view()(request, workspace_id=shop.workspace.id)


# --- Inactive memberships and workspaces ---------------------------------------


@pytest.mark.parametrize("status", [MembershipStatus.SUSPENDED, MembershipStatus.REMOVED])
def test_inactive_membership_is_rejected_everywhere(shop, client_for, status):
    client = client_for(shop.manager.user)
    assert client.get(url(shop.workspace, "members/")).status_code == 200

    WorkspaceMembership.objects.filter(pk=shop.manager.pk).update(status=status)

    for suffix in ["", "members/", "devices/"]:
        assert client.get(url(shop.workspace, suffix)).status_code == 404
    assert client.post(url(shop.workspace, "devices/"), {"name": "Phone"}).status_code == 404
    assert client.get("/api/v1/workspaces/").json()["memberships"] == []
    response = client.put("/api/v1/workspaces/current/", {"workspace_id": str(shop.workspace.id)})
    assert response.status_code == 404


def test_suspended_workspace_is_closed_to_its_members(shop, client_for):
    shop.workspace.status = WorkspaceStatus.SUSPENDED
    shop.workspace.save()
    client = client_for(shop.owner.user)
    response = client.get(url(shop.workspace))
    assert response.status_code == 403
    assert response.json()["code"] == "workspace_inactive"
    assert client.get("/api/v1/workspaces/").json()["memberships"] == []


# --- Workspace selection ----------------------------------------------------


def test_select_workspace_and_restore_it(shop, client_for):
    client = client_for(shop.affiliate.user)
    response = client.put("/api/v1/workspaces/current/", {"workspace_id": str(shop.workspace.id)})
    assert response.status_code == 200
    assert response.json()["role"] == "affiliate"
    assert client.get("/api/v1/workspaces/").json()["current_workspace_id"] == str(
        shop.workspace.id
    )


def test_cannot_select_a_workspace_without_membership(shop, other_shop, client_for):
    client = client_for(shop.owner.user)
    response = client.put(
        "/api/v1/workspaces/current/", {"workspace_id": str(other_shop.workspace.id)}
    )
    assert response.status_code == 404
    assert client.get("/api/v1/workspaces/").json()["current_workspace_id"] is None


def test_selection_is_dropped_when_membership_ends(shop, client_for):
    client = client_for(shop.affiliate.user)
    client.put("/api/v1/workspaces/current/", {"workspace_id": str(shop.workspace.id)})
    WorkspaceMembership.objects.filter(pk=shop.affiliate.pk).update(status=MembershipStatus.REMOVED)
    assert client.get("/api/v1/workspaces/").json()["current_workspace_id"] is None


def test_select_workspace_validates_input(shop, client_for):
    response = client_for(shop.owner.user).put(
        "/api/v1/workspaces/current/", {"workspace_id": "not-a-uuid"}
    )
    assert response.status_code == 400
    assert "workspace_id" in response.json()["errors"]
