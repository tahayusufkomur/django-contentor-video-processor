from urllib.parse import urlparse

from django.apps import apps
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.contrib.contenttypes.models import ContentType
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404
from django.utils.functional import cached_property
from django.views.decorators.csrf import csrf_exempt
from django.views.generic import View
from contentor_video_processor.files import ResumableFile
from contentor_video_processor.models import VideoProcessingRequest


class UploadView(View):

    @cached_property
    def request_data(self):
        return getattr(self.request, self.request.method)

    @cached_property
    def model_upload_field(self):
        content_type = ContentType.objects.get_for_id(
            self.request_data["content_type_id"]
        )
        return content_type.model_class()._meta.get_field(
            self.request_data["field_name"]
        )

    def post(self, request, *args, **kwargs):
        chunk = request.FILES.get("file")
        r = ResumableFile(
            self.model_upload_field, user=request.user, params=request.POST
        )
        if not r.chunk_exists:
            r.process_chunk(chunk)
        if r.is_complete:
            return HttpResponse(r.collect())
        return HttpResponse("chunk uploaded")

    def get(self, request, *args, **kwargs):
        r = ResumableFile(
            self.model_upload_field, user=request.user, params=request.GET
        )
        if not r.chunk_exists:
            return HttpResponse("chunk not found", status=404)
        if r.is_complete:
            return HttpResponse(r.collect())
        return HttpResponse("chunk exists")


contentor_video = login_required(csrf_exempt(UploadView.as_view()))


@login_required
def get_video_signed_url(request, video_id, quality):
    """
    Get a fresh signed URL for a specific video quality
    Args:
        video_id: The ID of the video
        quality: The quality string ('original', '720p', '480p', '360p')
    Returns:
        A JsonResponse with the signed URL
    """
    # Only allow GET requests
    if request.method != "GET":
        return JsonResponse(
            {"success": False, "message": "Method not allowed"}, status=405
        )

    VideoModel = apps.get_model(*settings.CONTENTOR_VIDEO_MODEL.split('.'))

    video = get_object_or_404(VideoModel, id=video_id)

    # Map quality string to the corresponding field
    quality_field_map = {}

    for res in settings.CONTENTOR_VIDEO_RESOLUTIONS:
        field_name = "video" if res == "original" else f"video_{res}"
        quality_field_map[res] = getattr(video, field_name, None)

    # Get the field from the map
    video_field = quality_field_map.get(quality)

    if not video_field:
        return JsonResponse(
            {
                "success": False,
                "message": f"Video quality {quality} not available for this video",
            },
            status=404,
        )

    try:
        url = video_field.url
        return JsonResponse({"success": True, "url": url})
    except Exception as e:
        return JsonResponse({"success": False, "message": str(e)}, status=500)



@csrf_exempt
def webhook_receiver(request):
    try:
        import hmac
        import hashlib
        import base64
        import json

        # Get the request data
        data = json.loads(request.body)
        payload = data.get("data")
        received_signature = data.get("signature")

        if not payload or not received_signature:
            return JsonResponse(
                {"status": "error", "message": "Missing data or signature"}, status=400
            )

        # For testing, use a hardcoded token
        token = settings.CONTENTOR_VIDEO_PROCESSING_ACCESS_TOKEN

        # Convert payload to JSON string in the same way as the sender
        payload_json = json.dumps(payload, sort_keys=True)

        # Compute the expected signature
        expected_signature = hmac.new(
            key=token.encode("utf-8"),
            msg=payload_json.encode("utf-8"),
            digestmod=hashlib.sha256,
        ).digest()

        # Base64 encode for comparison
        expected_signature_b64 = base64.b64encode(expected_signature).decode("utf-8")

        # Verify signatures match using constant-time comparison to prevent timing attacks
        if not hmac.compare_digest(expected_signature_b64, received_signature):
            return JsonResponse(
                {"status": "error", "message": "Invalid signature"}, status=403
            )

        # Process the webhook data
        request_id = payload.get(
            "uuid"
        )  # Updated to match the sender's payload structure
        status = payload.get("status")
        timestamp = payload.get("timestamp")

        request = VideoProcessingRequest.objects.get(uuid=request_id)
        if status == "completed":
            request.video_duration = payload.get("video_duration", 0)
            request.output_file_size_mb = payload.get("output_file_size_mb", 0)
            request.metadata = payload.get("metadata", {})


        # Log all received data for testing purposes
        print("Webhook received with payload:", payload)
        print(f"Request ID: {request_id}")
        print(f"Status: {status}")
        print(f"Timestamp: {timestamp}")

        request.status = status
        request.history[timestamp] = status
        request.save()

        if status == "completed":
            video = request.video
            res = request.resolution
            parsed_path = urlparse(
                request.upload_url
            ).path  # e.g. "/media/videos/720p/clip.mp4"
            path_parts = parsed_path.split("videos/", 1)
            relative_path = "videos/" + path_parts[1]  # e.g. "videos/720p/clip.mp4"

            if res == settings.CONTENTOR_VIDEO_PROCESSING_CONFIG.get("original_resolution", "1080p"):
                setattr(video, "video", relative_path)
            else:
                # for others
                field_name = f"video_{res}"
                setattr(video, field_name, relative_path)
            video.save(skip_processing=True)
        # Return all data for verification purposes
        return JsonResponse(
            {
                "status": "success",
                "message": f"Webhook processed for request {request_id}",
                "received_data": payload,
            }
        )

    except json.JSONDecodeError:
        return JsonResponse({"status": "error", "message": "Invalid JSON"}, status=400)
    except Exception as e:
        import traceback

        print(traceback.format_exc())
        return JsonResponse(
            {"status": "error", "message": f"Unexpected error: {str(e)}"}, status=500
        )