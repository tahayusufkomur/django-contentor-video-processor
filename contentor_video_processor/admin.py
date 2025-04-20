from django.contrib import admin

from contentor_video_processor.models import VideoProcessingRequest


@admin.register(VideoProcessingRequest)
class VideoProcessingAdmin(admin.ModelAdmin):
    actions = ["trigger_process"]
    list_display = (
        "uuid",
        "video",
        "resolution",
        "status",
        "upload_provider",
        "download_provider",
        "created_at",
        "updated_at",
    )
    list_filter = ("resolution", "status", "upload_provider", "download_provider")
    search_fields = ("uuid", "video__title")  # Assuming Video has a title field
    readonly_fields = (
        "uuid",
        "download_url",
        "upload_url",
        "webhook_url",
        "created_at",
        "updated_at",
        "history",
    )
    ordering = ("-created_at",)

    fieldsets = (
        (
            None,
            {
                "fields": (
                    "uuid",
                    "video",
                    "resolution",
                    "status",
                )
            },
        ),
        (
            "Meta",
            {
                "fields": (
                    "video_duration",
                    "output_file_size_mb",
                    "metadata",
                )
            },
        ),
        (
            "URLs",
            {
                "fields": (
                    "download_url",
                    "upload_url",
                    "webhook_url",
                )
            },
        ),
        (
            "Providers",
            {
                "fields": (
                    "download_provider",
                    "upload_provider",
                )
            },
        ),
        ("Advanced", {"fields": ("history",)}),
        (
            "Timestamps",
            {
                "fields": (
                    "created_at",
                    "updated_at",
                )
            },
        ),
    )

    @admin.action(description="1- Videoları İşle")
    def trigger_process(self, request, queryset):
        for video in queryset:
            video.process_video()