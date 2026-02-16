from rest_framework import serializers
from django.contrib.auth import get_user_model
from .models import InspectionTemplate, Inspection
from apps.photos.serializers import PhotoSerializer

User = get_user_model()


class InspectorSerializer(serializers.ModelSerializer):
    """Minimal user info for inspection responses"""

    class Meta:
        model = User
        fields = ["id", "email", "first_name", "last_name"]
        read_only_fields = fields


class InspectionTemplateSerializer(serializers.ModelSerializer):
    """Full inspection template with checklist items"""

    class Meta:
        model = InspectionTemplate
        fields = ["id", "name", "version", "checklist_items", "created_at"]
        read_only_fields = ["id", "created_at"]


class InspectionSerializer(serializers.ModelSerializer):
    """Full inspection with checklist items and photos"""

    template_id = serializers.UUIDField(source="template.id", read_only=True)
    inspector = InspectorSerializer()
    photos = PhotoSerializer(many=True, read_only=True)

    class Meta:
        model = Inspection
        fields = [
            "id",
            "template_id",
            "inspector",
            "facility_name",
            "facility_address",
            "responses",
            "status",
            "version",
            "approved_by",
            "approved_at",
            "approval_notes",
            "photos",
            "created_at",
            "submitted_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "inspector",
            "approved_by",
            "approved_at",
            "created_at",
            "updated_at",
        ]

    def validate_version(self, value):
        """Ensure version is provided for updates"""
        if self.instance and value is None:
            raise serializers.ValidationError("Version must be provided for updates.")
        return value


class CreateInspectionSerializer(serializers.ModelSerializer):
    """Create inspection"""

    template_id = serializers.PrimaryKeyRelatedField(
        source="template",
        queryset=InspectionTemplate.objects.all(),
        write_only=True,
    )

    class Meta:
        model = Inspection
        fields = [
            "template_id",
            "facility_name",
            "facility_address",
            "responses",
            "status",
            "version",
        ]

    def create(self, validated_data):
        # Inspector is set from request.user in view
        return Inspection.objects.create(**validated_data)


class UpdateInspectionSerializer(serializers.ModelSerializer):
    """Update inspection with version-checking"""

    class Meta:
        model = Inspection
        fields = [
            "facility_name",
            "facility_address",
            "responses",
            "status",
            "version",
        ]

    def validate_version(self, value):
        """Ensure version is provided for updates"""
        if not value:
            raise serializers.ValidationError("Version is required.")
        return value
