from django.core.management.base import BaseCommand
from django.db import connection, transaction

from apps.common.database_roles import grant_runtime_privileges


class Command(BaseCommand):
    help = (
        "Grant the runtime (application) database role exactly the privileges it needs. "
        "Run as the owner role, after every `migrate`. Idempotent."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--role", required=True, help="Name of the runtime role")

    def handle(self, *args, **options) -> None:
        with transaction.atomic(), connection.cursor() as cursor:
            grant_runtime_privileges(cursor, options["role"])
        self.stdout.write(self.style.SUCCESS(f"Runtime privileges granted to {options['role']}."))
