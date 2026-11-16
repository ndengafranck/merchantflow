from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.contrib.sessions.base_session import AbstractBaseSession
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


class InstallationStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    REVOKED = "revoked", "Revoked"


class DeviceInstallation(UUIDModel):
    """One browser installation used by one user.

    The server recognises an installation by the identifier cookie it set at
    an earlier login. The identifier is not a credential: it is consulted only
    after the password has been verified, and it never authenticates a request.
    Every session is bound to exactly one installation, so revoking the
    installation ends its sessions.

    An installation is global to the user. What it may do in a particular
    workspace is recorded by ``workspaces.WorkspaceDevice``.
    """

    user = models.ForeignKey(
        "accounts.User", on_delete=models.PROTECT, related_name="installations"
    )
    label = models.CharField(max_length=80)
    user_agent = models.CharField(max_length=255, blank=True)
    status = models.CharField(
        max_length=16, choices=InstallationStatus.choices, default=InstallationStatus.ACTIVE
    )
    created_at = models.DateTimeField(default=timezone.now)
    last_login_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="revoked_installations",
    )

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(status="active", revoked_at__isnull=True, revoked_by__isnull=True)
                    | models.Q(status="revoked", revoked_at__isnull=False, revoked_by__isnull=False)
                ),
                name="installation_revocation_consistent",
            ),
        ]
        indexes = [models.Index(fields=["user", "status"], name="installation_user_status_idx")]

    def __str__(self) -> str:
        return f"{self.label} ({self.status})"

    @property
    def is_active(self) -> bool:
        return self.status == InstallationStatus.ACTIVE


class UserSession(AbstractBaseSession):
    """Server-side session that records whose it is and which device holds it.

    Django's stock session row is opaque. These two columns are what make
    "revoke this device" and "end this user's sessions" possible.
    """

    user = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.CASCADE, related_name="sessions"
    )
    installation = models.ForeignKey(
        DeviceInstallation,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="sessions",
    )

    class Meta(AbstractBaseSession.Meta):
        db_table = "accounts_usersession"

    @classmethod
    def get_session_store_class(cls):
        from .session_store import SessionStore

        return SessionStore


class LoginAttemptBucket(models.Model):
    """Failed sign-in attempts for one key within one time window.

    Kept in PostgreSQL so every application process shares the counts. Keys
    are opaque (HMAC of the identifier and/or a network address), so the
    table holds no email addresses or phone numbers. Rows with an expired
    window are meaningless and are removed by ``manage.py purge_login_attempts``.
    """

    key = models.CharField(max_length=128, primary_key=True)
    window_started_at = models.DateTimeField()
    failures = models.PositiveIntegerField(default=0)

    class Meta:
        indexes = [models.Index(fields=["window_started_at"], name="login_bucket_window_idx")]

    def __str__(self) -> str:
        return f"{self.key}: {self.failures}"
