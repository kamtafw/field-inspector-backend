from rest_framework import serializers
from .models import Photo


class PhotoSerializer(serializers.ModelSerializer):
    """
    Serializer for Photo model
    """

    inspection_id = serializers.UUIDField(source="inspection.id", read_only=True)
    thumbnail_url = serializers.SerializerMethodField()
    medium_url = serializers.SerializerMethodField()

    class Meta:
        model = Photo
        fields = [
            "id",
            "inspection",
            "inspection_id",
            "cloudinary_public_id",
            "cloudinary_url",
            "thumbnail_url",
            "medium_url",
            "file_size",
            "width",
            "height",
            "uploaded_at",
        ]
        read_only_fields = ["id", "uploaded_at", "inspection_id", "thumbnail_url", "medium_url"]

    def get_thumbnail_url(self, obj):
        """Get 200px thumbnail"""
        return obj.thumbnail_url

    def get_medium_url(self, obj):
        """Get 800px medium size"""
        return obj.medium_url

    def validate_file_size(self, value):
        """Ensure file size is within limits"""
        max_size = 10 * 1024 * 1024  # 10mb
        if value > max_size:
            raise serializers.ValidationError(f"File size cannot exceed {max_size/(1024*1024)}MB")
        return value


class PhotoUploadRequestSerializer(serializers.Serializer):
    """
    Serializer for requesting upload URL
    """

    inspection_id = serializers.UUIDField(required=True)


class PhotoConfirmUploadSerializer(serializers.Serializer):
    """
    Serializer for confirming photo upload
    """

    inspection_id = serializers.UUIDField(required=True)
    cloudinary_public_id = serializers.CharField(required=True, max_length=500)
    cloudinary_url = serializers.URLField(required=True, max_length=1000)
    file_size = serializers.IntegerField(required=True)
    width = serializers.IntegerField(required=False, allow_null=True)
    height = serializers.IntegerField(required=False, allow_null=True)

    def validate_file_size(self, value):
        """Ensure file size is within limits"""
        if value <= 0:
            raise serializers.ValidationError("File size must be greater than 0")

        max_size = 10 * 1024 * 1024  # 10MB
        if value > max_size:
            raise serializers.ValidationError(f"File size cannot exceed {max_size / (1024 * 1024)}MB")
        return value
