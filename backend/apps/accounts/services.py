from django.contrib.auth.password_validation import validate_password
from django.db import transaction

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
