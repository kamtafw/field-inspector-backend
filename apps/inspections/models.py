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


class InspectionManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(is_deleted=False)


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

    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_by = models.ForeignKey(User, null=True, blank=True, related_name="deleted_inspections", on_delete=models.SET_NULL)

    def increment_version(self):
        """Increment version for optimistic locking"""
        self.version = models.F("version") + 1
        self.save(update_fields=["version"])
        self.refresh_from_db()

    def soft_delete(self, user):
        """Soft delete inspection"""
        self.is_deleted = True
        self.deleted_at = timezone.now()
        self.deleted_by = user
        self.save(update_fields=["is_deleted", "deleted_at", "deleted_by"])

    def restore(self):
        """Restore a soft-deleted inspection"""
        self.is_deleted = False
        self.deleted_at = None
        self.deleted_by = None
        self.save(update_fields=["is_deleted", "deleted_at", "deleted_by"])

    # override default queryset to exclude deleted
    objects = InspectionManager()
    all_objects = models.Manager()

    class Meta:
        db_table = "inspections"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["inspector", "status"]),
            models.Index(fields=["created_at"]),
            models.Index(fields=["template", "status"]),
            models.Index(fields=["submitted_at"]),
            models.Index(fields=["is_deleted", "status"]),
        ]
