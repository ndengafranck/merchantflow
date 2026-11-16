"""Audit events for sign-in and sign-out, through the API and the Django admin."""

from django.contrib.auth.signals import user_logged_in, user_logged_out
from django.dispatch import receiver

from apps.audit.services import record_event
from apps.common.net import client_ip


def _channel(request) -> str:
    return "admin" if request.path.startswith("/" + _admin_prefix()) else "api"


def _admin_prefix() -> str:
    from django.conf import settings

    return settings.ADMIN_PATH


@receiver(user_logged_in)
def audit_login(sender, request, user, **kwargs) -> None:
    if request is None:
        return
    record_event(
        action="auth.login_succeeded",
        target=user,
        actor=user,
        metadata={"channel": _channel(request), "ip": client_ip(request)},
    )


@receiver(user_logged_out)
def audit_logout(sender, request, user, **kwargs) -> None:
    if request is None or user is None:
        return
    record_event(
        action="auth.logout",
        target=user,
        actor=user,
        metadata={"channel": _channel(request), "ip": client_ip(request)},
    )
