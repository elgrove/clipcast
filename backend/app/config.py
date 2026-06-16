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

    @property
    def database_url(self) -> str:
        return f"sqlite:///{self.database_path}"

    @property
    def podcasts_path(self) -> Path:
        return Path(self.podcasts_dir)

    model_config = {"env_prefix": "", "env_file": ".env"}


settings = Settings()
