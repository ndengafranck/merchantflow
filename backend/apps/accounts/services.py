from django.contrib.auth.password_validation import validate_password
from django.db import transaction

from apps.audit.services import record_event
from apps.common.exceptions import DomainError

from .models import User, normalize_email


@transaction.atomic
def register_user(*, email: str, full_name: str, password: str, phone: str = "") -> User:
    """Create an account, enforcing the password policy.

    Raises ``django.core.exceptions.ValidationError`` for a weak password,
    an invalid email or a duplicate account.
    """
    candidate = User(email=normalize_email(email), full_name=full_name.strip(), phone=phone)
    validate_password(password, user=candidate)
    return User.objects.create_user(
        email=email, password=password, full_name=full_name.strip(), phone=phone
    )


def owned_workspace_names(user: User) -> list[str]:
    """Workspaces this user owns that are not archived.

    Such a user cannot be deactivated: the workspace would have an owner who
    cannot sign in. The database enforces the same rule
    (``accounts_user_owner_stays_active`` trigger).
    """
    from apps.workspaces.models import WorkspaceMembership, WorkspaceStatus

    return list(
        WorkspaceMembership.objects.filter(user=user, role="owner")
        .exclude(workspace__status=WorkspaceStatus.ARCHIVED)
        .order_by("workspace__name")
        .values_list("workspace__name", flat=True)
    )


@transaction.atomic
def deactivate_user(*, user_id, by: User | None, reason: str) -> User:
    """Suspend an account platform-wide. Its sessions stop working at once.

    Refused while the account owns a non-archived workspace: ownership must be
    transferred first, or the workspace would have an owner who cannot sign in.
    The database enforces the same rule. Idempotent.
    """
    user = User.objects.select_for_update().get(pk=user_id)
    if not user.is_active:
        return user
    owned = owned_workspace_names(user)
    if owned:
        raise DomainError(
            "This account owns " + ", ".join(owned) + ". Transfer ownership first.",
            code="owner_cannot_be_deactivated",
        )
    user.is_active = False
    user.save(update_fields=["is_active"])
    record_event(action="user.deactivated", target=user, actor=by, metadata={"reason": reason})
    return user
