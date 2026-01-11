from django.core.management.base import BaseCommand
from django_q.models import Schedule

SCHEDULED_TASKS = [
    {
        "func": "core.tasks.sync_and_process_new_episodes",
        "name": "Sync and process new episodes",
        "schedule_type": Schedule.HOURLY,
        "repeats": -1,
    },
]


class Command(BaseCommand):
    help = "Set up scheduled tasks for ClipCast"

    def handle(self, *args, **options):
        for task_config in SCHEDULED_TASKS:
            schedule, created = Schedule.objects.update_or_create(
                func=task_config["func"],
                defaults={
                    "name": task_config["name"],
                    "schedule_type": task_config["schedule_type"],
                    "repeats": task_config["repeats"],
                },
            )

            if created:
                self.stdout.write(self.style.SUCCESS(f"Created scheduled task: {schedule.name}"))
            else:
                self.stdout.write(self.style.SUCCESS(f"Updated scheduled task: {schedule.name}"))
