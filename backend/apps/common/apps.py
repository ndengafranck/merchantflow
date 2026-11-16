from django.apps import AppConfig


class CommonConfig(AppConfig):
    name = "apps.common"
    label = "common"

    def ready(self) -> None:
        from . import checks, schema  # noqa: F401  (registers the deploy check and OpenAPI scheme)
