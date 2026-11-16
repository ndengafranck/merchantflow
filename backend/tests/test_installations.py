"""Browser installations and device-bound sessions (R5, decisions 1, 2, 5, 7, 8)."""

import pytest
from django.conf import settings
from django.db import IntegrityError, transaction
from rest_framework.test import APIClient

from apps.accounts import installations
from apps.accounts.models import DeviceInstallation, UserSession
from apps.accounts.session_store import INSTALLATION_SESSION_KEY
from apps.audit.models import AuditEvent
from apps.common.exceptions import NotFoundError
from apps.workspaces.models import WorkspaceDevice

from .conftest import PASSWORD, sign_in

LOGIN = "/api/v1/auth/login/"
ME = "/api/v1/auth/me/"
INSTALLATIONS = "/api/v1/auth/installations/"
ANDROID_CHROME = (
    "Mozilla/5.0 (Linux; Android 13; TECNO KI5k) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Mobile Safari/537.36"
)


def login(client, user, **extra):
    response = client.post(LOGIN, {"email": user.email, "password": PASSWORD}, **extra)
    assert response.status_code == 200
    return response


# --- Recognising the installation at login ---------------------------------------------


def test_first_login_registers_the_browser_and_binds_the_session(make_user):
    user = make_user()
    browser = APIClient()
    response = login(browser, user, HTTP_USER_AGENT=ANDROID_CHROME)

    installation = DeviceInstallation.objects.get(user=user)
    assert installation.label == "Chrome on Android"
    assert installation.last_login_at is not None

    cookie = response.cookies[settings.DEVICE_COOKIE_NAME]
    assert cookie.value == str(installation.id)
    assert cookie["httponly"] and cookie["samesite"] == "Lax"
    assert int(cookie["max-age"]) == settings.DEVICE_COOKIE_AGE

    session = UserSession.objects.get()
    assert (session.user, session.installation) == (user, installation)
    assert AuditEvent.objects.filter(
        action="installation.registered", target_id=installation.id, actor=user
    ).exists()


def test_same_browser_is_recognised_at_the_next_login(make_user):
    user = make_user()
    browser = APIClient()
    login(browser, user)
    browser.post("/api/v1/auth/logout/")
    assert settings.DEVICE_COOKIE_NAME in browser.cookies  # identity survives sign-out
    login(browser, user)
    assert DeviceInstallation.objects.filter(user=user).count() == 1


def test_a_different_browser_is_a_different_installation(make_user):
    user = make_user()
    login(APIClient(), user)
    login(APIClient(), user)
    assert DeviceInstallation.objects.filter(user=user).count() == 2
    assert UserSession.objects.values("installation").distinct().count() == 2


@pytest.mark.parametrize("presented", ["someone-elses", "garbage", "revoked"])
def test_identifier_cookie_is_not_a_credential(make_user, presented):
    """Decision 8: presenting an identifier never confers anything."""
    victim, user = make_user(), make_user()
    victims = DeviceInstallation.objects.create(user=victim, label="Victim's phone")
    browser = APIClient()
    if presented == "someone-elses":
        browser.cookies[settings.DEVICE_COOKIE_NAME] = str(victims.id)
    elif presented == "garbage":
        browser.cookies[settings.DEVICE_COOKIE_NAME] = "'; DROP TABLE--"
    else:
        old = DeviceInstallation.objects.create(user=user, label="Old")
        installations.revoke_installation(user=user, installation_id=old.id)
        browser.cookies[settings.DEVICE_COOKIE_NAME] = str(old.id)

    # The identifier alone does not authenticate ...
    assert browser.get(ME).status_code == 401
    # ... and at login it is ignored: the user gets a brand-new installation.
    login(browser, user)
    bound = UserSession.objects.get().installation
    assert bound.user == user and bound.status == "active"
    assert bound.id != victims.id
    assert str(bound.id) == browser.cookies[settings.DEVICE_COOKIE_NAME].value
    assert victims.sessions.count() == 0


def test_two_users_on_one_browser_get_separate_installations(make_user):
    first, second = make_user(), make_user()
    browser = APIClient()
    login(browser, first)
    browser.post("/api/v1/auth/logout/")
    login(browser, second)
    assert (
        DeviceInstallation.objects.get(user=first).id
        != DeviceInstallation.objects.get(user=second).id
    )


# --- A session must be bound to an active installation -----------------------------------


def test_session_without_an_installation_is_not_accepted_by_the_api(make_user):
    """For example a session created by the Django admin login form."""
    client = APIClient()
    client.force_login(make_user())
    response = client.get(ME)
    assert response.status_code == 401
    assert response.json()["code"] == "device_session_invalid"


def test_session_bound_to_another_users_installation_is_not_accepted(make_user):
    user, other = make_user(), make_user()
    client = APIClient()
    sign_in(client, user, installation=DeviceInstallation.objects.create(user=other, label="x"))
    assert client.get(ME).status_code == 401


# --- Revoking an installation --------------------------------------------------------------


def test_revoking_an_installation_ends_its_sessions_and_only_those(make_user):
    """Decision 5."""
    user = make_user()
    phone, laptop = APIClient(), APIClient()
    login(phone, user)
    login(laptop, user)
    phone_installation = DeviceInstallation.objects.get(
        pk=phone.cookies[settings.DEVICE_COOKIE_NAME].value
    )

    response = laptop.post(f"{INSTALLATIONS}{phone_installation.id}/revoke/")
    assert response.status_code == 200 and response.json()["status"] == "revoked"

    assert phone.get(ME).status_code == 401
    assert laptop.get(ME).status_code == 200
    assert not UserSession.objects.filter(installation=phone_installation).exists()
    phone_installation.refresh_from_db()
    assert phone_installation.revoked_by == user and phone_installation.revoked_at
    assert AuditEvent.objects.filter(action="installation.revoked").count() == 1


def test_session_that_outlives_its_revoked_installation_is_useless(shop):
    """Decision 7, defence in depth: even if a session row survived revocation
    (here forced by bypassing the service), it cannot do anything."""
    user = shop.affiliate.user
    client = APIClient()
    login(client, user)
    assert client.get(f"/api/v1/workspaces/{shop.workspace.id}/").status_code == 200
    installation = DeviceInstallation.objects.get(user=user)
    DeviceInstallation.objects.filter(pk=installation.pk).update(
        status="revoked", revoked_at=installation.created_at, revoked_by=user
    )
    assert UserSession.objects.filter(installation=installation).exists()

    for method, url in [
        ("get", ME),
        ("get", "/api/v1/workspaces/"),
        ("get", f"/api/v1/workspaces/{shop.workspace.id}/"),
        ("post", f"/api/v1/workspaces/{shop.workspace.id}/sync/handshake/"),
        ("get", INSTALLATIONS),
    ]:
        assert getattr(client, method)(url).status_code == 401, url

    assert DeviceInstallation.objects.filter(user=user).count() == 1
    assert WorkspaceDevice.objects.filter(installation__user=user).count() == 1


def test_revoking_the_browser_in_use_signs_it_out(make_user):
    user = make_user()
    client = APIClient()
    login(client, user)
    current = DeviceInstallation.objects.get(user=user)
    assert client.post(f"{INSTALLATIONS}{current.id}/revoke/").status_code == 200
    assert client.get(ME).status_code == 401
    assert not UserSession.objects.exists()


def test_revocation_is_idempotent(make_user):
    user = make_user()
    installation = DeviceInstallation.objects.create(user=user, label="x")
    first = installations.revoke_installation(user=user, installation_id=installation.id)
    second = installations.revoke_installation(user=user, installation_id=installation.id)
    assert first.revoked_at == second.revoked_at
    assert AuditEvent.objects.filter(action="installation.revoked").count() == 1


def test_user_cannot_see_or_revoke_another_users_installation(make_user, client_for):
    victim = make_user()
    victims = DeviceInstallation.objects.create(user=victim, label="Victim's phone")
    attacker = client_for(make_user())

    assert attacker.post(f"{INSTALLATIONS}{victims.id}/revoke/").status_code == 404
    listed = attacker.get(INSTALLATIONS).json()
    assert [(i["id"], i["is_current"]) for i in listed] == [(str(attacker.installation.id), True)]
    victims.refresh_from_db()
    assert victims.status == "active"
    with pytest.raises(NotFoundError):
        installations.revoke_installation(
            user=attacker.installation.user, installation_id=victims.id
        )


def test_workspace_owner_cannot_revoke_a_members_installation(shop, client_for):
    """An installation spans all of a user's workspaces, so it is the user's own."""
    member = client_for(shop.affiliate.user)
    owner = client_for(shop.owner.user)
    assert owner.post(f"{INSTALLATIONS}{member.installation.id}/revoke/").status_code == 404
    assert member.get(ME).status_code == 200


def test_new_login_with_the_password_after_revocation_starts_a_new_installation(make_user):
    """Stated limit of the model: revocation defeats a stolen session, not a
    person who knows the password. See OPEN_DECISIONS O-020."""
    user = make_user()
    browser = APIClient()
    login(browser, user)
    old = DeviceInstallation.objects.get(user=user)
    installations.revoke_installation(user=user, installation_id=old.id)
    assert browser.get(ME).status_code == 401

    login(browser, user)
    assert browser.get(ME).status_code == 200
    assert DeviceInstallation.objects.filter(user=user, status="active").exclude(pk=old.pk).exists()


# --- Session lifecycle with the custom store -------------------------------------------------


def test_logout_deletes_the_session_row_and_password_change_ends_sessions(make_user):
    user = make_user()
    first, second = APIClient(), APIClient()
    login(first, user)
    login(second, user)
    assert UserSession.objects.filter(user=user).count() == 2

    first.post("/api/v1/auth/logout/")
    assert UserSession.objects.filter(user=user).count() == 1

    user.set_password("another-long-passphrase")
    user.save()
    assert second.get(ME).status_code == 401


def test_planted_session_id_is_replaced_at_login(make_user):
    from apps.accounts.session_store import SessionStore

    planted = SessionStore()
    planted["x"] = 1
    planted.save()
    browser = APIClient()
    browser.cookies[settings.SESSION_COOKIE_NAME] = planted.session_key
    login(browser, make_user())
    assert browser.cookies[settings.SESSION_COOKIE_NAME].value != planted.session_key
    assert not UserSession.objects.filter(session_key=planted.session_key).exists()


def test_session_columns_follow_the_session_payload(make_user):
    user = make_user()
    client = APIClient()
    installation = sign_in(client, user)
    row = UserSession.objects.get()
    assert (row.user_id, row.installation_id) == (user.id, installation.id)
    assert row.get_decoded()[INSTALLATION_SESSION_KEY] == str(installation.id)


def test_database_rejects_inconsistent_installation_state(make_user):
    installation = DeviceInstallation.objects.create(user=make_user(), label="x")
    with pytest.raises(IntegrityError), transaction.atomic():
        DeviceInstallation.objects.filter(pk=installation.pk).update(status="revoked")


@pytest.mark.parametrize(
    ("user_agent", "label"),
    [
        (ANDROID_CHROME, "Chrome on Android"),
        (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 "
            "(KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1",
            "Safari on iPhone",
        ),
        (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/126.0.0.0 Safari/537.36 Edg/126.0.0.0",
            "Edge on Windows",
        ),
        (
            "Mozilla/5.0 (X11; Linux x86_64; rv:127.0) Gecko/20100101 Firefox/127.0",
            "Firefox on Linux",
        ),
        ("", "Unknown browser"),
        ("curl/8.5.0", "Unknown browser"),
    ],
)
def test_describe_user_agent(user_agent, label):
    assert installations.describe_user_agent(user_agent) == label
