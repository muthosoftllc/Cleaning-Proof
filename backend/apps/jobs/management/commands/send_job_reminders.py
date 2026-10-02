from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.jobs.models import Job, JobStatus
from apps.notifications.models import Notification
from apps.notifications.services import NotificationKind, notify, notify_managers


class Command(BaseCommand):
    help = "Send 'starting soon' and 'overdue' notifications (run every 5-10 minutes)."

    def handle(self, *args, **options):
        now = timezone.now()
        soon = Job.objects.filter(
            status=JobStatus.SCHEDULED, assigned_to__isnull=False,
            scheduled_start__gt=now, scheduled_start__lte=now + timedelta(minutes=30),
        ).select_related("property", "assigned_to", "organization")
        sent = 0
        for job in soon:
            if _already_sent(job, NotificationKind.JOB_STARTING_SOON):
                continue
            notify(job.assigned_to, NotificationKind.JOB_STARTING_SOON, title="Job starting soon",
                   body=f"{job.display_title} at {timezone.localtime(job.scheduled_start):%H:%M}",
                   organization=job.organization, data={"job_id": str(job.id)})
            sent += 1

        overdue = Job.objects.filter(
            status=JobStatus.SCHEDULED, scheduled_start__lt=now - timedelta(minutes=30),
            scheduled_start__gt=now - timedelta(days=1),
        ).select_related("property", "organization")
        for job in overdue:
            if _already_sent(job, NotificationKind.JOB_OVERDUE):
                continue
            notify_managers(job.organization, NotificationKind.JOB_OVERDUE, title="Job overdue",
                            body=f"{job.display_title} hasn't started yet", data={"job_id": str(job.id)})
            sent += 1
        self.stdout.write(f"Sent {sent} reminder(s).")


def _already_sent(job, kind):
    return Notification.objects.filter(kind=kind, data__job_id=str(job.id)).exists()
