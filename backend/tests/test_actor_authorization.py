"""R2: services judge authority on the actor's current, locked membership."""

import threading

import pytest
from django.db import connection, transaction
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.common.exceptions import (
    ConflictError,
    DomainError,
    NotFoundError,
    NotPermittedError,
)
from apps.workspaces import device_services, services
from apps.workspaces.models import MembershipStatus, Workspace, WorkspaceMembership
from apps.workspaces.policies import Capability

from .conftest import sign_in


def stale_copy(membership) -> WorkspaceMembership:
    """What a caller holds if it loaded the membership before things changed."""
    return WorkspaceMembership.objects.select_related("user", "workspace").get(pk=membership.pk)


def sensitive_operations(shop, make_user):
    """Every owner-only service call, to be attempted with a stale actor."""
    device = device_services.ensure_workspace_device(
        installation=sign_in(APIClient(), shop.attendant.user), membership=shop.attendant
    )
    newcomer = make_user()
    return {
        "add_member": lambda actor: services.add_member(
            actor=actor, user=newcomer, role="affiliate"
        ),
        "change_member_role": lambda actor: services.change_member_role(
            actor=actor, membership_id=shop.attendant.id, role="manager"
        ),
        "set_member_status": lambda actor: services.set_member_status(
            actor=actor, membership_id=shop.attendant.id, status="removed"
        ),
        "transfer_ownership": lambda actor: services.transfer_ownership(
            actor=actor, new_owner_id=shop.attendant.id
        ),
        "revoke_workspace_device": lambda actor: device_services.revoke_workspace_device(
            actor=actor, device_id=device.id
        ),
    }


OPERATIONS = [
    "add_member",
    "change_member_role",
    "set_member_status",
    "transfer_ownership",
    "revoke_workspace_device",
]


def assert_nothing_happened(shop, operation):
    shop.attendant.refresh_from_db()
    assert (shop.attendant.role, shop.attendant.status) == ("attendant", "active"), operation


@pytest.mark.parametrize("operation", OPERATIONS)
def test_former_owner_cannot_act_with_a_stale_membership_object(shop, make_user, operation):
    """Review probe P16: the object says 'owner', the database says 'manager'."""
    operations = sensitive_operations(shop, make_user)
    former_owner = stale_copy(shop.owner)
    services.transfer_ownership(actor=shop.owner, new_owner_id=shop.manager.id)
    assert former_owner.role == "owner"  # the stale object still claims it

    if operation == "revoke_workspace_device":
        # A manager may revoke devices, so this one stays allowed after demotion.
        operations[operation](former_owner)
        return
    with pytest.raises(NotPermittedError):
        operations[operation](former_owner)
    assert_nothing_happened(shop, operation)


@pytest.mark.parametrize("operation", OPERATIONS)
@pytest.mark.parametrize(
    "how",
    # "user_deactivated" is covered below with a manager: since F-11 an owner's
    # account cannot be deactivated at all (tests/test_owner_integrity.py).
    ["membership_suspended", "membership_removed", "workspace_suspended"],
)
def test_actor_who_lost_access_is_refused_even_with_an_old_object(shop, make_user, operation, how):
    operations = sensitive_operations(shop, make_user)
    # Use the manager promoted to owner so the owner-must-be-active rule is not in the way.
    actor = stale_copy(shop.owner)
    if how.startswith("membership_"):
        services.transfer_ownership(actor=shop.owner, new_owner_id=shop.manager.id)
        WorkspaceMembership.objects.filter(pk=actor.pk).update(
            status=how.removeprefix("membership_")
        )
    else:
        Workspace.objects.filter(pk=shop.workspace.pk).update(status="suspended")

    with pytest.raises(NotPermittedError):
        operations[operation](actor)
    assert_nothing_happened(shop, operation)


def test_deactivated_account_is_refused_even_with_an_old_object(shop, make_user):
    """A manager may revoke an attendant's device; a deactivated one may not."""
    operations = sensitive_operations(shop, make_user)
    manager = stale_copy(shop.manager)
    User.objects.filter(pk=manager.user_id).update(is_active=False)
    with pytest.raises(NotPermittedError):
        operations["revoke_workspace_device"](manager)
    assert_nothing_happened(shop, "revoke_workspace_device")


def test_authorize_actor_returns_the_fresh_row(shop):
    stale = stale_copy(shop.manager)
    WorkspaceMembership.objects.filter(pk=stale.pk).update(role="attendant")
    with transaction.atomic(), pytest.raises(NotPermittedError):
        services.authorize_actor(stale, Capability.MEMBERS_VIEW)
    with transaction.atomic():
        fresh = services.authorize_actor(stale, Capability.WORKSPACE_VIEW)
    assert fresh.role == "attendant" and stale.role == "manager"


@pytest.mark.django_db(transaction=True)
def test_authorize_actor_refuses_to_run_outside_a_transaction(shop):
    with pytest.raises(RuntimeError):
        services.authorize_actor(shop.owner, Capability.MEMBERS_MANAGE)


@pytest.mark.django_db(transaction=True)
def test_action_waiting_on_a_transfer_is_refused_once_the_transfer_commits(shop):
    """Real locks: the old owner's action queues behind the transfer, then fails."""
    former_owner = stale_copy(shop.owner)
    outcome = {}

    def old_owner_acts():
        try:
            services.set_member_status(
                actor=former_owner, membership_id=shop.attendant.id, status="removed"
            )
            outcome["result"] = "applied"
        except NotPermittedError:
            outcome["result"] = "refused"
        finally:
            connection.close()

    worker = threading.Thread(target=old_owner_acts)
    with transaction.atomic():
        services.transfer_ownership(actor=shop.owner, new_owner_id=shop.manager.id)
        worker.start()
        worker.join(timeout=1.0)
        assert worker.is_alive(), "the action should be blocked on the actor's row lock"
    worker.join(timeout=10)

    assert outcome == {"result": "refused"}
    shop.attendant.refresh_from_db()
    assert shop.attendant.status == MembershipStatus.ACTIVE


# --- Domain errors over HTTP ------------------------------------------------------------


def test_domain_errors_are_plain_exceptions_with_no_http_knowledge():
    for kind in (DomainError, ConflictError, NotPermittedError, NotFoundError):
        assert not hasattr(kind, "status_code")
        assert issubclass(kind, Exception)


@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (NotPermittedError("no"), 403, "permission_denied"),
        (NotFoundError("gone"), 404, "not_found"),
        (ConflictError("already"), 409, "conflict"),
        (DomainError("bad", code="custom_rule"), 400, "custom_rule"),
    ],
)
def test_domain_errors_map_to_http_in_one_place(error, status, code):
    from apps.common.api_errors import api_exception_handler

    response = api_exception_handler(error, {})
    assert response.status_code == status
    assert response.data == {"code": code, "detail": error.detail}


def test_service_refusal_reaches_the_client_as_403(shop, client_for):
    """HTTP guard passes (role is manager-capable route), the service refuses."""
    client = client_for(shop.attendant.user)
    other = device_services.ensure_workspace_device(
        installation=sign_in(APIClient(), shop.affiliate.user), membership=shop.affiliate
    )
    response = client.post(f"/api/v1/workspaces/{shop.workspace.id}/devices/{other.id}/revoke/")
    assert response.status_code == 404  # not theirs to see, reported as not found
    assert response.json()["code"] == "not_found"
