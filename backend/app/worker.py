from celery import Celery
from celery.schedules import crontab

from app.config import settings

celery_app = Celery(
    "clipcast",
    broker=settings.redis_url,
    backend=settings.redis_url,
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_track_started=True,
    task_default_queue="default",
    task_routes={
        "app.tasks.task_download": {"queue": "default"},
        "app.tasks.task_detect_acast_ads": {"queue": "default"},
        "app.tasks.task_analyse": {"queue": "ai"},
        "app.tasks.task_edit": {"queue": "default"},
        # task_transcribe is routed dynamically at queue time
    },
    beat_schedule={
        "sync-and-process": {
            "task": "app.tasks.sync_and_process_new_episodes",
            "schedule": crontab(minute=0),
        },
        "cleanup-old-episodes": {
            "task": "app.tasks.cleanup_old_episodes",
            "schedule": crontab(hour=3, minute=0),
        },
    },
)

celery_app.autodiscover_tasks(["app"])
