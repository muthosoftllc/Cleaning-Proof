"""Plan catalogue. The server is the single source of truth for what an
organization may do; the app only displays what the API returns.

Deliberate choice: the free plan keeps photo evidence and customer share
links, because a report reaching a customer *is* the growth loop. Free is
limited by volume instead.
"""
from dataclasses import dataclass, field

UNLIMITED = None


@dataclass(frozen=True)
class Plan:
    code: str
    name: str
    jobs_per_month: int | None
    active_properties: int | None
    team_members: int | None  # active non-viewer members, owner included
    storage_gb: int
    features: frozenset = field(default_factory=frozenset)


FREE = Plan(
    code="free", name="Free", jobs_per_month=10, active_properties=3, team_members=1, storage_gb=1,
    features=frozenset({"photo_evidence", "share_links"}),
)
PRO = Plan(
    code="pro", name="Pro", jobs_per_month=UNLIMITED, active_properties=50, team_members=5, storage_gb=25,
    features=frozenset({"photo_evidence", "share_links", "pdf_reports", "recurring_jobs", "team"}),
)
BUSINESS = Plan(
    code="business", name="Business", jobs_per_month=UNLIMITED, active_properties=UNLIMITED,
    team_members=UNLIMITED, storage_gb=250,
    features=frozenset({
        "photo_evidence", "share_links", "pdf_reports", "recurring_jobs", "team",
        "multiple_teams", "advanced_permissions", "branding", "analytics", "priority_support",
    }),
)

PLANS = {p.code: p for p in (FREE, PRO, BUSINESS)}

# Google Play subscription product IDs -> plan codes.
PRODUCT_PLANS = {
    "cleaningproof_pro": "pro",
    "cleaningproof_business": "business",
}
