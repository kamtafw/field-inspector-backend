from django.db import models
from django.contrib.auth import get_user_model
from apps.inspections.models import Inspection
import uuid

User = get_user_model()


class SyncOperation(models.Model):
    """
    Track processed operations by idempotency key.
    Prevents duplicate processing of the same operation (retried requests).
    """

    idempotency_key = models.CharField(max_length=255, unique=True, db_index=True, help_text="Client-generated UUID for idempotency")
    operation_type = models.CharField(max_length=50, help_text="CREATE_INSPECTION, UPDATE_INSPECTION, etc.")
    entity_id = models.UUIDField(help_text="ID of the entity being processed")
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    processed_at = models.DateTimeField(auto_now_add=True)
    result = models.JSONField(null=True, blank=True, help_text="Response data to return to client")

    class Meta:
        db_table = "sync_operations"
        ordering = ["-processed_at"]
        indexes = [
            models.Index(fields=["idempotency_key"]),
            models.Index(fields=["entity_id"]),
        ]

    def __str__(self):
        return f"{self.operation_type} - {self.idempotency_key}"


class ConflictRecord(models.Model):
    """
    Track conflicts between client and server versions of an inspection.
    Used to resolve conflicts in the approval workflow.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    inspection = models.ForeignKey(Inspection, on_delete=models.CASCADE, related_name="conflicts")

    # snapshot of both versions at conflict time
    client_version_number = models.IntegerField(null=True, blank=True)
    server_version_number = models.IntegerField(null=True, blank=True)
    client_data = models.JSONField(null=True, blank=True, help_text="Client's version of data")
    server_data = models.JSONField(null=True, blank=True, help_text="Server's version of data")

    # resolution tracking
    resolved = models.BooleanField(default=False)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    resolution_strategy = models.CharField(max_length=50, null=True, blank=True, help_text="keep_mine, keep_theirs, merge")

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "conflict_records"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["inspection"]),
            models.Index(fields=["resolved"]),
        ]

    def __str__(self):
        status = "Resolved" if self.resolved else "Unresolved"
        return f"Conflict on {self.inspection.facility_name} - {status}"
