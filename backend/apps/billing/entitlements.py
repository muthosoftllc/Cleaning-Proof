from datetime import datetime

from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import APIException

from .plans import FREE, PLANS, Plan


class PlanLimitExceeded(APIException):
    status_code = status.HTTP_402_PAYMENT_REQUIRED
    default_code = "plan_limit"
    default_detail = "Your plan does not allow this. Upgrade to continue."


class Entitlements:
    """Server-authoritative answer to "what may this organization do?"."""

    def __init__(self, organization, plan: Plan, subscription=None):
        self.organization = organization
        self.plan = plan
        self.subscription = subscription

    @classmethod
    def for_org(cls, organization) -> "Entitlements":
        from .models import Subscription

        best = None
        for sub in Subscription.objects.filter(organization=organization).order_by("-expires_at"):
            if sub.is_entitled and sub.plan in PLANS:
                if best is None or _rank(sub.plan) > _rank(best.plan):
                    best = sub
        return cls(organization, PLANS[best.plan] if best else FREE, best)

    def has(self, feature: str) -> bool:
        return feature in self.plan.features

    def require(self, feature: str) -> None:
        if not self.has(feature):
            raise PlanLimitExceeded(f"'{feature.replace('_', ' ')}' is not included in the {self.plan.name} plan.")

    # --- usage -----------------------------------------------------------
    def jobs_in_month(self, when: datetime) -> int:
        from apps.jobs.models import Job

        local = timezone.localtime(when)
        return Job.objects.filter(
            organization=self.organization,
            scheduled_start__year=local.year,
            scheduled_start__month=local.month,
        ).count()

    def active_properties(self) -> int:
        from apps.properties.models import Property

        return Property.objects.filter(organization=self.organization, is_active=True).count()

    def team_members(self) -> int:
        from apps.organizations.models import Membership, Role

        return Membership.objects.filter(
            organization=self.organization, is_active=True
        ).exclude(role=Role.VIEWER).count()

    # --- checks ----------------------------------------------------------
    def check_can_create_job(self, scheduled_start: datetime) -> None:
        limit = self.plan.jobs_per_month
        if limit is not None and self.jobs_in_month(scheduled_start) >= limit:
            raise PlanLimitExceeded(f"The {self.plan.name} plan includes {limit} jobs per month.")

    def check_can_add_property(self) -> None:
        limit = self.plan.active_properties
        if limit is not None and self.active_properties() >= limit:
            raise PlanLimitExceeded(f"The {self.plan.name} plan includes {limit} active properties.")

    def check_can_add_member(self) -> None:
        limit = self.plan.team_members
        if limit is not None and self.team_members() >= limit:
            raise PlanLimitExceeded(f"The {self.plan.name} plan includes {limit} team member(s).")

    def as_dict(self) -> dict:
        now = timezone.now()
        return {
            "plan": self.plan.code,
            "plan_name": self.plan.name,
            "features": sorted(self.plan.features),
            "limits": {
                "jobs_per_month": self.plan.jobs_per_month,
                "active_properties": self.plan.active_properties,
                "team_members": self.plan.team_members,
                "storage_gb": self.plan.storage_gb,
            },
            "usage": {
                "jobs_this_month": self.jobs_in_month(now),
                "active_properties": self.active_properties(),
                "team_members": self.team_members(),
            },
            "subscription": None if self.subscription is None else {
                "status": self.subscription.status,
                "product_id": self.subscription.product_id,
                "expires_at": self.subscription.expires_at,
                "auto_renewing": self.subscription.auto_renewing,
            },
        }


def _rank(plan_code: str) -> int:
    return list(PLANS).index(plan_code)
