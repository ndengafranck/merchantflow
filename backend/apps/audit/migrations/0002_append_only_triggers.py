"""Make the audit table append-only in PostgreSQL itself.

Row triggers reject UPDATE and DELETE (including Django bulk operations and
raw SQL); a statement trigger rejects TRUNCATE, which also covers truncation
cascading from other tables. Only the table's owner can disable them (see
apps/audit/maintenance.py), so a deployment where the application connects
with a role that does not own the tables cannot alter the audit trail.
"""

from django.db import migrations

FORWARD = """
CREATE FUNCTION audit_auditevent_append_only() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'audit events are append-only (% refused)', TG_OP
        USING ERRCODE = 'restrict_violation';
END;
$$;

CREATE TRIGGER audit_auditevent_no_update_or_delete
    BEFORE UPDATE OR DELETE ON audit_auditevent
    FOR EACH ROW EXECUTE FUNCTION audit_auditevent_append_only();

CREATE TRIGGER audit_auditevent_no_truncate
    BEFORE TRUNCATE ON audit_auditevent
    FOR EACH STATEMENT EXECUTE FUNCTION audit_auditevent_append_only();
"""

REVERSE = """
DROP TRIGGER IF EXISTS audit_auditevent_no_truncate ON audit_auditevent;
DROP TRIGGER IF EXISTS audit_auditevent_no_update_or_delete ON audit_auditevent;
DROP FUNCTION IF EXISTS audit_auditevent_append_only();
"""


class Migration(migrations.Migration):
    dependencies = [
        ("audit", "0001_initial"),
        # 0003 rewrites legacy audit targets; it must run before rows are frozen.
        ("workspaces", "0004_device_revocation_reason"),
    ]

    operations = [migrations.RunSQL(FORWARD, REVERSE)]
