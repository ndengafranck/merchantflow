"""System checks that keep every workspace route behind the workspace guard.

They run with ``manage.py check``, at server start and in CI.
"""

from django.core.checks import Error, register
from django.urls import URLPattern, URLResolver, get_resolver

from .access import WorkspaceAPIView
from .policies import Capability

WORKSPACE_PARAMETER = "<uuid:workspace_id>"
HANDLER_METHODS = ("get", "post", "put", "patch", "delete")


def iter_routes(patterns=None, prefix: str = ""):
    """Yield ``(route, view_class_or_None)`` for every URL pattern."""
    if patterns is None:
        patterns = get_resolver().url_patterns
    for pattern in patterns:
        route = prefix + str(pattern.pattern)
        if isinstance(pattern, URLResolver):
            yield from iter_routes(pattern.url_patterns, route)
        elif isinstance(pattern, URLPattern):
            callback = pattern.callback
            yield route, getattr(callback, "view_class", getattr(callback, "cls", None))


def is_workspace_route(route: str) -> bool:
    return "workspace_id>" in route


@register()
def check_workspace_routes(app_configs, **kwargs) -> list[Error]:
    errors = []
    for route, view_class in iter_routes():
        if not is_workspace_route(route):
            continue
        if WORKSPACE_PARAMETER not in route:
            errors.append(
                Error(
                    f"Route {route!r} must declare the workspace as {WORKSPACE_PARAMETER}.",
                    id="workspaces.E003",
                )
            )
        if view_class is None or not issubclass(view_class, WorkspaceAPIView):
            errors.append(
                Error(
                    f"Route {route!r} takes a workspace_id but is not a WorkspaceAPIView.",
                    hint="Workspace-scoped endpoints must extend WorkspaceAPIView.",
                    id="workspaces.E001",
                )
            )
            continue
        required = view_class.required_capability
        for method in HANDLER_METHODS:
            if not hasattr(view_class, method):
                continue
            capability = required.get(method.upper()) if isinstance(required, dict) else required
            if not isinstance(capability, Capability):
                errors.append(
                    Error(
                        f"{view_class.__name__}.{method} ({route!r}) declares no capability.",
                        id="workspaces.E002",
                    )
                )
    return errors
