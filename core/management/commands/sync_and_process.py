from django.core.management.base import BaseCommand

from core.tasks import sync_and_process_new_episodes


class Command(BaseCommand):
    help = "Sync all podcasts and queue new episodes for the clipping pipeline"

    def handle(self, *args, **options):
        self.stdout.write("Starting sync and process...")
        results = sync_and_process_new_episodes()

        for podcast_id, count in results.items():
            if count == -1:
                self.stdout.write(self.style.ERROR(f"Failed to sync podcast {podcast_id}"))
            else:
                self.stdout.write(
                    self.style.SUCCESS(f"Podcast {podcast_id}: {count} new episodes queued")
                )

        self.stdout.write(self.style.SUCCESS("Done."))
