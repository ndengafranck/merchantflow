"""Session-cookie and CSRF behaviour, exercised with CSRF checks ON.

The other test modules use DRF's default test client, which skips CSRF.
These tests prove the protection that a real browser would meet.
"""

import pytest
from django.conf import settings
from rest_framework.test import APIClient

from .conftest import PASSWORD

LOGIN = "/api/v1/auth/login/"
CSRF = "/api/v1/auth/csrf/"
LOGOUT = "/api/v1/auth/logout/"


@pytest.fixture
def browser():
    return APIClient(enforce_csrf_checks=True)


def csrf_token(client: APIClient) -> str:
    """Fetch (or re-read) the CSRF cookie the way the SPA does."""
    client.get(CSRF)
    return client.cookies[settings.CSRF_COOKIE_NAME].value


def test_csrf_endpoint_sets_readable_cookie(browser, db):
    response = browser.get(CSRF)
    assert response.status_code == 204
    cookie = response.cookies[settings.CSRF_COOKIE_NAME]
    assert cookie.value
    assert not cookie["httponly"]  # the SPA must read it
    assert cookie["samesite"] == "Lax"


def test_login_without_csrf_token_is_rejected(browser, make_user):
    user = make_user()
    response = browser.post(LOGIN, {"email": user.email, "password": PASSWORD})
    assert response.status_code == 403
    assert response.json()["code"] == "csrf_failed"
    assert settings.SESSION_COOKIE_NAME not in response.cookies


def test_login_with_wrong_csrf_token_is_rejected(browser, make_user):
    user = make_user()
    csrf_token(browser)
    response = browser.post(
        LOGIN, {"email": user.email, "password": PASSWORD}, HTTP_X_CSRFTOKEN="a" * 64
    )
    assert response.status_code == 403


def test_login_with_csrf_token_sets_httponly_session_cookie(browser, make_user):
    user = make_user()
    token = csrf_token(browser)
    response = browser.post(
        LOGIN, {"email": user.email, "password": PASSWORD}, HTTP_X_CSRFTOKEN=token
    )
    assert response.status_code == 200
    session = response.cookies[settings.SESSION_COOKIE_NAME]
    assert session["httponly"]
    assert session["samesite"] == "Lax"
    # The session identifier never appears in a response body.
    assert session.value not in response.content.decode()


def test_login_rotates_csrf_token(browser, make_user):
    user = make_user()
    before = csrf_token(browser)
    browser.post(LOGIN, {"email": user.email, "password": PASSWORD}, HTTP_X_CSRFTOKEN=before)
    assert browser.cookies[settings.CSRF_COOKIE_NAME].value != before


def _login(browser, user) -> None:
    token = csrf_token(browser)
    response = browser.post(
        LOGIN, {"email": user.email, "password": PASSWORD}, HTTP_X_CSRFTOKEN=token
    )
    assert response.status_code == 200


def test_authenticated_write_without_csrf_token_is_rejected(browser, shop):
    _login(browser, shop.owner.user)
    response = browser.put("/api/v1/workspaces/current/", {"workspace_id": str(shop.workspace.id)})
    assert response.status_code == 403
    assert "CSRF" in response.json()["detail"]

    response = browser.post(LOGOUT)
    assert response.status_code == 403
    assert browser.get("/api/v1/auth/me/").status_code == 200  # still signed in


def test_authenticated_write_with_csrf_token_succeeds(browser, shop):
    _login(browser, shop.owner.user)
    token = browser.cookies[settings.CSRF_COOKIE_NAME].value
    response = browser.put(
        "/api/v1/workspaces/current/",
        {"workspace_id": str(shop.workspace.id)},
        HTTP_X_CSRFTOKEN=token,
    )
    assert response.status_code == 200
    assert browser.post(LOGOUT, HTTP_X_CSRFTOKEN=token).status_code == 204


def test_reads_do_not_need_a_csrf_token(browser, shop):
    _login(browser, shop.owner.user)
    assert browser.get("/api/v1/workspaces/").status_code == 200


def test_cross_origin_write_is_rejected_even_with_token(browser, shop):
    _login(browser, shop.owner.user)
    token = browser.cookies[settings.CSRF_COOKIE_NAME].value
    response = browser.post(LOGOUT, HTTP_X_CSRFTOKEN=token, HTTP_ORIGIN="https://evil.example")
    assert response.status_code == 403
