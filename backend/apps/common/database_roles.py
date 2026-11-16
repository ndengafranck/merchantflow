"""Least-privilege database roles: what the runtime role may do, and a check.

Two roles (docs/DEPLOYMENT.md, "Database roles"):

* the **owner role** owns the schema and every table, function and trigger,
  and is used only to run migrations and ``grant_runtime_privileges``;
* the **runtime role** is what the application connects as. It owns nothing,
  may read and write ordinary tables, may only read and insert audit events,
  and has no TRUNCATE, TRIGGER or schema CREATE privilege anywhere. Because it
  owns nothing it cannot disable or drop the audit and ownership triggers.

Neither role should be a superuser. Database superusers and whoever controls
the database server can still bypass every control here; that boundary is
outside the application.
"""

from psycopg import sql

AUDIT_TABLE = "audit_auditevent"
PROTECTED_TABLES = (
    AUDIT_TABLE,
    "workspaces_workspace",
    "workspaces_workspacemembership",
    "accounts_user",
)
PROTECTED_TRIGGERS = (
    "audit_auditevent_no_update_or_delete",
    "audit_auditevent_no_truncate",
    "workspaces_membership_keeps_one_owner",
    "workspaces_workspace_has_owner",
    "accounts_user_owner_stays_active",
)
FORBIDDEN_ON_AUDIT = ("UPDATE", "DELETE", "TRUNCATE", "TRIGGER", "REFERENCES")

# Ordinary tables of schema public, by OID (privilege functions on OIDs cannot
# fail on names of other schemas' relations, whatever order they run in).
_HAS_PRIVILEGE = "SELECT has_table_privilege(current_user, %s::regclass, %s)"
_PUBLIC_TABLES = (
    "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
    "WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p') "
)


def grant_runtime_privileges(cursor, role: str) -> None:
    """Run as the owner role after every migration. Idempotent."""
    r = sql.Identifier(role)
    statements = [
        sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(r),
        sql.SQL("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {}").format(
            r
        ),
        sql.SQL("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {}").format(r),
        sql.SQL(
            "REVOKE TRUNCATE, TRIGGER, REFERENCES ON ALL TABLES IN SCHEMA public FROM {}"
        ).format(r),
        # Audit events are append-only for the application.
        sql.SQL("REVOKE UPDATE, DELETE ON {} FROM {}").format(sql.Identifier(AUDIT_TABLE), r),
        # Only migrations (the owner) record migrations.
        sql.SQL("REVOKE INSERT, UPDATE, DELETE ON django_migrations FROM {}").format(r),
    ]
    for statement in statements:
        cursor.execute(statement)


def runtime_role_problems(cursor) -> list[str]:
    """Everything that makes the *current* role unfit to be the runtime role."""
    problems = []

    cursor.execute(
        "SELECT current_user, rolsuper, rolcreaterole, rolcreatedb "
        "FROM pg_roles WHERE rolname = current_user"
    )
    me, is_super, create_role, create_db = cursor.fetchone()
    if is_super:
        problems.append(f"{me} is a superuser; superusers bypass every database control.")
    if create_role or create_db:
        problems.append(f"{me} may create roles or databases; the runtime role needs neither.")

    cursor.execute(
        "SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND tableowner = current_user "
        "ORDER BY tablename"
    )
    owned = [row[0] for row in cursor.fetchall()]
    if owned:
        problems.append(
            f"{me} owns {len(owned)} table(s) (e.g. {', '.join(owned[:4])}); as owner it could "
            "disable or drop the audit and ownership triggers."
        )

    cursor.execute(
        "SELECT p.proname FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
        "WHERE n.nspname = 'public' AND p.proowner = (SELECT oid FROM pg_roles "
        "WHERE rolname = current_user) ORDER BY 1"
    )
    functions = [row[0] for row in cursor.fetchall()]
    if functions:
        problems.append(f"{me} owns function(s) {', '.join(functions)}.")

    cursor.execute(
        "SELECT DISTINCT tableowner FROM pg_tables WHERE schemaname = 'public' "
        "AND tablename = ANY(%s) AND tableowner <> current_user",
        [list(PROTECTED_TABLES)],
    )
    for (owner,) in cursor.fetchall():
        cursor.execute("SELECT pg_has_role(current_user, %s, 'MEMBER')", [owner])
        if cursor.fetchone()[0]:
            problems.append(f"{me} is a member of the owner role {owner} and can act as it.")

    cursor.execute("SELECT has_schema_privilege(current_user, 'public', 'CREATE')")
    if cursor.fetchone()[0]:
        problems.append(f"{me} may create objects in schema public.")

    cursor.execute("SELECT to_regclass(%s) IS NOT NULL", [AUDIT_TABLE])
    if cursor.fetchone()[0]:
        for privilege in FORBIDDEN_ON_AUDIT:
            cursor.execute(
                "SELECT has_table_privilege(current_user, %s, %s)", [AUDIT_TABLE, privilege]
            )
            if cursor.fetchone()[0]:
                problems.append(f"{me} has {privilege} on {AUDIT_TABLE}.")
        for privilege in ("SELECT", "INSERT"):
            cursor.execute(
                "SELECT has_table_privilege(current_user, %s, %s)", [AUDIT_TABLE, privilege]
            )
            if not cursor.fetchone()[0]:
                problems.append(
                    f"{me} lacks {privilege} on {AUDIT_TABLE}; run grant_runtime_privileges."
                )

    cursor.execute(
        _PUBLIC_TABLES + "AND (has_table_privilege(current_user, c.oid, 'TRUNCATE') "
        "OR has_table_privilege(current_user, c.oid, 'TRIGGER')) ORDER BY 1"
    )
    risky = [row[0] for row in cursor.fetchall()]
    if risky:
        problems.append(f"{me} has TRUNCATE or TRIGGER on {', '.join(risky[:6])}.")

    cursor.execute(
        _PUBLIC_TABLES + "AND NOT has_table_privilege(current_user, c.oid, 'SELECT') ORDER BY 1"
    )
    unreadable = [row[0] for row in cursor.fetchall()]
    if unreadable:
        problems.append(
            f"{me} cannot read {', '.join(unreadable[:6])}; run grant_runtime_privileges after "
            "migrating."
        )

    cursor.execute(
        "SELECT tgname, tgenabled FROM pg_trigger WHERE NOT tgisinternal AND tgname = ANY(%s)",
        [list(PROTECTED_TRIGGERS)],
    )
    state = dict(cursor.fetchall())
    for name in PROTECTED_TRIGGERS:
        if name not in state:
            problems.append(f"Trigger {name} is missing; apply all migrations.")
        elif state[name] != "O":
            problems.append(f"Trigger {name} is disabled.")
    return problems
