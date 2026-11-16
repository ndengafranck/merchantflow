from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.db import models
from django.db.models.functions import Lower
from django.utils import timezone

from apps.common.models import UUIDModel


def normalize_email(email: str) -> str:
    """Emails identify accounts case-insensitively, so store them lower-cased."""
    return email.strip().lower()


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create(self, email: str, password: str | None, **extra) -> "User":
        if not email:
            raise ValueError("An email address is required.")
        user = self.model(email=normalize_email(email), **extra)
        user.set_password(password)  # None produces an unusable password
        user.full_clean(exclude=["password"])
        user.save(using=self._db)
        return user

    def create_user(self, email: str, password: str | None = None, **extra) -> "User":
        extra.setdefault("is_staff", False)
        extra.setdefault("is_superuser", False)
        return self._create(email, password, **extra)

    def create_superuser(self, email: str, password: str | None = None, **extra) -> "User":
        extra["is_staff"] = True
        extra["is_superuser"] = True
        return self._create(email, password, **extra)

    def get_by_natural_key(self, email: str) -> "User":
        return self.get(email=normalize_email(email))


class User(UUIDModel, AbstractBaseUser, PermissionsMixin):
    """A person who can sign in. Global: not owned by any workspace.

    What a user may do inside a workspace is decided by their
    ``WorkspaceMembership``, never by fields on this model. ``is_staff`` and
    ``is_superuser`` only govern the internal Django admin.
    """

    email = models.EmailField(unique=True)
    full_name = models.CharField(max_length=150)
    phone = models.CharField(max_length=20, blank=True)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    date_joined = models.DateTimeField(default=timezone.now)

    objects = UserManager()

    USERNAME_FIELD = "email"
    EMAIL_FIELD = "email"
    REQUIRED_FIELDS = ["full_name"]

    class Meta:
        constraints = [
            # Backstop for writes that bypass the manager's normalisation.
            models.UniqueConstraint(Lower("email"), name="accounts_user_email_ci_unique"),
        ]

    def __str__(self) -> str:
        return self.email

    def clean(self) -> None:
        super().clean()
        self.email = normalize_email(self.email)
