import uuid
from django.db import models
from django.contrib.auth import get_user_model

User = get_user_model()


class InspectionTemplate(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    name = models.CharField(max_length=255)
    version = models.IntegerField(default=1)
    checklist_items = models.JSONField()  # array of questions
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "inspection_templates"
        ordering = ["-created_at"]


class Inspection(models.Model):
    STATUS_CHOICES = (
        ("draft", "Draft"),
        ("submitted", "Submitted"),
        ("rejected", "Rejected"),
        ("approved", "Approved"),
    )

    id = models.UUIDField(primary_key=True)  # client-generated
    template = models.ForeignKey(InspectionTemplate, on_delete=models.CASCADE)
    inspector = models.ForeignKey(User, related_name="inspections", on_delete=models.CASCADE)
    facility_name = models.CharField(max_length=255)
    facility_address = models.CharField(max_length=500)
    responses = models.JSONField()  # checklist responses
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="draft")
    version = models.IntegerField(default=1)  # for optimistic locking

    # approval workflow
    approved_by = models.ForeignKey(User, null=True, blank=True, related_name="approved_inspections", on_delete=models.SET_NULL)
    approved_at = models.DateTimeField(null=True, blank=True)
    approval_notes = models.TextField(null=True, blank=True)
    rejected_at = models.DateTimeField(null=True, blank=True)
    rejection_notes = models.TextField(null=True, blank=True)

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


class Photo(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    inspection = models.ForeignKey(Inspection, related_name="photos", on_delete=models.CASCADE)
    s3_key = models.CharField(max_length=255)
    s3_url = models.URLField(max_length=1000)
    file_size = models.IntegerField()  # bytes
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "photos"
        ordering = ["-uploaded_at"]
