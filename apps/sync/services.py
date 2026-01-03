from django.db import transaction
from .models import SyncOperation


class IdempotencyService:
    """
    Service for checking idempotency of sync operations
    Prevents duplicate processing of the same operation (retried requests)
    """

    @staticmethod
    def get_result(idempotency_key: str):
        """
        Check if an idempotency key has already been processed
        Returns cached result if available
        """

        try:
            operation = SyncOperation.objects.get(idempotency_key=idempotency_key)
            return operation.result
        except SyncOperation.DoesNotExist:
            return None

    @staticmethod
    @transaction.atomic
    def set_result(idempotency_key: str, operation_type: str, entity_id: str, user, result: dict):
        """
        Cache the result of an idempotency key
        """

        SyncOperation.objects.create(
            idempotency_key=idempotency_key,
            operation_type=operation_type,
            entity_id=entity_id,
            user=user,
            result=result,
        )

    @staticmethod
    def exists(idempotency_key: str):
        """
        Check if an operation exists
        """

        return SyncOperation.objects.filter(idempotency_key=idempotency_key).exists()


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
        if IdempotencyService.exists(idempotency_key):
            return IdempotencyService.get_result(idempotency_key)

        if operation_type == "CREATE_INSPECTION":
            from apps.inspections.serializers import CreateInspectionSerializer

            serializer = CreateInspectionSerializer(data=data)
            serializer.is_valid(raise_exception=True)
            inspection = serializer.save(inspector=user)

            # record idempotency
            IdempotencyService.record(
                idempotency_key=idempotency_key,
                operation_type=operation_type,
                entity_id=str(inspection.id),
                user=user,
                result={"id": str(inspection.id)},
            )

            return {"id": str(inspection.id)}
        elif operation_type == "UPDATE_INSPECTION":
            from apps.inspections.serializers import UpdateInspectionSerializer

            serializer = UpdateInspectionSerializer(data=data)
            serializer.is_valid(raise_exception=True)
            inspection = serializer.save()

            # record idempotency
            IdempotencyService.record(
                idempotency_key=idempotency_key,
                operation_type=operation_type,
                entity_id=str(inspection.id),
                user=user,
                result={"id": str(inspection.id)},
            )

            return {"id": str(inspection.id)}
        else:
            raise ValueError(f"Invalid operation type: {operation_type}")
