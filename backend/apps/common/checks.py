"""Deployment check of the database role (runs with `check --deploy --database default`)."""

from django.conf import settings
from django.core.checks import Error, Tags, register
from django.db import connections


@register(Tags.database, deploy=True)
def check_runtime_database_role(app_configs, databases=None, **kwargs) -> list[Error]:
    if not databases or not getattr(settings, "IS_PRODUCTION", False):
        return []
    from .database_roles import runtime_role_problems

    errors = []
    for alias in databases:
        with connections[alias].cursor() as cursor:
            for problem in runtime_role_problems(cursor):
                errors.append(Error(problem, id="common.E001", obj=f"database {alias}"))
    return errors
