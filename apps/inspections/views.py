from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.db import transaction
from django.utils import timezone
from django.core.exceptions import ValidationError

from .models import Inspection, InspectionTemplate
from .services import InspectionService, ConflictError
from .serializers import InspectionSerializer, CreateInspectionSerializer, UpdateInspectionSerializer, InspectionTemplateSerializer
from apps.sync.services import IdempotencyService


class InspectionTemplateViewSet(viewsets.ModelViewSet):
    """
    Read-only endpoint for inspection templates
    Mobile app downloads these while online and stores them locally
    """

    queryset = InspectionTemplate.objects.all()
    serializer_class = InspectionTemplateSerializer
    permission_classes = [IsAuthenticated]


class InspectionViewSet(viewsets.ModelViewSet):
    """
    CRUD operations for inspections with:
    - Idempotency checks
    - Optimistic locking (version-based conflict detection)
    - Manager approval workflow
    """

    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        # managers see all, inspectors see only their own
        if hasattr(user, "role") and user.role == "manager":
            return Inspection.objects.all()
        return Inspection.objects.filter(inspector=user)

    def get_serializer_class(self):
        if self.action == "create":
            return CreateInspectionSerializer
        elif self.action in ["update", "partial_update"]:
            return UpdateInspectionSerializer
        return InspectionSerializer

    @transaction.atomic
    def create(self, request):
        """
        Create inspection with idempotency check and optimistic locking

        Client provides:
        - id (UUID)
        - Idempotency-Key
        - Inspection data

        Server responses:
        - 201 Created (if successful)
        - 400 Bad Request (if data is invalid)
        """

        idempotency_key = request.headers.get("Idempotency-Key")

        # idempotency check
        if idempotency_key:
            if IdempotencyService.exists(idempotency_key):
                result = IdempotencyService.get_result(idempotency_key)
                inspection = Inspection.objects.get(id=result.get("id"))
                serializer = InspectionSerializer(inspection)

                return Response(serializer.data)

        try:
            inspection = InspectionService.create_inspection(data=request.data, user=request.user)

            # record idempotency
            if idempotency_key:
                IdempotencyService.record(
                    idempotency_key=idempotency_key,
                    operation_type="CREATE_INSPECTION",
                    entity_id=str(inspection.id),
                    user=request.user,
                    result={"id": str(inspection.id), "version": inspection.version},
                )

            serializer = InspectionSerializer(inspection)
            return Response(serializer.data, status=status.HTTP_201_CREATED)

        except ValidationError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @transaction.atomic
    def update(self, request, pk=None):
        """
        Update inspection with optimistic locking

        returns:
        - 200 OK (if successful)
        - 409 Conflict (if version mismatch)
        """
        idempotency_key = request.headers.get("Idempotency-Key")
        client_version = request.data.get("version")

        # idempotency check
        if idempotency_key:
            if IdempotencyService.exists(idempotency_key):
                inspection = Inspection.objects.get(id=pk)
                serializer = InspectionSerializer(inspection)

                return Response(serializer.data)

        try:
            inspection = InspectionService.update_inspection(
                inspection_id=pk,
                data=request.data,
                client_version=client_version,
            )

            # record idempotency
            if idempotency_key:
                IdempotencyService.record(
                    idempotency_key=idempotency_key,
                    operation_type="UPDATE_INSPECTION",
                    entity_id=str(inspection.id),
                    user=request.user,
                    result={"id": str(inspection.id), "version": inspection.version},
                )

            serializer = InspectionSerializer(inspection)
            return Response(serializer.data)

        except ConflictError as e:
            return Response(
                {
                    "error": "conflict",
                    "message": str(e),
                    "client_version": e.client_version,
                    "server_version": e.server_version,
                    "server_data": InspectionSerializer(e.inspection).data,
                },
                status=status.HTTP_409_CONFLICT,
            )

        except Inspection.DoesNotExist:
            return Response({"error": "Inspection not found"}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        """
        Approve inspection: Manager approval endpoint.
        Only accessible to managers (add permission check in production).
        """
        inspection = self.get_object()

        if inspection.status != "submitted":
            return Response({"error": "Only submitted inspections can be approved."}, status=status.HTTP_400_BAD_REQUEST)

        inspection.status = "approved"
        inspection.approved_by = request.user
        inspection.approved_at = timezone.now()
        inspection.approval_notes = request.data.get("notes", "")
        inspection.increment_version()
        inspection.save()

        # TODO: send push notification to inspector

        serializer = InspectionSerializer(inspection)
        return Response(serializer.data)

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        """
        Reject inspection: Manager rejection endpoint.
        Only accessible to managers (add permission check in production).
        """
        inspection = self.get_object()

        if inspection.status != "submitted":
            return Response({"error": "Only submitted inspections can be rejected."}, status=status.HTTP_400_BAD_REQUEST)

        inspection.status = "rejected"
        inspection.approved_by = request.user
        inspection.approved_at = timezone.now()
        inspection.approval_notes = request.data.get("notes", "")
        inspection.increment_version()
        inspection.save()

        # TODO: send push notification to inspector

        serializer = InspectionSerializer(inspection)
        return Response(serializer.data)
