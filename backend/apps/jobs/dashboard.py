from datetime import timedelta

from django.db.models import Avg, Count, DurationField, ExpressionWrapper, F, Q
from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import OrgRolePermission, resolve_membership
from apps.organizations.models import Membership, Role

from .models import Issue, Job, JobStatus, JobTask, TaskStatus


class DashboardView(APIView):
    """Owner overview: today's work plus 30-day metrics."""

    permission_classes = [OrgRolePermission]
    read_roles = Role.MANAGERS | {Role.VIEWER}

    def get(self, request):
        org = resolve_membership(request).organization
        now = timezone.now()
        today = timezone.localdate()
        since = now - timedelta(days=int(request.query_params.get("days", 30)))
        jobs = Job.objects.filter(organization=org)
        recent = jobs.filter(scheduled_start__gte=since, scheduled_start__lte=now)

        closed = recent.exclude(status=JobStatus.CANCELLED)
        completed = closed.filter(status=JobStatus.COMPLETED)
        completed_count = completed.count()
        closed_count = closed.count()
        avg_duration = completed.filter(started_at__isnull=False).aggregate(
            avg=Avg(ExpressionWrapper(F("completed_at") - F("started_at"), output_field=DurationField()))
        )["avg"]
        missed = (
            JobTask.objects.filter(job__in=completed)
            .exclude(status=TaskStatus.DONE)
            .values("section_name", "title")
            .annotate(count=Count("id"))
            .order_by("-count")[:5]
        )
        from apps.reports.models import Report

        return Response({
            "today": {
                "total": jobs.filter(scheduled_start__date=today).exclude(status=JobStatus.CANCELLED).count(),
                "completed": jobs.filter(scheduled_start__date=today, status=JobStatus.COMPLETED).count(),
                "in_progress": jobs.filter(status=JobStatus.IN_PROGRESS).count(),
            },
            "upcoming": jobs.filter(scheduled_start__date__gt=today, status=JobStatus.SCHEDULED).count(),
            "overdue": jobs.filter(scheduled_start__lt=now - timedelta(hours=1), status=JobStatus.SCHEDULED).count(),
            "counts": {
                "employees": Membership.objects.filter(organization=org, is_active=True).count(),
                "properties": org_count(org, "properties.Property", is_active=True),
                "customers": org_count(org, "properties.Customer"),
                "templates": org_count(org, "checklists.ChecklistTemplate", is_archived=False),
            },
            "metrics": {
                "period_start": since,
                "jobs_completed": completed_count,
                "completion_rate": round(completed_count / closed_count, 3) if closed_count else None,
                "average_duration_minutes": round(avg_duration.total_seconds() / 60) if avg_duration else None,
                "frequently_missed_tasks": list(missed),
                "issues_reported": Issue.objects.filter(organization=org, reported_at__gte=since).count(),
                "customer_approvals": Report.objects.filter(
                    organization=org, approved_at__gte=since
                ).count(),
            },
        })


def org_count(org, model_label, **filters):
    from django.apps import apps

    return apps.get_model(model_label).objects.filter(Q(organization=org), **filters).count()
