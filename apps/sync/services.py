import logging
from django.db import transaction, IntegrityError
from .models import SyncOperation, ConflictRecord
from apps.inspections.services import InspectionService, ConflictError
from apps.inspections.serializers import CreateInspectionSerializer, UpdateInspectionSerializer

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
        """Record a processed operation - atomic to prevent race conditions"""
        try:
            operation, created = SyncOperation.objects.get_or_create(
                idempotency_key=idempotency_key,
                defaults={
                    "operation_type": operation_type,
                    "entity_id": entity_id,
                    "user": user,
                    "result": result,
                },
            )

            if not created:
                logger.warning(f"Idempotency key {idempotency_key} already exists - returning cached result")
                return operation.result

            logger.info(f"Recorded operation {operation_type} with key {idempotency_key}")
            return result

        except IntegrityError:
            logger.warning(f"Race condition detected for key {idempotency_key} - fetching existing")
            operation = SyncOperation.objects.get(idempotency_key=idempotency_key)
            return operation.result

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

        for idx, operation in enumerate(operations):
            operation_type = operation["operation_type"]
            idempotency_key = operation["idempotency_key"]

            try:
                result = BatchSyncService.process_operation(
                    operation_type=operation_type,
                    idempotency_key=idempotency_key,
                    data=operation["data"],
                    user=user,
                )
                results.append(
                    {
                        "index": idx,
                        "success": True,
                        "data": result,
                        "idempotency_key": idempotency_key,
                        "operation_type": operation_type,
                    }
                )

            except ConflictError as e:
                logger.warning(f"Conflict detected: {str(e)}")

                ConflictRecord.objects.create(
                    inspection=e.inspection,
                    client_version_number=e.client_version,
                    server_version_number=e.server_version,
                    client_data=operation["data"],
                    server_data=BatchSyncService._serialize_inspection(e.inspection),
                )
                results.append(
                    {
                        "id": idx,
                        "success": False,
                        "error": "conflict",
                        "idempotency_key": idempotency_key,
                        "operation_type": operation_type,
                        "conflict_data": {
                            "client_version": e.client_version,
                            "server_version": e.server_version,
                            "server_data": {
                                "id": str(e.inspection.id),
                                "template_id": str(e.inspection.template.id),
                                "facility_name": e.inspection.facility_name,
                                "facility_address": e.inspection.facility_address,
                                "response": e.inspection.responses,
                                "status": e.inspection.status,
                                "version": e.inspection.version,
                                "updated_by": (
                                    {
                                        "id": str(e.inspection.inspector.id),
                                        "email": e.inspection.inspector.email,
                                        "name": f"{e.inspection.inspector.first_name} {e.inspection.inspector.last_name}".strip(),
                                        "updated_at": e.inspection.updated_at.isoformat(),
                                    }
                                    if e.inspection.inspector
                                    else None
                                ),
                            },
                        },
                    }
                )

            except Exception as e:
                logger.error(f"Operation failed: {str(e)}")
                results.append(
                    {
                        "index": idx,
                        "success": False,
                        "error": str(e),
                        "idempotency_key": idempotency_key,
                        "operation_type": operation_type,
                    }
                )
        logger.info(f"Batch processed: {sum(1 for r in results if r['success'])} succeeded, " f"{sum(1 for r in results if not r['success'])} failed")
        return results

    @staticmethod
    def process_operation(operation_type: str, idempotency_key: str, data: dict, user):
        """Process a single sync operation"""

        # check idempotency
        cached_result = IdempotencyService.get_result(idempotency_key)
        if cached_result:
            return cached_result

        result = None

        if operation_type == "CREATE_INSPECTION":
            serializer = CreateInspectionSerializer(data=data)
            serializer.is_valid(raise_exception=True)

            inspection = InspectionService.create_inspection(data=serializer.validated_data, user=user)
            result = {"id": str(inspection.id), "version": inspection.version}

        elif operation_type == "UPDATE_INSPECTION":
            serializer = UpdateInspectionSerializer(data=data)
            serializer.is_valid(raise_exception=True)

            inspection_id = data.get("id")
            client_version = serializer.validated_data.get("version")

            if not inspection_id:
                raise ValueError("Missing 'id' field for UPDATE_INSPECTION")
            if not client_version:
                raise ValueError("Missing 'id' field for UPDATE_INSPECTION")

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

    @staticmethod
    def _serialize_inspection(inspection):
        """Helper to serialize inspection data for conflict response"""
        return {
            "id": str(inspection.id),
            "template_id": str(inspection.template.id),
            "facility_name": inspection.facility_name,
            "facility_address": inspection.facility_address,
            "responses": inspection.responses,
            "status": inspection.status,
            "version": inspection.version,
            "updated_at": inspection.updated_at.isoformat(),
        }
