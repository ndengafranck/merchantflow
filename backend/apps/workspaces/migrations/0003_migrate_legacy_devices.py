"""Carry rows of the retired ``devices.Device`` model into the new structure.

Each legacy device (one row per user per workspace, with no link to a browser)
becomes one ``DeviceInstallation`` plus one ``WorkspaceDevice`` that keeps the
legacy primary key, so audit events keep pointing at a real record. Legacy
rows carry no information about which of them were the same browser, so they
are not merged. No browser holds an identifier for these installations: they
are history, and every browser gets a fresh installation at its next login.
"""

from django.db import migrations

LEGACY_TARGET = "devices.device"
NEW_TARGET = "workspaces.workspacedevice"


def forwards(apps, schema_editor):
    Device = apps.get_model("devices", "Device")
    Installation = apps.get_model("accounts", "DeviceInstallation")
    WorkspaceDevice = apps.get_model("workspaces", "WorkspaceDevice")
    AuditEvent = apps.get_model("audit", "AuditEvent")

    for legacy in Device.objects.order_by("created_at").iterator():
        installation = Installation.objects.create(
            user_id=legacy.user_id,
            label=legacy.name[:80] or "Unknown browser",
            user_agent=legacy.platform[:255],
            status=legacy.status,
            created_at=legacy.created_at,
            last_login_at=legacy.last_seen_at,
            revoked_at=legacy.revoked_at,
            revoked_by_id=legacy.revoked_by_id,
        )
        WorkspaceDevice.objects.create(
            id=legacy.id,
            workspace_id=legacy.workspace_id,
            installation=installation,
            status=legacy.status,
            last_seen_at=legacy.last_seen_at,
            revoked_at=legacy.revoked_at,
            revoked_by_id=legacy.revoked_by_id,
        )
        # auto_now_add / auto_now ignore values passed to create().
        WorkspaceDevice.objects.filter(pk=legacy.id).update(
            created_at=legacy.created_at, updated_at=legacy.updated_at
        )
    AuditEvent.objects.filter(target_type=LEGACY_TARGET).update(target_type=NEW_TARGET)


def backwards(apps, schema_editor):
    """Rebuild legacy rows, then remove what replaced them (ends bound sessions)."""
    Device = apps.get_model("devices", "Device")
    Installation = apps.get_model("accounts", "DeviceInstallation")
    WorkspaceDevice = apps.get_model("workspaces", "WorkspaceDevice")
    AuditEvent = apps.get_model("audit", "AuditEvent")

    for device in WorkspaceDevice.objects.select_related("installation").iterator():
        Device.objects.create(
            id=device.id,
            workspace_id=device.workspace_id,
            user_id=device.installation.user_id,
            name=device.installation.label,
            platform=device.installation.user_agent[:120],
            status=device.status,
            last_seen_at=device.last_seen_at,
            revoked_at=device.revoked_at,
            revoked_by_id=device.revoked_by_id,
        )
        Device.objects.filter(pk=device.id).update(
            created_at=device.created_at, updated_at=device.updated_at
        )
    installation_ids = list(WorkspaceDevice.objects.values_list("installation_id", flat=True))
    WorkspaceDevice.objects.all().delete()
    Installation.objects.filter(pk__in=installation_ids).delete()
    AuditEvent.objects.filter(target_type=NEW_TARGET).update(target_type=LEGACY_TARGET)


class Migration(migrations.Migration):
    dependencies = [
        ("workspaces", "0002_workspacedevice"),
        ("accounts", "0002_installations_and_sessions"),
        ("devices", "0001_initial"),
        ("audit", "0001_initial"),
    ]

    operations = [migrations.RunPython(forwards, backwards)]
