from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import SyncOperationViewSet, batch_sync

router = DefaultRouter()
router.register(r"operations", SyncOperationViewSet, basename="sync-operation")

urlpatterns = [
    path("", include(router.urls)),
    path("batch/", batch_sync, name="batch-sync"),
]
