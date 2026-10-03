from datetime import timedelta

from django.db.models import Avg, Count, DurationField, ExpressionWrapper, F
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.checklists.models import ChecklistTemplate
from apps.core.permissions import OrgRolePermission, resolve_membership
from apps.organizations.models import READER_ROLES, Membership
from apps.properties.models import Customer, Property

from .models import Issue, Job, JobStatus, JobTask, TaskStatus

MAX_PERIOD_DAYS = 366


def _period_days(request) -> int:
    try:
        days = int(request.query_params.get("days", 30))
    except ValueError:
        raise ValidationError({"days": "Must be a whole number."}) from None
    if not 1 <= days <= MAX_PERIOD_DAYS:
        raise ValidationError({"days": f"Must be between 1 and {MAX_PERIOD_DAYS}."})
    return days


class DashboardView(APIView):
    """Owner overview: today's work plus period metrics."""

    permission_classes = [OrgRolePermission]
    read_roles = READER_ROLES

    def get(self, request):
        from apps.reports.models import Report

        org = resolve_membership(request).organization
        now = timezone.now()
        today = timezone.localdate()
        since = now - timedelta(days=_period_days(request))
        jobs = Job.objects.filter(organization=org)
        today_jobs = jobs.filter(scheduled_start__date=today).exclude(status=JobStatus.CANCELLED)

        closed = jobs.filter(scheduled_start__gte=since, scheduled_start__lte=now).exclude(status=JobStatus.CANCELLED)
        completed = closed.filter(status=JobStatus.COMPLETED)
        completed_count, closed_count = completed.count(), closed.count()
        avg_duration = completed.filter(started_at__isnull=False).aggregate(
            avg=Avg(ExpressionWrapper(F("completed_at") - F("started_at"), output_field=DurationField()))
        )["avg"]
        frequently_missed = (
            JobTask.objects.filter(job__in=completed)
            .exclude(status=TaskStatus.DONE)
            .values("section_name", "title")
            .annotate(count=Count("id"))
            .order_by("-count")[:5]
        )
        return Response(
            {
                "today": {
                    "total": today_jobs.count(),
                    "completed": today_jobs.filter(status=JobStatus.COMPLETED).count(),
                    "in_progress": jobs.filter(status=JobStatus.IN_PROGRESS).count(),
                },
                "upcoming": jobs.filter(scheduled_start__date__gt=today, status=JobStatus.SCHEDULED).count(),
                "overdue": jobs.filter(
                    scheduled_start__lt=now - timedelta(hours=1), status=JobStatus.SCHEDULED
                ).count(),
                "counts": {
                    "employees": Membership.objects.filter(organization=org, is_active=True).count(),
                    "properties": Property.objects.filter(organization=org, is_active=True).count(),
                    "customers": Customer.objects.filter(organization=org).count(),
                    "templates": ChecklistTemplate.objects.filter(organization=org, is_archived=False).count(),
                },
                "metrics": {
                    "period_start": since,
                    "jobs_completed": completed_count,
                    "completion_rate": round(completed_count / closed_count, 3) if closed_count else None,
                    "average_duration_minutes": round(avg_duration.total_seconds() / 60) if avg_duration else None,
                    "frequently_missed_tasks": list(frequently_missed),
                    "issues_reported": Issue.objects.filter(organization=org, reported_at__gte=since).count(),
                    "customer_approvals": Report.objects.filter(organization=org, approved_at__gte=since).count(),
                },
            }
        )
