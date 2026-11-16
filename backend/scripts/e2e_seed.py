"""Prepare a throwaway database for the browser tests.

Creates the database if needed, migrates it, EMPTIES it, and loads a small set
of fictional people and shops. It refuses to touch a database whose name does
not end in ``_e2e``. Run with ``DATABASE_URL`` pointing at that database::

    DATABASE_URL=postgres://.../merchantflow_e2e python scripts/e2e_seed.py
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django  # noqa: E402

django.setup()

import psycopg  # noqa: E402
from django.conf import settings  # noqa: E402
from django.core.management import call_command  # noqa: E402
from psycopg import sql  # noqa: E402

from apps.accounts.services import register_user  # noqa: E402
from apps.workspaces.models import WorkspaceMembership  # noqa: E402
from apps.workspaces.services import add_member, create_workspace  # noqa: E402

# Test-only credential for fictional accounts in a database that is wiped on
# every run. Never used anywhere else.
PASSWORD = os.environ.get("E2E_PASSWORD", "e2e-only-passphrase-7421")


def ensure_database(config: dict) -> None:
    name = config["NAME"]
    if not name.endswith("_e2e"):
        sys.exit(f"Refusing to prepare {name!r}: the database name must end in '_e2e'.")
    connection = psycopg.connect(
        dbname="postgres",
        user=config["USER"],
        password=config["PASSWORD"],
        host=config["HOST"],
        port=config["PORT"] or 5432,
        autocommit=True,
    )
    with connection:
        exists = connection.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s", [name]
        ).fetchone()
        if not exists:
            connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))


def seed() -> None:
    def person(email: str, name: str):
        return register_user(email=email, full_name=name, password=PASSWORD)

    awa = person("awa@example.test", "Awa Ndongo")
    paul = person("paul@example.test", "Paul Etame")
    akwa = create_workspace(name="Akwa Phones", owner=awa)
    bonanjo = create_workspace(name="Bonanjo Mobile", owner=paul)
    akwa_owner = WorkspaceMembership.objects.get(workspace=akwa, role="owner")
    bonanjo_owner = WorkspaceMembership.objects.get(workspace=bonanjo, role="owner")

    # Awa owns one shop and sells for another: the multi-workspace case.
    add_member(actor=bonanjo_owner, user=awa, role="affiliate")
    add_member(actor=akwa_owner, user=person("marie@example.test", "Marie Fotso"), role="affiliate")
    # Dedicated accounts for tests that revoke devices, so they cannot disturb others.
    add_member(actor=akwa_owner, user=person("jean@example.test", "Jean Mbarga"), role="attendant")
    add_member(actor=akwa_owner, user=person("sam@example.test", "Sam Biya"), role="affiliate")
    # Only used by the sign-in lock-out test, which deliberately locks it.
    add_member(actor=akwa_owner, user=person("lock@example.test", "Lock Test"), role="affiliate")


def grant_to_runtime_role() -> None:
    """With --grant-to ROLE (run as the owner role), grant the runtime role its
    privileges, so the server under test can run as a least-privilege role."""
    if "--grant-to" not in sys.argv:
        return
    from django.db import connection

    from apps.common.database_roles import grant_runtime_privileges

    role = sys.argv[sys.argv.index("--grant-to") + 1]
    with connection.cursor() as cursor:
        grant_runtime_privileges(cursor, role)
    print(f"Granted runtime privileges to {role}")  # noqa: T201


if __name__ == "__main__":
    ensure_database(settings.DATABASES["default"])
    call_command("migrate", interactive=False, verbosity=0)
    from apps.audit.maintenance import audit_protection_suspended

    with audit_protection_suspended():  # throwaway database: audit rows may go
        call_command("flush", interactive=False, verbosity=0)
    seed()
    grant_to_runtime_role()
    print(f"Seeded {settings.DATABASES['default']['NAME']}")  # noqa: T201
