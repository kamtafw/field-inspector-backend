from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.db import transaction
from django.utils import timezone

from .models import Inspection, InspectionTemplate
from .serializers import InspectionSerializer, CreateInspectionSerializer, UpdateInspectionSerializer, InspectionTemplateSerializer
from sync.models import SyncOperation, ConflictRecord


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
        - 409 Conflict (if inspection already exists)
        """

        idempotency_key = request.headers.get("Idempotency-Key")

        # check idempotency
        if idempotency_key:
            try:
                sync_op = SyncOperation.objects.get(idempotency_key=idempotency_key)
                # already processed; return cached result
                return Response(sync_op.result, status=status.HTTP_200_OK)
            except SyncOperation.DoesNotExist:
                pass
        
        # validate & create

        # create inspection
        inspection = Inspection.objects.create(
            id=request.data["id"],
            template=request.data["template"],
            inspector=request.user,
            facility_name=request.data["facility_name"],
            facility_address=request.data["facility_address"],
            responses=request.data["responses"],
            status=request.data["status"],
            version=request.data["version"],
        )
