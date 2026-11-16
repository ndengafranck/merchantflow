from django.core.management.base import BaseCommand

from apps.accounts.login_protection import purge_expired


class Command(BaseCommand):
    help = "Delete sign-in attempt counters whose window has ended. Schedule it, e.g. hourly."

    def handle(self, *args, **options) -> None:
        self.stdout.write(f"Removed {purge_expired()} expired sign-in counters.")
