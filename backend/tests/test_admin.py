"""F-03 (and the admin half of F-11): the Django admin cannot bypass safeguards."""

import importlib

import pytest
from django.conf import settings
from django.contrib import admin
from django.test import Client, override_settings
from django.urls import clear_url_caches

from apps.audit.models import AuditEvent
from apps.workspaces.models import WorkspaceMembership

from .conftest import PASSWORD

PAIR = settings.LOGIN_PROTECTION["ACCOUNT_AND_ADDRESS"]


def load_urls(enabled: bool, path: str = "admin/"):
    with override_settings(ADMIN_ENABLED=enabled, ADMIN_PATH=path):
        import config.urls

        importlib.reload(config.urls)
        clear_url_caches()


@pytest.fixture
def admin_on():
    load_urls(True)
    yield
    load_urls(settings.ADMIN_ENABLED, settings.ADMIN_PATH)


@pytest.fixture
def operator(make_user, admin_on):
    user = make_user(is_staff=True, is_superuser=True)
    client = Client()
    client.force_login(user)
    client.user = user
    return client


def test_admin_uses_the_protected_site():
    from apps.common.admin_site import MerchantFlowAdminSite

    assert isinstance(
        admin.site._wrapped if admin.site._wrapped else admin.site, MerchantFlowAdminSite
    )


# --- Exposure ---------------------------------------------------------------------------


def test_admin_is_not_routed_when_disabled(db):
    load_urls(False)
    try:
        assert Client().get("/admin/login/").status_code == 404
    finally:
        load_urls(settings.ADMIN_ENABLED, settings.ADMIN_PATH)


def test_admin_path_is_configurable(db):
    load_urls(True, "ops-7f3a/")
    try:
        assert Client().get("/admin/login/").status_code == 404
        assert Client().get("/ops-7f3a/login/").status_code == 200
    finally:
        load_urls(settings.ADMIN_ENABLED, settings.ADMIN_PATH)


# --- Sign-in protection (assessment probe S7) -------------------------------------------


def test_admin_login_failures_are_limited_and_shared_with_the_api(make_user, admin_on):
    staff = make_user(is_staff=True, is_superuser=True)
    browser = Client()
    for _ in range(PAIR):
        response = browser.post("/admin/login/", {"username": staff.email, "password": "guess"})
        assert response.status_code == 200  # form shown again
    blocked = browser.post("/admin/login/", {"username": staff.email, "password": PASSWORD})
    assert blocked.status_code == 429
    assert int(blocked["Retry-After"]) > 0
    # The same counter protects the API sign-in for that account from that address.
    api = Client().post(
        "/api/v1/auth/login/",
        {"email": staff.email, "password": PASSWORD},
        content_type="application/json",
    )
    assert api.status_code == 429


def test_successful_admin_login_is_audited_and_not_counted(make_user, admin_on):
    staff = make_user(is_staff=True, is_superuser=True)
    for _ in range(PAIR + 2):
        browser = Client()
        response = browser.post("/admin/login/", {"username": staff.email, "password": PASSWORD})
        assert response.status_code == 302
    events = AuditEvent.objects.filter(action="auth.login_succeeded", target_id=staff.id)
    assert events.count() == PAIR + 2
    assert events.first().metadata["channel"] == "admin"


def test_admin_session_cannot_use_the_api(operator):
    assert operator.get("/api/v1/auth/me/").status_code == 401


# --- Memberships are read-only (assessment probe S6) --------------------------------------


def change_url(membership) -> str:
    return f"/admin/workspaces/workspacemembership/{membership.pk}/change/"


def test_operator_cannot_demote_the_owner_through_the_admin(operator, shop):
    form = {
        "workspace": str(shop.workspace.pk),
        "user": str(shop.owner.user.pk),
        "role": "attendant",
        "status": "active",
    }
    response = operator.post(change_url(shop.owner), form)
    assert response.status_code == 403
    shop.owner.refresh_from_db()
    assert (shop.owner.role, shop.owner.status) == ("owner", "active")


def test_membership_admin_is_view_only(operator, shop):
    assert operator.get(change_url(shop.affiliate)).status_code == 200  # can view
    assert operator.get("/admin/workspaces/workspacemembership/add/").status_code == 403
    response = operator.post(
        change_url(shop.affiliate),
        {
            "workspace": str(shop.workspace.pk),
            "user": str(shop.affiliate.user.pk),
            "role": "manager",
            "status": "removed",
        },
    )
    assert response.status_code == 403
    shop.affiliate.refresh_from_db()
    assert (shop.affiliate.role, shop.affiliate.status) == ("affiliate", "active")
    assert WorkspaceMembership.objects.filter(workspace=shop.workspace).count() == 4


@pytest.mark.parametrize(
    "path",
    [
        "/admin/workspaces/workspacedevice/add/",
        "/admin/accounts/deviceinstallation/add/",
        "/admin/audit/auditevent/add/",
        "/admin/workspaces/workspace/add/",
    ],
)
def test_records_with_lifecycle_rules_cannot_be_created_in_the_admin(operator, path):
    assert operator.get(path).status_code == 403


# --- Audited edits --------------------------------------------------------------------------


def test_workspace_edits_in_the_admin_are_audited(operator, shop):
    response = operator.post(
        f"/admin/workspaces/workspace/{shop.workspace.pk}/change/",
        {"name": "Akwa Phones Ltd", "status": "suspended", "currency": "XAF"},
    )
    assert response.status_code == 302
    event = AuditEvent.objects.get(action="workspace.updated", target_id=shop.workspace.pk)
    assert event.actor == operator.user
    assert event.metadata["changes"] == {"name": "Akwa Phones Ltd", "status": "suspended"}


def user_form(user, **overrides):
    data = {
        "email": user.email,
        "full_name": user.full_name,
        "phone": user.phone,
        "is_active": "on",
        "date_joined_0": "2026-01-01",
        "date_joined_1": "00:00:00",
    }
    data.update(overrides)
    return {k: v for k, v in data.items() if v is not None}


def test_admin_refuses_to_deactivate_a_workspace_owner(operator, shop):
    owner = shop.owner.user
    response = operator.post(
        f"/admin/accounts/user/{owner.pk}/change/", user_form(owner, is_active=None)
    )
    assert response.status_code == 200  # form re-displayed with the error
    assert "Transfer ownership" in response.content.decode()
    owner.refresh_from_db()
    assert owner.is_active


def test_admin_deactivation_of_a_non_owner_is_allowed_and_audited(operator, shop):
    member = shop.affiliate.user
    response = operator.post(
        f"/admin/accounts/user/{member.pk}/change/", user_form(member, is_active=None)
    )
    assert response.status_code == 302
    member.refresh_from_db()
    assert not member.is_active
    event = AuditEvent.objects.get(action="user.updated", target_id=member.pk)
    assert event.metadata["changes"] == {"is_active": "False"}


def test_password_set_in_the_admin_is_audited_without_the_password(operator, shop):
    member = shop.affiliate.user
    response = operator.post(
        f"/admin/accounts/user/{member.pk}/password/",
        {
            "password1": "Another-long-pass-42",
            "password2": "Another-long-pass-42",
            "usable_password": "true",
        },
    )
    assert response.status_code == 302
    event = AuditEvent.objects.get(action="user.password_set", target_id=member.pk)
    assert "Another-long-pass-42" not in str(event.metadata)
