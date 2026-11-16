# M2.1 code review package

Prepared for an independent senior review of Milestone 2.1 (security
hardening). **Evidence only:** every code block below is copied verbatim from
the repository by a script that reads the files and records their real line
numbers; nothing was retyped or rewritten. Commentary marked *Reviewer note*
is the preparer's reading of that code, to be checked, not trusted.

How this package was produced, and what was deliberately not done:

- No application code, test, migration, configuration or documentation was
  changed. This file is the only addition.
- **No tests were executed while preparing it.** Running the suite creates and
  drops a PostgreSQL test database, which the review brief forbids. Test
  results below come from the GitHub Actions log of the commit under review,
  and from `pytest --collect-only` (which collects without touching a
  database).
- No migration was run and no database was read or modified.
- No `.env` file was opened. Only `backend/.env.production.example`
  (placeholders, committed) is quoted.

---

## 1. Repository state

| Item | Value |
|---|---|
| Branch | `main` |
| HEAD | `4154d4c912b9ce3bd471fc4a7b596c9230e5a1b2` |
| `origin/main` | `4154d4c912b9ce3bd471fc4a7b596c9230e5a1b2` |
| Working tree before this report | clean (`git status --porcelain` printed nothing) |
| M2.1 present on this branch | yes: all commits below are ancestors of `HEAD` and of `origin/main` |

M2.1 commits (oldest last):

```
4154d4c 2026-11-16 19:39:09 +0000 M2.1: lock-out browser test and documentation
3ef1cf5 2026-11-16 19:36:30 +0000 M2.1 F-06: refuse unsafe production settings at start-up
a553147 2026-11-16 19:34:14 +0000 M2.1 F-10/F-11: workspace owner integrity in the database
73a7dcb 2026-11-16 19:30:29 +0000 M2.1 F-07: append-only audit table enforced by PostgreSQL
67eaf73 2026-11-16 19:28:37 +0000 M2.1 F-04/F-05: device rank rule and lifecycle on removal
3ca9243 2026-11-16 19:26:06 +0000 M2.1 F-03: protect the Django admin
eba578f 2026-11-16 19:24:25 +0000 M2.1 F-01/F-02: database-backed sign-in protection
5d22836 2026-11-16 19:21:34 +0000 Add the approved Milestone 2 repository assessment
```

`5d22836` only adds the approved assessment document. The implementation is
`eba578f` … `4154d4c`. Size of the change set:

```
54 files changed, 2727 insertions(+), 83 deletions(-)
```

Files changed by M2.1 (`git diff --name-status 5d22836..4154d4c`):

```
M	.github/workflows/ci.yml
M	.gitignore
M	README.md
M	backend/.env.example
A	backend/.env.production.example
M	backend/apps/accounts/admin.py
M	backend/apps/accounts/apps.py
A	backend/apps/accounts/login_protection.py
A	backend/apps/accounts/management/__init__.py
A	backend/apps/accounts/management/commands/__init__.py
A	backend/apps/accounts/management/commands/purge_login_attempts.py
A	backend/apps/accounts/migrations/0003_login_attempt_buckets.py
M	backend/apps/accounts/models.py
M	backend/apps/accounts/services.py
A	backend/apps/accounts/signals.py
M	backend/apps/accounts/views.py
A	backend/apps/audit/maintenance.py
A	backend/apps/audit/migrations/0002_append_only_triggers.py
A	backend/apps/common/admin_config.py
A	backend/apps/common/admin_site.py
A	backend/apps/common/middleware.py
A	backend/apps/common/net.py
M	backend/apps/devices/serializers.py
M	backend/apps/devices/urls.py
M	backend/apps/devices/views.py
M	backend/apps/workspaces/admin.py
M	backend/apps/workspaces/device_services.py
A	backend/apps/workspaces/migrations/0004_device_revocation_reason.py
A	backend/apps/workspaces/migrations/0005_owner_integrity.py
M	backend/apps/workspaces/models.py
M	backend/apps/workspaces/policies.py
M	backend/apps/workspaces/services.py
A	backend/config/production_checks.py
M	backend/config/settings.py
M	backend/config/urls.py
M	backend/scripts/e2e_seed.py
M	backend/tests/conftest.py
M	backend/tests/isolation.py
M	backend/tests/test_accounts.py
M	backend/tests/test_actor_authorization.py
A	backend/tests/test_admin.py
A	backend/tests/test_audit_integrity.py
A	backend/tests/test_device_lifecycle.py
A	backend/tests/test_login_protection.py
A	backend/tests/test_owner_integrity.py
A	backend/tests/test_production_settings.py
M	docs/ARCHITECTURE.md
M	docs/DECISIONS.md
A	docs/DEPLOYMENT.md
M	docs/IMPLEMENTATION_PLAN.md
M	docs/MILESTONE_2_ASSESSMENT.md
M	docs/OPEN_DECISIONS.md
M	frontend/e2e/auth.spec.ts
M	frontend/playwright.config.ts
```

### Reported vs verified test results

| Suite | Reported | Verified here | Source |
|---|---|---|---|
| Backend | 322 passed, 4 skipped | 326 collected (`pytest --collect-only`, no DB); CI log: `322 passed, 4 skipped` | GitHub Actions run 43941574998 on `4154d4c` |
| Frontend unit | 24 passed | CI log: `Tests 24 passed (24)` | same run |
| Browser | 14 passed | CI log: `14 passed` | same run |
| CI | passed | run 43941574998: backend, frontend and e2e jobs all `success` | `gh run view` |
| Skips | 4 | CI log: `SKIPPED [4] tests/test_isolation.py:70: endpoint takes no record id`; no other skip | same run |

The CI run is https://github.com/ndengafranck/merchantflow/actions/runs/43941574998.
These results were **read, not reproduced**, in this package.

---

## 2. Login protection (F-01, F-02)

### 2.1 Trusted proxy configuration and settings


**`backend/config/settings.py`, lines 128–144** — trusted proxies and sign-in limits

```python
# --- Reverse proxy and sign-in protection ------------------------------------
# How many reverse proxies in front of Django are trusted to append the client
# address to X-Forwarded-For. 0 = ignore the header (development, or Django
# reached directly). Must match the real deployment exactly: too high lets
# clients forge their address, too low makes every client look like the proxy.
TRUSTED_PROXY_COUNT = env.int("DJANGO_TRUSTED_PROXY_COUNT", default=0)
if TRUSTED_PROXY_COUNT > 0:
    # The outermost trusted proxy terminates TLS and says so in this header.
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# Failed sign-in attempts allowed per window (see apps/accounts/login_protection.py).
LOGIN_PROTECTION = {
    "WINDOW_SECONDS": env.int("LOGIN_WINDOW_SECONDS", default=15 * 60),
    "ACCOUNT_AND_ADDRESS": env.int("LOGIN_MAX_FAILURES_ACCOUNT_ADDRESS", default=5),
    "ACCOUNT": env.int("LOGIN_MAX_FAILURES_ACCOUNT", default=20),
    "ADDRESS": env.int("LOGIN_MAX_FAILURES_ADDRESS", default=100),
}
```

**`backend/config/settings.py`, lines 161–162** — DRF uses the same trust rule

```python
    # Same trust rule as apps.common.net.client_ip, for any DRF throttle added later.
    "NUM_PROXIES": TRUSTED_PROXY_COUNT,
```


*Reviewer note:* one integer, `DJANGO_TRUSTED_PROXY_COUNT` (default 0), drives
client-address resolution, DRF's `NUM_PROXIES`, and whether
`X-Forwarded-Proto` is believed for HTTPS detection. In production it must be
set explicitly and be at least 1 (section 7).

### 2.2 Client address resolution

**`backend/apps/common/net.py`, lines 1–46** — complete file

```python
"""The client's network address, as far as it can be trusted.

Only ``TRUSTED_PROXY_COUNT`` reverse proxies in front of the application are
believed. Each trusted proxy appends the address it received the request from
to ``X-Forwarded-For``, so with N trusted proxies the client is the N-th entry
from the right. Anything further left was written by the client and is
ignored. With no trusted proxy the header is ignored entirely.
"""

import ipaddress

from django.conf import settings


def client_ip(request) -> str:
    """The best trustworthy address for ``request`` (a Django ``HttpRequest``)."""
    remote = request.META.get("REMOTE_ADDR", "")
    trusted = settings.TRUSTED_PROXY_COUNT
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if trusted <= 0 or not forwarded:
        return _clean(remote)
    hops = [hop.strip() for hop in forwarded.split(",") if hop.strip()]
    if len(hops) < trusted:
        # Fewer hops than trusted proxies: the chain is not what we expect,
        # so fall back to the address of the peer we actually talk to.
        return _clean(remote)
    return _clean(hops[-trusted])


def address_bucket(ip: str) -> str:
    """The unit an address is limited by: the address itself for IPv4, its
    /64 network for IPv6 (one subscriber usually holds a whole /64)."""
    try:
        parsed = ipaddress.ip_address(ip)
    except ValueError:
        return "unknown"
    if parsed.version == 6:
        return str(ipaddress.ip_network(f"{parsed}/64", strict=False))
    return str(parsed)


def _clean(value: str) -> str:
    try:
        return str(ipaddress.ip_address(value.strip()))
    except ValueError:
        return "unknown"
```


**How forged headers are neutralised.** With `TRUSTED_PROXY_COUNT = 0` the
header is never read (`REMOTE_ADDR` only). With N trusted proxies the client
is `hops[-N]`: entries further left were written by the client and are
ignored, so prepending fake addresses changes nothing. If the chain is shorter
than N, the peer address is used. Unparseable values become the literal
`"unknown"`.

*Reviewer note:* this is only correct if the outermost proxy **overwrites**
any incoming `X-Forwarded-For` (stated in DEPLOYMENT.md; not verifiable
without a deployment). All requests whose address cannot be parsed share one
`"unknown"` address bucket.

### 2.3 Counter model

**`backend/apps/accounts/models.py`, lines 163–180** — `LoginAttemptBucket`

```python
class LoginAttemptBucket(models.Model):
    """Failed sign-in attempts for one key within one time window.

    Kept in PostgreSQL so every application process shares the counts. Keys
    are opaque (HMAC of the identifier and/or a network address), so the
    table holds no email addresses or phone numbers. Rows with an expired
    window are meaningless and are removed by ``manage.py purge_login_attempts``.
    """

    key = models.CharField(max_length=128, primary_key=True)
    window_started_at = models.DateTimeField()
    failures = models.PositiveIntegerField(default=0)

    class Meta:
        indexes = [models.Index(fields=["window_started_at"], name="login_bucket_window_idx")]

    def __str__(self) -> str:
        return f"{self.key}: {self.failures}"
```


### 2.4 Reservation, refund, limits, expiry (complete module)

**`backend/apps/accounts/login_protection.py`, lines 1–159** — complete file

```python
"""Protection of the sign-in forms against password guessing.

Three independent counters of **failed** attempts, all in PostgreSQL:

======================  ===========================================================
Bucket                  Stops
======================  ===========================================================
account + address       one client guessing one account (strict limit)
account                 many addresses guessing one account (distributed guessing)
address                 one address trying many accounts (password spraying);
                        generous, so people sharing a shop network are unaffected
======================  ===========================================================

Each attempt first *reserves* a failure in every bucket with an atomic upsert.
If any bucket is then over its limit the attempt is refused without checking
the password, and the reservations are given back, so refused attempts do not
extend a lock and one address cannot push an account into lock-out on its
own. If the password is checked and correct, the reservations are given back
and the account-and-address bucket is cleared: correct sign-ins never consume
the allowance. Reserving before checking means concurrent requests cannot
slip past a limit.

Unknown accounts are counted exactly like real ones, so the responses do not
reveal whether an account exists.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from django.conf import settings
from django.db import connection
from django.utils import timezone
from django.utils.crypto import salted_hmac

from .models import LoginAttemptBucket

_UPSERT = """
INSERT INTO accounts_loginattemptbucket AS b (key, window_started_at, failures)
VALUES (%(key)s, %(now)s, 1)
ON CONFLICT (key) DO UPDATE SET
    failures = CASE WHEN b.window_started_at <= %(expired_before)s THEN 1 ELSE b.failures + 1 END,
    window_started_at = CASE
        WHEN b.window_started_at <= %(expired_before)s THEN %(now)s ELSE b.window_started_at END
RETURNING failures, window_started_at
"""

_REFUND = """
UPDATE accounts_loginattemptbucket SET failures = failures - 1
WHERE key = %(key)s AND window_started_at = %(window)s AND failures > 0
"""


@dataclass(frozen=True)
class Limit:
    kind: str
    key: str
    maximum: int


@dataclass
class Reservation:
    limit: Limit
    failures: int
    window_started_at: datetime


@dataclass
class Attempt:
    """One sign-in attempt. Call ``failed()`` or ``succeeded()`` exactly once,
    unless ``blocked`` is true, in which case the password must not be checked."""

    reservations: list[Reservation]
    blocked: bool = False
    retry_after: int = 0
    _settled: bool = field(default=False, repr=False)

    def failed(self) -> list[str]:
        """Keep the reservations. Returns the bucket kinds that just reached
        their limit, so the caller can record a lock-out once per window."""
        self._settle()
        return [r.limit.kind for r in self.reservations if r.failures == r.limit.maximum]

    def succeeded(self) -> None:
        self._settle()
        _refund(self.reservations)
        pair = next(r for r in self.reservations if r.limit.kind == "account_address")
        LoginAttemptBucket.objects.filter(pk=pair.limit.key).delete()

    def _settle(self) -> None:
        if self._settled or self.blocked:
            raise RuntimeError("A login attempt is settled once, and never when blocked.")
        self._settled = True


def _config() -> dict:
    return settings.LOGIN_PROTECTION


def _key(kind: str, value: str) -> str:
    digest = salted_hmac("merchantflow.login-protection", f"{kind}:{value}").hexdigest()
    return f"{kind}:{digest}"


def limits_for(identifier: str, address: str) -> list[Limit]:
    config = _config()
    return [
        Limit(
            "account_address",
            _key("aa", f"{identifier}|{address}"),
            config["ACCOUNT_AND_ADDRESS"],
        ),
        Limit("account", _key("a", identifier), config["ACCOUNT"]),
        Limit("address", _key("ad", address), config["ADDRESS"]),
    ]


def begin_attempt(*, identifier: str, address: str) -> Attempt:
    """Reserve one failure in each bucket and decide whether to proceed.

    ``identifier`` must already be normalised (for example a lower-cased email)
    and ``address`` should come from ``apps.common.net.address_bucket``.
    Each upsert commits on its own, outside any request transaction, so a
    failed sign-in is counted even though the request then raises.
    """
    now = timezone.now()
    window = timedelta(seconds=_config()["WINDOW_SECONDS"])
    reservations = []
    with connection.cursor() as cursor:
        for limit in limits_for(identifier, address):
            cursor.execute(_UPSERT, {"key": limit.key, "now": now, "expired_before": now - window})
            failures, started = cursor.fetchone()
            reservations.append(Reservation(limit, failures, started))

    over = [r for r in reservations if r.failures > r.limit.maximum]
    if not over:
        return Attempt(reservations)
    _refund(reservations)
    retry_after = max(int((r.window_started_at + window - now).total_seconds()) for r in over)
    return Attempt(reservations, blocked=True, retry_after=max(retry_after, 1))


def _refund(reservations: list[Reservation]) -> None:
    with connection.cursor() as cursor:
        for r in reservations:
            cursor.execute(_REFUND, {"key": r.limit.key, "window": r.window_started_at})


def purge_expired(now: datetime | None = None) -> int:
    """Delete buckets whose window has ended. Returns the number removed."""
    now = now or timezone.now()
    cutoff = now - timedelta(seconds=_config()["WINDOW_SECONDS"])
    deleted, _ = LoginAttemptBucket.objects.filter(window_started_at__lte=cutoff).delete()
    return deleted


def blocked_message(retry_after: int) -> str:
    minutes = max(1, -(-retry_after // 60))
    unit = "minute" if minutes == 1 else "minutes"
    return f"Too many failed sign-in attempts. Try again in {minutes} {unit}."
```


**Atomic counting.** Each bucket is one row updated by a single
`INSERT … ON CONFLICT (key) DO UPDATE … RETURNING` statement (`_UPSERT`).
PostgreSQL serialises concurrent upserts on the same key with a row lock, so
each concurrent request sees a distinct, increasing count. The window resets
inside the same statement when `window_started_at <= now - window`.

**Why concurrent requests cannot exceed a limit.** A failure is reserved
*before* the password is checked. With a limit of 5, five concurrent requests
receive counts 1–5 and proceed; a sixth receives 6, is over the limit, is
refunded, and is refused without checking the password.

**Successes do not consume allowance.** `Attempt.succeeded()` refunds every
reservation (`_REFUND`, guarded by the same `window_started_at` and
`failures > 0`) and deletes the account-and-address row.

**Refused attempts do not extend a lock.** When blocked, all three
reservations are refunded, so one address cannot keep pushing the account
counter (an attacker at one address cannot by itself reach the account limit).

**Expiry.** A bucket's window starts at its first failure and lasts
`WINDOW_SECONDS`; the next failure after that resets it to 1.
`purge_expired()` deletes expired rows (scheduled job, section 8).

*Reviewer notes:*

- The three upserts are separate autocommit statements, not one transaction.
  Each bucket is individually strict, but the three are not updated atomically
  as a set.
- `begin_attempt` relies on running **outside** a request transaction
  (`ATOMIC_REQUESTS` is `False` in settings). Inside an outer transaction that
  rolls back on the 401, the failure would not be counted.
- If the process dies between reservation and refund, a successful sign-in
  stays counted as a failure. This fails closed.
- Keys are `salted_hmac` of the identifier and address, so the table holds no
  email or IP. Rotating `SECRET_KEY` resets all counters.
- Only the API login and the admin login use this. There is no registration,
  password reset or other credential endpoint yet.

### 2.5 Integration in the login view

**`backend/apps/accounts/views.py`, lines 35–65** — `LoginView`

```python
@method_decorator(csrf_protect, name="dispatch")
class LoginView(APIView):
    authentication_classes: list = []
    permission_classes = [AllowAny]
    # Guessing is limited by apps.accounts.login_protection, which counts only
    # failures and shares its counts across processes; no DRF throttle here.
    throttle_classes: list = []

    def get_authenticate_header(self, request: Request) -> str:
        # No authenticator runs here, so tell DRF to answer bad credentials
        # with 401 rather than downgrading them to 403.
        return "Session"

    @extend_schema(request=LoginSerializer, responses=UserSerializer)
    def post(self, request: Request) -> Response:
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = normalize_email(serializer.validated_data["email"])
        attempt = guarded_attempt(request, email)
        user = authenticate(request, username=email, password=serializer.validated_data["password"])
        if user is None:
            record_failure(request, attempt, email)
            # One message for unknown email, wrong password and disabled
            # account, so the endpoint cannot be used to discover accounts.
            raise AuthenticationFailed("Incorrect email or password.", code="invalid_credentials")
        attempt.succeeded()
        login(request, user)  # rotates the session key and the CSRF token
        installation = installations.bind_session_to_installation(request, user)
        response = Response(UserSerializer(user).data)
        installations.set_installation_cookie(response, installation)
        return response
```

**`backend/apps/accounts/views.py`, lines 68–69** — `TooManyAttempts`

```python
class TooManyAttempts(Throttled):
    default_code = "too_many_attempts"
```

**`backend/apps/accounts/views.py`, lines 72–81** — `guarded_attempt`

```python
def guarded_attempt(request, identifier: str) -> login_protection.Attempt:
    """Reserve a sign-in attempt, or refuse it before the password is checked."""
    attempt = login_protection.begin_attempt(
        identifier=identifier, address=address_bucket(client_ip(request))
    )
    if attempt.blocked:
        raise TooManyAttempts(
            wait=attempt.retry_after, detail=login_protection.blocked_message(attempt.retry_after)
        )
    return attempt
```

**`backend/apps/accounts/views.py`, lines 84–94** — `record_failure`

```python
def record_failure(request, attempt: login_protection.Attempt, identifier: str) -> None:
    """Count the failure and audit an account lock-out once per window."""
    if "account" not in attempt.failed():
        return
    user = User.objects.filter(email=identifier).first()
    if user is not None:
        record_event(
            action="auth.account_locked",
            target=user,
            metadata={"ip": client_ip(request), "reason": "failed_sign_in_limit"},
        )
```


Order of operations in `LoginView.post`:

1. The serializer validates the input; invalid input is not counted.
2. `guarded_attempt` reserves and may raise 429 `too_many_attempts`, without
   calling `authenticate`.
3. On a wrong password, `record_failure` keeps the reservation and writes
   `auth.account_locked` once, when the account bucket reaches exactly its
   limit, and only if the account exists.
4. On success the reservation is refunded before `login()`.

The DRF `ScopedRateThrottle` was removed (`throttle_classes: list = []`).

### 2.6 Sign-in audit and the purge command

**`backend/apps/accounts/signals.py`, lines 1–41** — complete file

```python
"""Audit events for sign-in and sign-out, through the API and the Django admin."""

from django.contrib.auth.signals import user_logged_in, user_logged_out
from django.dispatch import receiver

from apps.audit.services import record_event
from apps.common.net import client_ip


def _channel(request) -> str:
    return "admin" if request.path.startswith("/" + _admin_prefix()) else "api"


def _admin_prefix() -> str:
    from django.conf import settings

    return settings.ADMIN_PATH


@receiver(user_logged_in)
def audit_login(sender, request, user, **kwargs) -> None:
    if request is None:
        return
    record_event(
        action="auth.login_succeeded",
        target=user,
        actor=user,
        metadata={"channel": _channel(request), "ip": client_ip(request)},
    )


@receiver(user_logged_out)
def audit_logout(sender, request, user, **kwargs) -> None:
    if request is None or user is None:
        return
    record_event(
        action="auth.logout",
        target=user,
        actor=user,
        metadata={"channel": _channel(request), "ip": client_ip(request)},
    )
```

**`backend/apps/accounts/management/commands/purge_login_attempts.py`, lines 1–10** — complete file

```python
from django.core.management.base import BaseCommand

from apps.accounts.login_protection import purge_expired


class Command(BaseCommand):
    help = "Delete sign-in attempt counters whose window has ended. Schedule it, e.g. hourly."

    def handle(self, *args, **options) -> None:
        self.stdout.write(f"Removed {purge_expired()} expired sign-in counters.")
```


### 2.7 Key tests (verbatim)

Concurrency (threads, separate connections, committed transactions) and the
two-process test:

**`backend/tests/test_login_protection.py`, lines 215–233** — `test_concurrent_guesses_cannot_exceed_the_limit`

```python
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
```

**`backend/tests/test_login_protection.py`, lines 236–246** — `_CHILD`

```python
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
```

**`backend/tests/test_login_protection.py`, lines 249–279** — `test_the_limit_is_shared_between_separate_processes`

```python
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
```

**`backend/tests/test_login_protection.py`, lines 63–70** — `test_forged_forwarded_header_does_not_buy_more_attempts`

```python
def test_forged_forwarded_header_does_not_buy_more_attempts(make_user):
    """Assessment probe S1: 50 guesses with a fresh header each were never limited."""
    victim = make_user()
    for i in range(PAIR):
        response = attempt(victim.email, f"guess-{i}", HTTP_X_FORWARDED_FOR=f"203.0.113.{i}")
        assert response.status_code == 401
    blocked = attempt(victim.email, PASSWORD, HTTP_X_FORWARDED_FOR="203.0.113.250")
    assert blocked.status_code == 429
```

**`backend/tests/test_login_protection.py`, lines 73–81** — `test_behind_one_trusted_proxy_the_appended_address_is_limited`

```python
@override_settings(TRUSTED_PROXY_COUNT=1)
def test_behind_one_trusted_proxy_the_appended_address_is_limited(make_user):
    victim = make_user()
    for i in range(PAIR):
        forged = f"6.6.6.{i}, 203.0.113.50"  # client prepends junk; proxy appends the truth
        assert attempt(victim.email, "wrong", HTTP_X_FORWARDED_FOR=forged).status_code == 401
    assert attempt(victim.email, PASSWORD, HTTP_X_FORWARDED_FOR="203.0.113.50").status_code == 429
    # A different real client behind the same proxy is unaffected.
    assert attempt(victim.email, PASSWORD, HTTP_X_FORWARDED_FOR="203.0.113.51").status_code == 200
```

**`backend/tests/test_login_protection.py`, lines 107–113** — `test_people_sharing_a_shop_network_do_not_block_each_other`

```python
def test_people_sharing_a_shop_network_do_not_block_each_other(make_user):
    """Thirty staff behind one router, each mistyping twice, all get in."""
    shop_ip = "102.244.0.10"
    for user in [make_user() for _ in range(30)]:
        assert attempt(user.email, "typo", ip=shop_ip).status_code == 401
        assert attempt(user.email, "typo", ip=shop_ip).status_code == 401
        assert attempt(user.email, PASSWORD, ip=shop_ip).status_code == 200
```

**`backend/tests/test_login_protection.py`, lines 141–148** — `test_password_is_not_checked_while_blocked`

```python
def test_password_is_not_checked_while_blocked(make_user):
    user = make_user()
    for _ in range(PAIR):
        attempt(user.email, "wrong")
    with mock.patch("apps.accounts.views.authenticate") as authenticate:
        response = attempt(user.email, PASSWORD)
    assert response.status_code == 429
    authenticate.assert_not_called()
```


*Reviewer note on what these prove:*

- The concurrency test fires 20 simultaneous wrong passwords at one account
  from one address. It asserts exactly 5 answers of 401 and 15 of 429.
- The two-process test starts two Python interpreters, each with its own
  Django, against the same (committed) test database. It shows the limit is
  shared: the second process is refused after the combined count reaches 5.
- The shared-network test covers **honest** users only. It does not show
  that a hostile user on the same address (shop Wi-Fi, or a mobile carrier's
  shared address) cannot exhaust the address bucket of 100. They can, and
  then everyone at that address is refused for the window, including correct
  passwords (section 10).

---

## 3. Django admin protection (F-03)

### 3.1 Enablement and path

**`backend/config/settings.py`, lines 146–148**

```python
# --- Django admin ------------------------------------------------------------
ADMIN_ENABLED = env.bool("DJANGO_ADMIN_ENABLED", default=DEBUG)
ADMIN_PATH = env.str("DJANGO_ADMIN_PATH", default="admin/")
```

**`backend/config/settings.py`, lines 28–28** — INSTALLED_APPS entry replacing `django.contrib.admin`

```python
    "apps.common.admin_config.MerchantFlowAdminConfig",  # django.contrib.admin, protected
```

**`backend/config/urls.py`, lines 1–27** — complete file

```python
from django.conf import settings
from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from apps.common.views import HealthCheckView

api_v1 = [
    path("auth/", include("apps.accounts.urls")),
    path("workspaces/", include("apps.workspaces.urls")),
]

urlpatterns = [
    path("api/health/", HealthCheckView.as_view(), name="health"),
    path("api/v1/", include(api_v1)),
]

# The admin is the most privileged surface. It is off unless explicitly
# enabled, and its path is configurable so it can be kept off the public URL.
if settings.ADMIN_ENABLED:
    urlpatterns.append(path(settings.ADMIN_PATH, admin.site.urls))

if settings.API_DOCS_ENABLED:
    urlpatterns += [
        path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
        path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="docs"),
    ]
```

**`backend/apps/common/admin_config.py`, lines 1–7** — complete file

```python
from django.contrib.admin.apps import AdminConfig


class MerchantFlowAdminConfig(AdminConfig):
    """``django.contrib.admin`` with the protected site (``admin_site.py``)."""

    default_site = "apps.common.admin_site.MerchantFlowAdminSite"
```


`/admin/` (or `DJANGO_ADMIN_PATH`) is routed only when `DJANGO_ADMIN_ENABLED`
is true. The default is the value of `DJANGO_DEBUG`. In production the start-up
checks refuse an enabled admin at the default path (section 7).

### 3.2 How an administrator's login is protected

**`backend/apps/common/admin_site.py`, lines 1–32** — complete file

```python
"""The Django admin site, with the same sign-in protection as the API."""

from django.contrib import admin
from django.http import HttpResponse

from apps.accounts.login_protection import begin_attempt, blocked_message
from apps.accounts.models import normalize_email
from apps.common.net import address_bucket, client_ip


class MerchantFlowAdminSite(admin.AdminSite):
    site_header = "MerchantFlow administration"
    site_title = "MerchantFlow admin"

    def login(self, request, extra_context=None):
        if request.method != "POST":
            return super().login(request, extra_context)
        identifier = normalize_email(request.POST.get("username", ""))
        attempt = begin_attempt(identifier=identifier, address=address_bucket(client_ip(request)))
        if attempt.blocked:
            response = HttpResponse(
                blocked_message(attempt.retry_after), status=429, content_type="text/plain"
            )
            response["Retry-After"] = str(attempt.retry_after)
            return response
        response = super().login(request, extra_context)
        signed_in = response.status_code == 302 and request.user.is_authenticated
        if signed_in:
            attempt.succeeded()
        else:
            attempt.failed()
        return response
```


On every `POST` to the admin login, the submitted `username` (email,
normalised) and the trusted client address go through the same
`begin_attempt` as the API, sharing the same three counters. A blocked
attempt returns `429 text/plain` with `Retry-After`, and Django's login form
never runs. A `302` with an authenticated user counts as success; anything
else counts as a failure.

*Reviewer notes:*

- A valid password for a **non-staff** account is a failed admin login, and
  counts as a failure.
- There is no second factor.
- The admin uses the same session cookie name as the SPA. An admin session is
  not bound to a browser installation, so the API refuses it
  (`test_admin_session_cannot_use_the_api`).

### 3.3 Memberships read-only; audited workspace edits

**`backend/apps/workspaces/admin.py`, lines 1–69** — complete file

```python
from django.contrib import admin

from apps.audit.services import record_event

from .models import Workspace, WorkspaceDevice, WorkspaceMembership


class NoDeleteAdmin(admin.ModelAdmin):
    """History is archived through status fields, never deleted."""

    def has_delete_permission(self, request, obj=None) -> bool:
        return False


@admin.register(Workspace)
class WorkspaceAdmin(NoDeleteAdmin):
    list_display = ["name", "slug", "status", "created_at"]
    list_filter = ["status"]
    search_fields = ["name", "slug"]
    readonly_fields = ["slug", "created_at", "updated_at"]

    def has_add_permission(self, request) -> bool:
        # A workspace needs an owner membership: use `manage.py create_workspace`.
        return False

    def save_model(self, request, obj, form, change) -> None:
        super().save_model(request, obj, form, change)
        if change and form.changed_data:
            record_event(
                action="workspace.updated",
                target=obj,
                actor=request.user,
                workspace=obj,
                metadata={
                    "channel": "admin",
                    "changes": {f: str(form.cleaned_data[f]) for f in form.changed_data},
                },
            )


@admin.register(WorkspaceMembership)
class WorkspaceMembershipAdmin(NoDeleteAdmin):
    """View only. Roles, statuses and ownership change through the services,
    which enforce the ownership rules and write the audit trail."""

    list_display = ["user", "workspace", "role", "status"]
    list_filter = ["role", "status"]
    search_fields = ["user__email", "workspace__name"]

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False


@admin.register(WorkspaceDevice)
class WorkspaceDeviceAdmin(NoDeleteAdmin):
    """Read-only: revoke through the API so the change is audited."""

    list_display = ["installation", "workspace", "status", "last_seen_at"]
    list_filter = ["status"]
    search_fields = ["installation__user__email", "workspace__name"]

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False
```


### 3.4 Audited user edits; owner deactivation refused

**`backend/apps/accounts/admin.py`, lines 1–92** — complete file

```python
from django import forms
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.contrib.auth.forms import UserChangeForm

from apps.audit.services import record_event

from .models import DeviceInstallation, User
from .services import owned_workspace_names


class MerchantFlowUserChangeForm(UserChangeForm):
    class Meta(UserChangeForm.Meta):
        model = User
        fields = "__all__"

    def clean_is_active(self) -> bool:
        is_active = self.cleaned_data["is_active"]
        if self.instance.pk and self.instance.is_active and not is_active:
            owned = owned_workspace_names(self.instance)
            if owned:
                raise forms.ValidationError(
                    "This person owns " + ", ".join(owned) + ". Transfer ownership "
                    "before deactivating the account, or the workspace has no owner."
                )
        return is_active


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    form = MerchantFlowUserChangeForm
    ordering = ["email"]
    list_display = ["email", "full_name", "is_active", "is_staff"]
    search_fields = ["email", "full_name", "phone"]
    readonly_fields = ["last_login", "date_joined"]
    fieldsets = [
        (None, {"fields": ["email", "password"]}),
        ("Profile", {"fields": ["full_name", "phone"]}),
        ("Access", {"fields": ["is_active", "is_staff", "is_superuser"]}),
        ("Dates", {"fields": ["last_login", "date_joined"]}),
    ]
    add_fieldsets = [
        (None, {"fields": ["email", "full_name", "password1", "password2"]}),
    ]

    def save_model(self, request, obj, form, change) -> None:
        super().save_model(request, obj, form, change)
        changed = [f for f in form.changed_data if f != "password"]
        if change and changed:
            record_event(
                action="user.updated",
                target=obj,
                actor=request.user,
                metadata={
                    "channel": "admin",
                    "changes": {f: str(form.cleaned_data[f]) for f in changed},
                },
            )
        elif not change:
            record_event(
                action="user.created", target=obj, actor=request.user, metadata={"channel": "admin"}
            )

    def user_change_password(self, request, id, form_url=""):
        response = super().user_change_password(request, id, form_url)
        if request.method == "POST" and response.status_code == 302:
            user = User.objects.get(pk=id)
            record_event(
                action="user.password_set",
                target=user,
                actor=request.user,
                metadata={"channel": "admin"},
            )
        return response


@admin.register(DeviceInstallation)
class DeviceInstallationAdmin(admin.ModelAdmin):
    """Read-only: revoke through the API or services so sessions end too."""

    list_display = ["label", "user", "status", "last_login_at", "created_at"]
    list_filter = ["status"]
    search_fields = ["user__email", "label"]

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False
```

**`backend/apps/accounts/services.py`, lines 24–38** — `owned_workspace_names`

```python
def owned_workspace_names(user: User) -> list[str]:
    """Workspaces this user owns that are not archived.

    Such a user cannot be deactivated: the workspace would have an owner who
    cannot sign in. The database enforces the same rule
    (``accounts_user_owner_stays_active`` trigger).
    """
    from apps.workspaces.models import WorkspaceMembership, WorkspaceStatus

    return list(
        WorkspaceMembership.objects.filter(user=user, role="owner")
        .exclude(workspace__status=WorkspaceStatus.ARCHIVED)
        .order_by("workspace__name")
        .values_list("workspace__name", flat=True)
    )
```


*Reviewer notes:*

- `UserAdmin` keeps Django's default **delete** permission. Deleting a user
  is not audited. Database `PROTECT` foreign keys from memberships,
  installations and audit rows block it for any user with history, but no
  test covers user deletion through the admin.
- Workspace-status changes are audited (`workspace.updated`), including
  archiving. Archiving lifts the account-active rule for the owner (section 6).

---

## 4. Device and membership lifecycle (F-04, F-05)

### 4.1 Global installation vs workspace authorisation

| Record | Scope | Revoked by | Effect |
|---|---|---|---|
| `accounts.DeviceInstallation` | one browser of one user, **all** workspaces | the user only (`/api/v1/auth/installations/{id}/revoke/`) | deletes that browser's sessions; signed out everywhere |
| `workspaces.WorkspaceDevice` | one installation in **one** workspace | the user (own), or a higher-ranked holder of `devices.manage` | that workspace refuses the browser (403 `device_not_authorized`); session and other workspaces unaffected |

Neither is cryptographic proof of a physical device. The installation is a
server-issued identifier in an HttpOnly cookie, read only at login after the
password check.

**`backend/apps/workspaces/models.py`, lines 131–133** — `DeviceRevocationReason`

```python
class DeviceRevocationReason(models.TextChoices):
    MANUAL = "manual", "Revoked by a person"
    MEMBERSHIP_REMOVED = "membership_removed", "Member removed from the workspace"
```

**`backend/apps/workspaces/models.py`, lines 136–195** — `WorkspaceDevice`

```python
class WorkspaceDevice(UUIDModel, TimestampedModel, WorkspaceOwnedModel):
    """Authorisation of one browser installation to work in one workspace.

    Created automatically the first time an installation enters a workspace
    through an active membership. There is at most one row per installation
    per workspace and a revoked row is never replaced, so revoking it closes
    this workspace to that browser while the user's other workspaces, and
    their other browsers, are unaffected.
    """

    installation = models.ForeignKey(
        "accounts.DeviceInstallation", on_delete=models.PROTECT, related_name="workspace_devices"
    )
    status = models.CharField(
        max_length=16,
        choices=WorkspaceDeviceStatus.choices,
        default=WorkspaceDeviceStatus.ACTIVE,
    )
    last_seen_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="revoked_workspace_devices",
    )
    # NULL (not "") while active, so the check constraint can tie it to status.
    revocation_reason = models.CharField(  # noqa: DJ001
        max_length=32, choices=DeviceRevocationReason.choices, null=True, blank=True
    )

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "installation"],
                name="workspace_device_one_per_installation",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        status="active",
                        revoked_at__isnull=True,
                        revoked_by__isnull=True,
                        revocation_reason__isnull=True,
                    )
                    | Q(
                        status="revoked",
                        revoked_at__isnull=False,
                        revoked_by__isnull=False,
                        revocation_reason__in=DeviceRevocationReason.values,
                    )
                ),
                name="workspace_device_revocation_consistent_v2",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.installation_id} @ {self.workspace_id} ({self.status})"
```


### 4.2 Role ranking

**`backend/apps/workspaces/policies.py`, lines 15–20** — `Capability`

```python
class Capability(StrEnum):
    WORKSPACE_VIEW = "workspace.view"
    MEMBERS_VIEW = "members.view"
    MEMBERS_MANAGE = "members.manage"
    DEVICES_USE = "devices.use"  # register, use and revoke one's own devices
    DEVICES_MANAGE = "devices.manage"  # see and revoke any device in the workspace
```

**`backend/apps/workspaces/policies.py`, lines 25–30** — `ROLE_CAPABILITIES`

```python
ROLE_CAPABILITIES: dict[str, frozenset[Capability]] = {
    MembershipRole.OWNER: frozenset(Capability),
    MembershipRole.MANAGER: _EVERY_MEMBER | {Capability.MEMBERS_VIEW, Capability.DEVICES_MANAGE},
    MembershipRole.ATTENDANT: _EVERY_MEMBER,
    MembershipRole.AFFILIATE: _EVERY_MEMBER,
}
```

**`backend/apps/workspaces/policies.py`, lines 36–41** — `ROLE_RANK`

```python
ROLE_RANK: dict[str, int] = {
    MembershipRole.OWNER: 3,
    MembershipRole.MANAGER: 2,
    MembershipRole.ATTENDANT: 1,
    MembershipRole.AFFILIATE: 1,
}
```

**`backend/apps/workspaces/policies.py`, lines 44–45** — `outranks`

```python
def outranks(actor: WorkspaceMembership, target: WorkspaceMembership) -> bool:
    return ROLE_RANK.get(actor.role, 0) > ROLE_RANK.get(target.role, 0)
```


### 4.3 Device services (complete module)

**`backend/apps/workspaces/device_services.py`, lines 1–199** — complete file

```python
"""Workspace-specific device authorisation."""

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.accounts.models import DeviceInstallation
from apps.audit.services import record_event
from apps.common.exceptions import NotFoundError, NotPermittedError

from .models import (
    DeviceRevocationReason,
    MembershipStatus,
    WorkspaceDevice,
    WorkspaceDeviceStatus,
    WorkspaceMembership,
)
from .policies import Capability, has_capability, outranks
from .services import authorize_actor


def ensure_workspace_device(
    *, installation: DeviceInstallation, membership: WorkspaceMembership
) -> WorkspaceDevice:
    """Return this installation's authorisation for the workspace.

    The first entry by an active member creates it (no owner approval is
    required at present, see OPEN_DECISIONS O-020). A revoked authorisation is
    never recreated here; only ``reauthorize_workspace_device`` lifts it.
    """
    if installation.user_id != membership.user_id or not installation.is_active:
        raise NotPermittedError("This device cannot be used here.", code="device_not_authorized")
    lookup = {"workspace_id": membership.workspace_id, "installation": installation}
    device = WorkspaceDevice.objects.filter(**lookup).first()
    if device is None:
        device = _authorize_on_first_entry(membership, lookup)
    if device.status != WorkspaceDeviceStatus.ACTIVE:
        raise NotPermittedError(
            "This device is no longer authorised for this workspace.",
            code="device_not_authorized",
        )
    return device


def _authorize_on_first_entry(membership: WorkspaceMembership, lookup: dict) -> WorkspaceDevice:
    try:
        with transaction.atomic():
            # Lock the membership so this cannot interleave with its removal:
            # removal holds the row FOR UPDATE until it has revoked every device.
            still_active = (
                WorkspaceMembership.objects.select_for_update(no_key=True)
                .filter(pk=membership.pk, status=MembershipStatus.ACTIVE)
                .exists()
            )
            if not still_active:
                raise NotFoundError("Workspace not found.")
            device = WorkspaceDevice.objects.create(**lookup)
            record_event(
                action="device.authorized",
                target=device,
                actor=membership.user,
                workspace=membership.workspace,
            )
            return device
    except IntegrityError:
        # Another request from the same browser created it first.
        return WorkspaceDevice.objects.get(**lookup)


def _lock_device_and_holder(actor: WorkspaceMembership, device_id):
    """Lock a device of the actor's workspace and find its holder's membership."""
    device = (
        WorkspaceDevice.objects.for_workspace(actor.workspace)
        .select_for_update(of=("self",))
        .select_related("installation")
        .filter(pk=device_id)
        .first()
    )
    if device is None:
        return None, None
    holder = (
        WorkspaceMembership.objects.for_workspace(actor.workspace)
        .filter(user_id=device.installation.user_id)
        .first()
    )
    return device, holder


def _may_act_on(actor: WorkspaceMembership, device, holder) -> bool:
    """Own devices always; others only with devices.manage and a higher rank."""
    if device is None or holder is None:
        return False
    if holder.pk == actor.pk:
        return True
    return has_capability(actor, Capability.DEVICES_MANAGE) and outranks(actor, holder)


def _revoke(device: WorkspaceDevice, *, by, reason: str, workspace) -> None:
    device.status = WorkspaceDeviceStatus.REVOKED
    device.revoked_at = timezone.now()
    device.revoked_by = by
    device.revocation_reason = reason
    device.save(
        update_fields=["status", "revoked_at", "revoked_by", "revocation_reason", "updated_at"]
    )
    record_event(
        action="device.revoked",
        target=device,
        actor=by,
        workspace=workspace,
        metadata={"reason": reason},
    )


@transaction.atomic
def revoke_workspace_device(*, actor: WorkspaceMembership, device_id) -> WorkspaceDevice:
    """Close the workspace to one installation. Idempotent.

    Members revoke their own devices. Holders of ``devices.manage`` revoke
    devices of members ranked below them, so a manager cannot lock out the
    owner or another manager. A device the actor may not touch is reported as
    not found.
    """
    actor = authorize_actor(actor, Capability.DEVICES_USE)
    device, holder = _lock_device_and_holder(actor, device_id)
    if not _may_act_on(actor, device, holder):
        raise NotFoundError("Device not found in this workspace.")
    if device.status == WorkspaceDeviceStatus.ACTIVE:
        _revoke(
            device, by=actor.user, reason=DeviceRevocationReason.MANUAL, workspace=actor.workspace
        )
    return device


@transaction.atomic
def reauthorize_workspace_device(*, actor: WorkspaceMembership, device_id) -> WorkspaceDevice:
    """Lift a revocation, explicitly. Idempotent for an active device.

    The only way a revoked browser regains access to a workspace, including
    after the member was reinstated. Requires ``devices.manage`` and a higher
    rank than the device's holder; the owner may also re-authorise their own.
    The holder must be an active member and the installation still active.
    """
    actor = authorize_actor(actor, Capability.DEVICES_MANAGE)
    device, holder = _lock_device_and_holder(actor, device_id)
    own_as_owner = holder is not None and holder.pk == actor.pk and actor.is_owner
    if device is None or not (own_as_owner or (holder is not None and outranks(actor, holder))):
        raise NotFoundError("Device not found in this workspace.")
    if device.status == WorkspaceDeviceStatus.ACTIVE:
        return device
    if holder.status != MembershipStatus.ACTIVE:
        raise NotPermittedError(
            "Reinstate the member before re-authorising their device.",
            code="member_not_active",
        )
    if not device.installation.is_active:
        raise NotPermittedError(
            "This browser was signed out everywhere by its owner and cannot be re-authorised.",
            code="installation_revoked",
        )
    previous_reason = device.revocation_reason
    device.status = WorkspaceDeviceStatus.ACTIVE
    device.revoked_at = None
    device.revoked_by = None
    device.revocation_reason = None
    device.save(
        update_fields=["status", "revoked_at", "revoked_by", "revocation_reason", "updated_at"]
    )
    record_event(
        action="device.reauthorized",
        target=device,
        actor=actor.user,
        workspace=actor.workspace,
        metadata={"previous_reason": previous_reason},
    )
    return device


def revoke_devices_of_removed_member(*, membership: WorkspaceMembership, by) -> int:
    """Revoke every active device of a member being removed. Call inside the
    removal transaction, with the membership row already locked."""
    devices = (
        WorkspaceDevice.objects.for_workspace(membership.workspace)
        .select_for_update()
        .filter(installation__user_id=membership.user_id, status=WorkspaceDeviceStatus.ACTIVE)
    )
    count = 0
    for device in devices:
        _revoke(
            device,
            by=by,
            reason=DeviceRevocationReason.MEMBERSHIP_REMOVED,
            workspace=membership.workspace,
        )
        count += 1
    return count


def touch_workspace_device(device: WorkspaceDevice) -> None:
    WorkspaceDevice.objects.filter(pk=device.pk).update(last_seen_at=timezone.now())
```


Rules as implemented:

- **Revoke:** an actor may revoke their own device. Revoking anyone else's
  needs `devices.manage` and a strictly higher rank than the holder. Anything
  else is answered as *not found*.
- **Re-authorise:** needs `devices.manage` (checked by `authorize_actor`) and a
  higher rank, or the owner acting on their own device. The holder must be an
  active member and the installation still active. Re-authorising an active
  device is a no-op.
- **Removal:** `revoke_devices_of_removed_member` revokes every active device
  of that user in that workspace, with reason `membership_removed`, in the
  caller's transaction.
- **First entry vs removal race:** `_authorize_on_first_entry` takes
  `FOR NO KEY UPDATE` on the membership. A removal holds `FOR UPDATE` on the
  same row, so first entry waits for the removal, then sees `removed` and
  refuses.

*Reviewer notes:*

- `_lock_device_and_holder` locks the device row but **not** the holder's
  membership row. A concurrent role change of the holder (for example an
  attendant being promoted while a manager revokes their device) is not
  serialised with the revocation, and no test covers it.
- Device revocation on removal is enforced in the service layer only, not by
  the database. A membership set to `removed` by raw SQL would not revoke
  devices. The admin can no longer edit memberships (section 3.3).

### 4.4 Membership removal transaction and actor locking

**`backend/apps/workspaces/services.py`, lines 50–73** — `authorize_actor`

```python
def authorize_actor(actor: WorkspaceMembership, capability: Capability) -> WorkspaceMembership:
    """Re-read and lock the acting membership, then check it may do this.

    Must be called inside a transaction. The lock is held until commit, so the
    actor cannot be demoted, suspended or removed while the operation runs.
    Returns the fresh row; callers must use it instead of the one passed in.
    """
    if not transaction.get_connection().in_atomic_block:
        raise RuntimeError("authorize_actor must be called inside transaction.atomic().")
    fresh = (
        WorkspaceMembership.objects.select_for_update(of=("self",))
        .select_related("workspace", "user")
        .filter(pk=actor.pk)
        .first()
    )
    if (
        fresh is None
        or fresh.status != MembershipStatus.ACTIVE
        or fresh.workspace.status != WorkspaceStatus.ACTIVE
        or not fresh.user.is_active
    ):
        raise NotPermittedError("You no longer have access to this workspace.")
    require_capability(fresh, capability)
    return fresh
```

**`backend/apps/workspaces/services.py`, lines 76–85** — `_lock_target`

```python
def _lock_target(actor: WorkspaceMembership, membership_id) -> WorkspaceMembership:
    """Lock a membership for update, scoped to the (already authorised) actor's workspace."""
    try:
        return (
            WorkspaceMembership.objects.for_workspace(actor.workspace)
            .select_for_update(of=("self",))
            .get(pk=membership_id)
        )
    except WorkspaceMembership.DoesNotExist as exc:
        raise DomainError("Member not found in this workspace.", code="member_not_found") from exc
```

**`backend/apps/workspaces/services.py`, lines 139–169** — `set_member_status`

```python
@transaction.atomic
def set_member_status(
    *, actor: WorkspaceMembership, membership_id, status: str
) -> WorkspaceMembership:
    actor = authorize_actor(actor, Capability.MEMBERS_MANAGE)
    membership = _lock_target(actor, membership_id)
    if status not in MembershipStatus.values:
        raise DomainError("Unknown status.", code="invalid_status")
    if membership.is_owner:
        raise DomainError(
            "The owner cannot be suspended or removed. Transfer ownership first.",
            code="owner_status_locked",
        )
    if membership.status != status:
        previous = membership.status
        membership.status = status
        membership.save(update_fields=["status", "updated_at"])
        record_event(
            action="membership.status_changed",
            target=membership,
            actor=actor.user,
            workspace=actor.workspace,
            metadata={"from": previous, "to": status},
        )
        if status == MembershipStatus.REMOVED:
            # Removal ends this member's device authorisations. Reinstatement
            # does not restore them: see device_services.reauthorize_workspace_device.
            from .device_services import revoke_devices_of_removed_member

            revoke_devices_of_removed_member(membership=membership, by=actor.user)
    return membership
```


### 4.5 Endpoints and access guard

**`backend/apps/devices/views.py`, lines 28–38** — `DeviceRevokeView`

```python
class DeviceRevokeView(WorkspaceAPIView):
    # Any member may call this; the service decides whether the device is
    # their own or whether they manage devices.
    required_capability = Capability.DEVICES_USE

    @extend_schema(request=None, responses=WorkspaceDeviceSerializer)
    def post(self, request: Request, workspace_id, device_id) -> Response:
        device = device_services.revoke_workspace_device(
            actor=request.membership, device_id=device_id
        )
        return Response(WorkspaceDeviceSerializer(device, context={"request": request}).data)
```

**`backend/apps/devices/views.py`, lines 41–51** — `DeviceReauthorizeView`

```python
class DeviceReauthorizeView(WorkspaceAPIView):
    """Lift a revocation. Rank rules are enforced by the service."""

    required_capability = Capability.DEVICES_MANAGE

    @extend_schema(request=None, responses=WorkspaceDeviceSerializer)
    def post(self, request: Request, workspace_id, device_id) -> Response:
        device = device_services.reauthorize_workspace_device(
            actor=request.membership, device_id=device_id
        )
        return Response(WorkspaceDeviceSerializer(device, context={"request": request}).data)
```

**`backend/apps/devices/urls.py`, lines 1–17** — complete file

```python
from django.urls import path

from . import views

# Included under /workspaces/<workspace_id>/ by apps.workspaces.urls.
urlpatterns = [
    path("devices/", views.DeviceListView.as_view(), name="device-list"),
    path(
        "devices/<uuid:device_id>/revoke/", views.DeviceRevokeView.as_view(), name="device-revoke"
    ),
    path(
        "devices/<uuid:device_id>/reauthorize/",
        views.DeviceReauthorizeView.as_view(),
        name="device-reauthorize",
    ),
    path("sync/handshake/", views.SyncHandshakeView.as_view(), name="sync-handshake"),
]
```

**`backend/apps/workspaces/access.py`, lines 30–52** — `WorkspaceAccess`

```python
class WorkspaceAccess(BasePermission):
    """Membership, device authorisation and capability, in that order."""

    def has_permission(self, request, view) -> bool:
        # A missing workspace and one the user does not belong to are
        # indistinguishable (404), so identifiers cannot be probed.
        membership = find_active_membership(request.user, view.kwargs["workspace_id"])
        if membership is None:
            raise NotFound("Workspace not found.")
        if membership.workspace.status != WorkspaceStatus.ACTIVE:
            raise PermissionDenied("This workspace is not active.", code="workspace_inactive")
        if not isinstance(request.auth, DeviceInstallation):
            # Only the device-bound session authenticator may reach workspaces.
            raise PermissionDenied("A device-bound session is required.")
        # Raises NotPermittedError (403 device_not_authorized) if revoked.
        request.workspace_device = ensure_workspace_device(
            installation=request.auth, membership=membership
        )
        request.membership = membership
        request.workspace = membership.workspace
        if request.method == "OPTIONS":
            return True
        return has_capability(membership, required_capability_for(view, request.method))
```

**`backend/tests/isolation.py`, lines 24–32** — re-authorise endpoint registered for the isolation contract

```python
WORKSPACE_ENDPOINTS = [
    Endpoint(_BASE, "get"),
    Endpoint(_BASE + "members/", "get"),
    Endpoint(_BASE + "members/<uuid:membership_id>/", "patch", {"role": "attendant"}),
    Endpoint(_BASE + "devices/", "get"),
    Endpoint(_BASE + "devices/<uuid:device_id>/revoke/", "post"),
    Endpoint(_BASE + "devices/<uuid:device_id>/reauthorize/", "post"),
    Endpoint(_BASE + "sync/handshake/", "post"),
]
```


Audit events written: `device.authorized` (first entry), `device.revoked` with
`metadata.reason` (`manual` or `membership_removed`), `device.reauthorized`
with `metadata.previous_reason`, and `membership.status_changed`.

### 4.6 Locking test (verbatim)

**`backend/tests/test_device_lifecycle.py`, lines 211–241** — `test_first_entry_cannot_slip_in_while_the_member_is_being_removed`

```python
@pytest.mark.django_db(transaction=True)
def test_first_entry_cannot_slip_in_while_the_member_is_being_removed(shop):
    installation = sign_in(APIClient(), shop.affiliate.user)
    membership = WorkspaceMembership.objects.select_related("workspace", "user").get(
        pk=shop.affiliate.pk
    )
    outcome = {}

    def first_entry():
        try:
            device_services.ensure_workspace_device(
                installation=installation, membership=membership
            )
            outcome["result"] = "authorized"
        except NotFoundError:
            outcome["result"] = "refused"
        finally:
            connection.close()

    worker = threading.Thread(target=first_entry)
    with transaction.atomic():
        services.set_member_status(
            actor=shop.owner, membership_id=shop.affiliate.id, status="removed"
        )
        worker.start()
        worker.join(timeout=1.0)
        assert worker.is_alive(), "first entry should wait for the removal to finish"
    worker.join(timeout=10)

    assert outcome == {"result": "refused"}
    assert not WorkspaceDevice.objects.filter(installation=installation).exists()
```

**`backend/tests/test_device_lifecycle.py`, lines 149–159** — `test_reinstatement_does_not_restore_device_access`

```python
def test_reinstatement_does_not_restore_device_access(shop):
    member = enter(shop, shop.affiliate)
    services.set_member_status(actor=shop.owner, membership_id=shop.affiliate.id, status="removed")
    services.set_member_status(actor=shop.owner, membership_id=shop.affiliate.id, status="active")

    response = member.get(ws(shop))
    assert response.status_code == 403
    assert response.json()["code"] == "device_not_authorized"
    member.device.refresh_from_db()
    assert member.device.status == "revoked"
    assert WorkspaceDevice.objects.filter(installation=member.installation).count() == 1
```

**`backend/tests/test_device_lifecycle.py`, lines 45–53** — `test_manager_cannot_revoke_the_owners_device`

```python
def test_manager_cannot_revoke_the_owners_device(shop):
    """Assessment probe S4: a manager locked the owner's browser out."""
    owner = enter(shop, shop.owner)
    manager = enter(shop, shop.manager)
    response = revoke(manager, shop, owner.device)
    assert response.status_code == 404
    owner.device.refresh_from_db()
    assert owner.device.status == "active"
    assert owner.get(ws(shop)).status_code == 200
```


---

## 5. Audit immutability (F-07)

### 5.1 Model and writer

**`backend/apps/audit/models.py`, lines 1–47** — complete file

```python
from django.conf import settings
from django.db import models

from apps.common.models import UUIDModel


class AuditEvent(UUIDModel):
    """Append-only record of who did what to which record, and when."""

    workspace = models.ForeignKey(
        "workspaces.Workspace",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="audit_events",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="audit_events",
        help_text="Empty for actions performed by the system itself.",
    )
    action = models.CharField(max_length=64)
    target_type = models.CharField(max_length=64)
    target_id = models.UUIDField()
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["workspace", "-created_at"], name="audit_ws_created_idx"),
            models.Index(fields=["target_type", "target_id"], name="audit_target_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.action} {self.target_type}:{self.target_id}"

    def save(self, *args, **kwargs) -> None:
        if not self._state.adding:
            raise TypeError("Audit events are immutable.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise TypeError("Audit events cannot be deleted.")
```

**`backend/apps/audit/services.py`, lines 8–25** — `record_event`

```python
def record_event(
    *,
    action: str,
    target: models.Model,
    actor=None,
    workspace=None,
    metadata: dict[str, Any] | None = None,
) -> AuditEvent:
    """Record an audit event. Call inside the transaction of the change itself
    so the event and the change commit or roll back together."""
    return AuditEvent.objects.create(
        workspace=workspace,
        actor=actor,
        action=action,
        target_type=target._meta.label_lower,
        target_id=target.pk,
        metadata=metadata or {},
    )
```


### 5.2 Trigger migration (complete)

**`backend/apps/audit/migrations/0002_append_only_triggers.py`, lines 1–44** — complete file

```python
"""Make the audit table append-only in PostgreSQL itself.

Row triggers reject UPDATE and DELETE (including Django bulk operations and
raw SQL); a statement trigger rejects TRUNCATE, which also covers truncation
cascading from other tables. Only the table's owner can disable them (see
apps/audit/maintenance.py), so a deployment where the application connects
with a role that does not own the tables cannot alter the audit trail.
"""

from django.db import migrations

FORWARD = """
CREATE FUNCTION audit_auditevent_append_only() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'audit events are append-only (% refused)', TG_OP
        USING ERRCODE = 'restrict_violation';
END;
$$;

CREATE TRIGGER audit_auditevent_no_update_or_delete
    BEFORE UPDATE OR DELETE ON audit_auditevent
    FOR EACH ROW EXECUTE FUNCTION audit_auditevent_append_only();

CREATE TRIGGER audit_auditevent_no_truncate
    BEFORE TRUNCATE ON audit_auditevent
    FOR EACH STATEMENT EXECUTE FUNCTION audit_auditevent_append_only();
"""

REVERSE = """
DROP TRIGGER IF EXISTS audit_auditevent_no_truncate ON audit_auditevent;
DROP TRIGGER IF EXISTS audit_auditevent_no_update_or_delete ON audit_auditevent;
DROP FUNCTION IF EXISTS audit_auditevent_append_only();
"""


class Migration(migrations.Migration):
    dependencies = [
        ("audit", "0001_initial"),
        # 0003 rewrites legacy audit targets; it must run before rows are frozen.
        ("workspaces", "0004_device_revocation_reason"),
    ]

    operations = [migrations.RunSQL(FORWARD, REVERSE)]
```


### 5.3 Maintenance helper and its only users

**`backend/apps/audit/maintenance.py`, lines 1–37** — complete file

```python
"""Suspending audit protection. For wiping throwaway databases only.

The append-only triggers can only be disabled by the owner of the audit
table. Test teardown (which truncates every table) and the browser-test seed
script use this; application code must not. In production the application
should connect with a role that does not own the tables, which makes this
function fail with a permission error, as intended.
"""

from collections.abc import Iterator
from contextlib import contextmanager

from django.db import connections

_TRIGGERS = ("audit_auditevent_no_update_or_delete", "audit_auditevent_no_truncate")


def _set(connection, enabled: bool) -> None:
    verb = "ENABLE" if enabled else "DISABLE"
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT 1 FROM pg_trigger WHERE tgname = %s AND NOT tgisinternal", [_TRIGGERS[0]]
        )
        if cursor.fetchone() is None:
            return  # migrations not applied yet: nothing to suspend
        for name in _TRIGGERS:
            cursor.execute(f"ALTER TABLE audit_auditevent {verb} TRIGGER {name}")  # noqa: S608


@contextmanager
def audit_protection_suspended(using: str = "default") -> Iterator[None]:
    connection = connections[using]
    _set(connection, enabled=False)
    try:
        yield
    finally:
        _set(connection, enabled=True)
```

**`backend/tests/conftest.py`, lines 15–33** — test-only: wraps Django's `flush` used at the end of transactional tests

```python
def _flush_with_audit_protection_suspended():
    """Transactional tests end with ``flush`` (TRUNCATE of every table), which
    the audit table's append-only triggers refuse. The test database role owns
    the tables, so it may suspend them for that one statement, exactly like
    ``scripts/e2e_seed.py`` does."""
    from django.core.management.commands import flush

    from apps.audit.maintenance import audit_protection_suspended

    original = flush.Command.handle
    if getattr(original, "_suspends_audit", False):
        return

    def handle(self, **options):
        with audit_protection_suspended(options.get("database", "default")):
            return original(self, **options)

    handle._suspends_audit = True
    flush.Command.handle = handle
```

**`backend/scripts/e2e_seed.py`, lines 76–84** — browser-test seed (refuses databases not named `*_e2e`)

```python
if __name__ == "__main__":
    ensure_database(settings.DATABASES["default"])
    call_command("migrate", interactive=False, verbosity=0)
    from apps.audit.maintenance import audit_protection_suspended

    with audit_protection_suspended():  # throwaway database: audit rows may go
        call_command("flush", interactive=False, verbosity=0)
    seed()
    print(f"Seeded {settings.DATABASES['default']['NAME']}")  # noqa: T201
```


**What the triggers prevent.** The row trigger refuses every `UPDATE` and
`DELETE` on `audit_auditevent`, whoever issues it: ORM instances, bulk
`QuerySet.update()` and `.delete()`, raw SQL, and the admin. The statement
trigger refuses `TRUNCATE audit_auditevent`, and also `TRUNCATE` of another
table that cascades into it. Errors use SQLSTATE `restrict_violation`, so
Django raises `IntegrityError`.

**What the table owner can still do.** `ALTER TABLE … DISABLE TRIGGER`,
`DROP TRIGGER`, `DROP FUNCTION`, and anything else ownership permits.
Superusers can additionally bypass triggers with
`session_replication_role = replica`.

The protection therefore holds against the running application only if the
application connects with a role that does **not** own the table.
`docs/DEPLOYMENT.md` requires that split. In this repository's development
setup and in CI, a single role owns the tables and runs the application, so
there the protection covers every code path but not a person issuing SQL as
that role.

*Reviewer notes:*

- Append-only is not authenticity. The application can still **insert**
  arbitrary events. There is no hash chain or signature.
- The test teardown patch (`conftest.py`) and the e2e seed suspend the
  triggers globally for the duration of a `flush`, on throwaway databases.

### 5.4 Tests (verbatim): bulk, raw SQL, TRUNCATE, non-owner role

**`backend/tests/test_audit_integrity.py`, lines 19–24** — `settle_deferred_checks`

```python
def settle_deferred_checks():
    """Rows created in this test's transaction leave deferred foreign-key checks
    pending, and PostgreSQL refuses TRUNCATE and ALTER TABLE behind them."""
    with connection.cursor() as cursor:
        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
        cursor.execute("SET CONSTRAINTS ALL DEFERRED")
```

**`backend/tests/test_audit_integrity.py`, lines 27–30** — `refused`

```python
def refused(statement):
    settle_deferred_checks()
    with pytest.raises(IntegrityError, match="append-only"), transaction.atomic():
        statement()
```

**`backend/tests/test_audit_integrity.py`, lines 50–53** — `test_bulk_update_is_refused`

```python
def test_bulk_update_is_refused(events):
    """Assessment probe S8: every row was rewritten through a queryset."""
    refused(lambda: AuditEvent.objects.update(action="tampered"))
    assert not AuditEvent.objects.filter(action="tampered").exists()
```

**`backend/tests/test_audit_integrity.py`, lines 56–59** — `test_bulk_delete_is_refused`

```python
def test_bulk_delete_is_refused(events):
    count = events.count()
    refused(lambda: AuditEvent.objects.all().delete())
    assert AuditEvent.objects.count() == count
```

**`backend/tests/test_audit_integrity.py`, lines 62–67** — `test_raw_sql_update_delete_and_truncate_are_refused`

```python
def test_raw_sql_update_delete_and_truncate_are_refused(events):
    count = events.count()
    refused(sql("UPDATE audit_auditevent SET action = 'tampered'"))
    refused(sql("DELETE FROM audit_auditevent"))
    refused(sql("TRUNCATE audit_auditevent"))
    assert AuditEvent.objects.count() == count
```

**`backend/tests/test_audit_integrity.py`, lines 70–74** — `test_truncation_cascading_from_another_table_is_refused`

```python
def test_truncation_cascading_from_another_table_is_refused(events):
    count = events.count()
    refused(sql("TRUNCATE accounts_user CASCADE"))
    refused(sql("TRUNCATE workspaces_workspace CASCADE"))
    assert AuditEvent.objects.count() == count
```

**`backend/tests/test_audit_integrity.py`, lines 104–133** — `test_suspension_requires_owning_the_table`

```python
def test_suspension_requires_owning_the_table(events):
    """A role that does not own the table (as in production) cannot suspend it."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT rolcreaterole OR rolsuper FROM pg_roles WHERE rolname = current_user"
        )
        (can_create_roles,) = cursor.fetchone()
    if not can_create_roles:
        pytest.skip("the test database role may not create roles")
    settle_deferred_checks()
    grant = "GRANT SELECT, INSERT, UPDATE, DELETE ON audit_auditevent TO mf_app_probe"
    with connection.cursor() as cursor:
        cursor.execute("CREATE ROLE mf_app_probe NOLOGIN")
        # PostgreSQL 16: a CREATEROLE (non-superuser) creator must grant itself SET.
        cursor.execute("GRANT mf_app_probe TO CURRENT_USER WITH INHERIT FALSE, SET TRUE")
        cursor.execute(grant)
        cursor.execute("SET LOCAL ROLE mf_app_probe")
    with (
        pytest.raises(Exception, match="must be owner"),
        transaction.atomic(),
        audit_protection_suspended(),
    ):
        pass
    with connection.cursor() as cursor:
        cursor.execute("RESET ROLE")
        # As that role, the append-only rule still holds too.
        cursor.execute("SET LOCAL ROLE mf_app_probe")
    refused(sql("DELETE FROM audit_auditevent"))
    with connection.cursor() as cursor:
        cursor.execute("RESET ROLE")
```


`test_suspension_requires_owning_the_table` skips unless the database role is
a superuser or has `CREATEROLE`. In CI the PostgreSQL service user is a
superuser, and the CI log lists no skip for it, so it ran there. It creates a
`NOLOGIN` role with only DML grants, switches to it with `SET LOCAL ROLE`, and
shows two things: `ALTER TABLE … DISABLE TRIGGER` fails with *must be owner*,
and `DELETE` is still refused.

---

## 6. Owner integrity (F-10, F-11)

### 6.1 Pre-existing constraints (Milestone 1, unchanged)

**`backend/apps/workspaces/models.py`, lines 70–116** — membership model and its immediate constraints

```python
class WorkspaceMembership(UUIDModel, TimestampedModel):
    """A user's role inside one workspace.

    Workspace ownership has a single source of truth: the membership whose
    role is ``owner``. There is no separate ``Workspace.owner`` column that
    could drift out of step with it.
    """

    workspace = models.ForeignKey(Workspace, on_delete=models.PROTECT, related_name="memberships")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="memberships"
    )
    role = models.CharField(max_length=16, choices=MembershipRole.choices)
    status = models.CharField(
        max_length=16, choices=MembershipStatus.choices, default=MembershipStatus.ACTIVE
    )

    objects = WorkspaceScopedQuerySet.as_manager()

    class Meta:
        ordering = ["created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "user"], name="membership_one_per_user_per_workspace"
            ),
            # At most one owner per workspace ...
            models.UniqueConstraint(
                fields=["workspace"],
                condition=Q(role="owner"),
                name="membership_single_owner_per_workspace",
            ),
            # ... and that owner can never be suspended or removed. Ownership
            # must be transferred first (see services.transfer_ownership).
            models.CheckConstraint(
                condition=~Q(role="owner") | Q(status="active"),
                name="membership_owner_must_be_active",
            ),
            models.CheckConstraint(
                condition=Q(role__in=MembershipRole.values), name="membership_role_valid"
            ),
            models.CheckConstraint(
                condition=Q(status__in=MembershipStatus.values), name="membership_status_valid"
            ),
        ]
        indexes = [
            models.Index(fields=["user", "status"], name="membership_user_status_idx"),
        ]
```


### 6.2 Ownership triggers (complete migration)

**`backend/apps/workspaces/migrations/0005_owner_integrity.py`, lines 1–112** — complete file

```python
"""Ownership integrity enforced by PostgreSQL.

1. At commit, every workspace has exactly one active owner membership, and
   unless the workspace is archived, that owner's account is active. The
   check is a deferred constraint trigger, so an ownership transfer (demote,
   then promote, in one transaction) passes while any committed state without
   an owner is refused, whichever code path produced it.
2. An account that owns a non-archived workspace cannot be deactivated.
"""

from django.db import migrations

FORWARD = """
CREATE FUNCTION workspaces_assert_single_active_owner(ws uuid) RETURNS void
LANGUAGE plpgsql AS $$
DECLARE
    ws_status text;
    owners integer;
    inactive_owner_accounts integer;
BEGIN
    SELECT status INTO ws_status FROM workspaces_workspace WHERE id = ws;
    IF NOT FOUND THEN
        RETURN;
    END IF;
    SELECT count(*),
           count(*) FILTER (WHERE NOT u.is_active)
      INTO owners, inactive_owner_accounts
      FROM workspaces_workspacemembership m
      JOIN accounts_user u ON u.id = m.user_id
     WHERE m.workspace_id = ws AND m.role = 'owner' AND m.status = 'active';
    IF owners <> 1 THEN
        RAISE EXCEPTION 'workspace % must have exactly one active owner (found %)', ws, owners
            USING ERRCODE = 'check_violation';
    END IF;
    IF ws_status <> 'archived' AND inactive_owner_accounts > 0 THEN
        RAISE EXCEPTION 'the owner of workspace % must have an active account', ws
            USING ERRCODE = 'check_violation';
    END IF;
END;
$$;

CREATE FUNCTION workspaces_membership_owner_check() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP IN ('UPDATE', 'DELETE') THEN
        PERFORM workspaces_assert_single_active_owner(OLD.workspace_id);
    END IF;
    IF TG_OP IN ('INSERT', 'UPDATE') AND (TG_OP = 'INSERT' OR NEW.workspace_id <> OLD.workspace_id) THEN
        PERFORM workspaces_assert_single_active_owner(NEW.workspace_id);
    END IF;
    RETURN NULL;
END;
$$;

CREATE FUNCTION workspaces_workspace_owner_check() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    PERFORM workspaces_assert_single_active_owner(NEW.id);
    RETURN NULL;
END;
$$;

CREATE CONSTRAINT TRIGGER workspaces_membership_keeps_one_owner
    AFTER INSERT OR UPDATE OR DELETE ON workspaces_workspacemembership
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION workspaces_membership_owner_check();

CREATE CONSTRAINT TRIGGER workspaces_workspace_has_owner
    AFTER INSERT OR UPDATE OF status ON workspaces_workspace
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION workspaces_workspace_owner_check();

CREATE FUNCTION accounts_user_owner_stays_active() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF EXISTS (
        SELECT 1
          FROM workspaces_workspacemembership m
          JOIN workspaces_workspace w ON w.id = m.workspace_id
         WHERE m.user_id = NEW.id AND m.role = 'owner' AND w.status <> 'archived'
    ) THEN
        RAISE EXCEPTION 'account % owns a workspace and cannot be deactivated', NEW.id
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER accounts_user_owner_stays_active
    BEFORE UPDATE OF is_active ON accounts_user
    FOR EACH ROW WHEN (OLD.is_active AND NOT NEW.is_active)
    EXECUTE FUNCTION accounts_user_owner_stays_active();
"""

REVERSE = """
DROP TRIGGER IF EXISTS accounts_user_owner_stays_active ON accounts_user;
DROP FUNCTION IF EXISTS accounts_user_owner_stays_active();
DROP TRIGGER IF EXISTS workspaces_workspace_has_owner ON workspaces_workspace;
DROP TRIGGER IF EXISTS workspaces_membership_keeps_one_owner ON workspaces_workspacemembership;
DROP FUNCTION IF EXISTS workspaces_workspace_owner_check();
DROP FUNCTION IF EXISTS workspaces_membership_owner_check();
DROP FUNCTION IF EXISTS workspaces_assert_single_active_owner(uuid);
"""


class Migration(migrations.Migration):
    dependencies = [
        ("workspaces", "0004_device_revocation_reason"),
        ("accounts", "0003_login_attempt_buckets"),
    ]

    operations = [migrations.RunSQL(FORWARD, REVERSE)]
```


**How exactly one active owner is enforced at commit time.**

1. **Immediate constraints from Milestone 1**, checked per statement:
   - the partial unique index `membership_single_owner_per_workspace` allows
     at most one `owner` row per workspace;
   - the check `membership_owner_must_be_active` requires an owner row to be
     `active`.
2. **`workspaces_membership_keeps_one_owner`**, a deferred constraint trigger
   on every INSERT, UPDATE and DELETE of a membership. At commit it calls
   `workspaces_assert_single_active_owner` for the old and new workspace of
   each changed row, which requires **exactly one** active owner row. It also
   requires that owner's account to be active, unless the workspace is
   `archived`.
3. **`workspaces_workspace_has_owner`**, a deferred trigger on INSERT of a
   workspace and on UPDATE of its `status`. A workspace inserted without an
   owner, or un-archived while its owner's account is inactive, fails at
   commit.
4. **`accounts_user_owner_stays_active`**, an immediate BEFORE UPDATE trigger,
   refuses setting `is_active = false` on an account that owns a non-archived
   workspace.

Because the checks run at commit, a transfer (demote, then promote, in one
transaction) passes. Any committed state with zero owners, or with an
inactive owner account, fails with `check_violation`. `SET CONSTRAINTS`
changes *when* the check runs, never *whether*. Only the table owner (by
disabling or dropping the triggers) or a superuser (replica mode) can skip it.

### 6.3 Services and locking

**`backend/apps/workspaces/services.py`, lines 172–210** — `transfer_ownership`

```python
@transaction.atomic
def transfer_ownership(*, actor: WorkspaceMembership, new_owner_id) -> WorkspaceMembership:
    """Make another active member the owner; the previous owner becomes a manager."""
    # Lock the workspace row first so concurrent transfers serialise.
    Workspace.objects.select_for_update().get(pk=actor.workspace_id)
    current = authorize_actor(actor, Capability.MEMBERS_MANAGE)
    if not current.is_owner:
        raise NotPermittedError("Only the owner can transfer ownership.", code="not_owner")
    successor = (
        WorkspaceMembership.objects.for_workspace(current.workspace)
        .select_for_update(of=("self",))
        .select_related("user")
        .filter(pk=new_owner_id)
        .first()
    )
    if successor is None:
        raise DomainError("Member not found in this workspace.", code="member_not_found")
    # Lock the successor's account too, so a concurrent deactivation of that
    # account either finishes first (and is seen here) or waits and then sees
    # the new ownership (and is refused): accounts.services.deactivate_user.
    successor_user = User.objects.select_for_update().get(pk=successor.user_id)
    if successor.pk == current.pk:
        raise ConflictError("This member already owns the workspace.", code="already_owner")
    if successor.status != MembershipStatus.ACTIVE or not successor_user.is_active:
        raise DomainError("The new owner must be an active member.", code="successor_inactive")

    # Demote before promoting: the single-owner constraint is checked per statement.
    current.role = MembershipRole.MANAGER
    current.save(update_fields=["role", "updated_at"])
    successor.role = MembershipRole.OWNER
    successor.save(update_fields=["role", "updated_at"])
    record_event(
        action="workspace.ownership_transferred",
        target=successor,
        actor=current.user,
        workspace=current.workspace,
        metadata={"previous_owner_membership": str(current.pk)},
    )
    return successor
```

**`backend/apps/accounts/services.py`, lines 41–61** — `deactivate_user`

```python
@transaction.atomic
def deactivate_user(*, user_id, by: User | None, reason: str) -> User:
    """Suspend an account platform-wide. Its sessions stop working at once.

    Refused while the account owns a non-archived workspace: ownership must be
    transferred first, or the workspace would have an owner who cannot sign in.
    The database enforces the same rule. Idempotent.
    """
    user = User.objects.select_for_update().get(pk=user_id)
    if not user.is_active:
        return user
    owned = owned_workspace_names(user)
    if owned:
        raise DomainError(
            "This account owns " + ", ".join(owned) + ". Transfer ownership first.",
            code="owner_cannot_be_deactivated",
        )
    user.is_active = False
    user.save(update_fields=["is_active"])
    record_event(action="user.deactivated", target=user, actor=by, metadata={"reason": reason})
    return user
```


Lock order:

- **`transfer_ownership`:** workspace row `FOR UPDATE`, then the actor's
  membership (in `authorize_actor`), then the successor's membership, then
  the successor's **account** row.
- **`deactivate_user`:** the account row `FOR UPDATE`, then it reads the
  ownerships.

Whichever of the two takes the successor's account row first wins; the other
waits, then sees the committed result and is refused (`successor_inactive` or
`owner_cannot_be_deactivated`). Two tests hold one transaction open while the
other runs in a thread and assert exactly this.

### 6.4 Tests (verbatim)

**`backend/tests/test_owner_integrity.py`, lines 21–32** — `committed`

```python
def committed(change):
    """Run ``change`` and evaluate the deferred checks as a commit would."""
    try:
        with transaction.atomic():
            change()
            with connection.cursor() as cursor:
                cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
    finally:
        # Outside the (possibly rolled-back) savepoint: the test's transaction
        # continues, so restore commit-time checking for what follows.
        with connection.cursor() as cursor:
            cursor.execute("SET CONSTRAINTS ALL DEFERRED")
```

**`backend/tests/test_owner_integrity.py`, lines 43–47** — `test_owner_cannot_be_demoted_below_the_services`

```python
def test_owner_cannot_be_demoted_below_the_services(shop):
    """Assessment probe S6 reached this state through the admin."""
    refused(lambda: WorkspaceMembership.objects.filter(pk=shop.owner.pk).update(role="manager"))
    shop.owner.refresh_from_db()
    assert shop.owner.role == "owner"
```

**`backend/tests/test_owner_integrity.py`, lines 84–91** — `test_checks_are_enforced_at_a_real_commit`

```python
@pytest.mark.django_db(transaction=True)
def test_checks_are_enforced_at_a_real_commit(shop):
    with pytest.raises(IntegrityError, match=OWNERLESS), transaction.atomic():
        WorkspaceMembership.objects.filter(pk=shop.owner.pk).update(role="manager")
    shop.owner.refresh_from_db()
    assert shop.owner.role == "owner"
    services.transfer_ownership(actor=shop.owner, new_owner_id=shop.manager.id)  # commits
    assert WorkspaceMembership.objects.get(workspace=shop.workspace, role="owner") == shop.manager
```

**`backend/tests/test_owner_integrity.py`, lines 97–101** — `test_owner_account_cannot_be_deactivated_below_the_services`

```python
def test_owner_account_cannot_be_deactivated_below_the_services(shop):
    """Assessment probe S11 orphaned the workspace this way."""
    with pytest.raises(IntegrityError, match="cannot be deactivated"), transaction.atomic():
        User.objects.filter(pk=shop.owner.user_id).update(is_active=False)
    assert User.objects.get(pk=shop.owner.user_id).is_active
```

**`backend/tests/test_owner_integrity.py`, lines 153–166** — `test_deactivation_waiting_on_a_transfer_is_refused`

```python
@pytest.mark.django_db(transaction=True)
def test_deactivation_waiting_on_a_transfer_is_refused(shop):
    outcome = {}
    worker = _in_thread(
        lambda: deactivate_user(user_id=shop.manager.user_id, by=None, reason="race"), outcome
    )
    with transaction.atomic():
        services.transfer_ownership(actor=shop.owner, new_owner_id=shop.manager.id)
        worker.start()
        worker.join(timeout=1.0)
        assert worker.is_alive(), "deactivation should wait for the transfer"
    worker.join(timeout=10)
    assert outcome == {"result": "owner_cannot_be_deactivated"}
    assert User.objects.get(pk=shop.manager.user_id).is_active
```

**`backend/tests/test_owner_integrity.py`, lines 169–184** — `test_transfer_waiting_on_a_deactivation_is_refused`

```python
@pytest.mark.django_db(transaction=True)
def test_transfer_waiting_on_a_deactivation_is_refused(shop):
    outcome = {}
    worker = _in_thread(
        lambda: services.transfer_ownership(actor=shop.owner, new_owner_id=shop.manager.id),
        outcome,
    )
    with transaction.atomic():
        deactivate_user(user_id=shop.manager.user_id, by=None, reason="race")
        worker.start()
        worker.join(timeout=1.0)
        assert worker.is_alive(), "the transfer should wait for the deactivation"
    worker.join(timeout=10)
    assert outcome == {"result": "successor_inactive"}
    owner = WorkspaceMembership.objects.get(workspace=shop.workspace, role="owner")
    assert owner.pk == shop.owner.pk
```


*Reviewer notes:*

- Most F-10 tests run inside pytest's rolled-back test transaction and force
  the deferred check with `SET CONSTRAINTS ALL IMMEDIATE`, which evaluates
  the same trigger code a commit would. `test_checks_are_enforced_at_a_real_commit`
  (committed transactions) confirms behaviour at a real `COMMIT`.
- Not tested: un-archiving a workspace whose owner's account is inactive;
  races between arbitrary raw-SQL writers (only the service-level races are
  tested); deletion of an owner's user row (relies on `PROTECT` foreign keys).

---

## 7. Production security (F-06)

### 7.1 Start-up validation (complete module)

**`backend/config/production_checks.py`, lines 1–71** — complete file

```python
"""Settings that must hold whenever DJANGO_DEBUG is false.

``settings.py`` calls ``production_problems`` and refuses to start if it
returns anything, so an unsafe production configuration fails at boot rather
than being discovered later. The function is pure so every rule is unit tested
(tests/test_production_settings.py).
"""

from dataclasses import dataclass

MIN_SECRET_KEY_LENGTH = 50
MIN_SECRET_KEY_UNIQUE_CHARACTERS = 5  # same thresholds as Django's security.W009
MIN_HSTS_SECONDS = 60 * 60 * 24 * 180


@dataclass(frozen=True)
class SecuritySettings:
    secret_key: str
    secure_cookies: bool
    allowed_hosts: list[str]
    csrf_trusted_origins: list[str]
    trusted_proxy_count: int
    trusted_proxy_count_is_explicit: bool
    ssl_redirect: bool
    hsts_seconds: int
    admin_enabled: bool
    admin_path: str


def production_problems(s: SecuritySettings) -> list[str]:
    problems = []
    if (
        s.secret_key.startswith(("insecure-", "django-insecure-"))
        or len(s.secret_key) < MIN_SECRET_KEY_LENGTH
        or len(set(s.secret_key)) < MIN_SECRET_KEY_UNIQUE_CHARACTERS
    ):
        problems.append(
            f"DJANGO_SECRET_KEY must be a random value of at least {MIN_SECRET_KEY_LENGTH} "
            "characters, not the development placeholder."
        )
    if not s.secure_cookies:
        problems.append("DJANGO_SECURE_COOKIES must be true: cookies would be sent over HTTP.")
    if not s.allowed_hosts or "*" in s.allowed_hosts:
        problems.append("DJANGO_ALLOWED_HOSTS must list the site's host names (no '*').")
    insecure_origins = [o for o in s.csrf_trusted_origins if not o.startswith("https://")]
    if insecure_origins:
        problems.append(
            "DJANGO_CSRF_TRUSTED_ORIGINS must all be https:// origins: "
            + ", ".join(insecure_origins)
        )
    if not s.trusted_proxy_count_is_explicit:
        problems.append(
            "DJANGO_TRUSTED_PROXY_COUNT must be set explicitly to the number of reverse "
            "proxies in front of Django."
        )
    elif s.trusted_proxy_count < 1:
        problems.append(
            "DJANGO_TRUSTED_PROXY_COUNT must be at least 1: TLS has to be terminated by a "
            "reverse proxy in front of Django."
        )
    if not s.ssl_redirect:
        problems.append("DJANGO_SECURE_SSL_REDIRECT must be true.")
    if s.hsts_seconds < MIN_HSTS_SECONDS:
        problems.append(f"DJANGO_HSTS_SECONDS must be at least {MIN_HSTS_SECONDS}.")
    if s.admin_enabled and s.admin_path.strip("/") == "admin":
        problems.append(
            "The Django admin is enabled at the default path. Disable it "
            "(DJANGO_ADMIN_ENABLED=false) or set a non-default DJANGO_ADMIN_PATH and restrict "
            "access to it at the reverse proxy."
        )
    return problems
```

**`backend/config/settings.py`, lines 180–206** — where settings.py calls it

```python
# --- Production safeguards ----------------------------------------------------
# Submitting the domain to the browsers' HSTS preload list is a one-way
# operational decision, so it is opt-in (DJANGO_HSTS_PRELOAD) rather than
# a deploy-check failure.
SILENCED_SYSTEM_CHECKS = ["security.W021"]

if not DEBUG:
    from config.production_checks import SecuritySettings, production_problems

    _problems = production_problems(
        SecuritySettings(
            secret_key=SECRET_KEY,
            secure_cookies=SECURE_COOKIES,
            allowed_hosts=ALLOWED_HOSTS,
            csrf_trusted_origins=CSRF_TRUSTED_ORIGINS,
            trusted_proxy_count=TRUSTED_PROXY_COUNT,
            trusted_proxy_count_is_explicit="DJANGO_TRUSTED_PROXY_COUNT" in env.ENVIRON,
            ssl_redirect=SECURE_SSL_REDIRECT,
            hsts_seconds=SECURE_HSTS_SECONDS,
            admin_enabled=ADMIN_ENABLED,
            admin_path=ADMIN_PATH,
        )
    )
    if _problems:
        raise ImproperlyConfigured(
            "Unsafe production settings (DJANGO_DEBUG is false):\n- " + "\n- ".join(_problems)
        )
```

**`backend/config/settings.py`, lines 15–20** — `.env` reading can be switched off

```python
env = environ.Env()
# A local .env file is a development convenience; real environment variables
# win. Deployments (and tests of production settings) set
# DJANGO_READ_DOT_ENV=false so a stray file cannot fill in missing values.
if env.bool("DJANGO_READ_DOT_ENV", default=True):
    environ.Env.read_env(BASE_DIR / ".env")
```


### 7.2 Cookies, CSRF, hosts, HTTPS, HSTS

**`backend/config/settings.py`, lines 25–25**

```python
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=[])
```

**`backend/config/settings.py`, lines 94–114**

```python
# --- Sessions, cookies and CSRF ------------------------------------------
# The browser authenticates with a server-side session referenced by an
# HttpOnly cookie. JavaScript can never read the session identifier; it only
# reads the CSRF token, which is useless without the session cookie.
SECURE_COOKIES = env.bool("DJANGO_SECURE_COOKIES", default=not DEBUG)
SESSION_ENGINE = "apps.accounts.session_store"  # sessions know their user and device
SESSION_COOKIE_NAME = "mf_session"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SECURE = SECURE_COOKIES
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_AGE = 60 * 60 * 24 * 14
# Identifies the browser installation across logins. An identifier, not a
# credential: it is only read at login, after the password has been verified.
DEVICE_COOKIE_NAME = "mf_device"
DEVICE_COOKIE_AGE = 60 * 60 * 24 * 400
CSRF_COOKIE_NAME = "mf_csrftoken"
CSRF_COOKIE_HTTPONLY = False  # the SPA echoes it in the X-CSRFToken header
CSRF_COOKIE_SECURE = SECURE_COOKIES
CSRF_COOKIE_SAMESITE = "Lax"
CSRF_TRUSTED_ORIGINS = env.list("DJANGO_CSRF_TRUSTED_ORIGINS", default=[])
CSRF_FAILURE_VIEW = "apps.common.views.csrf_failure"
```

**`backend/config/settings.py`, lines 116–126**

```python
# --- Transport security --------------------------------------------------
# On by default whenever DEBUG is off; production_checks refuses to turn them off.
SECURE_SSL_REDIRECT = env.bool("DJANGO_SECURE_SSL_REDIRECT", default=not DEBUG)
SECURE_HSTS_SECONDS = env.int("DJANGO_HSTS_SECONDS", default=0 if DEBUG else 60 * 60 * 24 * 365)
SECURE_HSTS_INCLUDE_SUBDOMAINS = env.bool("DJANGO_HSTS_INCLUDE_SUBDOMAINS", default=False)
SECURE_HSTS_PRELOAD = env.bool("DJANGO_HSTS_PRELOAD", default=False)
# Health checks come from the load balancer over plain HTTP inside the network.
SECURE_REDIRECT_EXEMPT = [r"^api/health/$"]
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"
```


### 7.3 Content-Security-Policy middleware

**`backend/apps/common/middleware.py`, lines 1–23** — complete file

```python
"""Security headers for API responses.

Django's SecurityMiddleware covers HSTS, nosniff, referrer and opener policy.
This adds a Content-Security-Policy to JSON API responses, which must never
render as a document. The SPA's own policy is set by the reverse proxy that
serves it (see docs/DEPLOYMENT.md); the admin and the API docs pages are left
alone because they load their own scripts and styles.
"""

API_POLICY = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"


class ApiSecurityHeadersMiddleware:
    def __init__(self, get_response) -> None:
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        path = request.path
        if path.startswith("/api/") and not path.startswith("/api/docs"):
            response.headers.setdefault("Content-Security-Policy", API_POLICY)
            response.headers.setdefault("Cache-Control", "no-store")
        return response
```

**`backend/config/settings.py`, lines 43–52**

```python
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "apps.common.middleware.ApiSecurityHeadersMiddleware",
]
```


### 7.4 Environment variables (names and committed example values only)

`backend/.env.production.example` is a committed reference with placeholder
values (no real secret):

**`backend/.env.production.example`, lines 1–33** — complete file

```bash
# Production settings reference. Copy into the deployment's secret store or
# environment; never commit real values. The application refuses to start with
# DJANGO_DEBUG=false unless every rule in config/production_checks.py holds.
# CI runs `manage.py check --deploy --fail-level WARNING` with these values.

DJANGO_DEBUG=false
# Never read a .env file in production.
DJANGO_READ_DOT_ENV=false
# 50+ random characters:
#   python -c "from django.core.management.utils import get_random_secret_key as k; print(k())"
DJANGO_SECRET_KEY=replace-with-a-real-secret-key-of-at-least-fifty-characters-0000
DJANGO_ALLOWED_HOSTS=app.merchantflow.example
DJANGO_CSRF_TRUSTED_ORIGINS=https://app.merchantflow.example

DATABASE_URL=postgres://merchantflow_app:CHANGE_ME@db.internal:5432/merchantflow

# Number of reverse proxies in front of Django that append X-Forwarded-For.
# The outermost proxy terminates TLS and must OVERWRITE (not append to) any
# X-Forwarded-For and X-Forwarded-Proto received from the internet.
DJANGO_TRUSTED_PROXY_COUNT=1

DJANGO_SECURE_COOKIES=true
DJANGO_SECURE_SSL_REDIRECT=true
DJANGO_HSTS_SECONDS=31536000
DJANGO_HSTS_INCLUDE_SUBDOMAINS=true
# DJANGO_HSTS_PRELOAD=true   # only after deciding to submit the domain to the preload list

# The admin is off by default. If it is needed, choose an unguessable path and
# restrict it at the proxy (internal network or VPN only).
DJANGO_ADMIN_ENABLED=false
# DJANGO_ADMIN_PATH=ops-<random>/

API_DOCS_ENABLED=false
```


### 7.5 CI deploy check

**`.github/workflows/ci.yml`, lines 43–47** — backend job step

```yaml
      - name: Production settings pass the deploy check
        run: |
          set -a; . ./.env.production.example; set +a
          DJANGO_SECRET_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(64))')" \
            python manage.py check --deploy --fail-level WARNING
```


In run 43941574998 this step printed `System check identified no issues (1
silenced).` The silenced check is `security.W021` (HSTS preload).

*Reviewer notes:*

- The rules are enforced only when `DJANGO_DEBUG=false`. A deployment that
  leaves debug on bypasses them, and debug-mode behaviour is then unsafe for
  other reasons as well.
- Not checked at start-up: `API_DOCS_ENABLED`, database TLS (`sslmode`) and
  `CSRF_TRUSTED_ORIGINS` being empty.
- Whether `DJANGO_TRUSTED_PROXY_COUNT` matches the real proxy chain cannot be
  checked by the application.
- The SPA's own CSP is the proxy's responsibility and is unverifiable here.

---

## 8. Deployment requirements

**`docs/DEPLOYMENT.md`, lines 1–70** — complete file

```markdown
# Deployment requirements

What a production deployment must provide. The application enforces what it
can at start-up (`backend/config/production_checks.py`); the rest is the
operator's responsibility and is listed here. There is no deployment
automation yet (assessment item O-01).

## Settings

Start from `backend/.env.production.example`. With `DJANGO_DEBUG=false` the
application refuses to start unless:

| Setting | Rule |
|---|---|
| `DJANGO_SECRET_KEY` | 50+ random characters, at least 5 distinct, not a placeholder |
| `DJANGO_SECURE_COOKIES` | `true` |
| `DJANGO_ALLOWED_HOSTS` | the real host names; no `*` |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | `https://` origins only |
| `DJANGO_TRUSTED_PROXY_COUNT` | set explicitly, at least 1 |
| `DJANGO_SECURE_SSL_REDIRECT` | `true` (default outside debug) |
| `DJANGO_HSTS_SECONDS` | at least 180 days (default one year outside debug) |
| `DJANGO_ADMIN_ENABLED` / `DJANGO_ADMIN_PATH` | admin off, or on at a non-default path |

Set `DJANGO_READ_DOT_ENV=false` so no `.env` file is ever read on a server.
CI runs `manage.py check --deploy --fail-level WARNING` with the example values.

## Reverse proxy

- One origin serves both the built SPA (`frontend/dist`) and `/api/` (and the
  admin path, if enabled). No CORS is configured or needed.
- The **outermost** proxy terminates TLS and must **overwrite** — not append
  to — `X-Forwarded-For` and `X-Forwarded-Proto` received from the internet.
  `DJANGO_TRUSTED_PROXY_COUNT` must equal the number of proxies that append
  to `X-Forwarded-For` before Django. Too high lets clients choose their own
  address (and defeat the sign-in limits); too low makes every client look
  like the proxy (and share one address limit).
- Serve the SPA with its own security headers, for example
  `Content-Security-Policy: default-src 'self'; frame-ancestors 'none'; base-uri 'none'; object-src 'none'`.
  API responses already carry a stricter policy set by Django.
- If the admin is enabled, allow its path only from the internal network or a
  VPN.

## Database roles

The append-only audit triggers and the ownership triggers can be disabled by
the **owner** of the tables. For them to protect against a compromised
application, use two roles:

| Role | Used by | Privileges |
|---|---|---|
| `merchantflow_owner` | `manage.py migrate` only | owns the schema and tables |
| `merchantflow_app` | the running application | `SELECT, INSERT, UPDATE, DELETE` on tables, `USAGE` on sequences; **not** the owner |

With this split, `apps.audit.maintenance.audit_protection_suspended` fails
with a permission error for the application, as intended. If one role is used
for both, the triggers still stop every ordinary code path (ORM, bulk
operations, raw SQL, `TRUNCATE`), but not someone running SQL as the owner.

## Scheduled jobs

| Command | Frequency | Why |
|---|---|---|
| `manage.py purge_login_attempts` | hourly | removes expired sign-in counters |
| `manage.py clearsessions` | daily | removes expired session rows |

## Health check

`GET /api/health/` is exempt from the HTTPS redirect so a load balancer can
probe it over the internal network. It reveals only whether the database is
reachable.
```


Summary of what the document requires and what the code does about it:

| Requirement | In code? | Verified? |
|---|---|---|
| Application role does not own tables; separate migration role | No. A documented requirement; migrations do not create roles | No deployment exists. The non-owner behaviour is shown by `test_suspension_requires_owning_the_table` with a temporary role |
| Audit-trigger protection | Triggers in `audit.0002` | Tests (section 5) |
| Scheduled `purge_login_attempts` (hourly) and `clearsessions` (daily) | Commands exist; no scheduler is configured | No |
| Outermost proxy overwrites `X-Forwarded-For` / `X-Forwarded-Proto`; count matches `DJANGO_TRUSTED_PROXY_COUNT` | Address logic in `common/net.py`; count required ≥ 1 at start-up | Proxy behaviour unverifiable |
| Admin disabled, or non-default path restricted at the proxy | Off by default; default path refused at start-up | Proxy restriction unverifiable |
| Production variables per `.env.production.example`, `DJANGO_READ_DOT_ENV=false` | Validated at start-up when debug is off | CI deploy check; subprocess tests |

---

## 9. Migration review material

### accounts.0003

**`backend/apps/accounts/migrations/0003_login_attempt_buckets.py`, lines 1–31** — complete file

```python
# Generated by Django 5.2.19 on 2026-11-16 19:22

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0002_installations_and_sessions"),
    ]

    operations = [
        migrations.CreateModel(
            name="LoginAttemptBucket",
            fields=[
                (
                    "key",
                    models.CharField(max_length=128, primary_key=True, serialize=False),
                ),
                ("window_started_at", models.DateTimeField()),
                ("failures", models.PositiveIntegerField(default=0)),
            ],
            options={
                "indexes": [
                    models.Index(
                        fields=["window_started_at"], name="login_bucket_window_idx"
                    )
                ],
            },
        ),
    ]
```

- **Operations:** `CreateModel LoginAttemptBucket` (text primary key, timestamp, positive integer) and one index on `window_started_at`.
- **Reversible:** yes; the reverse drops the table, losing only transient counters.
- **Data assumptions:** none.
- **Failure conditions:** only if a table with the same name already exists.
- **Safe on an existing database:** yes. It creates a new empty table and touches no existing rows.

### workspaces.0004

**`backend/apps/workspaces/migrations/0004_device_revocation_reason.py`, lines 1–61** — complete file

```python
# Generated by Django 5.2.19 on 2026-11-16 19:26

from django.conf import settings
from django.db import migrations, models


def backfill_reason(apps, schema_editor):
    # Every revocation before this migration was made by a person.
    WorkspaceDevice = apps.get_model("workspaces", "WorkspaceDevice")
    WorkspaceDevice.objects.filter(status="revoked").update(revocation_reason="manual")


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0003_login_attempt_buckets"),
        ("workspaces", "0003_migrate_legacy_devices"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="workspacedevice",
            name="workspace_device_revocation_consistent",
        ),
        migrations.AddField(
            model_name="workspacedevice",
            name="revocation_reason",
            field=models.CharField(
                blank=True,
                choices=[
                    ("manual", "Revoked by a person"),
                    ("membership_removed", "Member removed from the workspace"),
                ],
                max_length=32,
                null=True,
            ),
        ),
        migrations.RunPython(backfill_reason, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="workspacedevice",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(
                        ("revocation_reason__isnull", True),
                        ("revoked_at__isnull", True),
                        ("revoked_by__isnull", True),
                        ("status", "active"),
                    ),
                    models.Q(
                        ("revocation_reason__in", ["manual", "membership_removed"]),
                        ("revoked_at__isnull", False),
                        ("revoked_by__isnull", False),
                        ("status", "revoked"),
                    ),
                    _connector="OR",
                ),
                name="workspace_device_revocation_consistent_v2",
            ),
        ),
    ]
```

- **Operations, in one transaction:**
  1. Remove constraint `workspace_device_revocation_consistent`.
  2. Add the nullable `revocation_reason` column.
  3. `RunPython backfill_reason`: every `revoked` row gets `manual`.
  4. Add constraint `workspace_device_revocation_consistent_v2`, which requires the reason to be NULL when active and one of the choices when revoked.
- **Reversible:** yes. The reverse drops v2, skips the backfill (`noop`), drops the column (losing reasons) and restores the original constraint. Rows remain valid for it.
- **Data assumptions:** existing rows satisfy the original constraint (active ⇒ no revocation fields; revoked ⇒ both set). The original constraint guaranteed this.
- **Failure conditions:** `AddConstraint` validates every row under an `ACCESS EXCLUSIVE` lock; a row violating v2 would abort the migration. The backfill makes the known case (legacy revoked rows) compliant. Verified during implementation on the development database (one legacy revoked row) forward, back and forward. That run is not reproduced here.
- **Safe on an existing database:** yes, with a brief exclusive lock on `workspaces_workspacedevice` during validation.

### audit.0002

**`backend/apps/audit/migrations/0002_append_only_triggers.py`, lines 1–44** — complete file

```python
"""Make the audit table append-only in PostgreSQL itself.

Row triggers reject UPDATE and DELETE (including Django bulk operations and
raw SQL); a statement trigger rejects TRUNCATE, which also covers truncation
cascading from other tables. Only the table's owner can disable them (see
apps/audit/maintenance.py), so a deployment where the application connects
with a role that does not own the tables cannot alter the audit trail.
"""

from django.db import migrations

FORWARD = """
CREATE FUNCTION audit_auditevent_append_only() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'audit events are append-only (% refused)', TG_OP
        USING ERRCODE = 'restrict_violation';
END;
$$;

CREATE TRIGGER audit_auditevent_no_update_or_delete
    BEFORE UPDATE OR DELETE ON audit_auditevent
    FOR EACH ROW EXECUTE FUNCTION audit_auditevent_append_only();

CREATE TRIGGER audit_auditevent_no_truncate
    BEFORE TRUNCATE ON audit_auditevent
    FOR EACH STATEMENT EXECUTE FUNCTION audit_auditevent_append_only();
"""

REVERSE = """
DROP TRIGGER IF EXISTS audit_auditevent_no_truncate ON audit_auditevent;
DROP TRIGGER IF EXISTS audit_auditevent_no_update_or_delete ON audit_auditevent;
DROP FUNCTION IF EXISTS audit_auditevent_append_only();
"""


class Migration(migrations.Migration):
    dependencies = [
        ("audit", "0001_initial"),
        # 0003 rewrites legacy audit targets; it must run before rows are frozen.
        ("workspaces", "0004_device_revocation_reason"),
    ]

    operations = [migrations.RunSQL(FORWARD, REVERSE)]
```

- **Dependencies:** `audit.0001` and `workspaces.0004`. Ordering matters: `workspaces.0003` (Milestone 1) **updates** audit rows in both directions. This dependency guarantees the triggers are not present when that migration runs, and that they are removed before it is reversed.
- **Operations:** one `RunSQL` creating a function and two triggers.
- **Reversible:** yes, via the reverse SQL (`DROP … IF EXISTS`).
- **Data assumptions:** no later migration needs to update or delete audit rows. Any future one must suspend the triggers explicitly.
- **Failure conditions:** `CREATE FUNCTION` (not `OR REPLACE`) fails if `audit_auditevent_append_only()` already exists. `CREATE TRIGGER` takes a `SHARE ROW EXCLUSIVE` lock briefly.
- **Safe on an existing database:** yes. Existing rows are untouched.

### workspaces.0005

**`backend/apps/workspaces/migrations/0005_owner_integrity.py`, lines 1–112** — complete file

```python
"""Ownership integrity enforced by PostgreSQL.

1. At commit, every workspace has exactly one active owner membership, and
   unless the workspace is archived, that owner's account is active. The
   check is a deferred constraint trigger, so an ownership transfer (demote,
   then promote, in one transaction) passes while any committed state without
   an owner is refused, whichever code path produced it.
2. An account that owns a non-archived workspace cannot be deactivated.
"""

from django.db import migrations

FORWARD = """
CREATE FUNCTION workspaces_assert_single_active_owner(ws uuid) RETURNS void
LANGUAGE plpgsql AS $$
DECLARE
    ws_status text;
    owners integer;
    inactive_owner_accounts integer;
BEGIN
    SELECT status INTO ws_status FROM workspaces_workspace WHERE id = ws;
    IF NOT FOUND THEN
        RETURN;
    END IF;
    SELECT count(*),
           count(*) FILTER (WHERE NOT u.is_active)
      INTO owners, inactive_owner_accounts
      FROM workspaces_workspacemembership m
      JOIN accounts_user u ON u.id = m.user_id
     WHERE m.workspace_id = ws AND m.role = 'owner' AND m.status = 'active';
    IF owners <> 1 THEN
        RAISE EXCEPTION 'workspace % must have exactly one active owner (found %)', ws, owners
            USING ERRCODE = 'check_violation';
    END IF;
    IF ws_status <> 'archived' AND inactive_owner_accounts > 0 THEN
        RAISE EXCEPTION 'the owner of workspace % must have an active account', ws
            USING ERRCODE = 'check_violation';
    END IF;
END;
$$;

CREATE FUNCTION workspaces_membership_owner_check() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP IN ('UPDATE', 'DELETE') THEN
        PERFORM workspaces_assert_single_active_owner(OLD.workspace_id);
    END IF;
    IF TG_OP IN ('INSERT', 'UPDATE') AND (TG_OP = 'INSERT' OR NEW.workspace_id <> OLD.workspace_id) THEN
        PERFORM workspaces_assert_single_active_owner(NEW.workspace_id);
    END IF;
    RETURN NULL;
END;
$$;

CREATE FUNCTION workspaces_workspace_owner_check() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    PERFORM workspaces_assert_single_active_owner(NEW.id);
    RETURN NULL;
END;
$$;

CREATE CONSTRAINT TRIGGER workspaces_membership_keeps_one_owner
    AFTER INSERT OR UPDATE OR DELETE ON workspaces_workspacemembership
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION workspaces_membership_owner_check();

CREATE CONSTRAINT TRIGGER workspaces_workspace_has_owner
    AFTER INSERT OR UPDATE OF status ON workspaces_workspace
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION workspaces_workspace_owner_check();

CREATE FUNCTION accounts_user_owner_stays_active() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF EXISTS (
        SELECT 1
          FROM workspaces_workspacemembership m
          JOIN workspaces_workspace w ON w.id = m.workspace_id
         WHERE m.user_id = NEW.id AND m.role = 'owner' AND w.status <> 'archived'
    ) THEN
        RAISE EXCEPTION 'account % owns a workspace and cannot be deactivated', NEW.id
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER accounts_user_owner_stays_active
    BEFORE UPDATE OF is_active ON accounts_user
    FOR EACH ROW WHEN (OLD.is_active AND NOT NEW.is_active)
    EXECUTE FUNCTION accounts_user_owner_stays_active();
"""

REVERSE = """
DROP TRIGGER IF EXISTS accounts_user_owner_stays_active ON accounts_user;
DROP FUNCTION IF EXISTS accounts_user_owner_stays_active();
DROP TRIGGER IF EXISTS workspaces_workspace_has_owner ON workspaces_workspace;
DROP TRIGGER IF EXISTS workspaces_membership_keeps_one_owner ON workspaces_workspacemembership;
DROP FUNCTION IF EXISTS workspaces_workspace_owner_check();
DROP FUNCTION IF EXISTS workspaces_membership_owner_check();
DROP FUNCTION IF EXISTS workspaces_assert_single_active_owner(uuid);
"""


class Migration(migrations.Migration):
    dependencies = [
        ("workspaces", "0004_device_revocation_reason"),
        ("accounts", "0003_login_attempt_buckets"),
    ]

    operations = [migrations.RunSQL(FORWARD, REVERSE)]
```

- **Dependencies:** `workspaces.0004`, `accounts.0003`.
- **Operations:** one `RunSQL` creating four functions, two deferred constraint triggers and one row trigger.
- **Reversible:** yes, via the reverse SQL.
- **Data assumptions — critical:** every workspace already has exactly one active owner membership, and every non-archived workspace's owner has an active account.
- **The migration does not check this.** Constraint triggers are not evaluated against existing rows when created, so the migration succeeds even on violating data.
- **Failure conditions after migrating violating data:** every later write that touches such a workspace fails at commit with `check_violation`. That covers any membership insert, update or delete there, and any change to the workspace's `status`. The workspace would be stuck until repaired by the table owner with the triggers suspended.
- **Safe on an existing database:** only after the data assumption has been verified.


### 9.1 Pre-migration check for `workspaces.0005`

**No such check exists in the repository.** No migration, management
command, script, test or CI step verifies the data before `workspaces.0005`
runs.

`docs/IMPLEMENTATION_PLAN.md` (Milestone 2.1, *Upgrade notes*) says to
"check before migrating (query in the M2.1 report)". That query is **not**
in the repository; it appeared only in the implementer's terminal session and
chat report. This is a documentation defect: the referenced check cannot be
found by a reader of the repository.

For completeness, this is the query that was run, ad hoc, against the
development database during implementation (it returned 0):

```sql
select count(*) from workspaces_workspace w
where (select count(*) from workspaces_workspacemembership m
       join accounts_user u on u.id = m.user_id
       where m.workspace_id = w.id and m.role = 'owner'
         and m.status = 'active' and u.is_active) <> 1
```

*Reviewer note:* that ad-hoc query is **stricter** than the trigger. It
requires an active owner account for archived workspaces too, which the
trigger exempts. It is reproduced as a historical record, not proposed as the
check.

---

## 10. Test evidence

All backend tests run against real PostgreSQL. Tests marked *rolled-back test
transaction* run inside a transaction that pytest-django rolls back, so
deferred triggers fire only when a test forces them with `SET CONSTRAINTS
ALL IMMEDIATE`. Tests marked *committed transactions* use
`django_db(transaction=True)` and really commit.

The traits column was **detected mechanically from each test's source** (use
of fixtures, threads, `subprocess`, `mock.patch`, `pytest.skip`). It is not
a claim about the test's quality.

### 10.1 New M2.1 test modules

**`backend/tests/test_login_protection.py`** (19 test functions)

| Test (line) | Docstring | Detected from source |
|---|---|---|
| `test_client_ip_trusts_only_the_configured_proxies` (L51) |  | no database (unit level), parametrised |
| `test_ipv6_addresses_are_limited_per_64_network` (L57) |  | no database (unit level) |
| `test_forged_forwarded_header_does_not_buy_more_attempts` (L63) | Assessment probe S1: 50 guesses with a fresh header each were never limited. | PostgreSQL (rolled-back test transaction) |
| `test_behind_one_trusted_proxy_the_appended_address_is_limited` (L74) |  | PostgreSQL (rolled-back test transaction) |
| `test_correct_logins_never_consume_the_allowance` (L87) | Assessment probe S2: the 11th correct login from one address was refused. | PostgreSQL (rolled-back test transaction) |
| `test_a_success_clears_earlier_typing_mistakes_from_that_address` (L97) |  | PostgreSQL (rolled-back test transaction) |
| `test_people_sharing_a_shop_network_do_not_block_each_other` (L107) | Thirty staff behind one router, each mistyping twice, all get in. | PostgreSQL (rolled-back test transaction) |
| `test_one_address_cannot_lock_an_account_for_everyone` (L116) |  | PostgreSQL (rolled-back test transaction) |
| `test_distributed_guessing_against_one_account_is_limited` (L123) | Assessment probe S3: guesses from many real addresses were never limited. | PostgreSQL (rolled-back test transaction) |
| `test_password_spraying_from_one_address_is_limited` (L133) |  | PostgreSQL (rolled-back test transaction) |
| `test_password_is_not_checked_while_blocked` (L141) |  | PostgreSQL (rolled-back test transaction), uses mock.patch |
| `test_unknown_and_known_accounts_are_indistinguishable` (L151) |  | PostgreSQL (rolled-back test transaction) |
| `test_lock_expires_with_the_window` (L164) |  | PostgreSQL (rolled-back test transaction), uses mock.patch |
| `test_counters_hold_no_identifiers` (L174) |  | PostgreSQL (rolled-back test transaction) |
| `test_purge_removes_only_expired_counters` (L182) |  | PostgreSQL (rolled-back test transaction) |
| `test_sign_in_and_sign_out_are_audited_with_the_trusted_address` (L193) |  | PostgreSQL (rolled-back test transaction) |
| `test_account_lock_is_audited_once_per_window` (L203) |  | PostgreSQL (rolled-back test transaction) |
| `test_concurrent_guesses_cannot_exceed_the_limit` (L216) |  | PostgreSQL, committed transactions, threads, separate DB connections |
| `test_the_limit_is_shared_between_separate_processes` (L250) | Two separate Python processes, each its own Django, one database. | PostgreSQL, committed transactions, separate OS process |

**`backend/tests/test_admin.py`** (13 test functions)

| Test (line) | Docstring | Detected from source |
|---|---|---|
| `test_admin_uses_the_protected_site` (L43) |  | no database (unit level) |
| `test_admin_is_not_routed_when_disabled` (L54) |  | PostgreSQL (rolled-back test transaction) |
| `test_admin_path_is_configurable` (L62) |  | PostgreSQL (rolled-back test transaction) |
| `test_admin_login_failures_are_limited_and_shared_with_the_api` (L74) |  | PostgreSQL (rolled-back test transaction) |
| `test_successful_admin_login_is_audited_and_not_counted` (L92) |  | PostgreSQL (rolled-back test transaction) |
| `test_admin_session_cannot_use_the_api` (L103) |  | PostgreSQL (rolled-back test transaction) |
| `test_operator_cannot_demote_the_owner_through_the_admin` (L114) |  | PostgreSQL (rolled-back test transaction) |
| `test_membership_admin_is_view_only` (L127) |  | PostgreSQL (rolled-back test transaction) |
| `test_records_with_lifecycle_rules_cannot_be_created_in_the_admin` (L154) |  | PostgreSQL (rolled-back test transaction), parametrised |
| `test_workspace_edits_in_the_admin_are_audited` (L161) |  | PostgreSQL (rolled-back test transaction) |
| `test_admin_refuses_to_deactivate_a_workspace_owner` (L185) |  | PostgreSQL (rolled-back test transaction) |
| `test_admin_deactivation_of_a_non_owner_is_allowed_and_audited` (L196) |  | PostgreSQL (rolled-back test transaction) |
| `test_password_set_in_the_admin_is_audited_without_the_password` (L208) |  | PostgreSQL (rolled-back test transaction) |

**`backend/tests/test_device_lifecycle.py`** (17 test functions)

| Test (line) | Docstring | Detected from source |
|---|---|---|
| `test_manager_cannot_revoke_the_owners_device` (L45) | Assessment probe S4: a manager locked the owner's browser out. | PostgreSQL (rolled-back test transaction) |
| `test_manager_cannot_revoke_another_managers_device` (L56) |  | PostgreSQL (rolled-back test transaction) |
| `test_manager_can_revoke_devices_of_lower_roles` (L64) |  | PostgreSQL (rolled-back test transaction), parametrised |
| `test_owner_can_revoke_a_managers_device` (L70) |  | PostgreSQL (rolled-back test transaction) |
| `test_attendant_cannot_revoke_an_affiliates_device` (L75) |  | PostgreSQL (rolled-back test transaction) |
| `test_everyone_can_revoke_their_own_device` (L81) |  | PostgreSQL (rolled-back test transaction), parametrised |
| `test_manager_cannot_reauthorize_the_owners_device` (L86) |  | PostgreSQL (rolled-back test transaction) |
| `test_lower_roles_cannot_reauthorize_anything` (L95) |  | PostgreSQL (rolled-back test transaction), parametrised |
| `test_owner_may_reauthorize_their_own_device_through_the_service` (L102) |  | PostgreSQL (rolled-back test transaction) |
| `test_removal_revokes_the_members_devices_in_that_workspace_only` (L112) | Assessment probe S5: the device stayed active after removal. | PostgreSQL (rolled-back test transaction) |
| `test_removal_through_the_api_revokes_devices` (L140) |  | PostgreSQL (rolled-back test transaction) |
| `test_reinstatement_does_not_restore_device_access` (L149) |  | PostgreSQL (rolled-back test transaction) |
| `test_access_returns_only_after_explicit_reauthorization` (L162) |  | PostgreSQL (rolled-back test transaction) |
| `test_a_browser_signed_out_everywhere_cannot_be_reauthorized` (L184) |  | PostgreSQL (rolled-back test transaction) |
| `test_suspension_blocks_access_but_keeps_devices` (L195) | Default agreed in the assessment (Q9): devices are revoked on removal only. | PostgreSQL (rolled-back test transaction) |
| `test_first_entry_cannot_slip_in_while_the_member_is_being_removed` (L212) |  | PostgreSQL, committed transactions, threads, separate DB connections |
| `test_existing_revocations_are_backfilled_as_manual` (L248) |  | PostgreSQL, committed transactions |

**`backend/tests/test_audit_integrity.py`** (9 test functions)

| Test (line) | Docstring | Detected from source |
|---|---|---|
| `test_instances_cannot_be_saved_again_or_deleted` (L41) |  | PostgreSQL (rolled-back test transaction) |
| `test_bulk_update_is_refused` (L50) | Assessment probe S8: every row was rewritten through a queryset. | PostgreSQL (rolled-back test transaction) |
| `test_bulk_delete_is_refused` (L56) |  | PostgreSQL (rolled-back test transaction) |
| `test_raw_sql_update_delete_and_truncate_are_refused` (L62) |  | PostgreSQL (rolled-back test transaction) |
| `test_truncation_cascading_from_another_table_is_refused` (L70) |  | PostgreSQL (rolled-back test transaction) |
| `test_appending_still_works` (L77) |  | PostgreSQL (rolled-back test transaction) |
| `test_the_triggers_are_installed_and_enabled` (L83) |  | PostgreSQL (rolled-back test transaction) |
| `test_maintenance_suspension_is_scoped_and_restores_protection` (L96) |  | PostgreSQL (rolled-back test transaction) |
| `test_suspension_requires_owning_the_table` (L104) | A role that does not own the table (as in production) cannot suspend it. | PostgreSQL (rolled-back test transaction), may skip |

**`backend/tests/test_owner_integrity.py`** (14 test functions)

| Test (line) | Docstring | Detected from source |
|---|---|---|
| `test_owner_cannot_be_demoted_below_the_services` (L43) | Assessment probe S6 reached this state through the admin. | PostgreSQL (rolled-back test transaction) |
| `test_owner_membership_cannot_be_deleted` (L50) |  | PostgreSQL (rolled-back test transaction) |
| `test_owner_membership_cannot_be_moved_to_another_workspace` (L55) |  | PostgreSQL (rolled-back test transaction) |
| `test_a_workspace_cannot_be_created_without_an_owner` (L63) |  | PostgreSQL (rolled-back test transaction) |
| `test_an_inactive_account_cannot_be_made_owner_directly` (L67) |  | PostgreSQL (rolled-back test transaction) |
| `test_supported_operations_still_pass_the_checks` (L77) |  | PostgreSQL (rolled-back test transaction) |
| `test_checks_are_enforced_at_a_real_commit` (L85) |  | PostgreSQL, committed transactions |
| `test_owner_account_cannot_be_deactivated_below_the_services` (L97) | Assessment probe S11 orphaned the workspace this way. | PostgreSQL (rolled-back test transaction) |
| `test_deactivate_user_refuses_an_owner_with_a_clear_error` (L104) |  | PostgreSQL (rolled-back test transaction) |
| `test_deactivate_user_works_for_members_and_ends_their_sessions` (L111) |  | PostgreSQL (rolled-back test transaction) |
| `test_owner_can_be_deactivated_after_transferring_ownership` (L125) |  | PostgreSQL (rolled-back test transaction) |
| `test_owner_of_an_archived_workspace_may_be_deactivated` (L131) |  | PostgreSQL (rolled-back test transaction) |
| `test_deactivation_waiting_on_a_transfer_is_refused` (L154) |  | PostgreSQL, committed transactions, threads, separate DB connections |
| `test_transfer_waiting_on_a_deactivation_is_refused` (L170) |  | PostgreSQL, committed transactions, threads, separate DB connections |

**`backend/tests/test_production_settings.py`** (8 test functions)

| Test (line) | Docstring | Detected from source |
|---|---|---|
| `test_a_safe_configuration_has_no_problems` (L31) |  | no database (unit level) |
| `test_each_unsafe_setting_is_reported` (L52) |  | no database (unit level), parametrised |
| `test_admin_on_a_private_path_is_accepted` (L58) |  | no database (unit level) |
| `test_the_documented_production_settings_pass_the_deploy_check` (L89) |  | separate OS process |
| `test_unsafe_production_settings_stop_the_application_starting` (L105) |  | separate OS process, parametrised |
| `test_debug_mode_is_not_subject_to_the_production_rules` (L112) |  | separate OS process |
| `test_api_responses_carry_a_restrictive_content_security_policy` (L120) |  | PostgreSQL (rolled-back test transaction) |
| `test_https_redirect_exempts_only_the_health_check` (L130) |  | PostgreSQL (rolled-back test transaction) |


### 10.2 Existing tests changed by M2.1

```
backend/tests/conftest.py                 | 24 ++++++++++++++++++++++++
 backend/tests/isolation.py                |  1 +
 backend/tests/test_accounts.py            | 13 +++++++------
 backend/tests/test_actor_authorization.py | 16 +++++++++++++---
 frontend/e2e/auth.spec.ts                 | 19 ++++++++++++++++++-
 5 files changed, 63 insertions(+), 10 deletions(-)
```

- `test_accounts.py`: the DRF-throttle test is replaced by
  `test_repeated_failures_are_refused_with_429`.
- `test_actor_authorization.py`: the `user_deactivated` case no longer
  deactivates an **owner's** account, which the database now forbids. It moved
  to `test_deactivated_account_is_refused_even_with_an_old_object`, which uses
  a manager.
- `conftest.py`: the `flush` patch (section 5.3).
- `isolation.py`: the re-authorise endpoint was added to the isolation registry.
- `frontend/e2e/auth.spec.ts`: one browser test for the lock-out message
  (`repeated wrong passwords lock the account for a while, without revealing
  it`), using a seeded account reserved for it.

### 10.3 Separate processes, mocks, skips

- **Separate OS processes:**
  - `test_login_protection.py::test_the_limit_is_shared_between_separate_processes`
    (two interpreters, one database);
  - every subprocess test in `test_production_settings.py`, which start
    `manage.py` with production environments.
- **Mocks:**
  - `test_password_is_not_checked_while_blocked` patches `authenticate` to
    prove it is not called;
  - `test_lock_expires_with_the_window` patches the clock.
- **Unit level, no database:**
  - `test_client_ip_trusts_only_the_configured_proxies`,
    `test_ipv6_addresses_are_limited_per_64_network`;
  - the `production_problems` rule tests.
- **Skips:**
  - 4 in CI, all `tests/test_isolation.py:70` ("endpoint takes no record id":
    the foreign-record-id contract does not apply to endpoints without a
    record id);
  - `test_suspension_requires_owning_the_table` can skip when the database
    role may not create roles. It did not skip in CI.

### 10.4 What the tests do not prove

- Behaviour behind a real reverse proxy and TLS.
- That the production database uses a non-owner application role.
- Resistance of the address bucket to a hostile user on a shared address.
- Races other than the specific ones tested: concurrent guesses; transfer vs
  deactivation; first entry vs removal; concurrent revocations and transfers
  from Milestone 1.
- Admin user deletion, and un-archiving with an inactive owner.

---

## 11. Independent-review checklist

| Area | Actual implementation found? | Relevant files | Evidence | Classification | Remaining concern |
|---|---|---|---|---|---|
| F-01 Forged `X-Forwarded-For` | Yes | `common/net.py`, `settings.py` (`TRUSTED_PROXY_COUNT`, `NUM_PROXIES`), `accounts/views.py` | `test_forged_forwarded_header_does_not_buy_more_attempts`, `test_client_ip_trusts_only_the_configured_proxies`, `test_behind_one_trusted_proxy_the_appended_address_is_limited` | IMPLEMENTED AND TESTED | Correct only if the deployed proxy overwrites the header and the count is right (unverifiable). Unparseable addresses share one `"unknown"` bucket |
| F-02 Per-account limits, successes, shared storage | Yes | `accounts/login_protection.py`, `accounts/models.py`, migration `accounts.0003` | Concurrency test (20 threads), two-process test, distributed-guessing, shared-network and success tests; e2e lock-out | IMPLEMENTED AND TESTED | A hostile user on a shared address can exhaust the address bucket and block everyone there. Distributed guessing can lock an account (O-023); no operator unlock. Three buckets not updated atomically as a set. Depends on no surrounding transaction |
| F-03 Admin login and membership edits | Yes | `common/admin_site.py`, `common/admin_config.py`, `config/urls.py`, `workspaces/admin.py`, `accounts/admin.py` | `test_admin.py` (16 tests) | IMPLEMENTED AND TESTED | No second factor. User deletion via admin allowed and unaudited (untested). Path restriction at the proxy unverifiable. Non-staff valid passwords counted as failures |
| F-04 Managers revoking owner devices | Yes | `workspaces/policies.py`, `workspaces/device_services.py` | Rank tests in `test_device_lifecycle.py` | IMPLEMENTED AND TESTED | Holder's membership not locked during revoke/re-authorise; a concurrent role change is not serialised (untested) |
| F-05 Device authorisation vs removal and reinstatement | Yes | `workspaces/services.py::set_member_status`, `workspaces/device_services.py`, `devices/views.py`, `devices/urls.py`, migration `workspaces.0004` | Removal, reinstatement, re-authorise, race and backfill tests | IMPLEMENTED AND TESTED | Enforced in the service layer only (raw SQL status change would not revoke). Suspension keeps devices by design (Q9). Re-authorise endpoint is an addition beyond the original finding |
| F-06 Unsafe production configuration | Yes | `config/production_checks.py`, `config/settings.py`, `common/middleware.py`, `.env.production.example`, `ci.yml` | Rule tests, subprocess start-up tests, CI deploy-check step | IMPLEMENTED AND TESTED | Rules apply only when debug is off. API docs, database TLS and the SPA CSP are not checked. W021 silenced |
| F-07 Mutable audit records | Yes | `audit/migrations/0002_append_only_triggers.py`, `audit/maintenance.py`, `tests/conftest.py`, `scripts/e2e_seed.py` | `test_audit_integrity.py` incl. TRUNCATE cascade and non-owner role | IMPLEMENTED AND TESTED for every application code path | The table owner can still disable or drop the triggers. The role split that closes this is documented but not implemented or verified (dev and CI use one owner role). Inserts are unrestricted (append-only, not authenticated) |
| F-10 Exactly one active owner | Yes | `workspaces/migrations/0005_owner_integrity.py`, Milestone 1 constraints | `test_owner_integrity.py` incl. real-commit test | IMPLEMENTED BUT INSUFFICIENTLY TESTED | Migration does not validate existing data and **no pre-migration check exists in the repository** (the doc points to one that is absent). Un-archiving with an inactive owner untested. Arbitrary raw-SQL races untested |
| F-11 Owner deactivation | Yes | `workspaces/migrations/0005_owner_integrity.py` (user trigger), `accounts/services.py::deactivate_user`, `accounts/admin.py`, `workspaces/services.py::transfer_ownership` | Trigger, service, admin and two race tests | IMPLEMENTED AND TESTED | No API for account suspension yet (M2.2). Owners of archived workspaces may be deactivated by design |

---

## 12. Known limitations

1. Tests were not re-run for this package (no database may be created);
   results are taken from CI run 43941574998 and `--collect-only`.
2. No deployment exists, so the proxy, TLS, database-role split and
   scheduled jobs in `docs/DEPLOYMENT.md` are requirements, not verified
   facts.
3. `docs/IMPLEMENTATION_PLAN.md` refers to a pre-migration owner check "in
   the M2.1 report" that is not in the repository (section 9.1).
4. F-08 (session idle/absolute expiry, sign-out-others) and F-09
   (re-authentication) are not implemented. They are planned for M2.2.
5. Concerns listed in section 11 are the preparer's reading of the code and
   need independent confirmation.
