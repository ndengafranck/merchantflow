from django.core.management.base import BaseCommand, CommandError
from django.db import connection

from apps.common.database_roles import runtime_role_problems


class Command(BaseCommand):
    help = (
        "Run with the application's own database credentials. Fails unless the role "
        "is a least-privilege runtime role that cannot alter audit or ownership "
        "protection. Read-only."
    )

    def handle(self, *args, **options) -> None:
        with connection.cursor() as cursor:
            problems = runtime_role_problems(cursor)
        if problems:
            raise CommandError(
                "The database role is not a safe runtime role:\n- " + "\n- ".join(problems)
            )
        self.stdout.write(self.style.SUCCESS("Database role is a least-privilege runtime role."))
