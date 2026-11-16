from django.apps import AppConfig


class WorkspacesConfig(AppConfig):
    name = "apps.workspaces"
    label = "workspaces"

    def ready(self) -> None:
        from . import checks  # noqa: F401  (registers the route-guard system checks)
