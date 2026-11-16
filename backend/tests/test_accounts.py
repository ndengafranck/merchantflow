import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.accounts.services import register_user

from .conftest import PASSWORD

LOGIN = "/api/v1/auth/login/"
ME = "/api/v1/auth/me/"


# --- Registration -------------------------------------------------------


def test_register_user_normalises_email_and_hashes_password(db):
    user = register_user(email="  Awa@Example.TEST ", full_name="Awa N.", password=PASSWORD)
    assert user.email == "awa@example.test"
    assert user.password != PASSWORD
    assert user.check_password(PASSWORD)
    assert not user.is_staff and not user.is_superuser


@pytest.mark.parametrize("password", ["short", "1234567890123", "password123"])
def test_register_user_rejects_weak_passwords(db, password):
    with pytest.raises(ValidationError):
        register_user(email="weak@example.test", full_name="Weak", password=password)
    assert not User.objects.filter(email="weak@example.test").exists()


def test_register_user_rejects_duplicate_email_case_insensitively(db, make_user):
    make_user("taken@example.test")
    with pytest.raises(ValidationError):
        register_user(email="TAKEN@example.test", full_name="Dup", password=PASSWORD)


def test_database_rejects_mixed_case_duplicate_that_bypasses_the_manager(db, make_user):
    make_user("taken@example.test")
    with pytest.raises(IntegrityError), transaction.atomic():
        User.objects.bulk_create([User(email="Taken@Example.test", full_name="Bypass")])


# --- Login / logout -----------------------------------------------------


def test_login_then_me_then_logout(make_user):
    user = make_user("owner@example.test")
    client = APIClient()

    response = client.post(LOGIN, {"email": "Owner@Example.test", "password": PASSWORD})
    assert response.status_code == 200
    assert response.json()["id"] == str(user.id)
    assert "password" not in response.json()

    assert client.get(ME).json()["email"] == "owner@example.test"

    assert client.post("/api/v1/auth/logout/").status_code == 204
    assert client.get(ME).status_code == 401


def test_me_requires_authentication(db):
    response = APIClient().get(ME)
    assert response.status_code == 401
    assert response.json()["code"] == "not_authenticated"


def test_failed_logins_are_indistinguishable(make_user):
    make_user("real@example.test")
    make_user("disabled@example.test", is_active=False)
    client = APIClient()
    attempts = [
        {"email": "real@example.test", "password": "wrong-password"},
        {"email": "nobody@example.test", "password": PASSWORD},
        {"email": "disabled@example.test", "password": PASSWORD},
    ]
    bodies = []
    for attempt in attempts:
        response = client.post(LOGIN, attempt)
        assert response.status_code == 401
        bodies.append(response.json())
    assert bodies[0] == bodies[1] == bodies[2]
    assert bodies[0]["code"] == "invalid_credentials"
    assert client.get(ME).status_code == 401


def test_login_validates_input(db):
    response = APIClient().post(LOGIN, {"email": "not-an-email"})
    assert response.status_code == 400
    body = response.json()
    assert body["code"] == "validation_error"
    assert set(body["errors"]) == {"email", "password"}


def test_deactivated_user_loses_existing_session(make_user):
    user = make_user()
    client = APIClient()
    client.post(LOGIN, {"email": user.email, "password": PASSWORD})
    assert client.get(ME).status_code == 200
    User.objects.filter(pk=user.pk).update(is_active=False)
    assert client.get(ME).status_code == 401


def test_login_is_rate_limited(make_user, settings):
    from rest_framework.throttling import ScopedRateThrottle

    limit = int(ScopedRateThrottle.THROTTLE_RATES["login"].split("/")[0])
    client = APIClient()
    payload = {"email": "nobody@example.test", "password": "wrong-password"}
    for _ in range(limit):
        assert client.post(LOGIN, payload).status_code == 401
    response = client.post(LOGIN, payload)
    assert response.status_code == 429
    assert response.json()["code"] == "throttled"
