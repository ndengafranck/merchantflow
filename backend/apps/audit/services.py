from typing import Any

from django.db import models

from .models import AuditEvent


def record_event(
    *,
    action: str,
    target: models.Model,
    actor=None,
    workspace=None,
    metadata: dict[str, Any] | None = None,
) -> AuditEvent:
    """Record an audit event. Call inside the transaction of the change itself
    so the event and the change commit or roll back together."""
    return AuditEvent.objects.create(
        workspace=workspace,
        actor=actor,
        action=action,
        target_type=target._meta.label_lower,
        target_id=target.pk,
        metadata=metadata or {},
    )
