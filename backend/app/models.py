import re
import uuid
from datetime import datetime
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel as PydanticBaseModel
from sqlmodel import Column, Field, Relationship, SQLModel, Text

from app.config import settings

# ── Pydantic schemas (JSON fields, API responses) ───────────────────────────


class PodcastEpisodeAdvert(PydanticBaseModel):
    start_time: str
    end_time: str
    advert_for: str
    front_text: str
    tail_text: str


class TranscriptionSegment(PydanticBaseModel):
    start_time: float
    end_time: float
    text: str


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
    def duration_seconds(self) -> float | None:
        if not self.started_at or not self.completed_at:
            return None
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
    warnings: str | None = None
    error: str | None = None

    @property
    def duration_seconds(self) -> float | None:
        if not self.started_at or not self.completed_at:
            return None
        start = datetime.fromisoformat(self.started_at)
        end = datetime.fromisoformat(self.completed_at)
        return (end - start).total_seconds()


# ── Enums ────────────────────────────────────────────────────────────────────


ACAST_ADVERT_LABEL = "Acast ad break"


class ClipMode(StrEnum):
    OFF = "off"
    AI = "ai"
    ACAST = "acast"


class Provider(StrEnum):
    GEMINI = "gemini"
    OPENAI_COMPATIBLE = "openai-compatible"
    OPENROUTER = "openrouter"
    WHISPER_CPP = "whisper.cpp"  # symbol renamed from WHISPER; string value unchanged

    @property
    def label(self) -> str:
        labels = {
            Provider.GEMINI: "Gemini",
            Provider.OPENAI_COMPATIBLE: "OpenAI-compatible",
            Provider.OPENROUTER: "OpenRouter",
            Provider.WHISPER_CPP: "Whisper.cpp",
        }
        return labels[self]


class ClippingStatus(StrEnum):
    QUEUED = "queued"
    DOWNLOADING = "downloading"
    TRANSCRIBING = "transcribing"
    ANALYSING = "analysing"
    EDITING = "editing"
    COMPLETED = "completed"

    @property
    def order(self) -> int:
        return {
            ClippingStatus.QUEUED: 0,
            ClippingStatus.DOWNLOADING: 1,
            ClippingStatus.TRANSCRIBING: 2,
            ClippingStatus.ANALYSING: 3,
            ClippingStatus.EDITING: 4,
            ClippingStatus.COMPLETED: 5,
        }[self]


PRESET_MODELS = {
    "gemini-2.5-flash": {
        "provider": Provider.GEMINI,
        "label": "Gemini 2.5 Flash",
        "transcription": True,
        "analysis": True,
        "recommended": True,
    },
    "gemini-2.5-flash-lite": {
        "provider": Provider.GEMINI,
        "label": "Gemini 2.5 Flash Lite",
        "transcription": True,
        "analysis": False,
        "recommended": False,
    },
    "gpt-4.1-mini": {
        "provider": Provider.OPENAI_COMPATIBLE,
        "label": "GPT-4.1 mini",
        "transcription": False,
        "analysis": True,
        "recommended": True,
    },
    "gpt-4o-transcribe": {
        "provider": Provider.OPENAI_COMPATIBLE,
        "label": "GPT-4o Transcribe",
        "transcription": True,
        "analysis": False,
        "recommended": True,
    },
    "gpt-4o-mini-transcribe": {
        "provider": Provider.OPENAI_COMPATIBLE,
        "label": "GPT-4o mini Transcribe",
        "transcription": True,
        "analysis": False,
        "recommended": False,
    },
    "google/gemini-2.5-flash": {
        "provider": Provider.OPENROUTER,
        "label": "Gemini 2.5 Flash (via OpenRouter)",
        "transcription": False,
        "analysis": True,
        "recommended": True,
    },
    "whisper.cpp": {
        "provider": Provider.WHISPER_CPP,
        "label": "Whisper.cpp",
        "transcription": True,
        "analysis": False,
        "recommended": True,
    },
}


# ── Helper ───────────────────────────────────────────────────────────────────


def new_uuid() -> str:
    return str(uuid.uuid4())


# ── Database models ──────────────────────────────────────────────────────────


class AIModel(SQLModel, table=True):
    __tablename__ = "ai_models"

    id: str = Field(default_factory=new_uuid, primary_key=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    name: str = Field(unique=True, max_length=100)
    provider: str = Field(max_length=20)
    host: str = Field(default="")
    is_preset: bool = Field(default=False)
    api_key: str = Field(default="")
    base_url: str = Field(default="")
    supports_transcription: bool = Field(default=False)
    supports_analysis: bool = Field(default=False)
    is_recommended: bool = Field(default=False)
    input_price: float = Field(default=0)
    output_price: float = Field(default=0)

    def __str__(self) -> str:
        if self.is_preset:
            return PRESET_MODELS.get(self.name, {}).get("label", self.name)
        return f"{Provider(self.provider).label} - {self.name}"


class AppConfig(SQLModel, table=True):
    __tablename__ = "config"

    id: str = Field(default="config", primary_key=True)
    transcription_model_id: str | None = Field(default=None, foreign_key="ai_models.id")
    analysis_model_id: str | None = Field(default=None, foreign_key="ai_models.id")
    gemini_api_key: str = Field(default="")

    transcription_model: AIModel | None = Relationship(
        sa_relationship_kwargs={
            "foreign_keys": "[AppConfig.transcription_model_id]",
            "lazy": "joined",
        }
    )
    analysis_model: AIModel | None = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[AppConfig.analysis_model_id]", "lazy": "joined"}
    )


class PodcastShow(SQLModel, table=True):
    __tablename__ = "podcast_shows"

    id: str = Field(default_factory=new_uuid, primary_key=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    title: str = Field(max_length=255)
    description: str = Field(default="", sa_column=Column(Text))
    itunes_id: str = Field(unique=True, max_length=100)
    source_rss_url: str = Field(max_length=500)
    path_directory: str = Field(max_length=500)
    has_ads: bool = Field(default=True)
    clip_mode: str = Field(default=ClipMode.AI, max_length=10)
    initial_sync_completed: bool = Field(default=False)
    cleanup_keep_days: int | None = Field(default=None)
    cleanup_keep_count: int | None = Field(default=None)
    custom_prompt: str = Field(default="", sa_column=Column(Text))

    episodes: list["PodcastEpisode"] = Relationship(
        back_populates="podcast",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )

    @staticmethod
    def generate_directory_name(title: str) -> str:
        clean_title = re.sub(r"[^\w\s]", "", title)
        return "_".join(clean_title.split())

    @property
    def directory(self) -> Path:
        return settings.podcasts_path / self.path_directory

    @property
    def image_path(self) -> Path:
        return self.directory / "image.jpg"


class PodcastEpisode(SQLModel, table=True):
    __tablename__ = "podcast_episodes"
    __table_args__ = ({"sqlite_autoincrement": False},)

    id: str = Field(default_factory=new_uuid, primary_key=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    podcast_id: str = Field(foreign_key="podcast_shows.id")
    guid: str = Field(max_length=500)
    title: str = Field(max_length=255)
    published_at: datetime | None = Field(default=None)
    description: str = Field(default="", sa_column=Column(Text))
    duration: int | None = Field(default=None)
    source_audio_url: str = Field(default="", max_length=500)
    stored_filename: str = Field(default="", max_length=500)
    cleaned_at: datetime | None = Field(default=None)
    ads_json: str = Field(default="[]", sa_column=Column("ads", Text))
    transcription_json: str = Field(default="[]", sa_column=Column("transcription", Text))

    podcast: PodcastShow = Relationship(back_populates="episodes")

    @property
    def ads(self) -> list[PodcastEpisodeAdvert]:
        import json

        raw = json.loads(self.ads_json)
        return [PodcastEpisodeAdvert(**a) for a in raw]

    @ads.setter
    def ads(self, value: list[PodcastEpisodeAdvert]) -> None:
        import json

        self.ads_json = json.dumps([a.model_dump() for a in value])

    @property
    def transcription(self) -> list[TranscriptionSegment]:
        import json

        raw = json.loads(self.transcription_json)
        return [TranscriptionSegment(**s) for s in raw]

    @transcription.setter
    def transcription(self, value: list[TranscriptionSegment]) -> None:
        import json

        self.transcription_json = json.dumps([s.model_dump() for s in value])

    def _generate_base_filename(self) -> str:
        date_prefix = self.published_at.strftime("%Y%m%d") if self.published_at else "00000000"
        clean_title = re.sub(r"[^\w\s-]", "", self.title)
        title_part = "_".join(clean_title.split())
        return f"{date_prefix}_{title_part}"

    def _get_base_filename(self) -> str:
        return self.stored_filename or self._generate_base_filename()

    def lock_filename(self) -> str:
        if not self.stored_filename:
            self.stored_filename = self._generate_base_filename()
        return self.stored_filename

    @property
    def mp3_path(self) -> Path:
        return self.podcast.directory / f"{self._get_base_filename()}.mp3"

    @property
    def raw_path(self) -> Path:
        return self.podcast.directory / f"{self._get_base_filename()}.mp3.raw"

    @property
    def srt_path(self) -> Path:
        return self.podcast.directory / f"{self._get_base_filename()}.mp3.srt"

    @property
    def ads_path(self) -> Path:
        return self.podcast.directory / f"{self._get_base_filename()}.mp3.json"

    @property
    def is_cleaned(self) -> bool:
        return self.cleaned_at is not None

    @property
    def has_file(self) -> bool:
        return self.mp3_path.exists() and self.mp3_path.stat().st_size > 0


class ClippingReport(SQLModel, table=True):
    __tablename__ = "clipping_reports"

    id: str = Field(default_factory=new_uuid, primary_key=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    episode_id: str = Field(foreign_key="podcast_episodes.id")
    transcription_model_id: str | None = Field(default=None, foreign_key="ai_models.id")
    analysis_model_id: str | None = Field(default=None, foreign_key="ai_models.id")
    queued_at: datetime = Field(default_factory=datetime.utcnow)
    downloaded_at: datetime | None = Field(default=None)
    transcribed_at: datetime | None = Field(default=None)
    analysed_at: datetime | None = Field(default=None)
    edited_at: datetime | None = Field(default=None)
    logs: str = Field(default="", sa_column=Column(Text))
    exceptions_json: str = Field(default="[]", sa_column=Column("exceptions", Text))
    transcription_report_json: str | None = Field(
        default=None, sa_column=Column("transcription_report", Text)
    )
    analysis_report_json: str | None = Field(
        default=None, sa_column=Column("analysis_report", Text)
    )
    celery_task_id: str = Field(default="")

    episode: PodcastEpisode = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[ClippingReport.episode_id]"}
    )

    @property
    def status(self) -> ClippingStatus:
        if self.edited_at:
            return ClippingStatus.COMPLETED
        if self.analysed_at:
            return ClippingStatus.EDITING
        if self.transcribed_at:
            return ClippingStatus.ANALYSING
        if self.downloaded_at:
            return ClippingStatus.TRANSCRIBING
        return ClippingStatus.QUEUED

    @property
    def exceptions(self) -> list[str]:
        import json

        return json.loads(self.exceptions_json)

    @property
    def transcription_report(self) -> TranscriptionReport | None:
        import json

        if not self.transcription_report_json:
            return None
        return TranscriptionReport(**json.loads(self.transcription_report_json))

    @transcription_report.setter
    def transcription_report(self, value: TranscriptionReport | None) -> None:
        import json

        self.transcription_report_json = json.dumps(value.model_dump()) if value else None

    @property
    def analysis_report(self) -> AnalysisReport | None:
        import json

        if not self.analysis_report_json:
            return None
        return AnalysisReport(**json.loads(self.analysis_report_json))

    @analysis_report.setter
    def analysis_report(self, value: AnalysisReport | None) -> None:
        import json

        self.analysis_report_json = json.dumps(value.model_dump()) if value else None

    def append_log(self, message: str) -> None:
        import logging

        logging.getLogger("clipcast").info(message)
        timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        self.logs += f"[{timestamp}] {message}\n"

    def add_exception(self, exception: Exception) -> None:
        import json
        import traceback

        tb = "".join(
            traceback.format_exception(type(exception), exception, exception.__traceback__)
        )
        exceptions = json.loads(self.exceptions_json)
        exceptions.append(tb)
        self.exceptions_json = json.dumps(exceptions)


# ── API schemas ──────────────────────────────────────────────────────────────


class PodcastShowRead(PydanticBaseModel):
    id: str
    created_at: datetime
    title: str
    description: str
    itunes_id: str
    source_rss_url: str
    clip_mode: str
    initial_sync_completed: bool
    episode_count: int = 0
    image_url: str | None = None
    cleanup_keep_days: int | None = None
    cleanup_keep_count: int | None = None
    custom_prompt: str = ""


class PodcastEpisodeRead(PydanticBaseModel):
    id: str
    created_at: datetime
    podcast_id: str
    guid: str
    title: str
    published_at: datetime | None
    description: str
    duration: int | None
    source_audio_url: str
    is_downloaded: bool = False
    is_clipped: bool = False
    is_cleaned: bool = False
    has_transcription: bool = False
    ad_count: int = 0
    clipping_status: str | None = None


class PodcastShowCreate(PydanticBaseModel):
    itunes_id: str
    clip_mode: str = ClipMode.AI


class PodcastShowUpdate(PydanticBaseModel):
    clip_mode: str | None = None
    cleanup_keep_days: int | None = None
    cleanup_keep_count: int | None = None
    custom_prompt: str | None = None


class ConfigRead(PydanticBaseModel):
    transcription_model_id: str | None
    analysis_model_id: str | None
    gemini_api_key: str = ""
    transcription_model: "AIModelRead | None" = None
    analysis_model: "AIModelRead | None" = None


class ConfigUpdate(PydanticBaseModel):
    transcription_model_id: str | None = None
    analysis_model_id: str | None = None
    gemini_api_key: str | None = None  # deprecated, accepted but ignored


class AIModelRead(PydanticBaseModel):
    id: str
    name: str
    provider: str
    host: str
    api_key: str = ""
    base_url: str = ""
    is_preset: bool
    input_price: float
    output_price: float
    supports_transcription: bool = False
    supports_analysis: bool = False
    is_recommended: bool = False
    display_name: str = ""


class AIModelCreate(PydanticBaseModel):
    name: str
    provider: str
    host: str = ""
    api_key: str = ""
    base_url: str = ""
    supports_transcription: bool = False
    supports_analysis: bool = False


class AIModelUpdate(PydanticBaseModel):
    name: str | None = None
    api_key: str | None = None
    base_url: str | None = None
    supports_transcription: bool | None = None
    supports_analysis: bool | None = None
    input_price: float | None = None
    output_price: float | None = None


class ModelTestResult(PydanticBaseModel):
    ok: bool
    message: str
    latency_ms: int


class ClippingReportRead(PydanticBaseModel):
    id: str
    episode_id: str
    status: str
    queued_at: datetime
    downloaded_at: datetime | None
    transcribed_at: datetime | None
    analysed_at: datetime | None
    edited_at: datetime | None
    logs: str
    exceptions: list[str]


class ClippingReportDetail(PydanticBaseModel):
    id: str
    episode_id: str
    episode_title: str
    podcast_title: str
    status: str
    queued_at: datetime
    downloaded_at: datetime | None
    transcribed_at: datetime | None
    analysed_at: datetime | None
    edited_at: datetime | None
    transcription_model: str | None = None
    analysis_model: str | None = None
    transcription_duration_s: float | None = None
    transcription_input_tokens: int | None = None
    transcription_output_tokens: int | None = None
    transcription_cost: float | None = None
    transcription_segments: int | None = None
    analysis_duration_s: float | None = None
    analysis_input_tokens: int | None = None
    analysis_output_tokens: int | None = None
    analysis_cost: float | None = None
    adverts_found: int | None = None
    has_exceptions: bool = False


class BatchClipRequest(PydanticBaseModel):
    episode_ids: list[str]


class ITunesSearchResult(PydanticBaseModel):
    itunes_id: str
    title: str
    artist: str
    feed_url: str
    artwork_url: str
    genre: str
    episode_count: int | None = None
    ads_by_acast: bool = False
