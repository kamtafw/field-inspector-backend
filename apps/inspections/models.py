import uuid
from django.db import models
from django.utils import timezone
from django.contrib.auth import get_user_model

User = get_user_model()


class InspectionTemplate(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    name = models.CharField(max_length=255)
    version = models.IntegerField(default=1)
    checklist_items = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    is_active = models.BooleanField(default=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "inspection_templates"
        ordering = ["-created_at"]

    def soft_delete(self):
        """Soft delete template to prevent new inspections"""
        self.is_active = False
        self.deleted_at = timezone.now()
        self.save(update_fields=["is_active", "deleted_at"])


class Inspection(models.Model):
    STATUS_CHOICES = (
        ("draft", "Draft"),
        ("submitted", "Submitted"),
        ("rejected", "Rejected"),
        ("approved", "Approved"),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    template = models.ForeignKey(InspectionTemplate, on_delete=models.PROTECT, related_name="inspections")
    inspector = models.ForeignKey(User, on_delete=models.CASCADE, related_name="inspections")
    facility_name = models.CharField(max_length=255)
    facility_address = models.CharField(max_length=500)
    responses = models.JSONField()  # checklist responses
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="draft")
    version = models.IntegerField(default=1)  # for optimistic locking

    # approval workflow
    approved_by = models.ForeignKey(User, null=True, blank=True, related_name="approved_inspections", on_delete=models.SET_NULL)
    approved_at = models.DateTimeField(null=True, blank=True)
    approval_notes = models.TextField(null=True, blank=True)

    # timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "inspections"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["inspector", "status"]),
            models.Index(fields=["created_at"]),
        ]

    def increment_version(self):
        """Increment version for optimistic locking"""
        self.version = models.F("version") + 1
        self.save(update_fields=["version"])
        self.refresh_from_db()
