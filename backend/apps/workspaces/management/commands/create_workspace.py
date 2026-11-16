import getpass
import os

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.accounts.models import User, normalize_email
from apps.accounts.services import register_user
from apps.workspaces.services import create_workspace


class Command(BaseCommand):
    help = (
        "Create a workspace and its owner. The owner account is created if the "
        "email is new; its password is read from MF_OWNER_PASSWORD or prompted."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--name", required=True, help="Workspace name")
        parser.add_argument("--owner-email", required=True)
        parser.add_argument("--owner-name", default="", help="Required for a new account")

    @transaction.atomic
    def handle(self, *args, **options) -> None:
        email = normalize_email(options["owner_email"])
        owner = User.objects.filter(email=email).first()
        if owner is None:
            if not options["owner_name"]:
                raise CommandError("--owner-name is required to create a new account.")
            password = os.environ.get("MF_OWNER_PASSWORD") or getpass.getpass("Owner password: ")
            try:
                owner = register_user(
                    email=email, full_name=options["owner_name"], password=password
                )
            except ValidationError as exc:
                raise CommandError("; ".join(exc.messages)) from exc
            self.stdout.write(f"Created account {owner.email}")
        workspace = create_workspace(name=options["name"], owner=owner)
        self.stdout.write(
            self.style.SUCCESS(f"Created workspace '{workspace.name}' ({workspace.id})")
        )
