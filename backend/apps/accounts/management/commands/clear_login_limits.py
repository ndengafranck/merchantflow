from django.core.management.base import BaseCommand, CommandError

from apps.accounts.login_protection import clear_limits
from apps.accounts.models import User, normalize_email
from apps.audit.services import record_event
from apps.common.net import address_bucket


class Command(BaseCommand):
    help = (
        "Operator recovery for a person locked out by failed sign-ins from unknown "
        "browsers. Clears the account's counters (and one address's, if given). "
        "Audited. There is deliberately no HTTP equivalent."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--email", required=True)
        parser.add_argument("--reason", required=True, help="Why, for the audit trail")
        parser.add_argument("--address", help="Also clear this client address's counters")

    def handle(self, *args, **options) -> None:
        email = normalize_email(options["email"])
        user = User.objects.filter(email=email).first()
        if user is None:
            raise CommandError("No account with that email.")
        if not options["reason"].strip():
            raise CommandError("--reason must say why the limits are cleared.")
        address = address_bucket(options["address"]) if options["address"] else None
        removed = clear_limits(identifier=email, address=address)
        record_event(
            action="auth.login_limits_cleared",
            target=user,
            metadata={
                "reason": options["reason"].strip(),
                "address": address,
                "counters_removed": removed,
                "channel": "manage.py",
            },
        )
        self.stdout.write(f"Cleared {removed} sign-in counter(s) for {email}.")
