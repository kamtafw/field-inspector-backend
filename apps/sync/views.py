from rest_framework import viewsets
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

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
def batch_sync(request):
    """
    Process a batch of sync operations

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

    serializer = BatchSyncRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    operations = serializer.validated_data["operations"]

    results = BatchSyncService.process_batch(operations, request.user)

    response_serializer = BatchSyncResponseSerializer(results, many=True)
    return Response(response_serializer.data)
