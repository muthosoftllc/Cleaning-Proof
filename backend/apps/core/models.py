import uuid

from django.db import models


class BaseModel(models.Model):
    """UUID primary key + timestamps.

    IDs are UUIDs so the Android client can create records offline and the
    server can treat repeated uploads of the same record idempotently.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
        ordering = ["-created_at"]


class OrgScopedModel(BaseModel):
    """A record that belongs to exactly one organization (tenant)."""

    organization = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="+")

    class Meta(BaseModel.Meta):
        abstract = True
