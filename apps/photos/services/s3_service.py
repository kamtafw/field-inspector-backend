import boto3
import uuid
from django.conf import settings
from botocore.exceptions import ClientError
import logging

logger = logging.getLogger(__name__)


class S3Service:
    """
    Service for handling S3 operations
    Generates pre-signed URLs for direct client uploads
    """

    def __init__(self):
        self.s3_client = boto3.client(
            "s3",
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
            region_name=settings.AWS_S3_REGION_NAME,
        )
        self.bucket_name = settings.AWS_STORAGE_BUCKET_NAME

    def generate_upload_url(self, inspection_id: str, file_extension: str = "jpg", content_type: str = "image/jpeg", expires_in: int = 3600) -> dict:
        """
        Generate a pre-signed URL for uploading a photo directly to S3

        Args:
            inspection_id: UUID of the inspection
            file_extension: File extension (jpg, png, etc.)
            content_type: MIME type
            expires_in: URL expiration time in seconds

        Returns:
            dict with upload_url, s3_key, and s3_url
        """
        try:
            # generate unique s3 key
            photo_id = str(uuid.uuid4())
            s3_key = f"inspections/{inspection_id}/photos/{photo_id}.{file_extension}"

            # generate pre-signed POST URL
            presigned_post = self.s3_client.generate_presigned_post(
                Bucket=self.bucket_name,
                Key=s3_key,
                Fields={"Content-Type": content_type},
                Conditions=[
                    {"Content-Type": content_type},
                    ["content-length-range", 1024, 10485760],  # 1kb - 10mb
                ],
                ExpiresIn=expires_in,
            )

            # generate public URL for accessing the file
            s3_url = f"https://{self.bucket_name}.s3.{settings.AWS_S3_REGION_NAME}.amazonaws.com/{s3_key}"

            logger.info(f"Generated upload URL for inspection {inspection_id}")

            return {
                "upload_url": presigned_post["url"],
                "upload_fields": presigned_post["fields"],
                "s3_key": s3_key,
                "s3_url": s3_url,
            }
        except ClientError as e:
            logger.error(f"Failed to generate upload URL: {str(e)}")
            raise Exception(f"S3 upload URL generation failed: {str(e)}")

    def confirm_upload(self, s3_key: str) -> bool:
        """Verify that a file was successfully uploaded to S3"""

        try:
            self.s3_client.head_object(Bucket=self.bucket_name, Key=s3_key)
            logger.info(f"Confirmed upload: {s3_key}")
            return True
        except ClientError:
            logger.warning(f"Upload not confirmed: {s3_key}")
            return False

    def delete_file(self, s3_key: str) -> bool:
        """Delete a file from S3"""
        try:
            self.s3_client.delete_object(Bucket=self.bucket_name, Key=s3_key)
            logger.info(f"Deleted file: {s3_key}")
            return True
        except ClientError as e:
            logger.error(f"Failed to delete file {s3_key}: {str(e)}")
            return False
