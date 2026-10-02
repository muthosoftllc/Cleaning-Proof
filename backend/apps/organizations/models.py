import secrets
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.core.models import BaseModel


class Role(models.TextChoices):
    OWNER = "owner", "Owner"
    ADMIN = "admin", "Admin"
    CLEANER = "cleaner", "Cleaner"
    VIEWER = "viewer", "Viewer"


# Role groups used by permission checks.
Role.ALL = frozenset(Role.values)
Role.MANAGERS = frozenset({Role.OWNER, Role.ADMIN})
Role.FIELD = frozenset({Role.OWNER, Role.ADMIN, Role.CLEANER})


class Organization(BaseModel):
    name = models.CharField(max_length=150)
    logo = models.ImageField(upload_to="org-logos/", blank=True, max_length=255)
    brand_color = models.CharField(max_length=7, blank=True, help_text="Hex color, e.g. #0F766E")
    contact_email = models.EmailField(blank=True)
    contact_phone = models.CharField(max_length=40, blank=True)
    website = models.URLField(blank=True)
    timezone = models.CharField(max_length=64, default="UTC")
    deleted_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return self.name

    def schedule_deletion(self):
        self.deleted_at = timezone.now()
        self.save(update_fields=["deleted_at", "updated_at"])


class Membership(BaseModel):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="memberships")
    role = models.CharField(max_length=16, choices=Role.choices, default=Role.CLEANER)
    is_active = models.BooleanField(default=True)

    class Meta(BaseModel.Meta):
        constraints = [
            models.UniqueConstraint(fields=["organization", "user"], name="unique_membership"),
        ]

    def __str__(self):
        return f"{self.user} @ {self.organization} ({self.role})"

    @property
    def is_manager(self) -> bool:
        return self.role in Role.MANAGERS

    @property
    def is_cleaner(self) -> bool:
        return self.role == Role.CLEANER


def _invite_token():
    return secrets.token_urlsafe(24)


def _invite_expiry():
    return timezone.now() + timedelta(days=14)


class Invitation(BaseModel):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="invitations")
    email = models.EmailField()
    role = models.CharField(max_length=16, choices=Role.choices, default=Role.CLEANER)
    token = models.CharField(max_length=64, unique=True, default=_invite_token)
    invited_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    expires_at = models.DateTimeField(default=_invite_expiry)
    accepted_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    @property
    def is_pending(self) -> bool:
        return not self.accepted_at and not self.revoked_at and self.expires_at > timezone.now()


class AuditEvent(models.Model):
    """Append-only audit trail of security- and evidence-relevant actions."""

    id = models.BigAutoField(primary_key=True)
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, null=True, blank=True, related_name="audit_events"
    )
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    action = models.CharField(max_length=64)
    target_type = models.CharField(max_length=64, blank=True)
    target_id = models.CharField(max_length=64, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["organization", "-created_at"])]

    def __str__(self):
        return f"{self.created_at:%Y-%m-%d %H:%M} {self.action}"
