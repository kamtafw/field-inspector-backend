import logging
import cloudinary
import cloudinary.uploader
import cloudinary.api
from django.conf import settings
import logging

logger = logging.getLogger(__name__)


class CloudinaryService:
    """
    Service for handling Cloudinary operations
    Generates signed upload parameters for direct client uploads
    """

    def __init__(self):
        cloudinary.config(
            cloud_name=settings.CLOUDINARY_STORAGE["CLOUD_NAME"],
            api_key=settings.CLOUDINARY_STORAGE["API_KEY"],
            api_secret=settings.CLOUDINARY_STORAGE["API_SECRET"],
            secure=True,
        )

    def generate_upload_params(self, inspection_id: str, folder: str = "inspections") -> dict:
        """
        Generate signed upload parameters for direct upload to Cloudinary

        Args:
            inspection_id: UUID for the inspection
            folder: Cloudinary folder path

        Returns:
            dict with upload URL, signature, and parameters
        """

        try:
            import time

            # generate timestamp
            timestamp = int(time.time())

            # generate public_id
            public_id = f"{folder}/{inspection_id}/photo_{timestamp}"

            # generate upload signature
            params_to_sign = {
                "folder": folder,
                "public_id": public_id,
                "timestamp": timestamp,
            }

            signature = cloudinary.utils.api_sign_request(
                params_to_sign,
                settings.CLOUDINARY_STORAGE["API_SECRET"],
            )

            upload_url = f"https://api.cloudinary.com/v1_1/{settings.CLOUDINARY_STORAGE['CLOUD_NAME']}/image/upload"

            logger.info(f"Generated Cloudinary upload params for inspection {inspection_id}")

            return {
                "upload_url": upload_url,
                "upload_params": {
                    "api_key": settings.CLOUDINARY_STORAGE["API_KEY"],
                    "timestamp": timestamp,
                    "signature": signature,
                    "folder": folder,
                    "public_id": public_id,
                },
                "public_id": public_id,
                # generate URL for accessing the uploaded image
                "cloudinary_url": f"https://res.cloudinary.com/{settings.CLOUDINARY_STORAGE['CLOUD_NAME']}/image/upload/{public_id}",
            }

        except Exception as e:
            logger.error(f"Failed to generate Cloudinary upload params for inspection {inspection_id}: {str(e)}")
            raise Exception(f"Cloudinary upload params generation failed: {str(e)}")

    def get_image_url(self, public_id: str, transformation: dict = None) -> str:
        """
        Get optimized image URL with optional transformation

        Args:
            public_id : Cloudinary public_id
            transformation : Optional transformation dict (width, height, crop, etc.)

        Returns:
            Cloudinary image URL
        """
        try:
            if transformation:
                url, _ = cloudinary.utils.cloudinary_url(public_id, **transformation)
            else:
                url, _ = cloudinary.utils.cloudinary_url(public_id)

            return url
        except Exception as e:
            logger.error(f"Failed to generate Cloudinary URL: {str(e)}")
            return ""

    def get_thumbnail_url(self, public_id: str, width: int = 200) -> str:
        """
        Get thumbnail URL (automatic transformation)

        Args:
            public_id : Cloudinary public_id
            width : Thumbnail width in pixels

        Returns:
            Thumbnail URL
        """
        return self.get_image_url(
            public_id,
            transformation={
                "width": width,
                "crop": "fill",
                "quality": "auto",
                "fetch_format": "auto",
            },
        )

    def delete_image(self, public_id: str) -> bool:
        """
        Delete an image from Cloudinary

        Args:
            public_id : Cloudinary public_id

        Returns:
            bool indicating success
        """
        try:
            result = cloudinary.uploader.destroy(public_id)
            logger.info(f"Deleted image: {public_id}")
            return result.get("result") == "ok"

        except Exception as e:
            logger.error(f"Failed to delete image {public_id}: {str(e)}")
            return False

    def verify_upload(self, public_id: str) -> bool:
        """
        Verify that an image exists in Cloudinary

        Args:
            public_id : Cloudinary public_id

        Returns:
            bool indicating image exists
        """
        try:
            cloudinary.api.resource(public_id)
            logger.info(f"Verified upload: {public_id}")
            return True

        except cloudinary.exceptions.NotFound:
            logger.warning(f"Upload not found: {public_id}")
            return False

        except Exception as e:
            logger.error(f"Failed to verify upload: {str(e)}")
            return False
