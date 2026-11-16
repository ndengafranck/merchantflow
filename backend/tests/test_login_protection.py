"""F-01 and F-02: sign-in guessing protection."""

import json
import os
import subprocess
import sys
import threading
from datetime import timedelta
from pathlib import Path
from unittest import mock

import pytest
from django.conf import settings
from django.db import connection
from django.test import RequestFactory, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts import login_protection
from apps.accounts.models import LoginAttemptBucket
from apps.audit.models import AuditEvent
from apps.common.net import address_bucket, client_ip

from .conftest import PASSWORD

LOGIN = "/api/v1/auth/login/"
BACKEND = Path(__file__).resolve().parent.parent
LIMITS = settings.LOGIN_PROTECTION
PAIR, ACCOUNT, ADDRESS = LIMITS["ACCOUNT_AND_ADDRESS"], LIMITS["ACCOUNT"], LIMITS["ADDRESS"]


def attempt(email, password, ip="198.51.100.7", **headers):
    return APIClient(REMOTE_ADDR=ip).post(LOGIN, {"email": email, "password": password}, **headers)


# --- Which address is trusted (F-01) ---------------------------------------------------


@pytest.mark.parametrize(
    ("trusted", "forwarded", "remote", "expected"),
    [
        (0, "203.0.113.9", "10.0.0.1", "10.0.0.1"),  # header ignored without a trusted proxy
        (1, "203.0.113.9", "10.0.0.1", "203.0.113.9"),
        (1, "6.6.6.6, 203.0.113.9", "10.0.0.1", "203.0.113.9"),  # client-written part ignored
        (2, "6.6.6.6, 203.0.113.9, 10.0.0.2", "10.0.0.1", "203.0.113.9"),
        (2, "203.0.113.9", "10.0.0.1", "10.0.0.1"),  # chain shorter than configured
        (1, "not-an-ip", "10.0.0.1", "unknown"),
        (0, "", "::1", "::1"),
    ],
)
def test_client_ip_trusts_only_the_configured_proxies(trusted, forwarded, remote, expected):
    request = RequestFactory().get("/", REMOTE_ADDR=remote, HTTP_X_FORWARDED_FOR=forwarded)
    with override_settings(TRUSTED_PROXY_COUNT=trusted):
        assert client_ip(request) == expected


def test_ipv6_addresses_are_limited_per_64_network():
    assert address_bucket("2001:db8:1:2:aaaa::1") == address_bucket("2001:db8:1:2:bbbb::9")
    assert address_bucket("2001:db8:1:3::1") != address_bucket("2001:db8:1:2::1")
    assert address_bucket("garbage") == "unknown"


def test_forged_forwarded_header_does_not_buy_more_attempts(make_user):
    """Assessment probe S1: 50 guesses with a fresh header each were never limited."""
    victim = make_user()
    for i in range(PAIR):
        response = attempt(victim.email, f"guess-{i}", HTTP_X_FORWARDED_FOR=f"203.0.113.{i}")
        assert response.status_code == 401
    blocked = attempt(victim.email, PASSWORD, HTTP_X_FORWARDED_FOR="203.0.113.250")
    assert blocked.status_code == 429


@override_settings(TRUSTED_PROXY_COUNT=1)
def test_behind_one_trusted_proxy_the_appended_address_is_limited(make_user):
    victim = make_user()
    for i in range(PAIR):
        forged = f"6.6.6.{i}, 203.0.113.50"  # client prepends junk; proxy appends the truth
        assert attempt(victim.email, "wrong", HTTP_X_FORWARDED_FOR=forged).status_code == 401
    assert attempt(victim.email, PASSWORD, HTTP_X_FORWARDED_FOR="203.0.113.50").status_code == 429
    # A different real client behind the same proxy is unaffected.
    assert attempt(victim.email, PASSWORD, HTTP_X_FORWARDED_FOR="203.0.113.51").status_code == 200


# --- What is counted (F-02) ------------------------------------------------------------


def test_correct_logins_never_consume_the_allowance(make_user):
    """Assessment probe S2: the 11th correct login from one address was refused."""
    users = [make_user() for _ in range(PAIR * 3)]
    for user in users:
        assert attempt(user.email, PASSWORD).status_code == 200
    for _ in range(PAIR * 3):
        assert attempt(users[0].email, PASSWORD).status_code == 200
    assert not LoginAttemptBucket.objects.filter(failures__gt=0).exists()


def test_a_success_clears_earlier_typing_mistakes_from_that_address(make_user):
    user = make_user()
    for _ in range(PAIR - 1):
        assert attempt(user.email, "typo").status_code == 401
    assert attempt(user.email, PASSWORD).status_code == 200
    for _ in range(PAIR - 1):
        assert attempt(user.email, "typo").status_code == 401
    assert attempt(user.email, PASSWORD).status_code == 200


def test_people_sharing_a_shop_network_do_not_block_each_other(make_user):
    """Thirty staff behind one router, each mistyping twice, all get in."""
    shop_ip = "102.244.0.10"
    for user in [make_user() for _ in range(30)]:
        assert attempt(user.email, "typo", ip=shop_ip).status_code == 401
        assert attempt(user.email, "typo", ip=shop_ip).status_code == 401
        assert attempt(user.email, PASSWORD, ip=shop_ip).status_code == 200


def test_one_address_cannot_lock_an_account_for_everyone(make_user):
    victim = make_user()
    for _ in range(ACCOUNT * 3):
        attempt(victim.email, "wrong", ip="203.0.113.66")
    assert attempt(victim.email, PASSWORD, ip="198.51.100.20").status_code == 200


def test_distributed_guessing_against_one_account_is_limited(make_user):
    """Assessment probe S3: guesses from many real addresses were never limited."""
    victim = make_user()
    for i in range(ACCOUNT):
        assert attempt(victim.email, "wrong", ip=f"198.51.100.{i}").status_code == 401
    response = attempt(victim.email, PASSWORD, ip="198.51.100.200")
    assert response.status_code == 429
    assert int(response["Retry-After"]) > 0


def test_password_spraying_from_one_address_is_limited(make_user):
    with override_settings(LOGIN_PROTECTION={**LIMITS, "ADDRESS": 10}):
        for i in range(10):
            assert attempt(f"nobody{i}@example.test", "Password123!").status_code == 401
        assert attempt("another@example.test", "Password123!").status_code == 429
        assert attempt(make_user().email, PASSWORD, ip="198.51.100.99").status_code == 200


def test_password_is_not_checked_while_blocked(make_user):
    user = make_user()
    for _ in range(PAIR):
        attempt(user.email, "wrong")
    with mock.patch("apps.accounts.views.authenticate") as authenticate:
        response = attempt(user.email, PASSWORD)
    assert response.status_code == 429
    authenticate.assert_not_called()


def test_unknown_and_known_accounts_are_indistinguishable(make_user):
    known = make_user()
    responses = {}
    for email in (known.email, "ghost@example.test"):
        statuses = [
            attempt(email, "wrong", ip="198.51.100.30").status_code for _ in range(PAIR + 1)
        ]
        final = attempt(email, "wrong", ip="198.51.100.30").json()
        responses[email] = (statuses, final["code"])
    assert responses[known.email] == responses["ghost@example.test"]
    assert responses[known.email][0] == [401] * PAIR + [429]


def test_lock_expires_with_the_window(make_user):
    user = make_user()
    for _ in range(PAIR):
        attempt(user.email, "wrong")
    assert attempt(user.email, PASSWORD).status_code == 429
    later = timezone.now() + timedelta(seconds=LIMITS["WINDOW_SECONDS"] + 1)
    with mock.patch("apps.accounts.login_protection.timezone.now", return_value=later):
        assert attempt(user.email, PASSWORD).status_code == 200


def test_counters_hold_no_identifiers(make_user):
    user = make_user()
    attempt(user.email, "wrong", ip="198.51.100.77")
    keys = " ".join(LoginAttemptBucket.objects.values_list("key", flat=True))
    assert user.email not in keys and "198.51.100.77" not in keys
    assert LoginAttemptBucket.objects.count() == 3


def test_purge_removes_only_expired_counters(make_user):
    attempt(make_user().email, "wrong")
    assert login_protection.purge_expired() == 0
    later = timezone.now() + timedelta(seconds=LIMITS["WINDOW_SECONDS"] + 1)
    assert login_protection.purge_expired(now=later) == 3
    assert not LoginAttemptBucket.objects.exists()


# --- Audit -------------------------------------------------------------------------------


def test_sign_in_and_sign_out_are_audited_with_the_trusted_address(make_user):
    user = make_user()
    client = APIClient(REMOTE_ADDR="198.51.100.40")
    client.post(LOGIN, {"email": user.email, "password": PASSWORD}, HTTP_X_FORWARDED_FOR="6.6.6.6")
    client.post("/api/v1/auth/logout/")
    events = list(AuditEvent.objects.filter(target_id=user.id).order_by("created_at"))
    assert [e.action for e in events] == ["auth.login_succeeded", "auth.logout"]
    assert events[0].metadata == {"channel": "api", "ip": "198.51.100.40"}


def test_account_lock_is_audited_once_per_window(make_user):
    victim = make_user()
    for i in range(ACCOUNT + 5):
        attempt(victim.email, "wrong", ip=f"198.51.100.{i}")
    locks = AuditEvent.objects.filter(action="auth.account_locked", target_id=victim.id)
    assert locks.count() == 1
    assert "password" not in json.dumps(locks.get().metadata)


# --- Concurrency and multiple processes ----------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_concurrent_guesses_cannot_exceed_the_limit(make_user):
    victim = make_user()
    results = []
    barrier = threading.Barrier(PAIR * 4)

    def guess():
        try:
            barrier.wait()
            results.append(attempt(victim.email, "wrong").status_code)
        finally:
            connection.close()

    threads = [threading.Thread(target=guess) for _ in range(PAIR * 4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert sorted(results) == [401] * PAIR + [429] * (PAIR * 3)


_CHILD = """
import os, sys, json
sys.path.insert(0, os.getcwd())
import django
django.setup()
from django.test import Client
client = Client(REMOTE_ADDR="198.51.100.150")
codes = [client.post("/api/v1/auth/login/", {"email": sys.argv[1], "password": "wrong"},
                     content_type="application/json").status_code for _ in range(int(sys.argv[2]))]
print(json.dumps(codes))
"""


@pytest.mark.django_db(transaction=True)
def test_the_limit_is_shared_between_separate_processes(make_user):
    """Two separate Python processes, each its own Django, one database."""
    victim = make_user()
    db = connection.settings_dict
    env = {
        **os.environ,
        "DJANGO_SETTINGS_MODULE": "config.settings",
        "DJANGO_ALLOWED_HOSTS": "testserver",
        "DATABASE_URL": (
            f"postgres://{db['USER']}:{db['PASSWORD']}@{db['HOST'] or '127.0.0.1'}:"
            f"{db['PORT'] or 5432}/{db['NAME']}"
        ),
    }

    def run(count):
        out = subprocess.run(  # noqa: S603 - our own interpreter and a constant script
            [sys.executable, "-c", _CHILD, victim.email, str(count)],
            cwd=BACKEND,
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
            check=True,
        )
        return json.loads(out.stdout.strip().splitlines()[-1])

    first = run(PAIR - 2)
    second = run(4)
    assert first == [401] * (PAIR - 2)
    assert second == [401, 401, 429, 429]
