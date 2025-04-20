from django.apps import AppConfig
from django.conf import settings


class ContentorVideoProcessorConfig(AppConfig):
    name = 'contentor_video_processor'

    def ready(self):
        from django.contrib import admin
        from django.apps import apps

        try:
            app_label = settings.CONTENTOR_VIDEO_PROCESSING_REQUESTS_APP
            model = apps.get_model(app_label, "VideoProcessingRequest")

            class DynamicVideoProcessingRequestAdmin(admin.ModelAdmin):
                list_display = ("video", "resolution", "status", "upload_provider", "download_provider")
                list_filter = ("status", "resolution")

            admin.site.register(model, DynamicVideoProcessingRequestAdmin)
        except Exception as e:
            # You might want to log this
            print(f"Admin registration failed: {e}")
