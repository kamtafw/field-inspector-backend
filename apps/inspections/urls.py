from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import InspectionViewSet, InspectionTemplateViewSet

router = DefaultRouter()
router.register(r"inspections", InspectionViewSet, basename="inspection")
router.register(r"templates", InspectionTemplateViewSet, basename="template")

urlpatterns = [
    path("", include(router.urls)),
]
