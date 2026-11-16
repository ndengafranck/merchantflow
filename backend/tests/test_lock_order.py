"""C6: membership changes and device revocation follow one lock order.

Real PostgreSQL, committed transactions, separate connections per thread.
These tests show specific interleavings and run a randomised mix; they do not
prove the absence of every possible race.
"""

import random
import threading

import pytest
from django.db import OperationalError, connection, transaction
from rest_framework.test import APIClient

from apps.audit.models import AuditEvent
from apps.common.exceptions import DomainError
from apps.workspaces import device_services, services
from apps.workspaces.models import WorkspaceDevice, WorkspaceMembership

from .conftest import sign_in

pytestmark = pytest.mark.django_db(transaction=True)


def device_for(membership) -> WorkspaceDevice:
    installation = sign_in(APIClient(), membership.user)
    return device_services.ensure_workspace_device(installation=installation, membership=membership)


def run_while_holding(hold, other, *, expect_wait=True):
    """Run ``hold`` in an open transaction, start ``other`` in a thread, check
    whether it waits, commit, then return what ``other`` did."""
    outcome = {}

    def work():
        try:
            outcome["result"] = ("ok", other())
        except DomainError as exc:
            outcome["result"] = ("refused", exc.code)
        finally:
            connection.close()

    worker = threading.Thread(target=work)
    with transaction.atomic():
        hold()
        worker.start()
        worker.join(timeout=1.0)
        waited = worker.is_alive()
    worker.join(timeout=15)
    assert waited is expect_wait, "the second operation should wait for the first"
    return outcome["result"]


def test_revocation_waits_for_a_promotion_and_then_respects_the_new_rank(shop):
    """The race confirmed in review: before C6 the manager revoked the device of
    someone who, by the time it committed, was a manager too."""
    device = device_for(shop.attendant)
    result = run_while_holding(
        lambda: services.change_member_role(
            actor=shop.owner, membership_id=shop.attendant.id, role="manager"
        ),
        lambda: device_services.revoke_workspace_device(actor=shop.manager, device_id=device.id),
    )
    assert result == ("refused", "not_found")
    device.refresh_from_db()
    assert device.status == "active"


def test_a_promotion_waits_for_a_revocation_already_under_way(shop):
    device = device_for(shop.attendant)
    result = run_while_holding(
        lambda: device_services.revoke_workspace_device(actor=shop.manager, device_id=device.id),
        lambda: services.change_member_role(
            actor=shop.owner, membership_id=shop.attendant.id, role="manager"
        ),
    )
    assert result[0] == "ok"
    device.refresh_from_db()
    assert device.status == "revoked"
    event = AuditEvent.objects.get(action="device.revoked", target_id=device.id)
    assert event.metadata["holder_role"] == "attendant"  # rank at the moment of revocation


def test_reauthorization_waits_for_a_removal_and_is_then_refused(shop):
    device = device_for(shop.attendant)
    device_services.revoke_workspace_device(actor=shop.owner, device_id=device.id)
    result = run_while_holding(
        lambda: services.set_member_status(
            actor=shop.owner, membership_id=shop.attendant.id, status="removed"
        ),
        lambda: device_services.reauthorize_workspace_device(actor=shop.owner, device_id=device.id),
    )
    assert result == ("refused", "member_not_active")
    device.refresh_from_db()
    assert device.status == "revoked"


def test_removal_waits_for_a_revocation_and_revokes_nothing_twice(shop):
    first, second = device_for(shop.attendant), device_for(shop.attendant)
    result = run_while_holding(
        lambda: device_services.revoke_workspace_device(actor=shop.manager, device_id=first.id),
        lambda: services.set_member_status(
            actor=shop.owner, membership_id=shop.attendant.id, status="removed"
        ),
    )
    assert result[0] == "ok"
    reasons = {
        d.pk: d.revocation_reason
        for d in WorkspaceDevice.objects.filter(pk__in=[first.pk, second.pk])
    }
    assert reasons == {first.pk: "manual", second.pk: "membership_removed"}
    assert AuditEvent.objects.filter(action="device.revoked").count() == 2


def test_a_removed_member_cannot_end_up_with_an_active_device(shop):
    """First entry and removal racing: the first-entry path waits, then refuses."""
    installation = sign_in(APIClient(), shop.attendant.user)
    membership = WorkspaceMembership.objects.select_related("workspace", "user").get(
        pk=shop.attendant.pk
    )
    result = run_while_holding(
        lambda: services.set_member_status(
            actor=shop.owner, membership_id=shop.attendant.id, status="removed"
        ),
        lambda: device_services.ensure_workspace_device(
            installation=installation, membership=membership
        ),
    )
    assert result == ("refused", "not_found")
    assert not WorkspaceDevice.objects.filter(installation=installation).exists()


def test_randomised_mix_never_deadlocks_or_breaks_the_rules(shop):
    """Many rounds of the six operations at once against one member."""
    rng = random.Random(20261116)  # noqa: S311 - reproducible test scheduling, not security
    target = shop.attendant
    unexpected = []

    def op_role():
        role = rng.choice(["manager", "attendant"])
        services.change_member_role(actor=shop.owner, membership_id=target.id, role=role)

    def op_remove():
        services.set_member_status(actor=shop.owner, membership_id=target.id, status="removed")

    def op_reinstate():
        services.set_member_status(actor=shop.owner, membership_id=target.id, status="active")

    def op_revoke():
        devices = list(WorkspaceDevice.objects.filter(installation__user=target.user))
        if devices:
            device_services.revoke_workspace_device(
                actor=shop.manager, device_id=rng.choice(devices).id
            )

    def op_reauthorize():
        devices = list(WorkspaceDevice.objects.filter(installation__user=target.user))
        if devices:
            device_services.reauthorize_workspace_device(
                actor=shop.owner, device_id=rng.choice(devices).id
            )

    def op_enter():
        installation = sign_in(APIClient(), target.user)
        fresh = WorkspaceMembership.objects.select_related("workspace", "user").get(pk=target.pk)
        if fresh.status == "active":
            device_services.ensure_workspace_device(installation=installation, membership=fresh)

    operations = [op_role, op_remove, op_reinstate, op_revoke, op_reauthorize, op_enter]

    for _ in range(25):
        barrier = threading.Barrier(6)

        def run(fn, barrier=barrier):
            try:
                barrier.wait()
                fn()
            except DomainError:
                pass  # refusals are expected outcomes of a race
            except OperationalError as exc:  # deadlocks and lock timeouts land here
                unexpected.append(repr(exc))
            except Exception as exc:  # noqa: BLE001 - anything else is a finding
                unexpected.append(repr(exc))
            finally:
                connection.close()

        threads = [threading.Thread(target=run, args=(rng.choice(operations),)) for _ in range(6)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
        assert not any(t.is_alive() for t in threads), "an operation hung"

        target.refresh_from_db()
        active = WorkspaceDevice.objects.filter(installation__user=target.user, status="active")
        if target.status == "removed":
            assert not active.exists(), "a removed member kept an active device"

    assert unexpected == []
    for event in AuditEvent.objects.filter(action="device.revoked", actor=shop.manager.user):
        assert event.metadata["holder_role"] in ("attendant", "affiliate"), event.metadata
