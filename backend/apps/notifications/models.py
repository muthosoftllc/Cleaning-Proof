from django.conf import settings
from django.db import models

from apps.core.models import BaseModel


class NotificationKind(models.TextChoices):
    JOB_ASSIGNED = "job_assigned", "New job assigned"
    JOB_STARTING_SOON = "job_starting_soon", "Job starting soon"
    JOB_OVERDUE = "job_overdue", "Job overdue"
    JOB_COMPLETED = "job_completed", "Job completed"
    REPORT_GENERATED = "report_generated", "Report generated"
    CUSTOMER_APPROVED = "customer_approved", "Customer approval"
    CUSTOMER_ISSUE = "customer_issue", "Customer issue/dispute"
    RECURRING_JOB_CREATED = "recurring_job_created", "Recurring job created"


class Notification(BaseModel):
    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, null=True, blank=True, related_name="+"
    )
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications")
    kind = models.CharField(max_length=32, choices=NotificationKind.choices)
    title = models.CharField(max_length=150)
    body = models.CharField(max_length=500, blank=True)
    data = models.JSONField(default=dict, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)
    pushed_at = models.DateTimeField(null=True, blank=True)

    class Meta(BaseModel.Meta):
        indexes = [models.Index(fields=["user", "-created_at"])]


class Device(BaseModel):
    """FCM registration token for push notifications."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="devices")
    token = models.CharField(max_length=512, unique=True)
    platform = models.CharField(max_length=16, default="android")
    app_version = models.CharField(max_length=32, blank=True)
    last_seen_at = models.DateTimeField(auto_now=True)
