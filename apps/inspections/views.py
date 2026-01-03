from django.forms import ValidationError
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.db import transaction
from django.utils import timezone

from .models import Inspection, InspectionTemplate
from .serializers import InspectionSerializer, CreateInspectionSerializer, UpdateInspectionSerializer, InspectionTemplateSerializer
from apps.sync.models import SyncOperation, ConflictRecord
from apps.inspections.services import InspectionService, ConflictError


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

        try:
            inspection = InspectionService.create_inspection(
                data=request.data,
                user=request.user,
                idempotency_key=idempotency_key,
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

        try:
            inspection = InspectionService.update_inspection(
                inspection_id=pk,
                data=request.data,
                client_version=client_version,
                idempotency_key=idempotency_key,
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

        # # check idempotency
        # if idempotency_key:
        #     try:
        #         sync_op = SyncOperation.objects.get(idempotency_key=idempotency_key)
        #         # already processed; return cached result
        #         return Response(sync_op.result, status=status.HTTP_200_OK)
        #     except SyncOperation.DoesNotExist:
        #         pass

        # inspection = self.get_object()
        # client_version = request.data.get("version")

        # # CRITICAL: check version for conflicts before updating
        # if inspection.version != client_version:
        #     server_data = InspectionSerializer(inspection).data

        #     # record conflict for audit
        #     ConflictRecord.objects.create(
        #         inspection=inspection,
        #         client_version_number=client_version,
        #         server_version_number=inspection.version,
        #         server_data=server_data,
        #         client_data=request.data,
        #     )

        #     return Response(
        #         {
        #             "error": "conflict",
        #             "message": "Another user has updated this inspection while you were editing it.",
        #             "client_version": client_version,
        #             "server_version": inspection.version,
        #             "server_data": server_data,
        #         },
        #         status=status.HTTP_409_CONFLICT,
        #     )

        # # no conflict; update inspection
        # serializer = self.get_serializer(inspection, data=request.data, partial=True)
        # serializer.is_valid(raise_exception=True)

        # # increment version
        # inspection.increment_version()

        # # handle status change
        # if request.data.get("status") == "submitted" and inspection.status != "draft":
        #     inspection.submitted_at = timezone.now()

        # inspection.save()

        # # record operation for idempotency
        # if idempotency_key:
        #     result_data = InspectionSerializer(inspection).data
        #     SyncOperation.objects.create(
        #         idempotency_key=idempotency_key,
        #         operation_type="UPDATE_INSPECTION",
        #         entity_id=inspection.id,
        #         user=request.user,
        #         result=result_data,
        #     )

        # response_serializer = InspectionSerializer(inspection)
        # return Response(response_serializer.data)

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
