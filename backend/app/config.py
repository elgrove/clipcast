from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_path: str = "clipcast.db"
    podcasts_dir: str = "_podcasts"
    redis_url: str = "redis://localhost:6379/0"
    debug: bool = False
    allowed_origins: list[str] = ["*"]
    celery_workers: int = 2
    frontend_dir: str = "static/frontend"
    external_url: str = ""
    linear_api_key: str = ""
    linear_team_id: str = ""
    linear_project_id: str = ""

    # Deterministic silence-based boundary snapping applied at edit time. Snaps
    # each ad-break edge into the nearest pause so cuts don't leave advert-word
    # fragments or jingle flashes. no_match_pad_ms (0 = leave untouched) is the
    # outward nudge used only when no pause is found near a boundary.
    silence_refinement_enabled: bool = True
    silence_threshold_db: float = -35.0
    silence_min_duration: float = 0.10
    silence_search_window_ms: int = 1500
    silence_snap_to_edge_ms: int = 5000
    silence_no_match_pad_ms: int = 0

    @property
    def database_url(self) -> str:
        return f"sqlite:///{self.database_path}"

    @property
    def podcasts_path(self) -> Path:
        return Path(self.podcasts_dir)

    model_config = {"env_prefix": "", "env_file": ".env"}


settings = Settings()
