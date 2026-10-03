from datetime import timedelta

from django.db.models import Prefetch, Q
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.billing.entitlements import Entitlements
from apps.core.http import uuid_param
from apps.core.permissions import OrgRolePermission, resolve_membership
from apps.core.viewsets import OrgScopedViewSet
from apps.organizations.audit import record_event
from apps.organizations.models import FIELD_ROLES, READER_ROLES

from .models import Issue, Job, JobStatus, Photo, RecurringSchedule, Signature
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
from .services import PhotoConflict, ingest_photo
from .sync import PushSerializer, apply_mutation

# Pull cursors overlap by this much so a commit racing the cursor is never
# missed; re-delivering a job is harmless (merging is idempotent).
PULL_OVERLAP = timedelta(seconds=5)
SYNC_WINDOW_PAST = timedelta(days=2)
SYNC_WINDOW_FUTURE = timedelta(days=30)


def with_job_details(qs):
    """Everything JobSerializer touches, in a constant number of queries."""
    return qs.select_related("property", "assigned_to", "report").prefetch_related(
        "tasks", "photos", "signatures", Prefetch("issues", queryset=Issue.objects.prefetch_related("photos"))
    )


def _datetime_param(request, name):
    raw = request.query_params.get(name)
    if not raw:
        return None
    value = parse_datetime(raw)
    if value is None:
        raise ValidationError({name: "Use an ISO 8601 datetime."})
    return value


class JobViewSet(OrgScopedViewSet):
    queryset = Job.objects.all()
    serializer_class = JobSerializer
    audit_prefix = "job"
    action_roles = {"signature": FIELD_ROLES}

    def get_queryset(self):
        qs = super().get_queryset()
        if self.action == "list":
            return self._filter(qs.select_related("property", "assigned_to", "report"))
        return with_job_details(qs)

    def _filter(self, qs):
        request = self.request
        statuses = [s for s in request.query_params.get("status", "").split(",") if s]
        if statuses:
            if not set(statuses) <= set(JobStatus.values):
                raise ValidationError({"status": f"Use any of: {', '.join(JobStatus.values)}."})
            qs = qs.filter(status__in=statuses)
        if property_id := uuid_param(request, "property"):
            qs = qs.filter(property_id=property_id)
        if request.query_params.get("assigned_to") == "me":
            qs = qs.filter(assigned_to=request.user)
        elif assignee := uuid_param(request, "assigned_to"):
            qs = qs.filter(assigned_to_id=assignee)
        today = timezone.localdate()
        when = request.query_params.get("when")
        if when == "today":
            qs = qs.filter(scheduled_start__date=today)
        elif when == "upcoming":
            qs = qs.filter(scheduled_start__date__gt=today, status=JobStatus.SCHEDULED)
        elif when == "overdue":
            qs = qs.filter(scheduled_start__lt=timezone.now(), status=JobStatus.SCHEDULED)
        if start := _datetime_param(request, "from"):
            qs = qs.filter(scheduled_start__gte=start)
        if end := _datetime_param(request, "to"):
            qs = qs.filter(scheduled_start__lt=end)
        return qs

    def scope_for_cleaner(self, qs):
        return qs.filter(assigned_to=self.request.user)

    def get_serializer_class(self):
        return JobSummarySerializer if self.action == "list" else JobSerializer

    def perform_create(self, serializer):
        self._audit("created", serializer.save())

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
        """Customer signs on the cleaner's device at the end of the job. Idempotent on ``id``."""
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
            id=data["id"],
            job=job,
            signer_name=data["signer_name"],
            source=Signature.Source.ON_SITE,
            signed_at=data["signed_at"],
        )
        signature.image.save("signature.png", data["image"], save=False)
        signature.save()
        record_event(request, "job.signed_on_site", job, organization=job.organization)
        return Response(SignatureSerializer(signature).data, status=status.HTTP_201_CREATED)


class PhotoViewSet(mixins.CreateModelMixin, mixins.RetrieveModelMixin, mixins.ListModelMixin, viewsets.GenericViewSet):
    """Photo evidence. Append-only: there is deliberately no delete endpoint."""

    serializer_class = PhotoSerializer
    permission_classes = [OrgRolePermission]
    parser_classes = [MultiPartParser, FormParser]
    write_roles = FIELD_ROLES

    def get_queryset(self):
        membership = resolve_membership(self.request)
        qs = Photo.objects.filter(organization=membership.organization)
        if membership.is_cleaner:
            qs = qs.filter(job__assigned_to=self.request.user)
        if job_id := uuid_param(self.request, "job"):
            qs = qs.filter(job_id=job_id)
        return qs

    def create(self, request, *args, **kwargs):
        serializer = PhotoUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        try:
            result = ingest_photo(
                user=request.user,
                photo_id=data.pop("id"),
                job_id=data.pop("job"),
                file=data.pop("file"),
                client_sha256=data.pop("sha256", None),
                job_task_id=data.pop("job_task", None),
                issue_id=data.pop("issue", None),
                **data,
            )
        except PhotoConflict as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
        return Response(
            self.get_serializer(result.photo).data,
            status=status.HTTP_201_CREATED if result.created else status.HTTP_200_OK,
        )


class RecurringScheduleViewSet(OrgScopedViewSet):
    queryset = RecurringSchedule.objects.select_related("property")
    serializer_class = RecurringScheduleSerializer
    read_roles = READER_ROLES
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
        window = Q(scheduled_start__gte=now - SYNC_WINDOW_PAST, scheduled_start__lte=now + SYNC_WINDOW_FUTURE)
        mine = Job.objects.filter(organization=membership.organization, assigned_to=request.user)
        active = mine.filter(window | Q(status=JobStatus.IN_PROGRESS)).exclude(status=JobStatus.CANCELLED)
        since = _datetime_param(request, "since")
        changed = mine.filter(updated_at__gt=since) if since else active
        jobs = with_job_details(Job.objects.filter(pk__in=changed.values("pk")))
        context = {"request": request, "organization": membership.organization}
        return Response(
            {
                "server_time": now - PULL_OVERLAP,
                "jobs": JobSerializer(jobs, many=True, context=context).data,
                # The device may drop local jobs not listed here once they have no
                # unsynced changes (reassigned or cancelled elsewhere).
                "active_job_ids": [str(pk) for pk in active.values_list("pk", flat=True)],
            }
        )
