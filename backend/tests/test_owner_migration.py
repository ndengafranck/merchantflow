"""C1: workspaces.0005 refuses to install its ownership triggers over invalid data."""

import importlib
import uuid

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

from apps.workspaces.ownership_checks import OWNER_VIOLATIONS_SQL

pytestmark = pytest.mark.django_db(transaction=True)

BEFORE = [("workspaces", "0004_device_revocation_reason")]
TARGET = [("workspaces", "0005_owner_integrity")]
OWNER_TRIGGERS = {
    "workspaces_membership_keeps_one_owner",
    "workspaces_workspace_has_owner",
    "accounts_user_owner_stays_active",
}
migration_module = importlib.import_module("apps.workspaces.migrations.0005_owner_integrity")
PreflightError = migration_module.OwnershipPreflightError


def migrate(targets):
    executor = MigrationExecutor(connection)
    executor.migrate(targets)
    return MigrationExecutor(connection).loader.project_state(targets).apps


def installed_triggers() -> set[str]:
    with connection.cursor() as cursor:
        cursor.execute("SELECT tgname FROM pg_trigger WHERE NOT tgisinternal")
        return {row[0] for row in cursor.fetchall()} & OWNER_TRIGGERS


def recorded(name: str) -> bool:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT 1 FROM django_migrations WHERE app = 'workspaces' AND name = %s", [name]
        )
        return cursor.fetchone() is not None


@pytest.fixture
def legacy():
    """The database just before workspaces.0005, with a factory for rows."""
    old = migrate(BEFORE)
    assert installed_triggers() == set()
    User = old.get_model("accounts", "User")
    Workspace = old.get_model("workspaces", "Workspace")
    Membership = old.get_model("workspaces", "WorkspaceMembership")

    class Factory:
        def user(self, active=True):
            n = uuid.uuid4().hex[:8]
            return User.objects.create(
                email=f"legacy-{n}@example.test", full_name="Legacy", password="!", is_active=active
            )

        def workspace(self, name, status="active", owners=1, owner_active=True):
            ws = Workspace.objects.create(name=name, slug=f"{uuid.uuid4().hex[:10]}", status=status)
            for _ in range(owners):
                Membership.objects.create(
                    workspace=ws, user=self.user(owner_active), role="owner", status="active"
                )
            Membership.objects.create(workspace=ws, user=self.user(), role="manager")
            return ws

    yield Factory()

    # Remove the legacy rows (no ownership triggers at this state), then
    # bring the schema back to the latest state for the other tests.
    migrate(BEFORE)
    with connection.cursor() as cursor:
        cursor.execute("DELETE FROM workspaces_workspacemembership")
        cursor.execute("DELETE FROM workspaces_workspace")
        cursor.execute("DELETE FROM accounts_user")
    executor = MigrationExecutor(connection)
    executor.migrate(executor.loader.graph.leaf_nodes())


def refused(expect_in_message: list[str]) -> str:
    with pytest.raises(PreflightError) as excinfo:
        migrate(TARGET)
    message = str(excinfo.value)
    for fragment in expect_in_message:
        assert fragment in message, message
    # Nothing was installed and the migration is not recorded as applied.
    assert installed_triggers() == set()
    assert not recorded("0005_owner_integrity")
    assert "Nothing was changed" in message and "docs/DEPLOYMENT.md" in message
    return message


def test_valid_existing_workspaces_migrate(legacy):
    legacy.workspace("Akwa Phones")
    legacy.workspace("Closed Shop", status="archived", owner_active=False)
    migrate(TARGET)
    assert installed_triggers() == OWNER_TRIGGERS
    assert recorded("0005_owner_integrity")


def test_workspace_without_an_owner_is_refused_with_diagnostics(legacy):
    good = legacy.workspace("Akwa Phones")
    bad = legacy.workspace("Bonanjo Mobile", owners=0)
    message = refused([str(bad.id), '"Bonanjo Mobile"', "no active owner membership", "1 existing"])
    assert str(good.id) not in message


def test_inactive_owner_account_on_an_active_workspace_is_refused(legacy):
    bad = legacy.workspace("Deido Gadgets", owner_active=False)
    refused([str(bad.id), "owner account is inactive", "status active"])


def test_suspended_workspace_with_an_inactive_owner_is_refused(legacy):
    """Only 'archived' is exempt from the active-account rule, as in the trigger."""
    bad = legacy.workspace("Paused Shop", status="suspended", owner_active=False)
    refused([str(bad.id), "owner account is inactive"])


def test_archived_workspace_with_an_inactive_owner_is_accepted(legacy):
    legacy.workspace("Closed Shop", status="archived", owner_active=False)
    migrate(TARGET)
    assert installed_triggers() == OWNER_TRIGGERS


def test_archived_workspace_without_an_owner_is_still_refused(legacy):
    bad = legacy.workspace("Closed Shop", status="archived", owners=0)
    refused([str(bad.id), "no active owner membership"])


def test_several_owners_are_refused(legacy):
    """Impossible since workspaces.0001's unique index, but a database restored from
    elsewhere could lack it; the preflight does not rely on the index."""
    with connection.cursor() as cursor:
        cursor.execute("DROP INDEX membership_single_owner_per_workspace")
    try:
        bad = legacy.workspace("Twin Owners", owners=2)
        refused([str(bad.id), "2 active owner memberships"])
    finally:
        with connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM workspaces_workspacemembership WHERE workspace_id = %s", [bad.id]
            )
            cursor.execute(
                "CREATE UNIQUE INDEX membership_single_owner_per_workspace "
                "ON workspaces_workspacemembership (workspace_id) WHERE role = 'owner'"
            )


def test_every_problem_is_listed_and_a_retry_succeeds_after_repair(legacy):
    first = legacy.workspace("A Shop", owners=0)
    second = legacy.workspace("B Shop", owner_active=False)
    message = refused([str(first.id), str(second.id), "2 existing"])
    assert message.index("A Shop") < message.index("B Shop")

    # Operator repair, as documented: give A Shop an owner, reactivate B Shop's owner.
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE workspaces_workspacemembership SET role = 'owner' "
            "WHERE workspace_id = %s AND role = 'manager'",
            [first.id],
        )
        cursor.execute(
            "UPDATE accounts_user SET is_active = true WHERE id IN (SELECT user_id FROM "
            "workspaces_workspacemembership WHERE workspace_id = %s AND role = 'owner')",
            [second.id],
        )
    call_command("check_workspace_owners")
    migrate(TARGET)
    assert installed_triggers() == OWNER_TRIGGERS


def test_check_command_reports_problems_without_changing_anything(legacy):
    bad = legacy.workspace("Bonanjo Mobile", owners=0)
    with pytest.raises(CommandError) as excinfo:
        call_command("check_workspace_owners")
    assert str(bad.id) in str(excinfo.value)
    assert "Nothing is repaired automatically" in str(excinfo.value)
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT count(*) FROM workspaces_workspacemembership WHERE workspace_id = %s",
            [bad.id],
        )
        assert cursor.fetchone()[0] == 1  # unchanged: only the manager


def test_the_migration_and_the_command_use_the_same_rule(db):
    assert migration_module.PREFLIGHT_SQL == OWNER_VIOLATIONS_SQL
