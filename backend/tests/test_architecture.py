"""Structural guarantees: the workspace guard cannot be skipped by accident."""

import ast
import sys
import types
from pathlib import Path

import pytest
from django.core.checks import run_checks
from django.test import override_settings
from django.urls import clear_url_caches, path
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.test import APIClient, APIRequestFactory, force_authenticate
from rest_framework.views import APIView

from apps.accounts.models import DeviceInstallation
from apps.workspaces.access import WorkspaceAccess, WorkspaceAPIView
from apps.workspaces.checks import check_workspace_routes, is_workspace_route, iter_routes
from apps.workspaces.policies import Capability

from .isolation import WORKSPACE_ENDPOINTS

BACKEND = Path(__file__).resolve().parent.parent

# Reachable without signing in. Adding to this list is a security decision.
PUBLIC_API_ROUTES = {
    "api/health/",
    "api/v1/auth/csrf/",
    "api/v1/auth/login/",
    "api/schema/",
    "api/docs/",
}


def api_routes():
    return [(route, view) for route, view in iter_routes() if route.startswith("api/")]


# --- Route coverage ---------------------------------------------------------------


def test_every_workspace_route_is_served_by_the_guarded_base_class():
    workspace_routes = [(r, v) for r, v in api_routes() if is_workspace_route(r)]
    assert len(workspace_routes) >= 6
    for route, view in workspace_routes:
        assert issubclass(view, WorkspaceAPIView), route
        permissions = view().get_permissions()
        assert isinstance(permissions[1], WorkspaceAccess), route
        assert view.required_capability is not None, route


def test_every_workspace_route_is_in_the_isolation_contract():
    """A new workspace endpoint must be added to tests/isolation.py."""
    in_urlconf = {route for route, _ in api_routes() if is_workspace_route(route)}
    in_contract = {endpoint.route for endpoint in WORKSPACE_ENDPOINTS}
    assert in_urlconf == in_contract


def test_every_handler_of_every_workspace_route_is_in_the_isolation_contract():
    covered = {(e.route, e.method) for e in WORKSPACE_ENDPOINTS}
    for route, view in api_routes():
        if not is_workspace_route(route):
            continue
        for method in ("get", "post", "put", "patch", "delete"):
            if hasattr(view, method):
                assert (route, method) in covered, f"{method.upper()} {route}"


def test_every_non_public_api_route_requires_authentication(db):
    import uuid

    checked = 0
    for route, _ in api_routes():
        if route in PUBLIC_API_ROUTES:
            continue
        url = "/" + route
        while "<uuid:" in url:
            start = url.index("<uuid:")
            url = url[:start] + str(uuid.uuid4()) + url[url.index(">", start) + 1 :]
        for method in ("get", "post", "put", "patch", "delete"):
            status = getattr(APIClient(), method)(url).status_code
            assert status == 401, f"{method.upper()} {route} answered {status} anonymously"
        checked += 1
    assert checked >= 12


def test_project_passes_its_own_route_checks():
    assert check_workspace_routes(None) == []
    assert not [m for m in run_checks() if m.id.startswith("workspaces.")]


# --- The guard cannot be replaced ---------------------------------------------------


@pytest.mark.parametrize(
    "attribute",
    ["get_permissions", "check_permissions", "initial", "authentication_classes"],
)
def test_subclass_cannot_replace_guard_machinery(attribute):
    with pytest.raises(TypeError, match="workspace guard cannot be replaced"):
        type("Sneaky", (WorkspaceAPIView,), {attribute: lambda self, *a, **k: []})


class _PermissiveView(WorkspaceAPIView):
    """Tries to open itself up the way a careless edit would."""

    permission_classes = [AllowAny]
    required_capability = Capability.MEMBERS_MANAGE

    def get(self, request, workspace_id):
        return Response({"reached": True})


def test_permission_classes_on_a_subclass_only_add_checks(shop, make_user):
    factory = APIRequestFactory()
    view = _PermissiveView.as_view()

    anonymous = view(factory.get("/"), workspace_id=shop.workspace.id)
    assert anonymous.status_code == 401

    def as_user(user):
        request = factory.get("/")
        installation = DeviceInstallation.objects.create(user=user, label="Test browser")
        force_authenticate(request, user=user, token=installation)
        return view(request, workspace_id=shop.workspace.id)

    assert as_user(make_user()).status_code == 404  # not a member
    assert as_user(shop.affiliate.user).status_code == 403  # member without the capability
    assert as_user(shop.owner.user).data == {"reached": True}


def test_guard_refuses_authentication_that_is_not_device_bound(shop):
    request = APIRequestFactory().get("/")
    force_authenticate(request, user=shop.owner.user)  # request.auth is None
    response = _PermissiveView.as_view()(request, workspace_id=shop.workspace.id)
    assert response.status_code == 403


def test_capability_mapping_answers_405_for_unlisted_methods(shop):
    class ReadOnly(WorkspaceAPIView):
        required_capability = {"GET": Capability.WORKSPACE_VIEW}

        def get(self, request, workspace_id):
            return Response({})

        def post(self, request, workspace_id):  # pragma: no cover - must not run
            raise AssertionError("reached a handler with no declared capability")

    request = APIRequestFactory().post("/")
    installation = DeviceInstallation.objects.create(user=shop.owner.user, label="Test browser")
    force_authenticate(request, user=shop.owner.user, token=installation)
    assert ReadOnly.as_view()(request, workspace_id=shop.workspace.id).status_code == 405


# --- The system check catches unguarded routes ----------------------------------------


class _Unguarded(APIView):
    def get(self, request, workspace_id):  # pragma: no cover
        return Response({})


class _NoCapability(WorkspaceAPIView):
    def get(self, request, workspace_id):  # pragma: no cover
        return Response({})


class _PartialCapability(WorkspaceAPIView):
    required_capability = {"GET": Capability.WORKSPACE_VIEW}

    def get(self, request, workspace_id):  # pragma: no cover
        return Response({})

    def delete(self, request, workspace_id):  # pragma: no cover
        return Response({})


@pytest.fixture
def faulty_urlconf():
    module = types.ModuleType("tests._faulty_urls")
    module.urlpatterns = [
        path("api/v1/workspaces/<uuid:workspace_id>/leak/", _Unguarded.as_view()),
        path("api/v1/workspaces/<uuid:workspace_id>/nocap/", _NoCapability.as_view()),
        path("api/v1/workspaces/<uuid:workspace_id>/partial/", _PartialCapability.as_view()),
        path("api/v1/workspaces/<str:workspace_id>/loose/", _NoCapability.as_view()),
    ]
    sys.modules[module.__name__] = module
    with override_settings(ROOT_URLCONF=module.__name__):
        clear_url_caches()
        yield
    clear_url_caches()
    del sys.modules[module.__name__]


def test_system_check_reports_unguarded_and_undeclared_routes(faulty_urlconf):
    errors = check_workspace_routes(None)
    found = {(error.id, error.msg) for error in errors}
    assert any(i == "workspaces.E001" and "leak" in m for i, m in found)
    assert any(i == "workspaces.E002" and "_NoCapability.get" in m for i, m in found)
    assert any(i == "workspaces.E002" and "_PartialCapability.delete" in m for i, m in found)
    assert not any("_PartialCapability.get" in m for _, m in found)
    assert any(i == "workspaces.E003" and "loose" in m for i, m in found)


# --- Layering ---------------------------------------------------------------------------

DOMAIN_MODULES = [
    "apps/common/exceptions.py",
    "apps/common/models.py",
    "apps/accounts/models.py",
    "apps/accounts/services.py",
    "apps/accounts/installations.py",
    "apps/accounts/session_store.py",
    "apps/audit/models.py",
    "apps/audit/services.py",
    "apps/workspaces/models.py",
    "apps/workspaces/policies.py",
    "apps/workspaces/selectors.py",
    "apps/workspaces/services.py",
    "apps/workspaces/device_services.py",
    "apps/workspaces/locking.py",
    "apps/workspaces/ownership_checks.py",
    "apps/common/database_roles.py",
    "apps/workspaces/context.py",
]
HTTP_PACKAGES = ("rest_framework", "django.http", "drf_spectacular")


@pytest.mark.parametrize("module", DOMAIN_MODULES)
def test_domain_modules_do_not_import_the_http_layer(module):
    tree = ast.parse((BACKEND / module).read_text())
    imported = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    offending = [name for name in imported if name.startswith(HTTP_PACKAGES)]
    assert not offending, f"{module} imports {offending}"


def test_every_service_module_is_listed_as_a_domain_module():
    """New service modules must be added to DOMAIN_MODULES above."""
    services = {str(p.relative_to(BACKEND)) for p in (BACKEND / "apps").glob("*/*services.py")}
    assert services <= set(DOMAIN_MODULES)
