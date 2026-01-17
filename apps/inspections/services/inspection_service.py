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
    Handles creation, updates, conflict detection, and approval workflows
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

        inspection = Inspection.objects.create(
            template=data.get("template"),
            inspector=user,
            facility_name=data.get("facility_name"),
            facility_address=data.get("facility_address", ""),
            responses=data.get("responses", {}),
            status=data.get("status", "draft"),
            version=1,  # start at version 1
        )

        logger.info(f"Created inspection {inspection.id}")
        return inspection

    @staticmethod
    @transaction.atomic
    def update_inspection(inspection_id: str, data: dict, client_version: int, is_conflict_resolution: bool = False):
        """
        Update an existing inspection with optimistic locking

        Args:
            inspection_id: UUID of inspection to update
            data: Dict containing fields to update
            client_version: Version number from client (for conflict detection)
            is_conflict_resolution: If True, this is a conflict resolution update

        Returns:
            Updated Inspection instance

        Raises:
            ConflictError: If version mismatch detected
            Inspection.DoesNotExist: If inspection not found
        """
        logger.info(f"Updating inspection {inspection_id}; " f"client_version {client_version}, " f"is_conflict_resolution={is_conflict_resolution}")

        # lock the row for update
        inspection = Inspection.objects.select_for_update().get(id=inspection_id)

        if is_conflict_resolution:
            logger.info(
                f"Processing conflict resolution for inspection {inspection_id}. "
                f"Client claims to have resolved conflict from server v{client_version}"
            )

            # check if server version has changed since conflict was detected
            if inspection.version != client_version:
                logger.warning(
                    f"Server version changed during conflict resolution! "
                    f"Client resolved v{client_version} but server is now v{inspection.version}"
                )

                raise ConflictError(inspection=inspection, client_version=client_version, server_version=inspection.version)

            # server version hasn't changed - accept the resolution
            logger.info(f"Accepting conflict resolution for inspection {inspection_id}")
            # continue with update below...

        else:
            # standard version check
            if inspection.version != client_version:
                logger.warning(f"Conflict detected on inspection {inspection_id}: " f"client v{client_version} vs server v{inspection.version}")

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

    @staticmethod
    @transaction.atomic
    def resolve_conflict(inspection_id: str, resolved_data: dict, conflict_server_version: int, user):
        """
        Convenience method for conflict resolution
        Wrapper around update_inspection with is_conflict_resolution=True

        Args:
            inspection_id: UUID of inspection
            resolved_data: The merged/resolved data
            conflict_server_version: The server version when conflict was detected
            user: User resolving the conflict

        Returns:
            Updated Inspection instance
        """
        return InspectionService.update_inspection(
            inspection_id=inspection_id, data=resolved_data, client_version=conflict_server_version, is_conflict_resolution=True
        )
