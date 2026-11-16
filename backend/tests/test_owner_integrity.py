"""F-10 and F-11: a workspace always keeps exactly one active owner."""

import threading

import pytest
from django.db import IntegrityError, connection, transaction
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.accounts.services import deactivate_user
from apps.audit.models import AuditEvent
from apps.common.exceptions import DomainError
from apps.workspaces import services
from apps.workspaces.models import Workspace, WorkspaceMembership

from .conftest import sign_in

OWNERLESS = "exactly one active owner"


def committed(change):
    """Run ``change`` and evaluate the deferred checks as a commit would."""
    try:
        with transaction.atomic():
            change()
            with connection.cursor() as cursor:
                cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
    finally:
        # Outside the (possibly rolled-back) savepoint: the test's transaction
        # continues, so restore commit-time checking for what follows.
        with connection.cursor() as cursor:
            cursor.execute("SET CONSTRAINTS ALL DEFERRED")


def refused(change, match=OWNERLESS):
    with pytest.raises(IntegrityError, match=match):
        committed(change)


# --- F-10: every committed state has one active owner -------------------------------------------


def test_owner_cannot_be_demoted_below_the_services(shop):
    """Assessment probe S6 reached this state through the admin."""
    refused(lambda: WorkspaceMembership.objects.filter(pk=shop.owner.pk).update(role="manager"))
    shop.owner.refresh_from_db()
    assert shop.owner.role == "owner"


def test_owner_membership_cannot_be_deleted(shop):
    refused(lambda: WorkspaceMembership.objects.filter(pk=shop.owner.pk).delete())
    assert WorkspaceMembership.objects.filter(pk=shop.owner.pk).exists()


def test_owner_membership_cannot_be_moved_to_another_workspace(shop, other_shop):
    def move():
        WorkspaceMembership.objects.filter(pk=shop.owner.pk).update(workspace=other_shop.workspace)

    with pytest.raises(IntegrityError):  # second owner there, or none left here
        committed(move)


def test_a_workspace_cannot_be_created_without_an_owner(db):
    refused(lambda: Workspace.objects.create(name="Orphan", slug="orphan"))


def test_an_inactive_account_cannot_be_made_owner_directly(shop, make_user):
    inactive = make_user(is_active=False)

    def swap():
        WorkspaceMembership.objects.filter(pk=shop.owner.pk).update(role="manager")
        WorkspaceMembership.objects.create(workspace=shop.workspace, user=inactive, role="owner")

    refused(swap, match="active account")


def test_supported_operations_still_pass_the_checks(shop, make_user):
    committed(lambda: services.transfer_ownership(actor=shop.owner, new_owner_id=shop.manager.id))
    committed(lambda: services.create_workspace(name="New Shop", owner=make_user()))
    owners = WorkspaceMembership.objects.filter(workspace=shop.workspace, role="owner")
    assert list(owners.values_list("pk", flat=True)) == [shop.manager.pk]


@pytest.mark.django_db(transaction=True)
def test_checks_are_enforced_at_a_real_commit(shop):
    with pytest.raises(IntegrityError, match=OWNERLESS), transaction.atomic():
        WorkspaceMembership.objects.filter(pk=shop.owner.pk).update(role="manager")
    shop.owner.refresh_from_db()
    assert shop.owner.role == "owner"
    services.transfer_ownership(actor=shop.owner, new_owner_id=shop.manager.id)  # commits
    assert WorkspaceMembership.objects.get(workspace=shop.workspace, role="owner") == shop.manager


# --- F-11: the owner's account cannot be deactivated ----------------------------------------------


def test_owner_account_cannot_be_deactivated_below_the_services(shop):
    """Assessment probe S11 orphaned the workspace this way."""
    with pytest.raises(IntegrityError, match="cannot be deactivated"), transaction.atomic():
        User.objects.filter(pk=shop.owner.user_id).update(is_active=False)
    assert User.objects.get(pk=shop.owner.user_id).is_active


def test_deactivate_user_refuses_an_owner_with_a_clear_error(shop):
    with pytest.raises(DomainError) as excinfo:
        deactivate_user(user_id=shop.owner.user_id, by=None, reason="test")
    assert excinfo.value.code == "owner_cannot_be_deactivated"
    assert "Akwa Phones" in excinfo.value.detail


def test_deactivate_user_works_for_members_and_ends_their_sessions(shop):
    client = APIClient()
    sign_in(client, shop.affiliate.user)
    assert client.get("/api/v1/auth/me/").status_code == 200

    deactivate_user(user_id=shop.affiliate.user_id, by=shop.owner.user, reason="left the shop")
    deactivate_user(user_id=shop.affiliate.user_id, by=shop.owner.user, reason="again")

    assert client.get("/api/v1/auth/me/").status_code == 401
    events = AuditEvent.objects.filter(action="user.deactivated", target_id=shop.affiliate.user_id)
    assert events.count() == 1
    assert events.get().metadata == {"reason": "left the shop", "sessions_ended": 1}
    from apps.accounts.models import UserSession

    assert not UserSession.objects.filter(user_id=shop.affiliate.user_id).exists()


def test_owner_can_be_deactivated_after_transferring_ownership(shop):
    services.transfer_ownership(actor=shop.owner, new_owner_id=shop.manager.id)
    deactivate_user(user_id=shop.owner.user_id, by=None, reason="retired")
    assert not User.objects.get(pk=shop.owner.user_id).is_active


def test_owner_of_an_archived_workspace_may_be_deactivated(shop):
    Workspace.objects.filter(pk=shop.workspace.pk).update(status="archived")
    deactivate_user(user_id=shop.owner.user_id, by=None, reason="shop closed")
    assert not User.objects.get(pk=shop.owner.user_id).is_active


# --- Concurrency: transfer against deactivation of the successor ----------------------------------


def _in_thread(fn, outcome):
    def run():
        try:
            fn()
            outcome["result"] = "applied"
        except (DomainError, IntegrityError) as exc:
            outcome["result"] = getattr(exc, "code", type(exc).__name__)
        finally:
            connection.close()

    return threading.Thread(target=run)


@pytest.mark.django_db(transaction=True)
def test_deactivation_waiting_on_a_transfer_is_refused(shop):
    outcome = {}
    worker = _in_thread(
        lambda: deactivate_user(user_id=shop.manager.user_id, by=None, reason="race"), outcome
    )
    with transaction.atomic():
        services.transfer_ownership(actor=shop.owner, new_owner_id=shop.manager.id)
        worker.start()
        worker.join(timeout=1.0)
        assert worker.is_alive(), "deactivation should wait for the transfer"
    worker.join(timeout=10)
    assert outcome == {"result": "owner_cannot_be_deactivated"}
    assert User.objects.get(pk=shop.manager.user_id).is_active


@pytest.mark.django_db(transaction=True)
def test_transfer_waiting_on_a_deactivation_is_refused(shop):
    outcome = {}
    worker = _in_thread(
        lambda: services.transfer_ownership(actor=shop.owner, new_owner_id=shop.manager.id),
        outcome,
    )
    with transaction.atomic():
        deactivate_user(user_id=shop.manager.user_id, by=None, reason="race")
        worker.start()
        worker.join(timeout=1.0)
        assert worker.is_alive(), "the transfer should wait for the deactivation"
    worker.join(timeout=10)
    assert outcome == {"result": "successor_inactive"}
    owner = WorkspaceMembership.objects.get(workspace=shop.workspace, role="owner")
    assert owner.pk == shop.owner.pk
