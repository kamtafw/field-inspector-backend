from django.db import transaction
from .models import SyncOperation
from apps.inspections.models import Inspection


class BatchSyncService:
    """
    Service for processing batch sync operations
    Handles multiple operations in a single request
    """

    @staticmethod
    @transaction.atomic
    def process_batch(operations: list, user) -> list:
        """
        Process a batch of sync operations
        Returns list of processed operations
        """

        results = []
        for operation in operations:
            try:
                result = BatchSyncService.process_operation(
                    operation_type=operation["operation_type"],
                    idempotency_key=operation["idempotency_key"],
                    data=operation["data"],
                    user=user,
                )
                results.append({"success": True, "data": result, "idempotency_key": operation["idempotency_key"]})
            except Exception as e:
                results.append({"success": False, "error": str(e), "idempotency_key": operation["idempotency_key"]})
        return results

    @staticmethod
    def process_operation(operation_type: str, idempotency_key: str, data: dict, user):
        """
        Process a single sync operation
        """

        # check idempotency

        if operation_type == "CREATE_INSPECTION":
            from apps.inspections.serializers import CreateInspectionSerializer

            serializer = CreateInspectionSerializer(data=data)
            serializer.is_valid(raise_exception=True)
            inspection = serializer.save(inspector=user)

            # record idempotency

            return {"id": str(inspection.id)}
        elif operation_type == "UPDATE_INSPECTION":
            from apps.inspections.serializers import UpdateInspectionSerializer

            serializer = UpdateInspectionSerializer(data=data)
            serializer.is_valid(raise_exception=True)
            inspection = serializer.save()

            # record idempotency

            return {"id": str(inspection.id)}
        else:
            raise ValueError(f"Invalid operation type: {operation_type}")
