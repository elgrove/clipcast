import logging
import shutil

import requests
from django.conf import settings
from django.contrib import messages
from django.core.paginator import Paginator
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django_q.tasks import async_task

from core.models import (
    PRESET_MODELS,
    AIModel,
    Config,
    PodcastEpisode,
    PodcastShow,
    Provider,
)
from core.services.feed import generate_podcast_feed
from core.services.rss import search_itunes
from core.tasks import queue_episode_for_clipping

logger = logging.getLogger(__name__)


def home(request):
    podcasts = PodcastShow.objects.all().order_by("-created_at")
    config_instance = Config.get_instance()

    is_ai_configured = bool(
        config_instance.transcription_model
        and config_instance.analysis_model
        and config_instance.gemini_api_key
    )

    return render(
        request,
        "home.html",
        {
            "podcasts": podcasts,
            "is_ai_configured": is_ai_configured,
        },
    )


def podcast_detail(request, podcast_id):
    podcast = get_object_or_404(PodcastShow, id=podcast_id)
    episodes_list = podcast.episodes.all().order_by("-published_at")

    paginator = Paginator(episodes_list, 50)
    page_number = request.GET.get("page", 1)
    episodes = paginator.get_page(page_number)

    return render(request, "podcast_detail.html", {"podcast": podcast, "episodes": episodes})


def podcast_add(request):
    return render(request, "podcast_add.html")


def podcast_search(request):
    query = request.GET.get("q", "").strip()
    results = []

    if query:
        results = search_itunes(query)

    return render(request, "partials/search_results.html", {"results": results, "query": query})


def podcast_add_confirm(request):
    itunes_id = request.POST.get("itunes_id") or request.GET.get("itunes_id")
    title = request.POST.get("title") or request.GET.get("title")
    feed_url = request.POST.get("feed_url") or request.GET.get("feed_url")
    artwork_url = request.POST.get("artwork_url") or request.GET.get("artwork_url")

    if not all([itunes_id, title, feed_url]):
        messages.error(request, "Missing required podcast information")
        return redirect("podcast_add")

    if PodcastShow.objects.filter(itunes_id=itunes_id).exists():
        messages.warning(request, f"'{title}' is already in your library")
        return redirect("home")

    if request.method == "POST" and request.POST.get("confirmed"):
        has_ads = request.POST.get("has_ads") == "on"

        podcast = PodcastShow.objects.create(
            itunes_id=itunes_id,
            title=title,
            source_rss_url=feed_url,
            path_directory=PodcastShow.generate_directory_name(title),
            has_ads=has_ads,
        )

        podcast.directory.mkdir(parents=True, exist_ok=True)

        if artwork_url:
            _download_podcast_image(podcast, artwork_url)

        async_task(
            "core.tasks.sync_podcast_show",
            str(podcast.id),
            task_name=f"Sync show: {podcast.title}",
        )
        async_task(
            "core.tasks.sync_podcast_episodes",
            str(podcast.id),
            task_name=f"Sync episodes: {podcast.title}",
        )

        messages.success(request, f"Added '{podcast.title}'.")
        return redirect("podcast_detail", podcast_id=podcast.id)

    return render(
        request,
        "podcast_add_confirm.html",
        {
            "itunes_id": itunes_id,
            "title": title,
            "feed_url": feed_url,
            "artwork_url": artwork_url,
        },
    )


def _download_podcast_image(podcast: PodcastShow, artwork_url: str) -> None:
    try:
        response = requests.get(artwork_url, timeout=30)
        response.raise_for_status()
        podcast.image_path.write_bytes(response.content)
    except Exception:
        logging.warning(f"Failed to download artwork for {podcast.title} from {artwork_url}")


def config(request):
    config_instance = Config.get_instance()

    for preset_name in PRESET_MODELS:
        AIModel.get_or_create_preset(preset_name)

    ai_models = AIModel.objects.all().order_by("-is_preset", "name")
    transcription_models = ai_models.all()
    analysis_models = ai_models.filter(provider=Provider.GEMINI.value)

    if request.method == "POST":
        transcription_model_id = request.POST.get("transcription_model")
        analysis_model_id = request.POST.get("analysis_model")
        gemini_api_key = request.POST.get("gemini_api_key", "").strip()
        whisper_host = request.POST.get("whisper_host", "").strip()

        if transcription_model_id:
            transcription_model = AIModel.objects.filter(id=transcription_model_id).first()
            config_instance.transcription_model = transcription_model

            if transcription_model and transcription_model.provider == Provider.WHISPER.value:
                transcription_model.host = whisper_host
                transcription_model.save()
        else:
            config_instance.transcription_model = None

        if analysis_model_id:
            config_instance.analysis_model = AIModel.objects.filter(id=analysis_model_id).first()
        else:
            config_instance.analysis_model = None

        config_instance.gemini_api_key = gemini_api_key
        config_instance.save()
        messages.success(request, "Configuration saved successfully")
        return redirect("config")

    return render(
        request,
        "config.html",
        {
            "config": config_instance,
            "transcription_models": transcription_models,
            "analysis_models": analysis_models,
        },
    )


def add_model(request):
    if request.method != "POST":
        return redirect("config")

    model_name = request.POST.get("model_name", "").strip()
    provider = request.POST.get("provider", "").strip()
    host = request.POST.get("host", "").strip()

    if not model_name or not provider:
        messages.error(request, "Model name and provider are required")
        return redirect("config")

    if AIModel.objects.filter(name=model_name).exists():
        messages.warning(request, f"Model '{model_name}' already exists")
        return redirect("config")

    if provider == Provider.WHISPER.value and not host:
        messages.error(request, "Host is required for Whisper models")
        return redirect("config")

    AIModel.objects.create(
        name=model_name,
        provider=provider,
        host=host,
        is_preset=False,
    )
    messages.success(request, f"Added model: {model_name}")
    return redirect("config")


def delete_podcast(request, podcast_id):
    if request.method != "POST":
        return redirect("home")

    podcast = get_object_or_404(PodcastShow, id=podcast_id)
    title = podcast.title
    podcast.delete()

    messages.success(request, f"Deleted '{title}' from your library")
    return redirect("home")


def delete_podcast_and_files(request, podcast_id):
    if request.method != "POST":
        return redirect("home")

    podcast = get_object_or_404(PodcastShow, id=podcast_id)
    title = podcast.title

    first_episode = podcast.episodes.first()
    if first_episode:
        podcast_dir = first_episode._get_podcast_directory()
        if podcast_dir.exists():
            shutil.rmtree(podcast_dir)
            messages.info(request, f"Removed files from {podcast_dir}")

    podcast.delete()

    messages.success(request, f"Deleted '{title}' and all associated files")
    return redirect("home")


def queue_download_episode(request, episode_id):
    if request.method != "POST":
        return redirect("home")

    episode = get_object_or_404(PodcastEpisode, id=episode_id)

    async_task(
        "core.services.download.download_episode",
        episode,
        task_name=f"Download: {episode.title[:50]}",
    )

    messages.success(request, f"Queued '{episode.title}' for download")
    page = request.POST.get("page", "1")
    url = reverse("podcast_detail", args=[episode.podcast.id])
    return redirect(f"{url}?page={page}")


def queue_clip_episode(request, episode_id):
    if request.method != "POST":
        return redirect("home")

    episode = get_object_or_404(PodcastEpisode, id=episode_id)

    is_sync_mode = settings.Q_CLUSTER.get("sync", False)
    queue_episode_for_clipping(episode, run_async=not is_sync_mode)

    messages.success(request, f"Queued '{episode.title}' for ad removal")
    page = request.POST.get("page", "1")
    url = reverse("podcast_detail", args=[episode.podcast.id])
    return redirect(f"{url}?page={page}")


def queue_sync_podcast_show(request, podcast_id):
    if request.method != "POST":
        return redirect("home")

    podcast = get_object_or_404(PodcastShow, id=podcast_id)

    async_task(
        "core.tasks.sync_podcast_show",
        str(podcast.id),
        task_name=f"Sync show: {podcast.title}",
    )

    messages.success(request, f"Queued '{podcast.title}' show data for sync")
    return redirect("podcast_detail", podcast_id=podcast.id)


def queue_sync_podcast_episodes(request, podcast_id):
    if request.method != "POST":
        return redirect("home")

    podcast = get_object_or_404(PodcastShow, id=podcast_id)

    async_task(
        "core.tasks.sync_podcast_episodes",
        str(podcast.id),
        task_name=f"Sync episodes: {podcast.title}",
    )

    messages.success(request, f"Queued '{podcast.title}' episodes for sync")
    return redirect("podcast_detail", podcast_id=podcast.id)


def queue_sync_and_process(request):
    """Queue sync and process task for all podcasts."""
    if request.method != "POST":
        return redirect("home")

    async_task(
        "core.tasks.sync_and_process_new_episodes",
        task_name="Sync and process all podcasts",
    )

    messages.success(request, "Queued all podcasts for sync and processing")
    return redirect("home")


def podcast_image(request, podcast_id):
    podcast = get_object_or_404(PodcastShow, id=podcast_id)

    if not podcast.image_path.exists():
        raise Http404("Image not found")

    return FileResponse(open(podcast.image_path, "rb"), content_type="image/jpeg")


def podcast_feed(request, itunes_id):
    podcast = get_object_or_404(PodcastShow, itunes_id=itunes_id)
    feed_xml = generate_podcast_feed(podcast, request)

    return HttpResponse(feed_xml, content_type="application/rss+xml; charset=utf-8")


def toggle_podcast_ads(request, podcast_id):
    if request.method != "POST":
        return redirect("home")

    podcast = get_object_or_404(PodcastShow, id=podcast_id)
    podcast.has_ads = not podcast.has_ads
    podcast.save()

    action = "has ads" if podcast.has_ads else "is ad-free"
    messages.success(request, f"'{podcast.title}' marked as {action}")
    return redirect("podcast_detail", podcast_id=podcast.id)


def episode_audio(request, podcast_id, episode_id):
    podcast = get_object_or_404(PodcastShow, id=podcast_id)
    episode = get_object_or_404(PodcastEpisode, id=episode_id, podcast=podcast)

    if not episode.mp3_path.exists():
        raise Http404("Audio file not found")

    return FileResponse(open(episode.mp3_path, "rb"), content_type="audio/mpeg")
