from django.urls import re_path, path  # Use re_path for regex-based URLs
from . import views
from .views import get_video_signed_url, webhook_receiver

urlpatterns = [
    re_path(r"^upload/$", views.contentor_video, name="contentor_video_processor"),
    re_path(r"^file-exists/$", views.contentor_file_exists, name='contentor_file_exists'),
    path(
        "videos/<int:video_id>/signed-url/<str:quality>/",
        get_video_signed_url,
        name="video_signed_url",
    ),
    path("video-processing/webhook/", webhook_receiver, name="webhook_receiver"),
]
