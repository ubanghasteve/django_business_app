"""
Reusable mixin for offline-first sync.
Adds uuid (deduplication/sync identity), updated_at (conflict resolution), and is_deleted (soft delete).
Apply only to models that require offline create/update. Models must be
tenant-scoped (account or company) and respect RBAC.
"""
import uuid
from django.db import models


class SyncMixin(models.Model):
    """
    Sync fields for offline-first: unique identity, last-modified time, soft delete.
    Last-write-wins: compare updated_at when merging.
    """
    uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    updated_at = models.DateTimeField(auto_now=True)
    is_deleted = models.BooleanField(default=False)

    class Meta:
        abstract = True
