from django.db import transaction
from rest_framework import serializers

from apps.checklists.models import ChecklistTemplate
from apps.core.serializers import OrgRelatedField
from apps.core.signed_urls import file_url
from apps.properties.models import Property
from apps.properties.serializers import OrgMemberField

from .models import (
    Frequency, Issue, Job, JobStatus, JobTask, Photo, PhotoKind, RecurringSchedule, Signature, TaskStatus,
)
from .services import create_job, notify_assignment, snapshot_checklist


class JobTaskSerializer(serializers.ModelSerializer):
    class Meta:
        model = JobTask
        fields = [
            "id", "section_name", "section_position", "title", "instructions", "is_required",
            "requires_photo", "position", "status", "note", "completed_at", "client_updated_at",
        ]
        read_only_fields = fields


class PhotoSerializer(serializers.ModelSerializer):
    url = serializers.SerializerMethodField()
    thumbnail_url = serializers.SerializerMethodField()

    class Meta:
        model = Photo
        fields = [
            "id", "job", "kind", "job_task", "issue", "room", "caption", "captured_at",
            "latitude", "longitude", "sha256", "width", "height", "size_bytes",
            "url", "thumbnail_url", "created_at",
        ]
        read_only_fields = fields

    def get_url(self, photo):
        return file_url("photo", photo.id, self.context.get("request"))

    def get_thumbnail_url(self, photo):
        return file_url("photo_thumb", photo.id, self.context.get("request"))


class PhotoUploadSerializer(serializers.Serializer):
    """Multipart upload. ``id`` is generated on the device so retries are
    idempotent."""

    id = serializers.UUIDField()
    job = serializers.UUIDField()
    file = serializers.ImageField()
    kind = serializers.ChoiceField(choices=PhotoKind.choices, default=PhotoKind.OTHER)
    job_task = serializers.UUIDField(required=False, allow_null=True)
    issue = serializers.UUIDField(required=False, allow_null=True)
    room = serializers.CharField(max_length=100, required=False, allow_blank=True)
    caption = serializers.CharField(max_length=200, required=False, allow_blank=True)
    captured_at = serializers.DateTimeField()
    latitude = serializers.DecimalField(max_digits=9, decimal_places=6, required=False, allow_null=True)
    longitude = serializers.DecimalField(max_digits=9, decimal_places=6, required=False, allow_null=True)
    sha256 = serializers.CharField(max_length=64, required=False, allow_blank=True)


class IssueSerializer(serializers.ModelSerializer):
    photo_ids = serializers.PrimaryKeyRelatedField(source="photos", many=True, read_only=True)

    class Meta:
        model = Issue
        fields = [
            "id", "job", "room", "description", "severity", "phase", "resolution",
            "reported_at", "photo_ids", "client_updated_at",
        ]
        read_only_fields = fields


class SignatureSerializer(serializers.ModelSerializer):
    class Meta:
        model = Signature
        fields = ["id", "signer_name", "source", "signed_at"]
        read_only_fields = fields


class PropertyBriefSerializer(serializers.ModelSerializer):
    """What a cleaner needs on site — no customer contact details."""

    class Meta:
        model = Property
        fields = [
            "id", "name", "address_line1", "address_line2", "city", "region", "postal_code",
            "country", "latitude", "longitude", "cleaning_instructions", "access_notes",
        ]


class AssigneeSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField(source="display_name")


class JobSummarySerializer(serializers.ModelSerializer):
    property_name = serializers.CharField(source="property.name", read_only=True)
    assigned_to_detail = AssigneeSerializer(source="assigned_to", read_only=True, allow_null=True)
    report_number = serializers.SerializerMethodField()
    duration_minutes = serializers.IntegerField(read_only=True)

    class Meta:
        model = Job
        fields = [
            "id", "title", "property", "property_name", "assigned_to_detail", "status",
            "scheduled_start", "scheduled_end", "started_at", "completed_at", "duration_minutes",
            "report_number", "updated_at",
        ]

    def get_report_number(self, job):
        report = getattr(job, "report", None)
        return report.number if report else None


class JobSerializer(serializers.ModelSerializer):
    property = OrgRelatedField(queryset=Property.objects.all())
    checklist_template = OrgRelatedField(
        queryset=ChecklistTemplate.objects.all(), required=False, allow_null=True
    )
    assigned_to = OrgMemberField(required=False, allow_null=True)
    property_detail = PropertyBriefSerializer(source="property", read_only=True)
    assigned_to_detail = AssigneeSerializer(source="assigned_to", read_only=True, allow_null=True)
    tasks = JobTaskSerializer(many=True, read_only=True)
    issues = IssueSerializer(many=True, read_only=True)
    photos = PhotoSerializer(many=True, read_only=True)
    signatures = SignatureSerializer(many=True, read_only=True)
    progress = serializers.SerializerMethodField()
    report = serializers.SerializerMethodField()
    missing_photo_ids = serializers.ListField(read_only=True)

    class Meta:
        model = Job
        fields = [
            "id", "title", "property", "property_detail", "assigned_to", "assigned_to_detail",
            "checklist_template", "recurring_schedule", "scheduled_start", "scheduled_end",
            "status", "instructions", "notes", "supply_notes", "started_at", "completed_at",
            "start_latitude", "start_longitude", "end_latitude", "end_longitude",
            "cancelled_reason", "tasks", "issues", "photos", "signatures", "progress", "report",
            "missing_photo_ids", "created_at", "updated_at",
        ]
        read_only_fields = [
            "status", "notes", "supply_notes", "started_at", "completed_at", "start_latitude",
            "start_longitude", "end_latitude", "end_longitude", "cancelled_reason",
            "recurring_schedule",
        ]

    def get_progress(self, job):
        tasks = list(job.tasks.all())
        done = sum(1 for t in tasks if t.status == TaskStatus.DONE)
        return {"done": done, "total": len(tasks)}

    def get_report(self, job):
        from apps.reports.serializers import ReportBriefSerializer

        report = getattr(job, "report", None)
        return ReportBriefSerializer(report, context=self.context).data if report else None

    def validate(self, attrs):
        start = attrs.get("scheduled_start", getattr(self.instance, "scheduled_start", None))
        end = attrs.get("scheduled_end", getattr(self.instance, "scheduled_end", None))
        if start and end and end < start:
            raise serializers.ValidationError({"scheduled_end": "Must be after the start."})
        return attrs

    def create(self, validated_data):
        return create_job(
            organization=self.context["organization"],
            created_by=self.context["request"].user,
            **validated_data,
        )

    @transaction.atomic
    def update(self, job, validated_data):
        if job.status in (JobStatus.COMPLETED, JobStatus.CANCELLED):
            raise serializers.ValidationError("Completed or cancelled jobs can't be edited.")
        old_assignee = job.assigned_to_id
        old_template = job.checklist_template_id
        job = super().update(job, validated_data)
        if job.checklist_template_id != old_template:
            if job.status != JobStatus.SCHEDULED:
                raise serializers.ValidationError("The checklist can't change once the job has started.")
            job.tasks.all().delete()
            snapshot_checklist(job)
        if job.assigned_to_id and job.assigned_to_id != old_assignee:
            notify_assignment(job)
        return job


class RecurringScheduleSerializer(serializers.ModelSerializer):
    property = OrgRelatedField(queryset=Property.objects.all())
    checklist_template = OrgRelatedField(
        queryset=ChecklistTemplate.objects.all(), required=False, allow_null=True
    )
    assigned_to = OrgMemberField(required=False, allow_null=True)

    class Meta:
        model = RecurringSchedule
        fields = [
            "id", "property", "assigned_to", "checklist_template", "title", "frequency",
            "interval_days", "weekdays", "day_of_month", "start_time", "duration_minutes",
            "timezone", "start_date", "end_date", "is_active", "created_at",
        ]
        read_only_fields = ["id", "created_at"]

    def validate_weekdays(self, value):
        if not isinstance(value, list) or any(not isinstance(d, int) or not 0 <= d <= 6 for d in value):
            raise serializers.ValidationError("Use a list of integers 0 (Mon) to 6 (Sun).")
        return sorted(set(value))

    def validate_timezone(self, value):
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise serializers.ValidationError("Unknown timezone.")
        return value

    def validate(self, attrs):
        freq = attrs.get("frequency", getattr(self.instance, "frequency", None))
        if freq == Frequency.MONTHLY:
            dom = attrs.get("day_of_month")
            if dom is not None and not 1 <= dom <= 31:
                raise serializers.ValidationError({"day_of_month": "Must be 1-31."})
        return attrs


class CancelJobSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=200, required=False, allow_blank=True)


class OnSiteSignatureSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    signer_name = serializers.CharField(max_length=150)
    image = serializers.ImageField()
    signed_at = serializers.DateTimeField()
