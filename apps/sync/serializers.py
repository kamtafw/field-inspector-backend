from rest_framework import serializers
from .models import SyncOperation, ConflictRecord
from apps.inspections.models import Inspection
from apps.inspections.serializers import InspectionSerializer


class SyncOperationSerializer(serializers.ModelSerializer):
    """
    Serializer for sync operation records (listing)
    """

    class Meta:
        model = SyncOperation
        fields = [
            "idempotency_key",
            "operation_type",
            "entity_id",
            "user",
            "processed_at",
            "result",
        ]
        read_only_fields = fields


class ConflictRecordSerializer(serializers.ModelSerializer):
    """
    Serializer for conflict records
    """

    inspection = InspectionSerializer(read_only=True)
    resolved_by_email = serializers.CharField(source="resolved_by.email", read_only=True, allow_null=True)

    class Meta:
        model = ConflictRecord
        fields = [
            "id",
            "inspection",
            "client_version_number",
            "server_version_number",
            "client_data",
            "server_data",
            "resolved",
            "resolved_at",
            "resolved_by",
            "resolved_by_email",
            "resolution_strategy",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "inspection",
            "created_at",
        ]


class BatchSyncOperationSerializer(serializers.Serializer):
    """
    Serializer for batch sync operations
    """

    operation_type = serializers.ChoiceField(choices=["CREATE_INSPECTION", "UPDATE_INSPECTION"], required=True)
    idempotency_key = serializers.CharField(required=True, max_length=255)
    data = serializers.JSONField(required=True)


class BatchSyncRequestSerializer(serializers.Serializer):
    """
    Serializer for batch sync requests
    """

    operations = BatchSyncOperationSerializer(many=True, required=True)

    def validate_operations(self, value):
        if len(value) > 100:
            raise serializers.ValidationError("Maximum 100 operations per batch")
        return value


class BatchSyncResponseSerializer(serializers.Serializer):
    """
    Serializer for batch sync responses
    """

    success = serializers.BooleanField()
    data = serializers.JSONField(required=False)
    errors = serializers.JSONField(required=False)
    idempotency_key = serializers.CharField()
