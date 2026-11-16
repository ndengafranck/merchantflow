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
