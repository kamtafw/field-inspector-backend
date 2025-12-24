from django.db import models
from django.contrib.auth import get_user_model
from apps.inspections.models import Inspection

User = get_user_model()


class SyncOperation(models.Model):
    """Track processed operations for idempotency"""

    idempotency_key = models.CharField(max_length=255, unique=True, db_index=True)
    operation_type = models.CharField(max_length=50)
    entity_id = models.UUIDField()
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    processed_at = models.DateTimeField(auto_now_add=True)
    result = models.JSONField(null=True)  # store responses for replay

    class Meta:
        db_table = "sync_operations"


class ConflictRecord(models.Model):
    inspection = models.ForeignKey(Inspection, on_delete=models.CASCADE)
    client_version = models.JSONField()
    server_version = models.JSONField()
    resolved = models.BooleanField(default=False)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    resolution_strategy = models.CharField(max_length=50, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "conflict_records"
