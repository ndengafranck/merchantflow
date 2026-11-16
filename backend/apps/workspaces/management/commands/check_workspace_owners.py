from django.core.management.base import BaseCommand, CommandError
from django.db import connection

from apps.workspaces.ownership_checks import (
    REMEDIATION,
    describe_violations,
    find_owner_violations,
)


class Command(BaseCommand):
    help = (
        "Report workspaces that break the ownership rule (exactly one active owner, "
        "with an active account unless archived). Read-only. Exit status 1 if any do. "
        "Run before migrating to workspaces.0005, and at any time afterwards."
    )

    def handle(self, *args, **options) -> None:
        with connection.cursor() as cursor:
            violations = find_owner_violations(cursor)
        if violations:
            raise CommandError(
                f"{len(violations)} workspace(s) break the ownership rule:\n"
                + describe_violations(violations)
                + "\n"
                + REMEDIATION
            )
        self.stdout.write(self.style.SUCCESS("Every workspace has exactly one active owner."))
