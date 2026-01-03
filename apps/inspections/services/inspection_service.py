from django.db import transaction
from django.utils import timezone
from django.core.exceptions import ValidationError
from apps.inspections.models import Inspection, InspectionTemplate
from apps.sync.models import ConflictRecord
import logging

logger = logging.getLogger(__name__)


class ConflictError(Exception):
    """
    Custom exception for version conflicts
    Contains both client and server versions of the inspection
    """

    def __init__(self, inspection, client_version, server_version):
        self.inspection = inspection
        self.client_version = client_version
        self.server_version = server_version
        super().__init__(f"Version conflict: client v{client_version} vs server v{server_version}")


class InspectionService:
    """
    Service layer for inspection operations
    Handles creation, updates, conflict detection, and approval workflows
    """

    @staticmethod
    @transaction.atomic
    def create_inspection(data: dict, user, idempotency_key: str = None):  # type: ignore
        """
        Create a new inspection

        Args:
            data: Dict containing inspection fields
            user: User creating the inspection
            idempotency_key: UUID for idempotency (optional)

        Returns:
            Created Inspection instance

        Raises:
            ValidationError: If data is invalid
        """
        logger.info(f"Creating inspection for user {user.email}")

        # idempotency check
        if idempotency_key:
            from apps.sync.services import IdempotencyService

            if IdempotencyService.exists(idempotency_key):
                logger.info(f"Returning cached result for key {idempotency_key}")
                result = IdempotencyService.get_result(idempotency_key)
                return Inspection.objects.get(id=result["id"])

        # validate template exists
        template_id = data.get("template_id")
        try:
            template = InspectionTemplate.objects.get(id=template_id)
        except InspectionTemplate.DoesNotExist:
            raise ValidationError(f"Template {template_id} not found")

        inspection = Inspection.objects.create(
            id=data.get("id"),
            template=template,
            inspector=user,
            facility_name=data.get("facility_name"),
            facility_address=data.get("facility_address", ""),
            responses=data.get("responses", {}),
            status=data.get("status", "draft"),
            version=1,  # start at version 1
        )

        logger.info(f"Created inspection {inspection.id}")

        # record idempotency if key provided
        if idempotency_key:
            from apps.sync.services import IdempotencyService

            IdempotencyService.set_result(
                idempotency_key=idempotency_key,
                operation_type="CREATE_INSPECTION",
                entity_id=str(inspection.id),
                user=user,
                result={"id": str(inspection.id), "version": inspection.version},
            )

        return inspection

    @staticmethod
    @transaction.atomic
    def update_inspection(inspection_id: str, data: dict, client_version: int, idempotency_key: str = None):
        """
        Update an existing inspection with optimistic locking

        Args:
            inspection_id: UUID of inspection to update
            data: Dict containing fields to update
            client_version: Version number from cient (for conlflict detection)
            idempotency_key: UUID for idempotency (optional)

        Returns:
            Updated Inspection instance

        Raises:
            ConflictError: If version mismatch detected
            Inspection.DoesNotExist: If inspection not found
        """

        logger.info(f"Updating inspection {inspection_id}; client_version {client_version}")

        # check idempotency
        if idempotency_key:
            from apps.sync.services import IdempotencyService

            if IdempotencyService.exists(idempotency_key):
                logger.info(f"Returning cached result for key {idempotency_key}")
                return Inspection.objects.get(id=inspection_id)

        # lock the row for update
        inspection = Inspection.objects.select_for_update().get(id=inspection_id)

        # check version for conflicts
        if inspection.version != client_version:
            logger.warning(f"Conflict detected on inspection {inspection_id}: " f"client v{client_version} vs server v{inspection.version}")

            # record conflict for audit trail

            raise ConflictError(inspection=inspection, client_version=client_version, server_version=inspection.version)

        if "facility_name" in data:
            inspection.facility_name = data["facility_name"]

        if "facility_address" in data:
            inspection.facility_address = data["facility_address"]

        if "responses" in data:
            inspection.responses = data["responses"]

        if "status" in data:
            new_status = data["status"]
            old_status = inspection.status

            if new_status == "submitted" and old_status == "draft":
                inspection.submitted_at = timezone.now()
                logger.info(f"Inspection {inspection_id} submitted.")

            inspection.status = new_status

        inspection.version += 1
        inspection.save()

        logger.info(f"Updated inspection {inspection_id} to version {inspection.version}")

        if idempotency_key:
            from apps.sync.services import IdempotencyService

            IdempotencyService.set_result(
                idempotency_key=idempotency_key,
                operation_type="UPDATE_INSPECTION",
                entity_id=str(inspection.id),
                user=inspection.inspector,
                result={"id": str(inspection.id), "version": inspection.version},
            )

        return inspection
