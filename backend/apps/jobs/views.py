from datetime import timedelta

from django.db import transaction
from django.db.models import Prefetch, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.billing.entitlements import Entitlements
from apps.core.permissions import OrgRolePermission, resolve_membership
from apps.core.viewsets import OrgScopedViewSet
from apps.organizations.audit import record_event
from apps.organizations.models import Membership, Role

from .models import Issue, Job, JobStatus, JobTask, Photo, RecurringSchedule, Signature
from .serializers import (
    CancelJobSerializer,
    JobSerializer,
    JobSummarySerializer,
    OnSiteSignatureSerializer,
    PhotoSerializer,
    PhotoUploadSerializer,
    RecurringScheduleSerializer,
    SignatureSerializer,
)
from .services import can_work_on, store_photo
from .sync import PushSerializer, apply_mutation


def job_detail_queryset():
    return Job.objects.select_related("property", "assigned_to", "report").prefetch_related(
        "tasks", "photos", "signatures", Prefetch("issues", queryset=Issue.objects.prefetch_related("photos"))
    )


class JobViewSet(OrgScopedViewSet):
    queryset = Job.objects.all()
    serializer_class = JobSerializer
    audit_prefix = "job"
    action_roles = {"signature": Role.FIELD}

    def get_queryset(self):
        if self.action == "list":
            self.queryset = Job.objects.select_related("property", "assigned_to", "report")
        else:
            self.queryset = job_detail_queryset()
        qs = super().get_queryset()
        params = self.request.query_params
        if params.get("status"):
            qs = qs.filter(status__in=params["status"].split(","))
        if params.get("property"):
            qs = qs.filter(property_id=params["property"])
        if params.get("assigned_to") == "me":
            qs = qs.filter(assigned_to=self.request.user)
        elif params.get("assigned_to"):
            qs = qs.filter(assigned_to_id=params["assigned_to"])
        when = params.get("when")
        today = timezone.localdate()
        if when == "today":
            qs = qs.filter(scheduled_start__date=today)
        elif when == "upcoming":
            qs = qs.filter(scheduled_start__date__gt=today, status=JobStatus.SCHEDULED)
        elif when == "overdue":
            qs = qs.filter(scheduled_start__lt=timezone.now(), status=JobStatus.SCHEDULED)
        for param, lookup in (("from", "scheduled_start__gte"), ("to", "scheduled_start__lt")):
            if params.get(param):
                value = parse_datetime(params[param])
                if value is None:
                    raise ValidationError({param: "Use an ISO 8601 datetime."})
                qs = qs.filter(**{lookup: value})
        return qs

    def scope_for_cleaner(self, qs):
        return qs.filter(assigned_to=self.request.user)

    def get_serializer_class(self):
        return JobSummarySerializer if self.action == "list" else JobSerializer

    def perform_create(self, serializer):
        instance = serializer.save()
        self._audit("created", instance)

    def perform_destroy(self, job):
        if job.status != JobStatus.SCHEDULED or job.photos.exists():
            raise ValidationError("Only scheduled jobs without evidence can be deleted; cancel it instead.")
        super().perform_destroy(job)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        job = self.get_object()
        serializer = CancelJobSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        if job.status == JobStatus.COMPLETED:
            raise ValidationError("Completed jobs can't be cancelled.")
        job.status = JobStatus.CANCELLED
        job.cancelled_reason = serializer.validated_data.get("reason", "")
        job.save(update_fields=["status", "cancelled_reason", "updated_at"])
        self._audit("cancelled", job)
        return Response(JobSerializer(job, context=self.get_serializer_context()).data)

    @action(detail=True, methods=["post"], parser_classes=[MultiPartParser, FormParser])
    def signature(self, request, pk=None):
        """Customer signs on the cleaner's device at the end of the job."""
        job = self.get_object()
        serializer = OnSiteSignatureSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        existing = Signature.objects.filter(pk=data["id"]).first()
        if existing is not None:
            if existing.job_id != job.id:
                raise ValidationError({"id": "Already used."})
            return Response(SignatureSerializer(existing).data)
        signature = Signature(
            id=data["id"], job=job, signer_name=data["signer_name"],
            source=Signature.Source.ON_SITE, signed_at=data["signed_at"],
        )
        signature.image.save("signature.png", data["image"], save=False)
        signature.save()
        record_event(request, "job.signed_on_site", job, organization=job.organization)
        return Response(SignatureSerializer(signature).data, status=status.HTTP_201_CREATED)


class PhotoViewSet(mixins.CreateModelMixin, mixins.RetrieveModelMixin, mixins.ListModelMixin,
                   viewsets.GenericViewSet):
    """Photo evidence. Append-only: there is deliberately no delete endpoint."""

    serializer_class = PhotoSerializer
    permission_classes = [OrgRolePermission]
    parser_classes = [MultiPartParser, FormParser]
    write_roles = Role.FIELD

    def get_queryset(self):
        membership = resolve_membership(self.request)
        qs = Photo.objects.filter(organization=membership.organization)
        if membership.is_cleaner:
            qs = qs.filter(job__assigned_to=self.request.user)
        if self.request.query_params.get("job"):
            qs = qs.filter(job_id=self.request.query_params["job"])
        return qs

    def create(self, request, *args, **kwargs):
        serializer = PhotoUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        upload = data.pop("file")
        from django.conf import settings

        if upload.size > settings.MAX_PHOTO_UPLOAD_BYTES:
            raise ValidationError({"file": "Photo is too large."})

        job = get_object_or_404(Job, pk=data.pop("job"))
        membership = Membership.objects.filter(
            organization_id=job.organization_id, user=request.user, is_active=True
        ).first()
        if not can_work_on(job, request.user, membership):
            raise PermissionDenied("Job not assigned to you.")

        existing = Photo.objects.filter(pk=data["id"]).first()
        if existing is not None:
            if existing.job_id != job.id:
                return Response({"detail": "Photo id already used."}, status=status.HTTP_409_CONFLICT)
            return Response(self.get_serializer(existing).data, status=status.HTTP_200_OK)

        task_id = data.pop("job_task", None)
        issue_id = data.pop("issue", None)
        job_task = None
        issue = None
        if task_id:
            job_task = JobTask.objects.filter(pk=task_id, job=job).first()
            if job_task is None:
                raise ValidationError({"job_task": "Task does not belong to this job."})
        if issue_id:
            issue = Issue.objects.filter(pk=issue_id, job=job).first()
            if issue is None:
                # The issue mutation hasn't synced yet; device should retry later.
                return Response({"detail": "Issue not synced yet."}, status=status.HTTP_409_CONFLICT)

        photo = store_photo(
            job=job, user=request.user, file=upload, client_sha256=data.pop("sha256", None),
            job_task=job_task, issue=issue, **data,
        )
        if job.status == JobStatus.COMPLETED:
            from apps.reports.services import finalize_report_if_ready

            transaction.on_commit(lambda: finalize_report_if_ready(job))
        return Response(self.get_serializer(photo).data, status=status.HTTP_201_CREATED)


class RecurringScheduleViewSet(OrgScopedViewSet):
    queryset = RecurringSchedule.objects.select_related("property")
    serializer_class = RecurringScheduleSerializer
    read_roles = Role.MANAGERS | {Role.VIEWER}
    audit_prefix = "schedule"

    def perform_create(self, serializer):
        Entitlements.for_org(self.organization).require("recurring_jobs")
        super().perform_create(serializer)


class SyncPushView(APIView):
    """Apply a batch of queued offline mutations, in order."""

    def post(self, request):
        serializer = PushSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        results = [apply_mutation(request.user, m) for m in serializer.validated_data["mutations"]]
        return Response({"results": results, "server_time": timezone.now()})


class SyncPullView(APIView):
    """Everything the device needs to work offline: the caller's jobs in the
    working window, with tasks, issues and photo metadata."""

    permission_classes = [OrgRolePermission]

    def get(self, request):
        membership = resolve_membership(request)
        now = timezone.now()
        window = Q(scheduled_start__gte=now - timedelta(days=2), scheduled_start__lte=now + timedelta(days=30))
        base = Job.objects.filter(organization=membership.organization, assigned_to=request.user)
        active = base.filter(window | Q(status=JobStatus.IN_PROGRESS)).exclude(status=JobStatus.CANCELLED)
        changed = job_detail_queryset().filter(pk__in=base.values("pk"))
        since = request.query_params.get("since")
        if since:
            since_dt = parse_datetime(since)
            if since_dt is None:
                raise ValidationError({"since": "Use an ISO 8601 datetime."})
            changed = changed.filter(updated_at__gt=since_dt)
        else:
            changed = changed.filter(pk__in=active.values("pk"))
        context = {"request": request, "organization": membership.organization}
        return Response({
            "server_time": now,
            "jobs": JobSerializer(changed, many=True, context=context).data,
            # The device may drop local jobs not listed here once they have no
            # unsynced changes (reassigned or cancelled elsewhere).
            "active_job_ids": [str(pk) for pk in active.values_list("pk", flat=True)],
        })
