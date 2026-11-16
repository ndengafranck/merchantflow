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


# --- C4: denial-of-service resistance -----------------------------------------------------

KNOWN = LIMITS["KNOWN_BROWSER"]


def known_browser(user, ip="198.51.100.7"):
    """A browser that has signed in to ``user`` before and then signed out:
    it still carries the account's device cookie, but no session."""
    browser = APIClient(REMOTE_ADDR=ip)
    assert browser.post(LOGIN, {"email": user.email, "password": PASSWORD}).status_code == 200
    assert browser.post("/api/v1/auth/logout/").status_code == 204
    assert settings.DEVICE_COOKIE_NAME in browser.cookies
    return browser


def sign(browser, user, password=PASSWORD):
    return browser.post(LOGIN, {"email": user.email, "password": password})


def exhaust_address(ip):
    for i in range(ADDRESS):
        attempt(f"spray{i}@example.test", "Password123!", ip=ip)
    assert attempt("one-more@example.test", "Password123!", ip=ip).status_code == 429


def test_hostile_user_on_a_shared_address_cannot_lock_out_regular_users(make_user):
    """Review C4: one user spraying from shop Wi-Fi blocked everyone there."""
    shop_ip = "102.244.0.10"
    staff = [make_user() for _ in range(5)]
    browsers = [known_browser(user, ip=shop_ip) for user in staff]
    exhaust_address(shop_ip)
    for user, browser in zip(staff, browsers, strict=True):
        assert sign(browser, user).status_code == 200
    # Residual cost, by design: a browser never used for that account, on the
    # attacked address, waits for the window to end.
    newcomer = make_user()
    assert attempt(newcomer.email, PASSWORD, ip=shop_ip).status_code == 429


def test_distributed_guessing_cannot_lock_the_owner_out_of_their_own_browser(make_user):
    victim = make_user()
    usual = known_browser(victim)
    for i in range(ACCOUNT):
        attempt(victim.email, "wrong", ip=f"203.0.113.{i}")
    assert attempt(victim.email, PASSWORD, ip="203.0.113.200").status_code == 429  # attacker
    assert sign(usual, victim).status_code == 200  # the owner, on their browser


def test_a_known_browser_still_gets_only_a_few_guesses(make_user):
    victim = make_user()
    stolen = known_browser(victim)
    for _ in range(KNOWN):
        assert sign(stolen, victim, "guess").status_code == 401
    assert sign(stolen, victim).status_code == 429  # even the right password, until the window ends
    # Its failures were not charged to the account: other browsers are unaffected.
    assert attempt(victim.email, PASSWORD, ip="198.51.100.88").status_code == 200


@pytest.mark.parametrize("cookie", ["not-a-uuid", "random", "other_users", "revoked"])
def test_only_a_genuine_active_device_cookie_of_this_account_counts(make_user, cookie):
    import uuid

    from apps.accounts import installations
    from apps.accounts.models import DeviceInstallation

    victim, other = make_user(), make_user()
    for i in range(ACCOUNT):
        attempt(victim.email, "wrong", ip=f"203.0.113.{i}")
    value = {"not-a-uuid": "x", "random": str(uuid.uuid4())}.get(cookie)
    if cookie == "other_users":
        value = str(DeviceInstallation.objects.create(user=other, label="other").pk)
    if cookie == "revoked":
        mine = DeviceInstallation.objects.create(user=victim, label="old")
        installations.revoke_installation(user=victim, installation_id=mine.pk)
        value = str(mine.pk)
    browser = APIClient(REMOTE_ADDR="198.51.100.150")
    browser.cookies[settings.DEVICE_COOKIE_NAME] = value
    assert sign(browser, victim).status_code == 429  # treated as an unknown browser


def test_a_shared_phone_is_known_only_for_the_last_account_used_on_it(make_user):
    first, second = make_user(), make_user()
    phone = known_browser(first)
    known_browser(second)  # a different browser
    for i in range(ACCOUNT):
        attempt(second.email, "wrong", ip=f"203.0.113.{i}")
    assert sign(phone, second).status_code == 429  # phone's cookie belongs to `first`
    assert sign(phone, first).status_code == 200


def test_success_on_a_known_browser_forgives_its_typing_mistakes(make_user):
    user = make_user()
    browser = known_browser(user)
    for _ in range(KNOWN - 1):
        sign(browser, user, "typo")
    assert sign(browser, user).status_code == 200
    browser.post("/api/v1/auth/logout/")
    for _ in range(KNOWN - 1):
        assert sign(browser, user, "typo").status_code == 401
    assert sign(browser, user).status_code == 200


def test_a_refused_attempt_leaves_every_counter_as_it_was(make_user):
    user = make_user()
    for _ in range(PAIR):
        attempt(user.email, "wrong")
    before = dict(LoginAttemptBucket.objects.values_list("key", "failures"))
    assert attempt(user.email, PASSWORD).status_code == 429
    assert dict(LoginAttemptBucket.objects.values_list("key", "failures")) == before


# --- Recovery ---------------------------------------------------------------------------


def test_operator_can_clear_a_lock_and_it_is_audited(make_user):
    from django.core.management import call_command

    victim = make_user()
    for i in range(ACCOUNT):
        attempt(victim.email, "wrong", ip=f"203.0.113.{i}")
    assert attempt(victim.email, PASSWORD, ip="198.51.100.66").status_code == 429

    call_command("clear_login_limits", email=victim.email.upper(), reason="Ticket 42, ID checked")

    assert attempt(victim.email, PASSWORD, ip="198.51.100.66").status_code == 200
    event = AuditEvent.objects.get(action="auth.login_limits_cleared", target_id=victim.id)
    assert event.metadata["reason"] == "Ticket 42, ID checked"
    assert event.metadata["counters_removed"] >= 1


def test_clearing_needs_a_known_account_and_a_reason(make_user):
    from django.core.management import call_command
    from django.core.management.base import CommandError

    with pytest.raises(CommandError):
        call_command("clear_login_limits", email="ghost@example.test", reason="x")
    with pytest.raises(CommandError):
        call_command("clear_login_limits", email=make_user().email, reason="   ")


def test_there_is_no_unlock_endpoint():
    from django.urls import Resolver404, resolve

    for path in ("/api/v1/auth/unlock/", "/api/v1/auth/login-limits/"):
        with pytest.raises(Resolver404):
            resolve(path)


# --- Concurrency of the combined statements ---------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_distributed_concurrent_guesses_cannot_exceed_the_account_limit(make_user):
    victim = make_user()
    total = ACCOUNT * 2
    results, barrier = [], threading.Barrier(total)

    def guess(i):
        try:
            barrier.wait()
            results.append(attempt(victim.email, "wrong", ip=f"203.0.113.{i}").status_code)
        finally:
            connection.close()

    threads = [threading.Thread(target=guess, args=(i,)) for i in range(total)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    assert sorted(results) == [401] * ACCOUNT + [429] * ACCOUNT


@pytest.mark.django_db(transaction=True)
def test_overlapping_buckets_under_concurrency_never_deadlock(make_user):
    """Mixed accounts, addresses, successes and failures at once: the
    reservation and refund statements lock in key order, so no deadlock."""
    users = [make_user() for _ in range(4)]
    errors, barrier = [], threading.Barrier(24)

    def worker(n):
        try:
            barrier.wait()
            for k in range(6):
                user = users[(n + k) % 4]
                password = PASSWORD if (n + k) % 3 == 0 else "wrong"
                status = attempt(user.email, password, ip=f"198.51.100.{(n * k) % 5}").status_code
                if status not in (200, 401, 429):
                    errors.append(status)
        except Exception as exc:  # noqa: BLE001 - any database error is the finding
            errors.append(repr(exc))
        finally:
            connection.close()

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(24)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=120)
    assert not any(t.is_alive() for t in threads)
    assert errors == []
    assert not LoginAttemptBucket.objects.filter(failures__lt=0).exists()
