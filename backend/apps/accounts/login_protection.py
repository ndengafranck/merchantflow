"""Protection of the sign-in forms against password guessing.

Counters of **failed** attempts, all in PostgreSQL, shared by every process.

**Unknown browser** (no recognised device cookie for this account):

======================  ===========================================================
Bucket                  Stops
======================  ===========================================================
account + address       one client guessing one account (strict limit)
account                 many addresses guessing one account (distributed guessing)
address                 one address trying many accounts (password spraying)
======================  ===========================================================

**Known browser**: the request carries the ``mf_device`` cookie of an *active*
installation that already signed in to *this* account. Only that browser's own
bucket applies (``KNOWN_BROWSER``); the account and address buckets neither
block it nor count its failures. This is OWASP's "device cookie" defence: a
legitimate user on their usual browser cannot be locked out by strangers
guessing their password, or by someone abusing a shared shop or carrier
address, while whoever holds that browser still gets only a few guesses per
window. The cookie is an identifier the server issued at an earlier
successful sign-in, it is never a credential: the password is always checked.

Each attempt first *reserves* a failure in every applicable bucket. If any is
then over its limit the attempt is refused without checking the password, and
the reservations are given back (refused attempts do not extend a lock, and
one address cannot push an account into lock-out on its own). If the password
is correct the reservations are given back and the strict bucket (account +
address, or the known browser's) is cleared: correct sign-ins never consume
allowance. Unknown accounts are counted exactly like real ones.

Consistency: all reservations of one attempt are a single SQL statement, and
so are all refunds; both lock their rows in key order, so concurrent attempts
cannot deadlock each other and cannot slip past a limit. Between the reserve
and the refund statements other attempts may see a count one higher than it
will settle at, which can only cause an extra refusal, never an extra guess.
The statements must run outside a rolled-back transaction (requests run in
autocommit; ``ATOMIC_REQUESTS`` is off) or failures would not be counted.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from uuid import UUID

from django.conf import settings
from django.db import connection
from django.utils import timezone
from django.utils.crypto import salted_hmac

from .models import DeviceInstallation, InstallationStatus, LoginAttemptBucket

_RESERVE = """
INSERT INTO accounts_loginattemptbucket AS b (key, window_started_at, failures)
SELECT k, %(now)s, 1 FROM unnest(%(keys)s::text[]) AS k ORDER BY k
ON CONFLICT (key) DO UPDATE SET
    failures = CASE WHEN b.window_started_at <= %(expired_before)s THEN 1 ELSE b.failures + 1 END,
    window_started_at = CASE
        WHEN b.window_started_at <= %(expired_before)s THEN %(now)s ELSE b.window_started_at END
RETURNING key, failures, window_started_at
"""

_REFUND = """
WITH locked AS (
    SELECT key FROM accounts_loginattemptbucket
     WHERE key = ANY(%(keys)s::text[]) ORDER BY key FOR UPDATE
)
UPDATE accounts_loginattemptbucket b SET failures = b.failures - 1
  FROM locked
  JOIN unnest(%(keys)s::text[], %(windows)s::timestamptz[]) AS r(key, window_started_at)
    ON r.key = locked.key
 WHERE b.key = locked.key AND b.window_started_at = r.window_started_at AND b.failures > 0
"""

# The bucket a successful sign-in clears (typing mistakes forgiven).
_CLEARED_ON_SUCCESS = ("account_address", "known_browser")


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
    known_browser: bool = False
    _settled: bool = field(default=False, repr=False)

    def failed(self) -> list[str]:
        """Keep the reservations. Returns the bucket kinds that just reached
        their limit, so the caller can record a lock-out once per window."""
        self._settle()
        return [r.limit.kind for r in self.reservations if r.failures == r.limit.maximum]

    def succeeded(self) -> None:
        self._settle()
        _refund(self.reservations)
        cleared = [r.limit.key for r in self.reservations if r.limit.kind in _CLEARED_ON_SUCCESS]
        LoginAttemptBucket.objects.filter(pk__in=cleared).delete()

    def _settle(self) -> None:
        if self._settled or self.blocked:
            raise RuntimeError("A login attempt is settled once, and never when blocked.")
        self._settled = True


def _config() -> dict:
    return settings.LOGIN_PROTECTION


def _key(kind: str, value: str) -> str:
    digest = salted_hmac("merchantflow.login-protection", f"{kind}:{value}").hexdigest()
    return f"{kind}:{digest}"


def recognised_installation(identifier: str, cookie_value: str | None) -> UUID | None:
    """The installation named by the browser's device cookie, if it is an
    active installation of the account being signed in to. Anything else
    (absent, malformed, another account's, revoked) is an unknown browser."""
    try:
        installation_id = UUID(cookie_value) if cookie_value else None
    except ValueError:
        return None
    if installation_id is None:
        return None
    found = DeviceInstallation.objects.filter(
        pk=installation_id, user__email=identifier, status=InstallationStatus.ACTIVE
    ).exists()
    return installation_id if found else None


def limits_for(identifier: str, address: str, installation_id: UUID | None = None) -> list[Limit]:
    config = _config()
    if installation_id is not None:
        return [Limit("known_browser", _key("kb", str(installation_id)), config["KNOWN_BROWSER"])]
    return [
        Limit(
            "account_address",
            _key("aa", f"{identifier}|{address}"),
            config["ACCOUNT_AND_ADDRESS"],
        ),
        Limit("account", _key("a", identifier), config["ACCOUNT"]),
        Limit("address", _key("ad", address), config["ADDRESS"]),
    ]


def begin_attempt(*, identifier: str, address: str, installation_id: UUID | None = None) -> Attempt:
    """Reserve one failure in each applicable bucket and decide whether to proceed.

    ``identifier`` must already be normalised (for example a lower-cased email),
    ``address`` should come from ``apps.common.net.address_bucket``, and
    ``installation_id`` from ``recognised_installation``.
    """
    now = timezone.now()
    window = timedelta(seconds=_config()["WINDOW_SECONDS"])
    limits = {limit.key: limit for limit in limits_for(identifier, address, installation_id)}
    with connection.cursor() as cursor:
        cursor.execute(
            _RESERVE, {"keys": sorted(limits), "now": now, "expired_before": now - window}
        )
        rows = cursor.fetchall()
    reservations = [Reservation(limits[key], failures, started) for key, failures, started in rows]
    known = installation_id is not None

    over = [r for r in reservations if r.failures > r.limit.maximum]
    if not over:
        return Attempt(reservations, known_browser=known)
    _refund(reservations)
    retry_after = max(int((r.window_started_at + window - now).total_seconds()) for r in over)
    return Attempt(reservations, blocked=True, retry_after=max(retry_after, 1), known_browser=known)


def _refund(reservations: list[Reservation]) -> None:
    ordered = sorted(reservations, key=lambda r: r.limit.key)
    with connection.cursor() as cursor:
        cursor.execute(
            _REFUND,
            {
                "keys": [r.limit.key for r in ordered],
                "windows": [r.window_started_at for r in ordered],
            },
        )


def clear_limits(*, identifier: str, address: str | None = None) -> int:
    """Operator recovery: forget the failures recorded against an account (and,
    if given, against one address). Returns the number of counters removed.
    Exposed only as ``manage.py clear_login_limits``, never over HTTP."""
    keys = [_key("a", identifier)]
    if address is not None:
        keys += [_key("aa", f"{identifier}|{address}"), _key("ad", address)]
    installation_ids = DeviceInstallation.objects.filter(user__email=identifier).values_list(
        "pk", flat=True
    )
    keys += [_key("kb", str(i)) for i in installation_ids]
    deleted, _ = LoginAttemptBucket.objects.filter(pk__in=keys).delete()
    return deleted


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
