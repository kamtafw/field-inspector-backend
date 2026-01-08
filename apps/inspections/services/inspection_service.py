from django.db import transaction
from django.utils import timezone
from django.core.exceptions import ValidationError
from apps.inspections.models import Inspection, InspectionTemplate
import logging

logger = logging.getLogger(__name__)


class ConflictError(Exception):
    """Custom exception for version conflicts"""

    def __init__(self, inspection, client_version, server_version):
        self.inspection = inspection
        self.client_version = client_version
        self.server_version = server_version
        super().__init__(f"Version conflict: client v{client_version} vs server v{server_version}")


class InspectionService:
    """
    Service layer for inspection operations
    Handles creation, updates, conflict detection, and approval workflows (NO idempotency check)
    """

    @staticmethod
    @transaction.atomic
    def create_inspection(data: dict, user):  # type: ignore
        """
        Create a new inspection

        Args:
            data: Dict containing inspection fields
            user: User creating the inspection

        Returns:
            Created Inspection instance

        Raises:
            ValidationError: If data is invalid
        """
        logger.info(f"Creating inspection for user {user.email}")

        # validate template exists
        template_id = data.get("template_id")
        try:
            template = InspectionTemplate.objects.get(id=template_id)
        except InspectionTemplate.DoesNotExist:
            raise ValidationError(f"Template {template_id} not found")

        inspection = Inspection.objects.create(
            template=template,
            inspector=user,
            facility_name=data.get("facility_name"),
            facility_address=data.get("facility_address", ""),
            responses=data.get("responses", {}),
            status=data.get("status", "draft"),
            version=1,  # start at version 1
        )

        print("Created inspection", inspection.id)

        logger.info(f"Created inspection {inspection.id}")

        return inspection

    @staticmethod
    @transaction.atomic
    def update_inspection(inspection_id: str, data: dict, client_version: int):
        """
        Update an existing inspection with optimistic locking

        Args:
            inspection_id: UUID of inspection to update
            data: Dict containing fields to update
            client_version: Version number from client (for conflict detection)

        Returns:
            Updated Inspection instance

        Raises:
            ConflictError: If version mismatch detected
            Inspection.DoesNotExist: If inspection not found
        """

        logger.info(f"Updating inspection {inspection_id}; client_version {client_version}")

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

        return inspection
