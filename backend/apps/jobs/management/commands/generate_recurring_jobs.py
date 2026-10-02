from django.core.management.base import BaseCommand

from apps.jobs.services import generate_recurring_jobs


class Command(BaseCommand):
    help = "Create upcoming jobs from recurring schedules (run hourly via cron)."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=14)

    def handle(self, *args, **options):
        created = generate_recurring_jobs(days_ahead=options["days"])
        self.stdout.write(f"Created {created} job(s).")
