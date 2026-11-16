import itertools

import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from apps.accounts.models import DeviceInstallation, User
from apps.accounts.session_store import INSTALLATION_SESSION_KEY
from apps.workspaces.models import MembershipRole, WorkspaceMembership
from apps.workspaces.services import create_workspace

PASSWORD = "correct-horse-battery"
_sequence = itertools.count(1)


@pytest.fixture(autouse=True)
def _fast_password_hashing(settings):
    """Production hashing is deliberately slow; tests do not need that."""
    settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]


@pytest.fixture(autouse=True)
def _clear_cache():
    """Throttle counters live in the cache; keep tests independent."""
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def make_user(db):
    def _make(email: str | None = None, **extra) -> User:
        n = next(_sequence)
        extra.setdefault("full_name", f"Test User {n}")
        return User.objects.create_user(email or f"user{n}@example.test", PASSWORD, **extra)

    return _make


@pytest.fixture
def make_member(make_user):
    def _make(workspace, role: str, **extra) -> WorkspaceMembership:
        return WorkspaceMembership.objects.create(
            workspace=workspace, user=make_user(), role=role, **extra
        )

    return _make


def sign_in(client: APIClient, user: User, installation=None) -> DeviceInstallation:
    """Give the client a session bound to a browser installation, as login does."""
    if installation is None:
        installation = DeviceInstallation.objects.create(user=user, label="Test browser")
    client.force_login(user)
    session = client.session
    session[INSTALLATION_SESSION_KEY] = str(installation.pk)
    session.save()
    client.installation = installation
    return installation


@pytest.fixture
def client_for():
    """An API client signed in as the given user on its own browser installation."""

    def _client(user: User | None = None) -> APIClient:
        client = APIClient()
        if user is not None:
            sign_in(client, user)
        return client

    return _client


@pytest.fixture
def shop(make_user, make_member):
    """A workspace with one member of every role."""
    owner = make_user()
    workspace = create_workspace(name="Akwa Phones", owner=owner)

    class Shop:
        pass

    s = Shop()
    s.workspace = workspace
    s.owner = WorkspaceMembership.objects.select_related("user", "workspace").get(
        workspace=workspace, role=MembershipRole.OWNER
    )
    s.manager = make_member(workspace, MembershipRole.MANAGER)
    s.attendant = make_member(workspace, MembershipRole.ATTENDANT)
    s.affiliate = make_member(workspace, MembershipRole.AFFILIATE)
    s.by_role = {m.role: m for m in (s.owner, s.manager, s.attendant, s.affiliate)}
    return s


@pytest.fixture
def other_shop(make_user, make_member):
    """A second, unrelated tenant."""
    owner = make_user()
    workspace = create_workspace(name="Bonanjo Mobile", owner=owner)

    class Shop:
        pass

    s = Shop()
    s.workspace = workspace
    s.owner = WorkspaceMembership.objects.get(workspace=workspace, role=MembershipRole.OWNER)
    s.affiliate = make_member(workspace, MembershipRole.AFFILIATE)
    return s
