from urllib.parse import urlparse, unquote

import boto3
import requests
from django.apps import apps
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.safestring import mark_safe

from contentor_video_processor.fields import FormResumableFileField
from contentor_video_processor.functions import process_video, get_webhook_url, replace_file_format
from contentor_video_processor.widgets import ResumableAdminWidget


def get_s3_client(access_key, secret_key, endpoint_url=None):
    s3_args = {
        "aws_access_key_id": access_key,
        "aws_secret_access_key": secret_key,
    }

    # Only add endpoint_url if it's provided
    if endpoint_url:
        s3_args["endpoint_url"] = endpoint_url

    return boto3.client("s3", **s3_args)


class AsyncFileField(models.FileField):

    def formfield(self, **kwargs):
        defaults = {"form_class": FormResumableFileField}
        if self.model and self.name:
            defaults["widget"] = ResumableAdminWidget(
                attrs={"model": self.model, "field_name": self.name}
            )
        kwargs.update(defaults)
        return super(AsyncFileField, self).formfield(**kwargs)


class ContentorVideoField(AsyncFileField):
    def __init__(self, *args, allowed_formats=None, max_size_mb=None, resolutions=None, **kwargs):
        self.allowed_formats = allowed_formats or []  # Empty = allow anything
        self.max_size_mb = max_size_mb or 3000  # Default to 3GB
        self.resolutions = resolutions or settings.CONTENTOR_VIDEO_PROCESSING_CONFIG.get("resolutions", ["original"])
        super().__init__(*args, **kwargs)

    def clean(self, value, model_instance):
        file = value.file

        # Validate file extension (if specified)
        if self.allowed_formats:
            ext = file.name.split('.')[-1].lower()
            if ext not in self.allowed_formats:
                raise ValidationError(f"Only files with extensions {', '.join(self.allowed_formats)} are allowed.")

        # Validate file size
        if file.size > self.max_size_mb * 1024 * 1024:
            raise ValidationError(f"File size must be smaller than {self.max_size_mb}MB.")

        return super().clean(value, model_instance)


class ContentorVideoModelMixin(models.Model):
    class Meta:
        abstract = True

    def sync_video_resolutions(self):
        """
        Sync video resolutions with external storage and database.
        Checks if resolution files exist in storage and creates/updates processing requests accordingly.
        """
        # Get the video field dynamically
        video_field_name = self.get_video_file_field()
        if not video_field_name:
            return

        video_field = getattr(self, video_field_name)
        if not video_field:
            return

        # Get video URL and parse it
        video_url = video_field.url
        video_parsed = urlparse(video_url)

        aws_location = getattr(settings, "AWS_LOCATION", None)
        original_path = f"{aws_location}/{video_field.name}" if aws_location else video_field.name


        # Get configuration
        contentor_config = getattr(settings, "CONTENTOR_VIDEO_PROCESSING_CONFIG", {})
        resolutions = contentor_config.get("resolutions", ["original"])

        video_processing_request_model = get_video_processing_request_model()

        # Process each resolution
        for resolution in resolutions:
            # Replace "original" with the resolution in the path
            check_path = original_path.replace("original", resolution)

            # Create a signed URL for checking existence
            output_file_size_mb = self._check_file_exists(check_path)

            # Get the most recent processing request for this resolution
            existing_request = (
                video_processing_request_model.objects
                .filter(video=self, resolution=resolution)
                .order_by("-id")
                .first()
            )

            # Prepare URLs
            download_url = video_field.url.split('?')[0]  # do not take the signature part
            upload_url = f"{video_parsed.scheme}://{video_parsed.netloc}/{original_path}"

            if output_file_size_mb:
                if resolution != "original":
                    # Check if there's a field for this resolution
                    resolution_field_name = f"{video_field_name}_{resolution}"
                    if hasattr(self, resolution_field_name):
                        # Update the resolution field if it exists
                        resolution_field = getattr(self, resolution_field_name)
                        if hasattr(resolution_field, 'name'):
                            resolution_field.name = video_field.name.replace("original", resolution)
                            self.save(update_fields=[resolution_field_name], skip_processing=True)

                resolution = contentor_config.get("original_resolution",
                                                  "1080p") if resolution == "original" else resolution

                # Create or update processing request with skip_process=True
                if existing_request:
                    # Update existing request if needed
                    if existing_request.status != "completed":
                        existing_request.status = "completed"
                        existing_request.save(skip_process=True)
                else:
                    # First create the instance without saving
                    video_processing_request = video_processing_request_model(
                        video=self,
                        resolution=resolution,
                        download_url=download_url,
                        upload_url=upload_url,
                        output_file_size_mb=output_file_size_mb,
                        download_provider=contentor_config.get("download_provider", "aws"),
                        upload_provider=contentor_config.get("upload_provider", "aws"),
                        webhook_url=getattr(settings, "CONTENTOR_WEBHOOK_URL", get_webhook_url()),
                        history={},
                        status="completed",
                    )
                    # Then save it with skip_process=True
                    video_processing_request.save(skip_process=True)
            else:
                # File doesn't exist in storage
                if not existing_request or existing_request.status not in ["pending", "processing"]:
                    # Create new processing request without skipping
                    pass
                    video_processing_request_model.objects.create(
                        video=self,
                        resolution=resolution,
                        download_url=download_url,
                        upload_url=upload_url,
                        download_provider=contentor_config.get("download_provider", "aws"),
                        upload_provider=contentor_config.get("upload_provider", "aws"),
                        webhook_url=getattr(settings, "CONTENTOR_WEBHOOK_URL", get_webhook_url()),
                        history={},
                    )

    def _check_file_exists(self, path):
        """
        Check if a file exists in S3 using direct boto3 client
        """
        from botocore.exceptions import ClientError

        try:
            # Remove leading slash from path
            s3_key = path.lstrip("/")

            # Get AWS credentials from settings
            aws_access_key = getattr(settings, 'AWS_ACCESS_KEY_ID', None)
            aws_secret_key = getattr(settings, 'AWS_SECRET_ACCESS_KEY', None)
            aws_bucket_name = getattr(settings, 'AWS_STORAGE_BUCKET_NAME', None)
            aws_endpoint = getattr(settings, 'AWS_S3_ENDPOINT_URL', None)

            if not all([aws_access_key, aws_secret_key, aws_bucket_name]):
                return False

            # Create S3 client
            s3_client = get_s3_client(
                aws_access_key,
                aws_secret_key,
                aws_endpoint
            )

            # Use head_object to check if the file exists
            head_object = s3_client.head_object(Bucket=aws_bucket_name, Key=s3_key)
            # Get size in bytes from the response
            size_in_bytes = head_object['ContentLength']

            # Convert to megabytes
            size_in_mb = size_in_bytes / (1024 * 1024)

            return size_in_mb

        except ClientError as e:
            # If error code is 404, the file doesn't exist
            if e.response['Error']['Code'] == '404':
                return False
            # For other errors, log and return False
            print(f"Error checking file existence: {e}")
            return False
        except Exception as e:
            # Log the error if needed
            print(f"Error checking file existence: {e}")
            return False

    def sync_selected_videos(self, video_queryset=None):
        """
        Class method to sync multiple videos.
        Can be called on a queryset or collection of video objects.
        """
        if video_queryset is None:
            video_queryset = [self]

        for video in video_queryset:
            if hasattr(video, 'sync_video_resolutions'):
                video.sync_video_resolutions()

    def get_video_file_field(self):
        for field in self._meta.fields:
            if isinstance(field, ContentorVideoField):
                return field.name
        return None

    def create_video_processing_objects(self):
        video_field_name = self.get_video_file_field()
        if not video_field_name:
            return

        video_field = getattr(self, video_field_name)
        if not video_field:
            return
        video_url = video_field.url

        video_parsed = urlparse(video_url)
        original_path = unquote(video_parsed.path)
        download_url = f"{video_parsed.scheme}://{video_parsed.netloc}{original_path}"

        contentor_config = getattr(settings, "CONTENTOR_VIDEO_PROCESSING_CONFIG", {})
        resolutions = contentor_config.get("resolutions", ["original"])

        for resolution in resolutions:
            # If resolution is not 'original', modify the upload URL
            if resolution == "original":
                upload_url = download_url
                resolution = contentor_config.get("original_resolution", "1080p")
            else:
                upload_url = download_url.replace("original", resolution)

            upload_url = replace_file_format(upload_url, "mp4")

            video_processing_request_model = get_video_processing_request_model()
            object = video_processing_request_model.objects.create(
                video=self,
                resolution=resolution,
                download_url=download_url,
                upload_url=upload_url,
                download_provider=contentor_config.get("download_provider", "aws"),
                upload_provider=contentor_config.get("upload_provider", "aws"),
                webhook_url=getattr(settings, "CONTENTOR_WEBHOOK_URL", get_webhook_url()),
                history={},
            )

            if resolution:
                object.resolution = resolution
                object.save(update_fields=["resolution"])

    def get_video_resolution_table_html(self):
        resolutions = ["original", "720p", "480p", "360p"]
        cells = []

        contentor_config = getattr(settings, "CONTENTOR_VIDEO_PROCESSING_CONFIG", {})

        for res in resolutions:
            # Map 'original' to None if your model stores it that way
            resolution_key = contentor_config.get("original_resolution", "1080p") if res == "original" else res

            request = (
                VideoProcessingRequest.objects
                .filter(video=self, resolution=resolution_key)
                .order_by("-id")  # or use -created_at if you have it
                .first()
            )

            if not request:
                cell = f"<td><i>no request</i></td>"
            elif request.status != "completed":
                cell = f"<td><span>{request.status}</span></td>"
            else:
                size_mb = round(request.output_file_size_mb, 2)
                cell = f"<td>{size_mb} MB</td>"

            cells.append(cell)

        html = f"""
        <table border="1" style="border-collapse: collapse;">
            <tr>
                <th>Original</th>
                <th>720p</th>
                <th>480p</th>
                <th>360p</th>
            </tr>
            <tr>
                {''.join(cells)}
            </tr>
        </table>
        """
        return mark_safe(html)

    def save(self, skip_processing=False, *args, **kwargs):
        is_new = self.pk is None
        video_field = self.get_video_file_field()
        file_has_changed = False

        if self.pk and video_field:
            old = self.__class__.objects.get(pk=self.pk)
            file_has_changed = getattr(old, video_field) != getattr(self, video_field)

        if is_new or file_has_changed:
            # Here you can add code to handle the file change
            # For example, trigger transcoding for each resolution
            if not skip_processing:
                self.create_video_processing_objects()
        super().save(*args, **kwargs)


# MetaClass to handle dynamic field creation
class ContentorVideoModelBase(models.base.ModelBase):

    def __new__(mcs, name, bases, attrs):
        # First create the class
        cls = super().__new__(mcs, name, bases, attrs)

        # Only apply to subclasses of ContentorVideoModelMixin, not the mixin itself
        if name == 'ContentorVideoModelMixin':
            return cls

        # Find ContentorVideoField instances in the class
        video_fields = []
        for field_name, field in attrs.items():
            if isinstance(field, ContentorVideoField):
                video_fields.append((field_name, field))

        # Add resolution-specific fields for each video field
        for field_name, field in video_fields:
            for resolution in field.resolutions:
                if resolution == "original":
                    continue

                # Remove 'p' for field name if present (e.g., '720p' -> '720')

                # Add path field
                video_field_name = f"video_{resolution}"
                if not hasattr(cls, video_field_name):
                    video_field = models.FileField(
                        null=True,
                        blank=True,
                        editable=False,
                        upload_to=f"videos/{resolution}",
                        help_text="Yalnızca mov veya mp4 formatında, 3GB'den küçük dosyalar yükleyiniz.",
                    )
                    cls.add_to_class(video_field_name, video_field)

        return cls


class ContentorVideoModel(ContentorVideoModelMixin, models.Model, metaclass=ContentorVideoModelBase):
    class Meta:
        abstract = True


class AbstractVideoProcessingRequest(models.Model):
    uuid = models.UUIDField(blank=True, null=True, editable=False)
    video = models.ForeignKey(
        settings.CONTENTOR_VIDEO_MODEL, related_name="processing_jobs", on_delete=models.CASCADE
    )
    output_file_size_mb = models.FloatField(verbose_name="Output File Size (MB)", null=True, blank=True)
    video_duration = models.FloatField(verbose_name="Duration (seconds)", null=True, blank=True)
    metadata = models.JSONField(default=dict)

    RESOLUTION_CHOICES = [
        ("2160p", "2160p (4K)"),
        ("1080p", "1080p (Full HD)"),
        ("720p", "720p (HD)"),
        ("480p", "480p (SD)"),
        ("360p", "360p (Low)"),
    ]
    resolution = models.CharField(
        max_length=5, choices=RESOLUTION_CHOICES, default="1080p"
    )

    download_url = models.URLField(max_length=500, blank=True, null=True)
    upload_url = models.URLField(max_length=500, blank=True, null=True)

    download_provider = models.CharField(max_length=100, blank=True, null=True)
    upload_provider = models.CharField(max_length=100, blank=True, null=True)

    webhook_url = models.URLField(max_length=500, blank=True, null=True)

    history = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=50, default="pending")

    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = settings.CONTENTOR_PROCESSING_REQUEST_MODEL_VERBOSE_NAME
        verbose_name_plural = settings.CONTENTOR_PROCESSING_REQUEST_MODEL_VERBOSE_NAME_PLURAL
        abstract = True

    def __str__(self):
        return f"Processing Job for Video {self.video_id} [{self.id}]"

    def process_video(self):
        self.uuid = process_video(
            download_url=self.download_url,
            upload_url=self.upload_url,
            resolution=self.resolution,
        )
        self.save(update_fields=["uuid"], skip_process=True)  # Only updates the uuid field

    def save(self, skip_process=False, *args, **kwargs):
        super().save(*args, **kwargs)
        if not self.uuid and not skip_process:
            self.process_video()


def get_video_processing_request_model():
    app_label = settings.CONTENTOR_VIDEO_PROCESSING_REQUESTS_APP
    return apps.get_model(app_label, "VideoProcessingRequest")


class VideoProcessingRequest(AbstractVideoProcessingRequest):
    class Meta:
        app_label = settings.CONTENTOR_VIDEO_PROCESSING_REQUESTS_APP
        verbose_name = settings.CONTENTOR_PROCESSING_REQUEST_MODEL_VERBOSE_NAME
        verbose_name_plural = settings.CONTENTOR_PROCESSING_REQUEST_MODEL_VERBOSE_NAME_PLURAL
