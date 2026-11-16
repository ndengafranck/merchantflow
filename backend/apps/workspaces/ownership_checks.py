"""Find workspaces that break the ownership rule enforced by the database.

The rule (migration ``workspaces.0005``, function
``workspaces_assert_single_active_owner``):

* every workspace has exactly one membership with ``role = 'owner'`` and
  ``status = 'active'``;
* unless the workspace is ``archived``, that owner's account is active.

``OWNER_VIOLATIONS_SQL`` mirrors that rule exactly. ``workspaces.0005`` runs a
frozen copy of it before installing its triggers (a test asserts the copies
are identical), and ``manage.py check_workspace_owners`` runs it on demand.
"""

OWNER_VIOLATIONS_SQL = """
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

REMEDIATION = """\
How to repair (see docs/DEPLOYMENT.md, "Repairing workspace ownership"):
  * No active owner: decide which existing member should own the workspace and
    set exactly that membership to role 'owner', status 'active'.
  * More than one owner: keep the rightful owner and set the others to
    role 'manager'.
  * Owner account inactive on a non-archived workspace: reactivate the
    account, transfer ownership to an active member, or archive the workspace.
Nothing is repaired automatically. Re-run `manage.py check_workspace_owners`
until it reports no problems, then run `manage.py migrate` again."""


def find_owner_violations(cursor) -> list[dict]:
    cursor.execute(OWNER_VIOLATIONS_SQL)
    columns = [c.name for c in cursor.description]
    return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]


def describe_violations(violations: list[dict], limit: int = 50) -> str:
    lines = []
    for v in violations[:limit]:
        problems = []
        if v["active_owner_memberships"] == 0:
            problems.append("no active owner membership")
        elif v["active_owner_memberships"] > 1:
            problems.append(f"{v['active_owner_memberships']} active owner memberships")
        if v["status"] != "archived" and v["inactive_owner_accounts"]:
            problems.append("owner account is inactive")
        owners = ", ".join(v["owner_membership_ids"]) or "none"
        lines.append(
            f'  - workspace {v["id"]} "{v["name"]}" (status {v["status"]}): '
            f"{'; '.join(problems)}; owner membership ids: {owners}"
        )
    if len(violations) > limit:
        lines.append(f"  ... and {len(violations) - limit} more")
    return "\n".join(lines)
