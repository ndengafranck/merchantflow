"""C3: the runtime database role cannot alter audit or ownership protection.

A real, non-owner role is created inside the test transaction, granted its
privileges by the production code (grant_runtime_privileges), and the
connection switches to it with SET LOCAL ROLE. Requires a test database role
that may create roles (a superuser in CI); skipped otherwise. CI also checks
the same boundaries with separate LOGIN roles (the database-roles job).
"""

import importlib.util
from pathlib import Path

import pytest
from django.db import DatabaseError, connection, transaction
from django.test import override_settings
from rest_framework.test import APIClient

from apps.audit.models import AuditEvent
from apps.common.checks import check_runtime_database_role
from apps.common.database_roles import grant_runtime_privileges, runtime_role_problems
from apps.workspaces.models import WorkspaceDevice

from .conftest import PASSWORD

ROLE = "mf_runtime_probe"
_spec = importlib.util.spec_from_file_location(
    "boundaries",
    Path(__file__).resolve().parent.parent / "scripts" / "verify_runtime_role_boundaries.py",
)
boundaries = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(boundaries)


def run(statement, params=None):
    with connection.cursor() as cursor:
        cursor.execute(statement, params)


@pytest.fixture
def runtime_role(db):
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT rolsuper OR rolcreaterole FROM pg_roles WHERE rolname = current_user"
        )
        if not cursor.fetchone()[0]:
            pytest.skip("the test database role may not create roles")
        # Settle deferred foreign-key checks so later DDL attempts report on privileges.
        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
        cursor.execute("SET CONSTRAINTS ALL DEFERRED")
        cursor.execute(f"CREATE ROLE {ROLE} NOLOGIN")
        # PostgreSQL 16: a non-superuser creator must grant itself SET to switch.
        cursor.execute(f"GRANT {ROLE} TO CURRENT_USER WITH INHERIT FALSE, SET TRUE")
        grant_runtime_privileges(cursor, ROLE)
        grant_runtime_privileges(cursor, ROLE)  # idempotent
    return ROLE  # the role and its grants vanish with the test transaction


def as_role(role):
    run(f"SET LOCAL ROLE {role}")


def as_owner():
    run("RESET ROLE")


def outcome(statement) -> str | None:
    try:
        with transaction.atomic():
            run(statement)
            raise boundaries.Rollback
    except boundaries.Rollback:
        return None
    except DatabaseError as exc:
        return str(exc).splitlines()[0]


def test_the_runtime_role_passes_verification_and_the_owner_does_not(runtime_role):
    with connection.cursor() as cursor:
        owner_problems = runtime_role_problems(cursor)
    assert any("owns" in p for p in owner_problems)
    as_role(runtime_role)
    with connection.cursor() as cursor:
        assert runtime_role_problems(cursor) == []
    as_owner()


@pytest.mark.parametrize("label", sorted(boundaries.FORBIDDEN))
def test_the_runtime_role_is_refused(runtime_role, label):
    as_role(runtime_role)
    error = outcome(boundaries.FORBIDDEN[label])
    as_owner()
    assert error is not None, f"runtime role was able to {label}"
    assert "permission denied" in error or "must be owner" in error, error


@pytest.mark.parametrize("label", sorted(boundaries.REQUIRED))
def test_the_runtime_role_can_do_its_job(runtime_role, label):
    as_role(runtime_role)
    error = outcome(boundaries.REQUIRED[label])
    as_owner()
    assert error is None, error


def test_the_application_works_as_the_runtime_role(runtime_role, shop):
    """Sign-in, workspace access, device revocation and audit, all as the runtime role."""
    as_role(runtime_role)
    owner, member = APIClient(), APIClient()
    for client, user in ((owner, shop.owner.user), (member, shop.affiliate.user)):
        response = client.post("/api/v1/auth/login/", {"email": user.email, "password": PASSWORD})
        assert response.status_code == 200
    assert member.get(f"/api/v1/workspaces/{shop.workspace.id}/").status_code == 200
    device = WorkspaceDevice.objects.get(installation__user=shop.affiliate.user)
    revoked = owner.post(f"/api/v1/workspaces/{shop.workspace.id}/devices/{device.id}/revoke/")
    assert revoked.status_code == 200
    assert AuditEvent.objects.filter(action="device.revoked").exists()
    as_owner()


def test_the_production_deploy_check_reports_an_owner_role(runtime_role):
    with override_settings(IS_PRODUCTION=True):
        owner_errors = check_runtime_database_role(None, databases=["default"])
        as_role(runtime_role)
        runtime_errors = check_runtime_database_role(None, databases=["default"])
        as_owner()
    assert owner_errors and all(e.id == "common.E001" for e in owner_errors)
    assert runtime_errors == []


def test_the_deploy_check_is_silent_outside_production(db):
    assert check_runtime_database_role(None, databases=["default"]) == []
    assert check_runtime_database_role(None, databases=None) == []
