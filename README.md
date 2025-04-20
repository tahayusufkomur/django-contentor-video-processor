# Contentor Video Processor

A Django app for programmatically creating different video resolutions, compressing videos, and reducing storage and bandwidth costs without sacrificing quality. Reduce video sizes dramatically (e.g., from 1GB to 100MB) while maintaining visual quality.

## Preview

Below are screenshots that demonstrate the key features and interfaces of the Contentor Video Processor Demo:

*The video uploaded with chunks to prevent timeout or memory leak*
![Video Upload Interface](/docs/upload.gif)

*Contentor dashboard for realtime monitoring*
![Results Dashboard](/docs/contentor-dashboard.png)

*Status Table in the beginning admin panel*
![Status Table](/docs/status-table-1.png)

*Status Table after complete in the admin panel*
![Status Table](/docs/status-table-2.png)

*Built-in player with resolution settings*
![Video Player](/docs/video_player.gif)

## Features

- Chunk upload support for large video files (10GB+ files can be uploaded with proper settings)
- Automatic video compression and resolution conversion
- Support for multiple video resolutions (original, 720p, 480p, 360p)
- S3-compatible storage integration
- Chunked file uploads for large video files
- Webhook notifications for processing status updates
- Easy integration with your existing Django models

## 🧪 Have a Look at the Demo Repo

Curious to see how it works in action? Check out the [**Demo Repository**](https://github.com/tahayusufkomur/django-contentor-processor-demo) for a fully functional example.


> Perfect for testing, learning, or using as a starting point for your own project.


## Installation

```bash
pip install django-contentor-video-processor
```

## Quick Start

### 1. Add to INSTALLED_APPS

Add `contentor_video_processor` to your `INSTALLED_APPS` in `settings.py`:

```python
INSTALLED_APPS = [
    # ...
    'contentor_video_processor',
    # ...
]
```

### 2. Configure Settings

Add the following to your `settings.py`:

```python
# STORAGE SETTINGS
DEFAULT_FILE_STORAGE = "storages.backends.s3boto3.S3Boto3Storage"

AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
AWS_STORAGE_BUCKET_NAME = os.getenv("AWS_BUCKET_NAME")
AWS_S3_ENDPOINT_URL = os.getenv("AWS_ENDPOINT")

AWS_LOCATION = "customers/your-org/media"

# Remove hardcoded `MEDIA_URL` if you want signed URLs
AWS_DEFAULT_ACL = None
AWS_QUERYSTRING_AUTH = True  # Enable signed URLs
AWS_S3_FILE_OVERWRITE = True
AWS_S3_OBJECT_PARAMETERS = {
    "CacheControl": "max-age=3600",  # Cache for 1 hour
}

ADMIN_RESUMABLE_CHUNK_STORAGE = "storages.backends.s3boto3.S3Boto3Storage"
ADMIN_RESUMABLE_STORAGE = "storages.backends.s3boto3.S3Boto3Storage"
ADMIN_RESUMABLE_CHUNKSIZE = 52428800  # 50MB matching chunk size

# Contentor API credentials (get your free API key at https://contentor.app)
CONTENTOR_VIDEO_PROCESSING_ACCESS_KEY = os.getenv("CONTENTOR_VIDEO_PROCESSING_ACCESS_KEY", "")
CONTENTOR_VIDEO_PROCESSING_ACCESS_TOKEN = os.getenv("CONTENTOR_VIDEO_PROCESSING_ACCESS_TOKEN", "")

# Your application's base URL (needed for webhook notifications)
BASE_URL = "https://your-app-url.com"

# The app and model that will contain your videos
CONTENTOR_VIDEO_MODEL = "your_app.Video"
CONTENTOR_VIDEO_PROCESSING_REQUESTS_APP = "your_app"
CONTENTOR_PROCESSING_REQUEST_MODEL_VERBOSE_NAME = "Video Processing Request"
CONTENTOR_PROCESSING_REQUEST_MODEL_VERBOSE_NAME_PLURAL = "Video Processing Requests"
CONTENTOR_VIDEO_RESOLUTIONS = ["original", "720p", "480p", "360p"]
CONTENTOR_ORIGINAL_RESOLUTION = "1080p"

# Additional configuration options
CONTENTOR_VIDEO_PROCESSING_CONFIG = {
    # contentor settings
    "api_url": "https://process.contentor.app/api/process-video/",
    "download_provider": "minio",
    "upload_provider": "minio",
    "original_resolution": "1080p",
    "resolutions": ["original", "720p", "480p", "360p"],

    # video quality settings
    "crf": "30",                # Compression quality (lower = better quality, higher file size)
    "preset": "ultrafast",      # Encoding speed preset
    "optimise_for_web": True,
    "output_file_format": "mp4" # Output format
}
```

### 3. Update URLs

Add the Contentor Video Processor URLs to your main `urls.py`:

```python
from django.urls import include, path

urlpatterns = [
    # ...
    path("contentor-video/", include("contentor_video_processor.urls")),
    # ...
]
```

### 4. Integrate with Your Models

Inherit from `ContentorVideoModel` and add a `ContentorVideoField` to your model:

```python
from django.db import models
from contentor_video_processor.models import ContentorVideoModel
from contentor_video_processor.models import ContentorVideoField

class Video(ContentorVideoModel):
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    
    # This field will store your video and handle processing
    video = ContentorVideoField(
        null=True,
        blank=True,
        upload_to="videos/original/",
    )
    
    # Add any other fields you need
```

### 5. Run Migrations

```bash
python manage.py makemigrations
python manage.py migrate
```

### 6. Collect Static Files

Ensure that `STATICFILES_FINDERS` includes `AppDirectoriesFinder`:

```python
STATICFILES_FINDERS = [
    'django.contrib.staticfiles.finders.FileSystemFinder',
    'django.contrib.staticfiles.finders.AppDirectoriesFinder',
]
```

Then run:

```bash
python manage.py collectstatic
```

### 7. Use the Video Template

In your templates, use the provided video element to display your videos with all available resolutions:

```html
{% include "contentor_video_processor/video_element.html" with video=your_video_object %}
```

## Server Configuration

### Nginx Configuration for Large File Uploads

When handling large video files, you may need to adjust your server timeout settings to avoid upload timeouts. Here's an example Nginx configuration:

```nginx
location /contentor-video/upload {
    proxy_pass http://app:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;

    proxy_connect_timeout 300;
    proxy_send_timeout    300;
    proxy_read_timeout    300;
    send_timeout          300;
}
```

## Advanced Usage

### Customizing Video Processing Options

You can customize the video processing options by modifying the `CONTENTOR_VIDEO_PROCESSING_CONFIG` in your settings:

```python
CONTENTOR_VIDEO_PROCESSING_CONFIG = {
    # ...
    "crf": "23",            # Better quality but larger file size
    "preset": "medium",     # Balance between encoding speed and compression
    # ...
}
```

### Webhook Notifications

The app can send notifications when video processing is complete. To enable this, make sure you have set either:

- The `BASE_URL` setting, which will construct a webhook URL automatically
- A hardcoded webhook URL in your configuration

## Troubleshooting

### Upload Issues

- If you're experiencing timeouts during large file uploads, increase the timeout settings in your web server configuration.
- Ensure your S3-compatible storage is properly configured with the correct credentials.

### Processing Issues

- Verify that your Contentor API credentials are correct.
- Check the Contentor dashboard for processing status and error messages.
- Ensure your webhook URL is accessible from the internet if you're expecting status updates.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

[License information]
This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.
```