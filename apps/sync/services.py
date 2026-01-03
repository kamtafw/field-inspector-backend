import logging
from django.db import transaction
from .models import SyncOperation
from apps.inspections.services import InspectionService

logger = logging.getLogger(__name__)


class IdempotencyService:
    """
    Centralized idempotency handling
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
            logger.info(f"Found cached result for key {idempotency_key}")
            return operation.result
        except SyncOperation.DoesNotExist:
            logger.info(f"No cached result found for key {idempotency_key}")
            return None

    @staticmethod
    @transaction.atomic
    def record(idempotency_key: str, operation_type: str, entity_id: str, user, result: dict):
        """Record a processed operation"""

        SyncOperation.objects.create(
            idempotency_key=idempotency_key,
            operation_type=operation_type,
            entity_id=entity_id,
            user=user,
            result=result,
        )
        logger.info(f"Recorded operation {operation_type} with key {idempotency_key}")

    @staticmethod
    def exists(idempotency_key: str) -> bool:
        """Check if an operation exists"""

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
                print(e)
                logger.error(f"Operation failed: {str(e)}")
                results.append({"success": False, "error": str(e), "idempotency_key": operation["idempotency_key"]})
        print("RESULTS:", results)
        return results

    @staticmethod
    def process_operation(operation_type: str, idempotency_key: str, data: dict, user):
        """Process a single sync operation"""

        # check idempotency
        if IdempotencyService.exists(idempotency_key):
            logger.info(f"Returning cached result for {idempotency_key}")
            return IdempotencyService.get_result(idempotency_key)

        result = None

        if operation_type == "CREATE_INSPECTION":
            inspection = InspectionService.create_inspection(data=data, user=user)

            result = {"id": str(inspection.id), "version": inspection.version}

        elif operation_type == "UPDATE_INSPECTION":
            inspection_id = data.get("id")
            client_version = data.get("version")

            inspection = InspectionService.update_inspection(inspection_id=inspection_id, data=data, client_version=client_version)

            result = {"id": str(inspection.id), "version": inspection.version}
        else:
            raise ValueError(f"Invalid operation type: {operation_type}")

        # record idempotency
        IdempotencyService.record(
            idempotency_key=idempotency_key,
            operation_type=operation_type,
            entity_id=result.get("id"),
            user=user,
            result=result,
        )

        return result
