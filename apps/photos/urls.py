from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import generate_upload_params, confirm_upload, PhotoViewSet

router = DefaultRouter()
router.register(r"photos", PhotoViewSet, basename="photo")

urlpatterns = [
    path("upload-params/", generate_upload_params, name="generate-upload-params"),
    path("confirm-upload/", confirm_upload, name="confirm-upload"),
    path("", include(router.urls)),
]
