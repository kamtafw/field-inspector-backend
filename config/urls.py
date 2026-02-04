from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path("admin/", admin.site.urls),
    # API v1
    path("api/v1/auth/", include("apps.authentication.urls")),
    path("api/v1/", include("apps.inspections.urls")),
    path("api/v1/photos/", include("apps.photos.urls")),
    path("api/v1/sync/", include("apps.sync.urls")),
]
