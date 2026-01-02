from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/auth/", include("apps.authentication.urls")),
    path("api/", include("apps.inspections.urls")),
    path("api/sync/", include("apps.sync.urls")),
]
