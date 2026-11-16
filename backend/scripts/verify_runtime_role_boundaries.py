"""Prove, as the runtime role itself, what it can and cannot do.

Run with DATABASE_URL set to the application's (runtime) credentials, after
`migrate` (as the owner) and `grant_runtime_privileges`. Every statement runs in
a transaction that is always rolled back, so this is safe on any database:
even a forbidden statement that unexpectedly succeeds changes nothing.
Exit status 0 only if every forbidden action is refused and every required
one works.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django  # noqa: E402

django.setup()

from django.db import DatabaseError, connection, transaction  # noqa: E402

from apps.common.database_roles import runtime_role_problems  # noqa: E402


class Rollback(Exception):
    pass


def attempt(statement: str) -> str | None:
    """Run ``statement`` and roll back. Returns the error text, or None if it worked."""
    try:
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(statement)
            raise Rollback
    except Rollback:
        return None
    except DatabaseError as exc:
        return str(exc).splitlines()[0]


FORBIDDEN = {
    "update an audit event": "UPDATE audit_auditevent SET action = action",
    "delete audit events": "DELETE FROM audit_auditevent",
    "truncate the audit table": "TRUNCATE audit_auditevent",
    "truncate a table that cascades into audit": "TRUNCATE accounts_user CASCADE",
    "disable the audit triggers": "ALTER TABLE audit_auditevent DISABLE TRIGGER USER",
    "drop an audit trigger": "DROP TRIGGER audit_auditevent_no_truncate ON audit_auditevent",
    "drop the audit trigger function": "DROP FUNCTION audit_auditevent_append_only() CASCADE",
    "disable the ownership triggers": (
        "ALTER TABLE workspaces_workspacemembership DISABLE TRIGGER USER"
    ),
    "drop the ownership check": (
        "DROP FUNCTION workspaces_assert_single_active_owner(uuid) CASCADE"
    ),
    "create a table": "CREATE TABLE public.mf_probe (id int)",
    "record a fake migration": (
        "INSERT INTO django_migrations (app, name, applied) VALUES ('probe', 'x', now())"
    ),
    "become a superuser setting": "SET session_replication_role = replica",
}
REQUIRED = {
    "read audit events": "SELECT count(*) FROM audit_auditevent",
    "insert an audit event": (
        "INSERT INTO audit_auditevent (id, action, target_type, target_id, metadata, created_at) "
        "VALUES (gen_random_uuid(), 'probe', 'probe', gen_random_uuid(), '{}', now())"
    ),
    "update ordinary rows": "UPDATE accounts_user SET last_login = last_login",
    "write sign-in counters": "DELETE FROM accounts_loginattemptbucket WHERE false",
}


def main() -> int:
    failures = []
    with connection.cursor() as cursor:
        cursor.execute("SELECT current_user")
        role = cursor.fetchone()[0]
        problems = runtime_role_problems(cursor)
    print(f"Connected as {role}")  # noqa: T201
    for problem in problems:
        failures.append(f"verify_database_roles: {problem}")
    for label, statement in FORBIDDEN.items():
        error = attempt(statement)
        verdict = "refused" if error else "ALLOWED"
        print(f"  [{verdict:>7}] {label}" + (f"  ({error})" if error else ""))  # noqa: T201
        if error is None:
            failures.append(f"{role} was able to {label}")
    for label, statement in REQUIRED.items():
        error = attempt(statement)
        print(f"  [{'works' if error is None else 'BROKEN':>7}] {label}")  # noqa: T201
        if error is not None:
            failures.append(f"{role} cannot {label}: {error}")
    if failures:
        print("FAILED:\n- " + "\n- ".join(failures))  # noqa: T201
        return 1
    print("Runtime role boundaries hold.")  # noqa: T201
    return 0


if __name__ == "__main__":
    sys.exit(main())
