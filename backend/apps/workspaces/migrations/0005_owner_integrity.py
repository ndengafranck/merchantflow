"""Ownership integrity enforced by PostgreSQL.

1. At commit, every workspace has exactly one active owner membership, and
   unless the workspace is archived, that owner's account is active. The
   check is a deferred constraint trigger, so an ownership transfer (demote,
   then promote, in one transaction) passes while any committed state without
   an owner is refused, whichever code path produced it.
2. An account that owns a non-archived workspace cannot be deactivated.

Constraint triggers are not evaluated against rows that already exist, so the
migration first locks the tables against writes and refuses to continue if any
existing workspace already breaks rule 1 (``preflight``). It never repairs data.
The whole migration is one transaction: a refusal leaves nothing installed.
"""

from django.db import migrations

# Frozen copy of apps.workspaces.ownership_checks.OWNER_VIOLATIONS_SQL at the
# time of this migration (tests/test_owner_migration.py checks they match).
PREFLIGHT_SQL = """
SELECT w.id,
       w.name,
       w.status,
       count(m.id) AS active_owner_memberships,
       count(m.id) FILTER (WHERE NOT u.is_active) AS inactive_owner_accounts,
       coalesce(array_agg(m.id::text ORDER BY m.id) FILTER (WHERE m.id IS NOT NULL), '{}')
           AS owner_membership_ids
  FROM workspaces_workspace w
  LEFT JOIN workspaces_workspacemembership m
         ON m.workspace_id = w.id AND m.role = 'owner' AND m.status = 'active'
  LEFT JOIN accounts_user u ON u.id = m.user_id
 GROUP BY w.id, w.name, w.status
HAVING count(m.id) <> 1
    OR (w.status <> 'archived' AND count(m.id) FILTER (WHERE NOT u.is_active) > 0)
 ORDER BY w.name, w.id
"""


class OwnershipPreflightError(RuntimeError):
    """Existing data breaks the rule this migration is about to enforce."""


def preflight(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        # Block writes (reads continue) until this migration commits, so no
        # invalid row can appear between the check and the trigger creation.
        cursor.execute(
            "LOCK TABLE workspaces_workspace, workspaces_workspacemembership, accounts_user "
            "IN SHARE ROW EXCLUSIVE MODE"
        )
        cursor.execute(PREFLIGHT_SQL)
        columns = [c.name for c in cursor.description]
        violations = [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]
    if not violations:
        return
    lines = []
    for v in violations[:50]:
        problems = []
        if v["active_owner_memberships"] == 0:
            problems.append("no active owner membership")
        elif v["active_owner_memberships"] > 1:
            problems.append(f"{v['active_owner_memberships']} active owner memberships")
        if v["status"] != "archived" and v["inactive_owner_accounts"]:
            problems.append("owner account is inactive")
        owners = ", ".join(v["owner_membership_ids"]) or "none"
        lines.append(
            f"  - workspace {v['id']} \"{v['name']}\" (status {v['status']}): "
            f"{'; '.join(problems)}; owner membership ids: {owners}"
        )
    if len(violations) > 50:
        lines.append(f"  ... and {len(violations) - 50} more")
    raise OwnershipPreflightError(
        f"workspaces.0005 refused: {len(violations)} existing workspace(s) break the "
        "ownership rule it enforces. Nothing was changed.\n"
        + "\n".join(lines)
        + "\nRepair them as described in docs/DEPLOYMENT.md (\"Repairing workspace "
        "ownership\"), confirm with `manage.py check_workspace_owners`, then migrate again. "
        "No data is repaired automatically."
    )

FORWARD = """
CREATE FUNCTION workspaces_assert_single_active_owner(ws uuid) RETURNS void
LANGUAGE plpgsql AS $$
DECLARE
    ws_status text;
    owners integer;
    inactive_owner_accounts integer;
BEGIN
    SELECT status INTO ws_status FROM workspaces_workspace WHERE id = ws;
    IF NOT FOUND THEN
        RETURN;
    END IF;
    SELECT count(*),
           count(*) FILTER (WHERE NOT u.is_active)
      INTO owners, inactive_owner_accounts
      FROM workspaces_workspacemembership m
      JOIN accounts_user u ON u.id = m.user_id
     WHERE m.workspace_id = ws AND m.role = 'owner' AND m.status = 'active';
    IF owners <> 1 THEN
        RAISE EXCEPTION 'workspace % must have exactly one active owner (found %)', ws, owners
            USING ERRCODE = 'check_violation';
    END IF;
    IF ws_status <> 'archived' AND inactive_owner_accounts > 0 THEN
        RAISE EXCEPTION 'the owner of workspace % must have an active account', ws
            USING ERRCODE = 'check_violation';
    END IF;
END;
$$;

CREATE FUNCTION workspaces_membership_owner_check() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP IN ('UPDATE', 'DELETE') THEN
        PERFORM workspaces_assert_single_active_owner(OLD.workspace_id);
    END IF;
    IF TG_OP IN ('INSERT', 'UPDATE') AND (TG_OP = 'INSERT' OR NEW.workspace_id <> OLD.workspace_id) THEN
        PERFORM workspaces_assert_single_active_owner(NEW.workspace_id);
    END IF;
    RETURN NULL;
END;
$$;

CREATE FUNCTION workspaces_workspace_owner_check() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    PERFORM workspaces_assert_single_active_owner(NEW.id);
    RETURN NULL;
END;
$$;

CREATE CONSTRAINT TRIGGER workspaces_membership_keeps_one_owner
    AFTER INSERT OR UPDATE OR DELETE ON workspaces_workspacemembership
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION workspaces_membership_owner_check();

CREATE CONSTRAINT TRIGGER workspaces_workspace_has_owner
    AFTER INSERT OR UPDATE OF status ON workspaces_workspace
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION workspaces_workspace_owner_check();

CREATE FUNCTION accounts_user_owner_stays_active() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF EXISTS (
        SELECT 1
          FROM workspaces_workspacemembership m
          JOIN workspaces_workspace w ON w.id = m.workspace_id
         WHERE m.user_id = NEW.id AND m.role = 'owner' AND w.status <> 'archived'
    ) THEN
        RAISE EXCEPTION 'account % owns a workspace and cannot be deactivated', NEW.id
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER accounts_user_owner_stays_active
    BEFORE UPDATE OF is_active ON accounts_user
    FOR EACH ROW WHEN (OLD.is_active AND NOT NEW.is_active)
    EXECUTE FUNCTION accounts_user_owner_stays_active();
"""

REVERSE = """
DROP TRIGGER IF EXISTS accounts_user_owner_stays_active ON accounts_user;
DROP FUNCTION IF EXISTS accounts_user_owner_stays_active();
DROP TRIGGER IF EXISTS workspaces_workspace_has_owner ON workspaces_workspace;
DROP TRIGGER IF EXISTS workspaces_membership_keeps_one_owner ON workspaces_workspacemembership;
DROP FUNCTION IF EXISTS workspaces_workspace_owner_check();
DROP FUNCTION IF EXISTS workspaces_membership_owner_check();
DROP FUNCTION IF EXISTS workspaces_assert_single_active_owner(uuid);
"""


class Migration(migrations.Migration):
    dependencies = [
        ("workspaces", "0004_device_revocation_reason"),
        ("accounts", "0003_login_attempt_buckets"),
    ]

    operations = [
        migrations.RunPython(preflight, migrations.RunPython.noop),
        migrations.RunSQL(FORWARD, REVERSE),
    ]
