"""Browser installations: recognising them at login and revoking them."""

import re
from uuid import UUID

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.audit.services import record_event
from apps.common.exceptions import NotFoundError

from .models import DeviceInstallation, InstallationStatus, User, UserSession
from .session_store import INSTALLATION_SESSION_KEY

_BROWSERS = [("Edg", "Edge"), ("OPR", "Opera"), ("Firefox", "Firefox"), ("Chrome", "Chrome")]
_SYSTEMS = [
    ("Android", "Android"),
    ("iPhone", "iPhone"),
    ("iPad", "iPad"),
    ("Windows", "Windows"),
    ("Mac OS X", "macOS"),
    ("Linux", "Linux"),
]


def describe_user_agent(user_agent: str) -> str:
    """A short human label such as "Chrome on Android". Display only."""
    browser = next((name for token, name in _BROWSERS if token in user_agent), None)
    if browser is None and re.search(r"Version/[\d.]+.*Safari", user_agent):
        browser = "Safari"
    system = next((name for token, name in _SYSTEMS if token in user_agent), None)
    if browser and system:
        return f"{browser} on {system}"
    return browser or system or "Unknown browser"


def _parse_uuid(value: str | None) -> UUID | None:
    try:
        return UUID(value) if value else None
    except ValueError:
        return None


@transaction.atomic
def bind_session_to_installation(request, user: User) -> DeviceInstallation:
    """Attach the freshly authenticated session to this browser's installation.

    Called by the login view after the password check. The identifier cookie
    is honoured only if it names an active installation of the same user;
    anything else (absent, malformed, another user's, revoked) results in a
    new installation, so a revoked installation can never be resumed.
    """
    presented = _parse_uuid(request.COOKIES.get(settings.DEVICE_COOKIE_NAME))
    installation = None
    if presented is not None:
        installation = (
            DeviceInstallation.objects.select_for_update()
            .filter(pk=presented, user=user, status=InstallationStatus.ACTIVE)
            .first()
        )
    now = timezone.now()
    user_agent = request.headers.get("User-Agent", "")[:255]
    if installation is None:
        installation = DeviceInstallation.objects.create(
            user=user,
            label=describe_user_agent(user_agent),
            user_agent=user_agent,
            last_login_at=now,
        )
        record_event(action="installation.registered", target=installation, actor=user)
    else:
        installation.last_login_at = now
        installation.user_agent = user_agent
        installation.save(update_fields=["last_login_at", "user_agent"])
    request.session[INSTALLATION_SESSION_KEY] = str(installation.pk)
    return installation


def set_installation_cookie(response, installation: DeviceInstallation) -> None:
    response.set_cookie(
        settings.DEVICE_COOKIE_NAME,
        str(installation.pk),
        max_age=settings.DEVICE_COOKIE_AGE,
        httponly=True,
        secure=settings.SESSION_COOKIE_SECURE,
        samesite="Lax",
    )


def installation_for_session(session, user: User) -> DeviceInstallation | None:
    """The active installation this session is bound to, or ``None``."""
    installation_id = _parse_uuid(session.get(INSTALLATION_SESSION_KEY))
    if installation_id is None:
        return None
    return DeviceInstallation.objects.filter(
        pk=installation_id, user=user, status=InstallationStatus.ACTIVE
    ).first()


@transaction.atomic
def revoke_installation(*, user: User, installation_id) -> DeviceInstallation:
    """Revoke one of the user's own installations and end its sessions.

    Idempotent. Sessions are deleted in the same transaction, so there is no
    moment at which the installation is revoked but still signed in.
    """
    try:
        installation = DeviceInstallation.objects.select_for_update().get(
            pk=installation_id, user=user
        )
    except DeviceInstallation.DoesNotExist as exc:
        raise NotFoundError("Device not found.") from exc
    if installation.status == InstallationStatus.REVOKED:
        return installation
    installation.status = InstallationStatus.REVOKED
    installation.revoked_at = timezone.now()
    installation.revoked_by = user
    installation.save(update_fields=["status", "revoked_at", "revoked_by"])
    UserSession.objects.filter(installation=installation).delete()
    record_event(action="installation.revoked", target=installation, actor=user)
    return installation
