from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.db import transaction
from django.db.models import Max
from django.utils import timezone
from django.utils.http import http_date
from django.views.decorators.http import condition
from django.utils.decorators import method_decorator
from django.core.exceptions import ValidationError
from django_ratelimit.decorators import ratelimit

from .models import Inspection, InspectionTemplate
from .serializers import InspectionSerializer, CreateInspectionSerializer, UpdateInspectionSerializer, InspectionTemplateSerializer
from .services import InspectionService, ConflictError
from apps.sync.models import ConflictRecord


def get_templates_etag(request, *args, **kwargs):
    """Generate ETag based on template update"""
    latest = InspectionTemplate.objects.filter(is_active=True).aggregate(Max("updated_at"))["updated_at__max"]

    if latest:
        return latest.isoformat()
    return "no-templates"


class InspectionTemplateViewSet(viewsets.ModelViewSet):
    """Read-only viewset for inspection templates with ETag caching"""

    serializer_class = InspectionTemplateSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "head", "options"]

    def get_queryset(self):
        return InspectionTemplate.objects.filter(is_active=True)

    @condition(
        etag_func=lambda request, *args, **kwargs: (
            InspectionTemplate.objects.aggregate(Max("updated_at"))["updated_at__max"].isoformat() if InspectionTemplate.objects.exists() else None
        )
    )
    @method_decorator(condition(etag_func=get_templates_etag))
    def list(self, request, *args, **kwargs):
        """
        List all active templates with ETag caching
        Returns 304 Not Modified if client ETag matches
        """
        return super().list(request, *args, **kwargs)

    def retrieve(self, request, *args, **kwargs):
        """Retrieve single template"""
        return super().retrieve(request, *args, **kwargs)


class InspectionViewSet(viewsets.ModelViewSet):
    """Viewset for inspections with conflict handling"""

    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        qs = Inspection.objects.all()

        # prefetch related data to avoid N+1 queries
        qs = qs.select_related("inspector", "approved_by", "template")
        qs = qs.prefetch_related("photos")

        # managers see all, inspectors see only their own
        if hasattr(user, "role") and user.role == "manager":
            return qs

        return qs.filter(inspector=user)

    def get_serializer_class(self):
        if self.action == "create":
            return CreateInspectionSerializer
        elif self.action in ["update", "partial_update"]:
            return UpdateInspectionSerializer
        return InspectionSerializer

    def get_object(self):
        obj = Inspection.objects.select_for_update().get(pk=self.kwargs["pk"])

        # if self.request.user.role != "manager" and obj.inspector != self.request.user:
        #     raise PermissionDenied("You cannot update this inspection")

        return obj

    @method_decorator(ratelimit(key="user", rate="100/h", method="POST"))
    @transaction.atomic
    def create(self, request):
        """
        Create new inspection
        Handles idempotency check and optimistic locking
        """

        if getattr(request, "limited", False):
            return Response(
                {"error": "Rate limited exceeded", "detail": "Maximum 100 inspections per hour. Please try again later."},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # idempotency check
        idempotency_key = request.headers.get("Idempotency-Key")
        if idempotency_key:
            from apps.sync.services import IdempotencyService

            cached_result = IdempotencyService.get_result(idempotency_key)
            if cached_result:
                return Response(cached_result)

        try:
            inspection = InspectionService.create_inspection(data=serializer.validated_data, user=request.user)

            result = {"id": str(inspection.id), "version": inspection.version}

            # record idempotency
            if idempotency_key:
                IdempotencyService.record(
                    idempotency_key=idempotency_key,
                    operation_type="CREATE_INSPECTION",
                    entity_id=str(inspection.id),
                    user=request.user,
                    result=result,
                )

            return Response(result, status=status.HTTP_201_CREATED)

        except ValidationError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @method_decorator(ratelimit(key="user", rate="200/h", method=["PUT", "PATCH"]))
    @transaction.atomic
    def update(self, request, pk=None):
        """
        Update inspection with optimistic locking
        Returns 409 Conflict if version mismatch
        """

        if getattr(request, "limited", False):
            return Response(
                {"error": "Rate limit exceeded", "detail": "Maximum 200 updates per hour. Please try again later."},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        inspection = self.get_object()
        serializer = self.get_serializer(inspection, data=request.data, partial=False)
        serializer.is_valid(raise_exception=True)

        client_version = serializer.validated_data.get("version")

        # idempotency check
        idempotency_key = request.headers.get("Idempotency-Key")
        if idempotency_key:
            from apps.sync.services import IdempotencyService

            cached_result = IdempotencyService.get_result(idempotency_key)
            if cached_result:
                return Response(cached_result)

        try:
            updated_inspection = InspectionService.update_inspection(
                inspection_id=str(inspection.id),
                data=request.data,
                client_version=client_version,
            )

            result = {"id": str(updated_inspection.id), "version": updated_inspection.version}

            # record idempotency
            if idempotency_key:
                from apps.sync.services import IdempotencyService

                IdempotencyService.record(
                    idempotency_key=idempotency_key,
                    operation_type="UPDATE_INSPECTION",
                    entity_id=str(updated_inspection.id),
                    user=request.user,
                    result=result,
                )

            return Response(result)

        except ConflictError as e:
            ConflictRecord.objects.create(
                inspection=e.inspection,
                client_version_number=e.client_version,
                server_version_number=e.server_version,
                client_data=serializer.validated_data,
                server_data={
                    "id": str(e.inspection.id),
                    "template_id": str(e.inspection.template_id),
                    "facility_name": e.inspection.facility_name,
                    "facility_address": e.inspection.facility_address,
                    "responses": e.inspection.responses,
                    "status": e.inspection.status,
                    "version": e.inspection.version,
                },
            )

            return Response(
                {
                    "error": "conflict",
                    "message": str(e),
                    "client_version": e.client_version,
                    "server_version": e.server_version,
                    "server_data": {
                        "id": str(e.inspection.id),
                        "template_id": str(e.inspection.template.id),
                        "facility_name": e.inspection.facility_name,
                        "facility_address": e.inspection.facility_address,
                        "responses": e.inspection.responses,
                        "status": e.inspection.status,
                        "version": e.inspection.version,
                        "updated_by": {
                            "id": str(e.inspection.inspector.id) if e.inspection.inspector else None,
                            "email": e.inspection.inspector.email if e.inspection.inspector else None,
                            "name": (
                                f"{e.inspection.inspector.first_name} {e.inspection.inspector.last_name}".strip()
                                if e.inspection.inspector and (e.inspection.inspector.first_name or e.inspection.inspector.last_name)
                                else e.inspection.inspector.email if e.inspection.inspector else "Unknown"
                            ),
                        },
                        "updated_at": e.inspection.updated_at.isoformat() if e.inspection.updated_at else None,
                    },
                },
                status=status.HTTP_409_CONFLICT,
            )

        except Inspection.DoesNotExist:
            return Response({"error": "Inspection not found"}, status=status.HTTP_400_BAD_REQUEST)

    @transaction.atomic
    def destroy(self, request, pk=None):
        """
        Soft delete an inspection
        Only drafts can be deleted
        """
        inspection = self.get_object()

        if inspection.status != "draft":
            return Response(
                {"error": "Cannot delete inspection", "detail": "Only draft inspections can be deleted"}, status=status.HTTP_400_BAD_REQUEST
            )

        inspection.soft_delete(user=request.user)

        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["get"])
    def check_version(self, request, pk=None):
        """
        Check if client version is current before editing

        GET /api/inspections/{id}/check_version?version=5
        Returns: { "is_current": true/false, "server_version": 6 }
        """
        inspection = self.get_object()
        client_version = int(request.query_params.get("version", 0))

        return Response(
            {
                "is_current": inspection.version == client_version,
                "server_version": inspection.version,
                "last_updated_by": (
                    {
                        "name": f"{inspection.inspector.first_name} {inspection.inspector.last_name}",
                        "email": inspection.inspector.email,
                    }
                    if inspection.inspector
                    else None
                ),
                "updated_at": inspection.updated_at.isoformat(),
            }
        )

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
        # inspection.save()

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
        # inspection.save()

        # TODO: send push notification to inspector

        serializer = InspectionSerializer(inspection)
        return Response(serializer.data)
