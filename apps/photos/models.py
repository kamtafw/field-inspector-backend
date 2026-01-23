import uuid
from apps.inspections.models import Inspection
from django.db import models


class Photo(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    inspection = models.ForeignKey(Inspection, on_delete=models.CASCADE, related_name="photos")

    cloudinary_public_id = models.CharField(max_length=500)
    cloudinary_url = models.URLField(max_length=1000)

    file_size = models.IntegerField()
    width = models.IntegerField(null=True, blank=True)
    height = models.IntegerField(null=True, blank=True)

    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "photos"
        ordering = ["-uploaded_at"]
        indexes = [models.Index(fields=["inspection"])]

    def __str__(self):
        return f"Photo {self.id} for inspection {self.inspection_id}"

    @property
    def thumbnail_url(self):
        """Get 200px thumbnail URL"""
        from .services.cloudinary_service import CloudinaryService

        service = CloudinaryService()
        return service.get_thumbnail_url(self.cloudinary_public_id, width=200)

    @property
    def medium_url(self):
        """Get 800px medium size URL"""
        from .services.cloudinary_service import CloudinaryService

        service = CloudinaryService()
        return service.get_image_url(
            self.cloudinary_public_id,
            transformation={"width": 800, "crop": "limit", "quality": "auto"},
        )
