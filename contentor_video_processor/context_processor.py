from django.conf import settings


def video_resolutions(request):
    return {
        'AVAILABLE_VIDEO_RESOLUTIONS': settings.CONTENTOR_VIDEO_PROCESSING_CONFIG.get('resolutions', []),
    }