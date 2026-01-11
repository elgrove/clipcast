from django.core.management.base import BaseCommand, CommandError

from core.models import PodcastEpisode
from core.tasks import (
    queue_episode_for_clipping,
    run_clipping_pipeline_for_episode,
)


class Command(BaseCommand):
    help = "Send a podcast episode into the clipping process"

    def add_arguments(self, parser):
        parser.add_argument(
            "episode_id",
            type=str,
            help="The UUID of the episode to clip",
        )
        parser.add_argument(
            "--sync",
            action="store_true",
            help="Run the clipping process synchronously (blocking)",
        )

    def handle(self, *args, **options):
        episode_id = options["episode_id"]
        sync = options["sync"]

        try:
            episode = PodcastEpisode.objects.get(id=episode_id)
        except PodcastEpisode.DoesNotExist as e:
            raise CommandError(f"Episode with ID '{episode_id}' not found") from e

        self.stdout.write(f"Queueing episode: {episode}")

        if sync:
            report = queue_episode_for_clipping(episode, run_async=False)
            self.stdout.write("Running clipping pipeline synchronously...")
            try:
                run_clipping_pipeline_for_episode(episode, report)
                self.stdout.write(self.style.SUCCESS(f"Completed: {episode}"))
                self.stdout.write(f"Report: {report.id}")
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"Failed: {e}"))
                self.stdout.write(f"Report: {report.id}")
                raise CommandError(str(e)) from e
        else:
            report = queue_episode_for_clipping(episode)
            self.stdout.write(self.style.SUCCESS(f"Episode queued for clipping: {episode}"))
            self.stdout.write(f"Report ID: {report.id}")
            self.stdout.write(
                "Note: Run with --sync to process immediately, or use django-q2 for background processing"
            )
