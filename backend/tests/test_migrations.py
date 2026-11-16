"""The legacy ``devices.Device`` rows survive the move to installations."""

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

AUDIT = ("audit", "0001_initial")
BEFORE = [("workspaces", "0002_workspacedevice"), ("devices", "0001_initial"), AUDIT]
AFTER = [("workspaces", "0003_migrate_legacy_devices"), ("devices", "0002_remove_device"), AUDIT]


def migrate(targets):
    executor = MigrationExecutor(connection)
    executor.migrate(targets)
    return MigrationExecutor(connection).loader.project_state(targets).apps


@pytest.mark.django_db(transaction=True)
def test_legacy_devices_become_installations_and_workspace_devices():
    try:
        old = migrate(BEFORE)
        user = old.get_model("accounts", "User").objects.create(
            email="legacy@example.test", full_name="Legacy User", password="!"
        )
        workspace = old.get_model("workspaces", "Workspace").objects.create(
            name="Legacy Shop", slug="legacy-shop"
        )
        Device = old.get_model("devices", "Device")
        now = timezone.now()
        active = Device.objects.create(
            workspace=workspace,
            user=user,
            name="Tecno Spark",
            platform="Android Chrome",
            last_seen_at=now,
        )
        revoked = Device.objects.create(
            workspace=workspace,
            user=user,
            name="Old laptop",
            status="revoked",
            revoked_at=now,
            revoked_by=user,
        )
        old.get_model("audit", "AuditEvent").objects.create(
            action="device.registered", target_type="devices.device", target_id=active.id
        )

        new = migrate(AFTER)
        WorkspaceDevice = new.get_model("workspaces", "WorkspaceDevice")
        Installation = new.get_model("accounts", "DeviceInstallation")

        assert "devices_device" not in connection.introspection.table_names()
        assert Installation.objects.count() == 2
        kept = WorkspaceDevice.objects.select_related("installation").get(pk=active.id)
        assert kept.status == "active" and kept.last_seen_at == now
        assert (kept.installation.user_id, kept.installation.label) == (user.id, "Tecno Spark")
        gone = WorkspaceDevice.objects.select_related("installation").get(pk=revoked.id)
        assert gone.status == gone.installation.status == "revoked"
        assert gone.revoked_by_id == user.id
        event = new.get_model("audit", "AuditEvent").objects.get(target_id=active.id)
        assert event.target_type == "workspaces.workspacedevice"

        back = migrate(BEFORE)
        restored = back.get_model("devices", "Device").objects.order_by("name")
        assert [(d.name, d.status) for d in restored] == [
            ("Old laptop", "revoked"),
            ("Tecno Spark", "active"),
        ]
        assert back.get_model("workspaces", "WorkspaceDevice").objects.count() == 0
    finally:
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
