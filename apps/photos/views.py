from rest_framework import status, viewsets
from rest_framework.decorators import api_view, action, permission_classes
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.shortcuts import get_object_or_404

from apps.inspections.models import Inspection
from .models import Photo
from .services.cloudinary_service import CloudinaryService
from .serializers import PhotoSerializer, PhotoUploadRequestSerializer, PhotoConfirmUploadSerializer

cloudinary_service = CloudinaryService()


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def generate_upload_params(request):
    """
    Generate Cloudinary signed upload parameters

    POST /api/photos/upload-params/
    {
        "inspection_id": "uuid"
    }
    """
    serializer = PhotoUploadRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    print("GENERATING URL VALIDATED:", serializer.validated_data)

    inspection_id = serializer.validated_data["inspection_id"]

    # verify inspection exists and user has access
    get_object_or_404(Inspection, id=inspection_id, inspector=request.user)

    try:
        upload_data = cloudinary_service.generate_upload_params(
            inspection_id=str(inspection_id),
            folder="inspections",
        )
        return Response(upload_data)

    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def confirm_upload(request):
    """
    Confirm that photo was uploaded to Cloudinary and create Photo record

    POST /api/photos/confirm-upload/
    {
        "inspection_id": "uuid",
        "cloudinary_public_id": "inspections/.../photo_123",
        "cloudinary_url": "https://res.cloudinary.com/...",
        "file_size": 123456,
        "width": 1024,
        "height": 768
    }
    """
    serializer = PhotoConfirmUploadSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    inspection_id = serializer.validated_data["inspection_id"]
    cloudinary_public_id = serializer.validated_data["cloudinary_public_id"]
    cloudinary_url = serializer.validated_data["cloudinary_url"]
    file_size = serializer.validated_data["file_size"]
    width = serializer.validated_data.get("width")
    height = serializer.validated_data.get("height")

    # verify inspection exists and user has access
    inspection = get_object_or_404(Inspection, id=inspection_id, inspector=request.user)

    # verify image exists in Cloudinary
    if not cloudinary_service.verify_upload(cloudinary_public_id):
        return Response({"error": "Upload not found in Cloudinary"}, status=status.HTTP_400_BAD_REQUEST)

    # create Photo record
    photo = Photo.objects.create(
        inspection=inspection,
        cloudinary_public_id=cloudinary_public_id,
        cloudinary_url=cloudinary_url,
        file_size=file_size,
        width=width,
        height=height,
    )

    photo_serializer = PhotoSerializer(photo)
    return Response(photo_serializer.data, status=status.HTTP_201_CREATED)


class PhotoViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing photos
    """

    serializer_class = PhotoSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """Only show photos for user's inspections"""
        return Photo.objects.filter(inspection__inspector=self.request.user)

    @action(detail=True, methods=["delete"])
    def delete_photo(self, request, pk=None):
        """Delete photo from Cloudinary and database"""
        photo = self.get_object()

        if photo.cloudinary_public_id:
            cloudinary_service.delete_file(photo.cloudinary_public_id)

        photo.delete()

        return Response(status=status.HTTP_204_NO_CONTENT)
