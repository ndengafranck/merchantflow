"""Abstract base models shared by every domain app."""

import uuid

from django.db import models


class UUIDModel(models.Model):
    """Business records use opaque UUID keys.

    UUIDs can be generated on an offline device before the server has seen the
    record, and they do not leak record counts through sequential identifiers.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    class Meta:
        abstract = True


class TimestampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
