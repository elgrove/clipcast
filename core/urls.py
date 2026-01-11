from django.urls import path

from core import views

urlpatterns = [
    path("", views.home, name="home"),
    path("podcast/<uuid:podcast_id>/", views.podcast_detail, name="podcast_detail"),
    path("podcast/<uuid:podcast_id>/image/", views.podcast_image, name="podcast_image"),
    path("podcast/<uuid:podcast_id>/delete/", views.delete_podcast, name="delete_podcast"),
    path(
        "podcast/<uuid:podcast_id>/delete-with-files/",
        views.delete_podcast_and_files,
        name="delete_podcast_and_files",
    ),
    path(
        "podcast/<uuid:podcast_id>/sync-show/",
        views.queue_sync_podcast_show,
        name="queue_sync_podcast_show",
    ),
    path(
        "podcast/<uuid:podcast_id>/sync-episodes/",
        views.queue_sync_podcast_episodes,
        name="queue_sync_podcast_episodes",
    ),
    path(
        "podcast/<uuid:podcast_id>/toggle-ads/",
        views.toggle_podcast_ads,
        name="toggle_podcast_ads",
    ),
    path("podcast/add/", views.podcast_add, name="podcast_add"),
    path("podcast/search/", views.podcast_search, name="podcast_search"),
    path("podcast/add/confirm/", views.podcast_add_confirm, name="podcast_add_confirm"),
    path("podcast/sync-and-process/", views.queue_sync_and_process, name="queue_sync_and_process"),
    path(
        "episode/<uuid:episode_id>/download/",
        views.queue_download_episode,
        name="queue_download_episode",
    ),
    path("episode/<uuid:episode_id>/clip/", views.queue_clip_episode, name="queue_clip_episode"),
    path("config/", views.config, name="config"),
    path("config/add-model/", views.add_model, name="add_model"),
    path("feed/<str:itunes_id>/", views.podcast_feed, name="podcast_feed"),
    path(
        "podcast/<uuid:podcast_id>/episode/<uuid:episode_id>/audio/",
        views.episode_audio,
        name="episode_audio",
    ),
]
