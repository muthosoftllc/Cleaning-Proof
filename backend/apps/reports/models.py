from django.conf import settings
from django.db import models
from django.urls import reverse

from apps.core.ids import generate_report_number, generate_share_token
from apps.core.models import OrgScopedModel


class ReportStatus(models.TextChoices):
    PENDING_EVIDENCE = "pending_evidence", "Waiting for photos to upload"
    FINAL = "final", "Final"
    REVOKED = "revoked", "Revoked"


def report_pdf_upload_to(instance, filename):
    return f"orgs/{instance.organization_id}/reports/{instance.number}-r{instance.revision}.pdf"


class Report(OrgScopedModel):
    """The proof of cleaning for one job.

    ``snapshot`` freezes what the report shows; ``content_hash`` is the
    SHA-256 of that snapshot (which itself includes every photo's SHA-256),
    so any later tampering is detectable from the verification page.
    """

    job = models.OneToOneField("jobs.Job", on_delete=models.CASCADE, related_name="report")
    number = models.CharField(max_length=20, unique=True, default=generate_report_number)
    share_token = models.CharField(max_length=64, unique=True, default=generate_share_token)
    status = models.CharField(max_length=20, choices=ReportStatus.choices, default=ReportStatus.PENDING_EVIDENCE)
    revision = models.PositiveIntegerField(default=1)
    snapshot = models.JSONField(default=dict)
    content_hash = models.CharField(max_length=64, blank=True)
    generated_at = models.DateTimeField(null=True, blank=True)
    finalized_at = models.DateTimeField(null=True, blank=True)
    pdf = models.FileField(upload_to=report_pdf_upload_to, blank=True, max_length=255)
    # Customer interaction (kept outside the hashed snapshot).
    approved_at = models.DateTimeField(null=True, blank=True)
    approved_by_name = models.CharField(max_length=150, blank=True)
    view_count = models.PositiveIntegerField(default=0)
    last_viewed_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return self.number

    @property
    def share_url(self) -> str:
        return settings.PUBLIC_BASE_URL + reverse("public-report", kwargs={"token": self.share_token})

    @property
    def verify_url(self) -> str:
        return settings.PUBLIC_BASE_URL + reverse("verify-report", kwargs={"number": self.number})


class CustomerFeedback(OrgScopedModel):
    class Kind(models.TextChoices):
        ISSUE = "issue", "Issue / dispute"
        COMMENT = "comment", "Comment"

    report = models.ForeignKey(Report, on_delete=models.CASCADE, related_name="feedback")
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.ISSUE)
    name = models.CharField(max_length=150, blank=True)
    message = models.TextField(max_length=2000)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
