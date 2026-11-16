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
