"""Invariants under real concurrency: committed transactions on PostgreSQL."""

import threading

import pytest
from django.db import connection
from rest_framework.test import APIClient

from apps.accounts import installations
from apps.accounts.models import DeviceInstallation, UserSession
from apps.audit.models import AuditEvent
from apps.common.exceptions import ConflictError, NotPermittedError
from apps.workspaces import device_services, services
from apps.workspaces.models import WorkspaceDevice, WorkspaceMembership

from .conftest import sign_in

pytestmark = pytest.mark.django_db(transaction=True)


def run_concurrently(callables):
    """Start every callable at the same instant; return ("ok", value) or the exception."""
    results = [None] * len(callables)
    barrier = threading.Barrier(len(callables))

    def work(index, fn):
        try:
            barrier.wait()
            results[index] = ("ok", fn())
        except Exception as exc:  # noqa: BLE001 - the exception is the result
            results[index] = (type(exc), exc)
        finally:
            connection.close()

    threads = [threading.Thread(target=work, args=(i, fn)) for i, fn in enumerate(callables)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)
    assert all(result is not None for result in results), "a worker did not finish"
    return results


def test_concurrent_ownership_transfers_leave_exactly_one_owner(shop):
    for _ in range(5):
        owner = WorkspaceMembership.objects.get(workspace=shop.workspace, role="owner")
        others = list(
            WorkspaceMembership.objects.filter(workspace=shop.workspace).exclude(pk=owner.pk)
        )
        results = run_concurrently(
            [
                lambda owner=owner, other=other: services.transfer_ownership(
                    actor=owner, new_owner_id=other.id
                )
                for other in others
            ]
        )
        kinds = [kind for kind, _ in results]
        assert kinds.count("ok") == 1, results
        assert kinds.count(NotPermittedError) == len(others) - 1, results
        assert (
            WorkspaceMembership.objects.filter(workspace=shop.workspace, role="owner").count() == 1
        )
    assert AuditEvent.objects.filter(action="workspace.ownership_transferred").count() == 5


def test_concurrent_add_member_never_surfaces_a_database_error(shop, make_user):
    """Review finding D-02: the loser gets a domain conflict, not an IntegrityError."""
    for _ in range(6):
        user = make_user()
        results = run_concurrently(
            [lambda user=user: services.add_member(actor=shop.owner, user=user, role="affiliate")]
            * 6
        )
        kinds = [kind for kind, _ in results]
        assert kinds.count("ok") == 1, results
        assert set(kinds) <= {"ok", ConflictError}, results
        assert WorkspaceMembership.objects.filter(workspace=shop.workspace, user=user).count() == 1


def test_concurrent_first_entry_creates_one_workspace_device(shop):
    """A browser opening several requests at once is still one device."""
    for _ in range(5):
        installation = sign_in(APIClient(), shop.affiliate.user)
        results = run_concurrently(
            [
                lambda installation=installation: device_services.ensure_workspace_device(
                    installation=installation, membership=shop.affiliate
                )
            ]
            * 6
        )
        assert {kind for kind, _ in results} == {"ok"}, results
        assert len({device.id for _, device in results}) == 1
        assert WorkspaceDevice.objects.filter(installation=installation).count() == 1
        assert (
            AuditEvent.objects.filter(
                action="device.authorized", target_id=results[0][1].id
            ).count()
            == 1
        )


def test_concurrent_workspace_device_revocations_are_audited_once(shop):
    installation = sign_in(APIClient(), shop.affiliate.user)
    device = device_services.ensure_workspace_device(
        installation=installation, membership=shop.affiliate
    )
    results = run_concurrently(
        [lambda: device_services.revoke_workspace_device(actor=shop.owner, device_id=device.id)] * 6
    )
    assert {kind for kind, _ in results} == {"ok"}
    assert AuditEvent.objects.filter(action="device.revoked", target_id=device.id).count() == 1


def test_concurrent_installation_revocations_end_sessions_once(make_user):
    user = make_user()
    client = APIClient()
    installation = sign_in(client, user)
    results = run_concurrently(
        [lambda: installations.revoke_installation(user=user, installation_id=installation.id)] * 6
    )
    assert {kind for kind, _ in results} == {"ok"}
    assert not UserSession.objects.filter(installation=installation).exists()
    assert AuditEvent.objects.filter(action="installation.revoked").count() == 1
    assert DeviceInstallation.objects.get(pk=installation.pk).status == "revoked"
    assert client.get("/api/v1/auth/me/").status_code == 401
