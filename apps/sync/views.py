from rest_framework import viewsets, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django_ratelimit.decorators import ratelimit

from .models import SyncOperation
from .serializers import BatchSyncRequestSerializer, BatchSyncResponseSerializer, SyncOperationSerializer
from .services import BatchSyncService


class SyncOperationViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet for viewing sync operation history
    Read-only - operations are created automatically
    """

    serializer_class = SyncOperationSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return SyncOperation.objects.filter(user=self.request.user).order_by("-processed_at")


@api_view(["POST"])
@permission_classes([IsAuthenticated])
@ratelimit(key="user", rate="20/m", method="POST")
def batch_sync(request):
    """
    Process a batch of sync operations
    Rate limited to 20 requests per minute per user

    POST /api/sync/batch/
    {
        "operations": [
            {
                "operation_type": "CREATE_INSPECTION",
                "idempotency_key": "uuid-here",
                "data": { ... },
            },
            ...
        ]
    }
    """

    if getattr(request, "limited", False):
        return Response(
            {"error": "Rate limited exceeded", "detail": "Maximum 20 batch sync requests per minute. Please try again later."},
            status=status.HTTP_429_TOO_MANY_REQUESTS,
        )

    serializer = BatchSyncRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    operations = serializer.validated_data["operations"]

    if len(operations) > 100:
        return Response({"error": "Maximum 100 operations per batch"}, status=status.HTTP_400_BAD_REQUEST)

    try:
        results = BatchSyncService.process_batch(operations, request.user)
        response_serializer = BatchSyncResponseSerializer(results, many=True)

        has_failures = any(not r["success"] for r in results)
        status_code = status.HTTP_207_MULTI_STATUS if has_failures else status.HTTP_200_OK

        return Response(response_serializer, status=status_code)
    except Exception as e:
        return Response({"error": "Batch sync failed", "detail": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
