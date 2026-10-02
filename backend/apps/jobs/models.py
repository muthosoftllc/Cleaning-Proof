import builtins

from django.conf import settings
from django.db import models

from apps.core.models import BaseModel, OrgScopedModel


class JobStatus(models.TextChoices):
    SCHEDULED = "scheduled", "Scheduled"
    IN_PROGRESS = "in_progress", "In progress"
    COMPLETED = "completed", "Completed"
    CANCELLED = "cancelled", "Cancelled"


class Job(OrgScopedModel):
    property = models.ForeignKey("properties.Property", on_delete=models.PROTECT, related_name="jobs")
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="assigned_jobs"
    )
    checklist_template = models.ForeignKey(
        "checklists.ChecklistTemplate", on_delete=models.SET_NULL, null=True, blank=True, related_name="jobs"
    )
    recurring_schedule = models.ForeignKey(
        "jobs.RecurringSchedule", on_delete=models.SET_NULL, null=True, blank=True, related_name="jobs"
    )
    title = models.CharField(max_length=150, blank=True)
    scheduled_start = models.DateTimeField()
    scheduled_end = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=JobStatus.choices, default=JobStatus.SCHEDULED)

    # Execution evidence, reported by the device (it may have been offline).
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    started_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    completed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    start_latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    start_longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    end_latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    end_longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    location_accuracy_m = models.FloatField(null=True, blank=True)

    instructions = models.TextField(blank=True, help_text="Job-specific instructions for the cleaner")
    notes = models.TextField(blank=True, help_text="Cleaner notes, shown on the report")
    supply_notes = models.TextField(blank=True, help_text="Supplies used/needed (internal)")
    # IDs of every photo captured on the device for this job, declared at
    # finish. The report is only finalized once all of them have arrived.
    expected_photo_ids = models.JSONField(default=list, blank=True)
    cancelled_reason = models.CharField(max_length=200, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta(OrgScopedModel.Meta):
        ordering = ["scheduled_start"]
        indexes = [
            models.Index(fields=["organization", "scheduled_start"]),
            models.Index(fields=["assigned_to", "status"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["recurring_schedule", "scheduled_start"],
                name="unique_recurring_occurrence",
                condition=models.Q(recurring_schedule__isnull=False),
            )
        ]

    def __str__(self):
        return self.display_title

    @builtins.property  # the 'property' field shadows the builtin here
    def display_title(self) -> str:
        return self.title or f"{self.property.name} cleaning"

    @builtins.property
    def duration_minutes(self) -> int | None:
        if self.started_at and self.completed_at:
            return max(0, int((self.completed_at - self.started_at).total_seconds() // 60))
        return None

    @builtins.property
    def missing_photo_ids(self) -> list[str]:
        if not self.expected_photo_ids:
            return []
        received = {str(pk) for pk in self.photos.values_list("id", flat=True)}
        return [pid for pid in self.expected_photo_ids if pid not in received]


class TaskStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    DONE = "done", "Done"
    SKIPPED = "skipped", "Skipped"


class JobTask(BaseModel):
    """A checklist item copied onto a job. Snapshotting means later template
    edits never rewrite what was actually checked on a past job."""

    job = models.ForeignKey(Job, on_delete=models.CASCADE, related_name="tasks")
    section_name = models.CharField(max_length=100)
    section_position = models.PositiveIntegerField(default=0)
    title = models.CharField(max_length=200)
    instructions = models.TextField(blank=True)
    is_required = models.BooleanField(default=True)
    requires_photo = models.BooleanField(default=False)
    position = models.PositiveIntegerField(default=0)

    status = models.CharField(max_length=16, choices=TaskStatus.choices, default=TaskStatus.PENDING)
    note = models.CharField(max_length=500, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    completed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    # Device clock of the last accepted change; drives last-writer-wins.
    client_updated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["section_position", "position"]

    def __str__(self):
        return f"{self.section_name}: {self.title}"


class PhotoKind(models.TextChoices):
    BEFORE = "before", "Before"
    AFTER = "after", "After"
    TASK = "task", "Task"
    ISSUE = "issue", "Issue"
    OTHER = "other", "Other"


class IssueSeverity(models.TextChoices):
    LOW = "low", "Low"
    MEDIUM = "medium", "Medium"
    HIGH = "high", "High"


class IssuePhase(models.TextChoices):
    BEFORE_CLEANING = "before_cleaning", "Present before cleaning"
    DURING_CLEANING = "during_cleaning", "Found during cleaning"
    AFTER_CLEANING = "after_cleaning", "Found after cleaning"


class IssueResolution(models.TextChoices):
    UNCHANGED = "unchanged", "Unchanged"
    IMPROVED = "improved", "Improved"
    RESOLVED = "resolved", "Resolved"
    NOT_APPLICABLE = "n/a", "Not applicable"


class Issue(OrgScopedModel):
    """Damage or problem noted on site, e.g. 'Large stain already present on
    bedroom carpet before cleaning.' Protects cleaner and customer alike."""

    job = models.ForeignKey(Job, on_delete=models.CASCADE, related_name="issues")
    room = models.CharField(max_length=100, blank=True)
    description = models.TextField()
    severity = models.CharField(max_length=8, choices=IssueSeverity.choices, default=IssueSeverity.LOW)
    phase = models.CharField(max_length=20, choices=IssuePhase.choices, default=IssuePhase.BEFORE_CLEANING)
    resolution = models.CharField(
        max_length=12, choices=IssueResolution.choices, default=IssueResolution.UNCHANGED
    )
    reported_at = models.DateTimeField()
    reported_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    client_updated_at = models.DateTimeField(null=True, blank=True)

    class Meta(OrgScopedModel.Meta):
        ordering = ["reported_at"]

    def __str__(self):
        return self.description[:60]


def photo_upload_to(instance, filename):
    return f"orgs/{instance.organization_id}/jobs/{instance.job_id}/photos/{instance.id}.jpg"


def thumb_upload_to(instance, filename):
    return f"orgs/{instance.organization_id}/jobs/{instance.job_id}/photos/{instance.id}_thumb.jpg"


class Photo(OrgScopedModel):
    job = models.ForeignKey(Job, on_delete=models.CASCADE, related_name="photos")
    kind = models.CharField(max_length=8, choices=PhotoKind.choices, default=PhotoKind.OTHER)
    job_task = models.ForeignKey(JobTask, on_delete=models.SET_NULL, null=True, blank=True, related_name="photos")
    issue = models.ForeignKey(Issue, on_delete=models.SET_NULL, null=True, blank=True, related_name="photos")
    room = models.CharField(max_length=100, blank=True)
    caption = models.CharField(max_length=200, blank=True)
    file = models.ImageField(upload_to=photo_upload_to, max_length=255)
    thumbnail = models.ImageField(upload_to=thumb_upload_to, blank=True, max_length=255)
    sha256 = models.CharField(max_length=64)
    width = models.PositiveIntegerField(null=True, blank=True)
    height = models.PositiveIntegerField(null=True, blank=True)
    size_bytes = models.PositiveIntegerField(default=0)
    captured_at = models.DateTimeField()
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta(OrgScopedModel.Meta):
        ordering = ["captured_at"]

    def __str__(self):
        return f"{self.kind} photo for {self.job_id}"


def signature_upload_to(instance, filename):
    return f"orgs/{instance.job.organization_id}/jobs/{instance.job_id}/signature-{instance.id}.png"


class Signature(BaseModel):
    """Customer sign-off, captured on the cleaner's device or remotely on the
    public report page."""

    class Source(models.TextChoices):
        ON_SITE = "on_site", "On site"
        REMOTE = "remote", "Remote (report link)"

    job = models.ForeignKey(Job, on_delete=models.CASCADE, related_name="signatures")
    signer_name = models.CharField(max_length=150)
    image = models.ImageField(upload_to=signature_upload_to, blank=True, max_length=255)
    source = models.CharField(max_length=8, choices=Source.choices)
    signed_at = models.DateTimeField()
    ip_address = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        ordering = ["signed_at"]


class ProcessedMutation(models.Model):
    """Idempotency log for the offline sync queue: a replayed mutation returns
    its original result instead of being applied twice."""

    id = models.UUIDField(primary_key=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    type = models.CharField(max_length=32)
    result = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)


class Frequency(models.TextChoices):
    DAILY = "daily", "Daily"
    WEEKLY = "weekly", "Weekly"
    BIWEEKLY = "biweekly", "Every two weeks"
    MONTHLY = "monthly", "Monthly"
    CUSTOM = "custom", "Every N days"


class RecurringSchedule(OrgScopedModel):
    """e.g. Apartment #204, every Monday + Thursday at 09:00, John, Airbnb Turnover."""

    property = models.ForeignKey("properties.Property", on_delete=models.CASCADE, related_name="schedules")
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    checklist_template = models.ForeignKey(
        "checklists.ChecklistTemplate", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    title = models.CharField(max_length=150, blank=True)
    frequency = models.CharField(max_length=10, choices=Frequency.choices)
    interval_days = models.PositiveIntegerField(default=1, help_text="Only for 'custom'")
    weekdays = models.JSONField(default=list, blank=True, help_text="0=Mon..6=Sun, for weekly/biweekly")
    day_of_month = models.PositiveSmallIntegerField(null=True, blank=True)
    start_time = models.TimeField()
    duration_minutes = models.PositiveIntegerField(default=120)
    timezone = models.CharField(max_length=64, default="UTC")
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.property} ({self.get_frequency_display()})"
