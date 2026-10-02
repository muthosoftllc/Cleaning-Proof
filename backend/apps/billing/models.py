from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.core.models import OrgScopedModel


class SubscriptionStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    IN_GRACE = "in_grace", "In grace period"
    ON_HOLD = "on_hold", "On hold"
    PAUSED = "paused", "Paused"
    CANCELED = "canceled", "Canceled (active until expiry)"
    EXPIRED = "expired", "Expired"
    PENDING = "pending", "Pending"


ENTITLED_STATUSES = {SubscriptionStatus.ACTIVE, SubscriptionStatus.IN_GRACE, SubscriptionStatus.CANCELED}


class Subscription(OrgScopedModel):
    provider = models.CharField(max_length=16, default="google_play")
    plan = models.CharField(max_length=16)
    product_id = models.CharField(max_length=100)
    purchase_token = models.CharField(max_length=512, unique=True)
    linked_purchase_token = models.CharField(max_length=512, blank=True)
    status = models.CharField(max_length=16, choices=SubscriptionStatus.choices)
    expires_at = models.DateTimeField(null=True, blank=True)
    auto_renewing = models.BooleanField(default=False)
    acknowledged = models.BooleanField(default=False)
    purchased_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    raw = models.JSONField(default=dict, blank=True)
    last_verified_at = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return f"{self.organization} {self.plan} ({self.status})"

    @property
    def is_entitled(self) -> bool:
        if self.status not in ENTITLED_STATUSES:
            return False
        return self.expires_at is None or self.expires_at > timezone.now()
