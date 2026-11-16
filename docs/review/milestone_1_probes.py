"""Review probes. Each test asserts the behaviour OBSERVED; names say what it shows."""
import threading, uuid
import pytest
from django.db import IntegrityError, connection
from django.test import Client
from django.urls import get_resolver, URLPattern, URLResolver
from rest_framework.test import APIClient

from apps.audit.models import AuditEvent
from apps.accounts.models import User
from apps.devices import services as dsvc
from apps.workspaces import services as wsvc
from apps.workspaces.access import WorkspaceAPIView, WorkspaceAccess
from apps.workspaces.models import WorkspaceMembership
from tests.conftest import PASSWORD

LOGIN = "/api/v1/auth/login/"

def test_P01_throttle_bypassed_by_rotating_x_forwarded_for(make_user):
    c = APIClient(); codes = set()
    for i in range(40):
        r = c.post(LOGIN, {"email": "x@example.test", "password": "bad-password"}, HTTP_X_FORWARDED_FOR=f"10.0.{i}.1")
        codes.add(r.status_code)
    assert codes == {401}          # never 429

def test_P02_successful_logins_consume_the_shared_ip_budget(make_user):
    users = [make_user() for _ in range(11)]; codes = []
    for u in users:
        codes.append(APIClient().post(LOGIN, {"email": u.email, "password": PASSWORD}).status_code)
    assert codes == [200]*10 + [429]

def test_P03_orm_can_leave_workspace_without_owner(shop):
    shop.owner.role = "manager"; shop.owner.save()
    assert not WorkspaceMembership.objects.filter(workspace=shop.workspace, role="owner").exists()

def test_P03b_orm_can_delete_owner_membership(shop):
    WorkspaceMembership.objects.filter(pk=shop.owner.pk).delete()
    assert not WorkspaceMembership.objects.filter(workspace=shop.workspace, role="owner").exists()

def test_P03c_admin_ui_can_demote_owner(shop, make_user):
    admin = make_user(is_staff=True, is_superuser=True)
    c = Client(); c.force_login(admin)
    url = f"/admin/workspaces/workspacemembership/{shop.owner.pk}/change/"
    r = c.post(url, {"workspace": str(shop.workspace.pk), "user": str(shop.owner.user.pk), "role": "attendant", "status": "active"})
    assert r.status_code == 302
    assert not WorkspaceMembership.objects.filter(workspace=shop.workspace, role="owner").exists()
    assert not AuditEvent.objects.filter(target_id=shop.owner.pk).exclude(action="workspace.created").exists()

def test_P04_audit_events_mutable_via_queryset(shop):
    n = AuditEvent.objects.count(); assert n > 0
    assert AuditEvent.objects.update(action="tampered") == n
    AuditEvent.objects.all().delete()
    assert AuditEvent.objects.count() == 0

def hs(c, shop, dev): return c.post(f"/api/v1/workspaces/{shop.workspace.id}/sync/handshake/", HTTP_X_DEVICE_ID=str(dev))

def test_P05_revoked_device_holder_reregisters_and_syncs(shop, client_for):
    thief = client_for(shop.affiliate.user)   # the browser on the lost phone, session still valid
    d = dsvc.register_device(membership=shop.affiliate, name="Lost phone")
    dsvc.revoke_device(actor=shop.owner, device_id=d.id)
    assert hs(thief, shop, d.id).status_code == 403
    assert thief.get("/api/v1/auth/me/").status_code == 200           # session survives revocation
    new = thief.post(f"/api/v1/workspaces/{shop.workspace.id}/devices/", {"name": "Lost phone"}).json()
    assert hs(thief, shop, new["id"]).status_code == 200              # back in

def test_P06_any_session_of_user_can_claim_any_of_their_device_ids(shop):
    a, b = APIClient(), APIClient()
    for c in (a, b): assert c.post(LOGIN, {"email": shop.affiliate.user.email, "password": PASSWORD}).status_code == 200
    dev = a.post(f"/api/v1/workspaces/{shop.workspace.id}/devices/", {"name": "Phone A"}).json()
    ids = [d["id"] for d in b.get(f"/api/v1/workspaces/{shop.workspace.id}/devices/").json()]
    assert dev["id"] in ids and hs(b, shop, dev["id"]).status_code == 200

def test_P07_password_change_invalidates_existing_sessions(make_user):
    u = make_user(); c = APIClient()
    c.post(LOGIN, {"email": u.email, "password": PASSWORD}); assert c.get("/api/v1/auth/me/").status_code == 200
    u.set_password("another-long-passphrase"); u.save()
    assert c.get("/api/v1/auth/me/").status_code == 401

def test_P08_attacker_planted_session_id_is_replaced_at_login_and_logout_kills_session(make_user, settings):
    from django.contrib.sessions.backends.db import SessionStore
    from django.contrib.sessions.models import Session
    planted = SessionStore(); planted["x"] = 1; planted.save()          # session fixation attempt
    u = make_user(); c = APIClient(); c.cookies[settings.SESSION_COOKIE_NAME] = planted.session_key
    assert c.post(LOGIN, {"email": u.email, "password": PASSWORD}).status_code == 200
    k = c.cookies[settings.SESSION_COOKIE_NAME].value
    assert k != planted.session_key and not Session.objects.filter(session_key=planted.session_key).exists()
    c.post("/api/v1/auth/logout/"); assert not Session.objects.filter(session_key=k).exists()
    replay = APIClient(); replay.cookies[settings.SESSION_COOKIE_NAME] = k
    assert replay.get("/api/v1/auth/me/").status_code == 401

def test_P09_superuser_has_no_implicit_workspace_access(shop, make_user, client_for):
    su = make_user(is_staff=True, is_superuser=True)
    assert client_for(su).get(f"/api/v1/workspaces/{shop.workspace.id}/members/").status_code == 404

def _walk(patterns, prefix=""):
    for p in patterns:
        if isinstance(p, URLResolver): yield from _walk(p.url_patterns, prefix + str(p.pattern))
        elif isinstance(p, URLPattern): yield prefix + str(p.pattern), p.callback

def test_P10_every_workspace_route_uses_the_guard_and_all_api_routes_need_auth(db):
    public = {"api/health/", "api/v1/auth/csrf/", "api/v1/auth/login/", "api/schema/", "api/docs/"}
    seen = []
    for route, cb in _walk(get_resolver().url_patterns):
        if not route.startswith("api/"): continue
        cls = getattr(cb, "view_class", None) or getattr(cb, "cls", None)
        if "<uuid:workspace_id>" in route:
            assert issubclass(cls, WorkspaceAPIView), route
            assert WorkspaceAccess in cls.permission_classes, route
            assert cls.required_capability is not None, route
        url = "/" + route.replace("<uuid:workspace_id>", str(uuid.uuid4())).replace("<uuid:membership_id>", str(uuid.uuid4())).replace("<uuid:device_id>", str(uuid.uuid4()))
        if route in public: continue
        for m in ("get", "post", "put", "patch", "delete"):
            code = getattr(APIClient(), m)(url).status_code
            assert code == 401, (m, route, code)
        seen.append(route)
    print("\nPROTECTED ROUTES:", *seen, sep="\n  ")
    assert len(seen) == 10

def test_P11_admin_login_is_not_rate_limited(make_user):
    su = make_user(is_staff=True, is_superuser=True); c = Client(); codes = set()
    for _ in range(40):
        codes.add(c.post("/admin/login/", {"username": su.email, "password": "wrong-guess"}).status_code)
    assert codes == {200}   # form re-rendered every time, never throttled
    assert c.post("/admin/login/", {"username": su.email, "password": PASSWORD}).status_code == 302

def test_P12_removed_member_devices_stay_active_and_revive(shop, client_for):
    d = dsvc.register_device(membership=shop.affiliate, name="P")
    wsvc.set_member_status(actor=shop.owner, membership_id=shop.affiliate.id, status="removed")
    d.refresh_from_db(); assert d.status == "active"
    wsvc.set_member_status(actor=shop.owner, membership_id=shop.affiliate.id, status="active")
    assert hs(client_for(shop.affiliate.user), shop, d.id).status_code == 200

def test_P13_malformed_and_wrong_type_bodies(shop, client_for):
    c = client_for(shop.owner.user)
    r = c.put("/api/v1/workspaces/current/", data="{not json", content_type="application/json")
    assert (r.status_code, r.json()["code"]) == (400, "parse_error")
    r = c.put("/api/v1/workspaces/current/", data="a=b", content_type="application/x-www-form-urlencoded")
    assert r.status_code == 415
    r = c.patch(f"/api/v1/workspaces/{shop.workspace.id}/members/{shop.attendant.id}/", data="[1,2]", content_type="application/json")
    print("\nLIST BODY ->", r.status_code, r.content[:200])

def test_P14_unlimited_device_registration(shop, client_for):
    c = client_for(shop.affiliate.user)
    assert {c.post(f"/api/v1/workspaces/{shop.workspace.id}/devices/", {"name": f"d{i}"}).status_code for i in range(60)} == {201}

def test_P15_deactivated_owner_leaves_workspace_unmanageable(shop):
    User.objects.filter(pk=shop.owner.user.pk).update(is_active=False)
    o = WorkspaceMembership.objects.get(pk=shop.owner.pk)
    assert (o.role, o.status, o.user.is_active) == ("owner", "active", False)

def test_P16_stale_actor_object_still_authorises(shop):
    """Owner object loaded before a transfer keeps owner powers in the service layer."""
    stale_owner = WorkspaceMembership.objects.select_related("user", "workspace").get(pk=shop.owner.pk)
    wsvc.transfer_ownership(actor=shop.owner, new_owner_id=shop.manager.id)
    wsvc.set_member_status(actor=stale_owner, membership_id=shop.attendant.id, status="removed")  # no error
    shop.attendant.refresh_from_db(); assert shop.attendant.status == "removed"

# ---- concurrency (real commits, real locks) ----
def _run(fns):
    out = [None]*len(fns); barrier = threading.Barrier(len(fns))
    def work(i, fn):
        try:
            barrier.wait(); out[i] = ("ok", fn())
        except Exception as e:  # noqa
            out[i] = (type(e).__name__, getattr(e, "code", ""))
        finally:
            connection.close()
    ts = [threading.Thread(target=work, args=(i, f)) for i, f in enumerate(fns)]
    [t.start() for t in ts]; [t.join() for t in ts]
    return out

@pytest.mark.django_db(transaction=True)
def test_P17_concurrent_ownership_transfers_leave_exactly_one_owner(shop):
    for _ in range(5):
        owner = WorkspaceMembership.objects.get(workspace=shop.workspace, role="owner")
        others = list(WorkspaceMembership.objects.filter(workspace=shop.workspace).exclude(pk=owner.pk)[:3])
        res = _run([lambda o=o: wsvc.transfer_ownership(actor=owner, new_owner_id=o.id) for o in others])
        kinds = sorted(r[0] for r in res)
        assert kinds.count("ok") == 1, res
        assert WorkspaceMembership.objects.filter(workspace=shop.workspace, role="owner").count() == 1
        print("\nTRANSFER RACE:", res)

@pytest.mark.django_db(transaction=True)
def test_P18_concurrent_add_member_surfaces_raw_integrity_error(shop, make_user):
    seen = set()
    for _ in range(8):
        u = make_user()
        res = _run([lambda: wsvc.add_member(actor=shop.owner, user=u, role="affiliate")]*6)
        assert WorkspaceMembership.objects.filter(workspace=shop.workspace, user=u).count() == 1
        seen |= {r[0] for r in res}
    print("\nADD_MEMBER RACE OUTCOMES:", seen)

@pytest.mark.django_db(transaction=True)
def test_P19_concurrent_revoke_audited_once(shop):
    d = dsvc.register_device(membership=shop.affiliate, name="P")
    res = _run([lambda: dsvc.revoke_device(actor=shop.owner, device_id=d.id)]*6)
    assert all(r[0] == "ok" for r in res)
    assert AuditEvent.objects.filter(action="device.revoked", target_id=d.id).count() == 1
