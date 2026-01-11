import logging
import re
import traceback
import uuid
from datetime import timedelta
from enum import StrEnum
from pathlib import Path

import srt
from django.conf import settings
from django.db import models
from django.utils import timezone
from django_pydantic_field import SchemaField
from pydantic import BaseModel as PydanticBaseModel

logger = logging.getLogger(__name__)


class BaseModel(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True, null=False)
    updated_at = models.DateTimeField(auto_now=True, null=False)

    class Meta:
        abstract = True


class Provider(StrEnum):
    GEMINI = "gemini"
    WHISPER = "whisper.cpp"

    @property
    def label(self) -> str:
        labels = {
            Provider.GEMINI: "Gemini",
            Provider.WHISPER: "Whisper.cpp",
        }
        return labels[self]


PRESET_MODELS = {
    "gemini-2.5-flash": {"provider": Provider.GEMINI, "label": "Gemini 2.5 Flash"},
    "gemini-2.5-flash-lite": {"provider": Provider.GEMINI, "label": "Gemini 2.5 Flash Lite"},
    "whisper.cpp": {"provider": Provider.WHISPER, "label": "Whisper.cpp"},
}


class AIModel(BaseModel):
    PROVIDER_CHOICES = [(p.value, p.label) for p in Provider]

    name = models.CharField(max_length=100, unique=True)
    provider = models.CharField(max_length=20, choices=PROVIDER_CHOICES)
    host = models.CharField(max_length=255, blank=True, default="")
    is_preset = models.BooleanField(default=False)
    input_price = models.DecimalField(max_digits=10, decimal_places=4, default=0)
    output_price = models.DecimalField(max_digits=10, decimal_places=4, default=0)

    class Meta:
        verbose_name = "AI Model"
        verbose_name_plural = "AI Models"

    def __str__(self) -> str:
        if self.is_preset:
            return PRESET_MODELS.get(self.name, {}).get("label", self.name)
        return f"{self.get_provider_display()} - {self.name}"

    @classmethod
    def get_or_create_preset(cls, name: str):
        if name not in PRESET_MODELS:
            raise ValueError(f"Unknown preset model: {name}")
        preset = PRESET_MODELS[name]
        model, _ = cls.objects.get_or_create(
            name=name,
            defaults={
                "provider": preset["provider"].value,
                "is_preset": True,
            },
        )
        return model


class Config(BaseModel):
    transcription_model = models.ForeignKey(
        AIModel,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="transcription_configs",
    )

    analysis_model = models.ForeignKey(
        AIModel,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="analysis_configs",
    )

    gemini_api_key = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        verbose_name = "Configuration"
        verbose_name_plural = "Configuration"

    def __str__(self) -> str:
        return "Configuration"

    @classmethod
    def get_instance(cls):
        instance, _ = cls.objects.get_or_create(id=uuid.UUID(int=0))
        return instance


class PodcastShow(BaseModel):
    title = models.CharField(max_length=255, blank=False, null=False)
    description = models.TextField(blank=True, default="")
    itunes_id = models.CharField(max_length=100, unique=True)
    source_rss_url = models.URLField(max_length=500)
    path_directory = models.CharField(max_length=500, blank=False, null=False)
    has_ads = models.BooleanField()
    initial_sync_completed = models.BooleanField(default=False)

    def __str__(self) -> str:
        return self.title

    @staticmethod
    def generate_directory_name(title: str) -> str:
        """Generate a safe directory name from podcast title.

        Strips special characters and joins words with underscores.
        Example: "The Joe's Podcast" -> "The_Joes_Podcast"
        """
        # Remove special characters except spaces and alphanumerics
        clean_title = re.sub(r"[^\w\s]", "", title)
        # Replace spaces with underscores
        return "_".join(clean_title.split())

    @property
    def directory(self) -> Path:
        """Full path to the podcast's storage directory."""
        return Path(settings.BASE_DIR) / settings.PODCASTS_DIR / self.path_directory

    @property
    def image_path(self) -> Path:
        """Path to the podcast's cover image."""
        return self.directory / "image.jpg"


class PodcastEpisodeAdvert(PydanticBaseModel):
    start_time: str
    end_time: str
    advert_for: str
    front_text: str
    tail_text: str


class PodcastEpisodeAdverts(PydanticBaseModel):
    adverts: list[PodcastEpisodeAdvert] = []


class TranscriptionSegment(PydanticBaseModel):
    start_time: float
    end_time: float
    text: str


class Transcription(PydanticBaseModel):
    segments: list[TranscriptionSegment] = []

    def to_srt(self) -> str:
        subtitles = [
            srt.Subtitle(
                index=i,
                start=timedelta(seconds=seg.start_time),
                end=timedelta(seconds=seg.end_time),
                content=seg.text,
            )
            for i, seg in enumerate(self.segments, 1)
        ]
        return srt.compose(subtitles)


class TranscriptionReport(PydanticBaseModel):
    started_at: str | None = None
    completed_at: str | None = None
    provider: str | None = None
    model_name: str | None = None
    segments_count: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: float | None = None
    error: str | None = None

    @property
    def duration_seconds(self):
        if not self.started_at or not self.completed_at:
            return None
        from datetime import datetime

        start = datetime.fromisoformat(self.started_at)
        end = datetime.fromisoformat(self.completed_at)
        return (end - start).total_seconds()


class AnalysisReport(PydanticBaseModel):
    started_at: str | None = None
    completed_at: str | None = None
    provider: str | None = None
    model_name: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: float | None = None
    adverts_found: int | None = None
    error: str | None = None

    @property
    def duration_seconds(self):
        if not self.started_at or not self.completed_at:
            return None
        from datetime import datetime

        start = datetime.fromisoformat(self.started_at)
        end = datetime.fromisoformat(self.completed_at)
        return (end - start).total_seconds()


class PodcastEpisode(BaseModel):
    podcast = models.ForeignKey(PodcastShow, on_delete=models.CASCADE, related_name="episodes")
    guid = models.CharField(max_length=500, null=False, blank=False)
    title = models.CharField(max_length=255)
    published_at = models.DateTimeField(null=True, blank=True)
    description = models.TextField(blank=True, default="")
    duration = models.IntegerField(null=True, blank=True)
    source_audio_url = models.URLField(max_length=500, blank=True, default="")
    ads: list[PodcastEpisodeAdvert] = SchemaField(default=list)
    transcription: list[TranscriptionSegment] = SchemaField(default=list)

    class Meta:
        unique_together = ["podcast", "guid"]

    def __str__(self) -> str:
        return f"{self.podcast.title} - {self.title}"

    def _get_base_filename(self) -> str:
        date_prefix = self.published_at.strftime("%Y%m%d") if self.published_at else "00000000"
        clean_title = re.sub(r"[^\w\s-]", "", self.title)
        title_part = "_".join(clean_title.split())
        return f"{date_prefix}_{title_part}"

    def _get_podcast_directory(self) -> Path:
        return self.podcast.directory

    @property
    def mp3_path(self) -> Path:
        return self._get_podcast_directory() / f"{self._get_base_filename()}.mp3"

    @property
    def raw_path(self) -> Path:
        return self._get_podcast_directory() / f"{self._get_base_filename()}.mp3.raw"

    @property
    def srt_path(self) -> Path:
        return self._get_podcast_directory() / f"{self._get_base_filename()}.mp3.srt"

    @property
    def ads_path(self) -> Path:
        return self._get_podcast_directory() / f"{self._get_base_filename()}.mp3.json"

    @property
    def is_downloaded(self) -> bool:
        return self.mp3_path.exists() and self.mp3_path.stat().st_size > 0

    def transcription_to_srt(self) -> str:
        return Transcription(segments=self.transcription).to_srt()


class ClippingReportStatus(StrEnum):
    QUEUED = "queued"
    DOWNLOADING = "downloading"
    TRANSCRIBING = "transcribing"
    ANALYSING = "analysing"
    EDITING = "editing"
    COMPLETED = "completed"

    @property
    def order(self) -> int:
        return {
            ClippingReportStatus.QUEUED: 0,
            ClippingReportStatus.DOWNLOADING: 1,
            ClippingReportStatus.TRANSCRIBING: 2,
            ClippingReportStatus.ANALYSING: 3,
            ClippingReportStatus.EDITING: 4,
            ClippingReportStatus.COMPLETED: 5,
        }[self]


class ClippingReport(BaseModel):
    episode = models.ForeignKey(
        PodcastEpisode,
        on_delete=models.CASCADE,
        related_name="clipping_reports",
    )
    transcription_model = models.ForeignKey(
        AIModel,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="transcription_reports",
    )
    analysis_model = models.ForeignKey(
        AIModel,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="analysis_reports",
    )
    queued_at = models.DateTimeField(auto_now_add=True)
    downloaded_at = models.DateTimeField(null=True, blank=True)
    transcribed_at = models.DateTimeField(null=True, blank=True)
    analysed_at = models.DateTimeField(null=True, blank=True)
    edited_at = models.DateTimeField(null=True, blank=True)
    logs = models.TextField(blank=True, default="")
    exceptions: list[str] = SchemaField(default=list)
    transcription: TranscriptionReport | None = SchemaField(null=True, default=None)
    analysis: AnalysisReport | None = SchemaField(null=True, default=None)

    class Meta:
        verbose_name = "Clipping Report"
        verbose_name_plural = "Clipping Reports"
        ordering = ["-queued_at"]

    def __str__(self) -> str:
        return f"ClippingReport {self.episode} - {self.status.value}"

    @property
    def status(self) -> ClippingReportStatus:
        if self.edited_at:
            return ClippingReportStatus.COMPLETED
        if self.analysed_at:
            return ClippingReportStatus.EDITING
        if self.transcribed_at:
            return ClippingReportStatus.ANALYSING
        if self.downloaded_at:
            return ClippingReportStatus.TRANSCRIBING
        return ClippingReportStatus.QUEUED

    def append_log(self, message: str) -> None:
        logger.info(message)
        timestamp = timezone.now().strftime("%Y-%m-%d %H:%M:%S")
        log_line = f"[{timestamp}] {message}\n"
        self.logs += log_line

    def add_exception(self, exception: Exception) -> None:
        tb = "".join(
            traceback.format_exception(type(exception), exception, exception.__traceback__)
        )
        self.exceptions.append(tb)
