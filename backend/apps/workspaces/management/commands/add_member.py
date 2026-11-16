import getpass
import os

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.accounts.models import User, normalize_email
from apps.accounts.services import register_user
from apps.common.exceptions import DomainError
from apps.workspaces.models import MembershipRole, Workspace, WorkspaceMembership
from apps.workspaces.services import add_member


class Command(BaseCommand):
    help = (
        "Add a member to a workspace on behalf of its owner. Interim tool until "
        "the invitation flow exists (see docs/OPEN_DECISIONS.md). A new account's "
        "password is read from MF_MEMBER_PASSWORD or prompted."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--workspace", required=True, help="Workspace slug")
        parser.add_argument("--email", required=True)
        parser.add_argument("--name", default="", help="Required for a new account")
        parser.add_argument(
            "--role",
            required=True,
            choices=[r for r in MembershipRole.values if r != MembershipRole.OWNER],
        )

    @transaction.atomic
    def handle(self, *args, **options) -> None:
        try:
            workspace = Workspace.objects.get(slug=options["workspace"])
        except Workspace.DoesNotExist as exc:
            raise CommandError("No workspace with that slug.") from exc
        owner = WorkspaceMembership.objects.select_related("user", "workspace").get(
            workspace=workspace, role=MembershipRole.OWNER
        )
        email = normalize_email(options["email"])
        user = User.objects.filter(email=email).first()
        if user is None:
            if not options["name"]:
                raise CommandError("--name is required to create a new account.")
            password = os.environ.get("MF_MEMBER_PASSWORD") or getpass.getpass("Password: ")
            try:
                user = register_user(email=email, full_name=options["name"], password=password)
            except ValidationError as exc:
                raise CommandError("; ".join(exc.messages)) from exc
        try:
            membership = add_member(actor=owner, user=user, role=options["role"])
        except DomainError as exc:
            raise CommandError(exc.detail) from exc
        self.stdout.write(
            self.style.SUCCESS(f"Added {user.email} to '{workspace.name}' as {membership.role}")
        )
