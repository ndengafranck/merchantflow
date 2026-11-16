"""F-07: audit events cannot be changed or removed, even below the ORM."""

import pytest
from django.db import IntegrityError, connection, transaction

from apps.audit.maintenance import audit_protection_suspended
from apps.audit.models import AuditEvent
from apps.audit.services import record_event


@pytest.fixture
def events(shop):
    """``shop`` creation already wrote a workspace.created event."""
    record_event(action="test.marker", target=shop.workspace, workspace=shop.workspace)
    assert AuditEvent.objects.count() >= 2
    return AuditEvent.objects.all()


def settle_deferred_checks():
    """Rows created in this test's transaction leave deferred foreign-key checks
    pending, and PostgreSQL refuses TRUNCATE and ALTER TABLE behind them."""
    with connection.cursor() as cursor:
        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")


def refused(statement):
    settle_deferred_checks()
    with pytest.raises(IntegrityError, match="append-only"), transaction.atomic():
        statement()


def sql(text):
    def run():
        with connection.cursor() as cursor:
            cursor.execute(text)

    return run


def test_instances_cannot_be_saved_again_or_deleted(events):
    event = events.first()
    event.action = "tampered"
    with pytest.raises(TypeError):
        event.save()
    with pytest.raises(TypeError):
        event.delete()


def test_bulk_update_is_refused(events):
    """Assessment probe S8: every row was rewritten through a queryset."""
    refused(lambda: AuditEvent.objects.update(action="tampered"))
    assert not AuditEvent.objects.filter(action="tampered").exists()


def test_bulk_delete_is_refused(events):
    count = events.count()
    refused(lambda: AuditEvent.objects.all().delete())
    assert AuditEvent.objects.count() == count


def test_raw_sql_update_delete_and_truncate_are_refused(events):
    count = events.count()
    refused(sql("UPDATE audit_auditevent SET action = 'tampered'"))
    refused(sql("DELETE FROM audit_auditevent"))
    refused(sql("TRUNCATE audit_auditevent"))
    assert AuditEvent.objects.count() == count


def test_truncation_cascading_from_another_table_is_refused(events):
    count = events.count()
    refused(sql("TRUNCATE accounts_user CASCADE"))
    refused(sql("TRUNCATE workspaces_workspace CASCADE"))
    assert AuditEvent.objects.count() == count


def test_appending_still_works(shop):
    before = AuditEvent.objects.count()
    record_event(action="test.append", target=shop.workspace, workspace=shop.workspace)
    assert AuditEvent.objects.count() == before + 1


def test_the_triggers_are_installed_and_enabled(db):
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT tgname, tgenabled FROM pg_trigger "
            "WHERE tgrelid = 'audit_auditevent'::regclass AND NOT tgisinternal ORDER BY tgname"
        )
        rows = cursor.fetchall()
    assert rows == [
        ("audit_auditevent_no_truncate", "O"),
        ("audit_auditevent_no_update_or_delete", "O"),
    ]


def test_maintenance_suspension_is_scoped_and_restores_protection(events):
    settle_deferred_checks()
    with audit_protection_suspended():
        AuditEvent.objects.filter(action="test.marker").delete()
    assert not AuditEvent.objects.filter(action="test.marker").exists()
    refused(lambda: AuditEvent.objects.update(action="tampered"))


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
    # The role is dropped with the test transaction's rollback.
