from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.common.models import TimestampedModel, UUIDModel


class WorkspaceStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    SUSPENDED = "suspended", "Suspended"
    ARCHIVED = "archived", "Archived"


class Workspace(UUIDModel, TimestampedModel):
    """A merchant's isolated tenant. Every business record belongs to one."""

    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=140, unique=True)
    status = models.CharField(
        max_length=16, choices=WorkspaceStatus.choices, default=WorkspaceStatus.ACTIVE
    )
    currency = models.CharField(max_length=3, default="XAF")

    class Meta:
        ordering = ["name"]
        constraints = [
            models.CheckConstraint(
                condition=Q(status__in=WorkspaceStatus.values), name="workspace_status_valid"
            ),
        ]

    def __str__(self) -> str:
        return self.name


class MembershipRole(models.TextChoices):
    OWNER = "owner", "Owner"
    MANAGER = "manager", "Manager"
    ATTENDANT = "attendant", "Attendant"
    AFFILIATE = "affiliate", "Affiliate"


class MembershipStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    SUSPENDED = "suspended", "Suspended"
    REMOVED = "removed", "Removed"


class WorkspaceMembership(UUIDModel, TimestampedModel):
    """A user's role inside one workspace.

    Workspace ownership has a single source of truth: the membership whose
    role is ``owner``. There is no separate ``Workspace.owner`` column that
    could drift out of step with it.
    """

    workspace = models.ForeignKey(Workspace, on_delete=models.PROTECT, related_name="memberships")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="memberships"
    )
    role = models.CharField(max_length=16, choices=MembershipRole.choices)
    status = models.CharField(
        max_length=16, choices=MembershipStatus.choices, default=MembershipStatus.ACTIVE
    )

    class Meta:
        ordering = ["created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "user"], name="membership_one_per_user_per_workspace"
            ),
            # At most one owner per workspace ...
            models.UniqueConstraint(
                fields=["workspace"],
                condition=Q(role="owner"),
                name="membership_single_owner_per_workspace",
            ),
            # ... and that owner can never be suspended or removed. Ownership
            # must be transferred first (see services.transfer_ownership).
            models.CheckConstraint(
                condition=~Q(role="owner") | Q(status="active"),
                name="membership_owner_must_be_active",
            ),
            models.CheckConstraint(
                condition=Q(role__in=MembershipRole.values), name="membership_role_valid"
            ),
            models.CheckConstraint(
                condition=Q(status__in=MembershipStatus.values), name="membership_status_valid"
            ),
        ]
        indexes = [
            models.Index(fields=["user", "status"], name="membership_user_status_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.user} @ {self.workspace} ({self.role})"

    @property
    def is_owner(self) -> bool:
        return self.role == MembershipRole.OWNER
