from django.contrib import admin

from .models import (
    AIModel,
    ClippingReport,
    Config,
    PodcastEpisode,
    PodcastShow,
)


@admin.register(AIModel)
class AIModelAdmin(admin.ModelAdmin):
    list_display = ("name", "provider", "is_preset", "host")
    list_filter = ("provider", "is_preset")


@admin.register(Config)
class ConfigAdmin(admin.ModelAdmin):
    list_display = ("__str__", "transcription_model", "analysis_model")


@admin.register(PodcastShow)
class PodcastShowAdmin(admin.ModelAdmin):
    list_display = ("title", "itunes_id")
    search_fields = ("title", "itunes_id")


@admin.register(PodcastEpisode)
class PodcastEpisodeAdmin(admin.ModelAdmin):
    list_display = ("title", "podcast", "published_at")
    list_filter = ("podcast",)
    search_fields = ("title", "guid")


@admin.register(ClippingReport)
class ClippingReportAdmin(admin.ModelAdmin):
    list_display = ("episode", "status", "queued_at")
    list_filter = ("episode__podcast",)
    readonly_fields = ("logs", "exceptions", "transcription", "analysis")
