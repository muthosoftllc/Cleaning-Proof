"""Google Play Developer API (subscriptionsv2) verification.

The device never decides entitlements. It hands the purchase token to the
server, which asks Google, stores the result and acknowledges the purchase.
"""
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import lru_cache

from django.conf import settings
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .models import SubscriptionStatus

logger = logging.getLogger(__name__)
SCOPE = "https://www.googleapis.com/auth/androidpublisher"
API = "https://androidpublisher.googleapis.com/androidpublisher/v3/applications"

STATE_MAP = {
    "SUBSCRIPTION_STATE_ACTIVE": SubscriptionStatus.ACTIVE,
    "SUBSCRIPTION_STATE_IN_GRACE_PERIOD": SubscriptionStatus.IN_GRACE,
    "SUBSCRIPTION_STATE_ON_HOLD": SubscriptionStatus.ON_HOLD,
    "SUBSCRIPTION_STATE_PAUSED": SubscriptionStatus.PAUSED,
    "SUBSCRIPTION_STATE_CANCELED": SubscriptionStatus.CANCELED,
    "SUBSCRIPTION_STATE_EXPIRED": SubscriptionStatus.EXPIRED,
    "SUBSCRIPTION_STATE_PENDING": SubscriptionStatus.PENDING,
}


class VerificationError(Exception):
    pass


@dataclass
class PurchaseState:
    product_id: str
    status: str
    expires_at: datetime | None
    auto_renewing: bool
    acknowledged: bool
    linked_purchase_token: str
    obfuscated_account_id: str
    raw: dict


def parse_subscription_v2(data: dict) -> PurchaseState:
    line_items = data.get("lineItems") or [{}]
    item = max(line_items, key=lambda li: li.get("expiryTime", ""))
    expiry = parse_datetime(item["expiryTime"]) if item.get("expiryTime") else None
    return PurchaseState(
        product_id=item.get("productId", ""),
        status=STATE_MAP.get(data.get("subscriptionState"), SubscriptionStatus.EXPIRED),
        expires_at=expiry,
        auto_renewing=bool((item.get("autoRenewingPlan") or {}).get("autoRenewEnabled")),
        acknowledged=data.get("acknowledgementState") == "ACKNOWLEDGEMENT_STATE_ACKNOWLEDGED",
        linked_purchase_token=data.get("linkedPurchaseToken", ""),
        obfuscated_account_id=(data.get("externalAccountIdentifiers") or {}).get("obfuscatedExternalAccountId", ""),
        raw=data,
    )


class GooglePlayClient:
    @staticmethod
    @lru_cache(maxsize=1)
    def _session():
        from google.auth.transport.requests import AuthorizedSession
        from google.oauth2 import service_account

        creds = service_account.Credentials.from_service_account_file(
            settings.GOOGLE_PLAY_SERVICE_ACCOUNT_FILE, scopes=[SCOPE]
        )
        return AuthorizedSession(creds)

    def get_subscription(self, purchase_token: str) -> PurchaseState:
        if not settings.GOOGLE_PLAY_SERVICE_ACCOUNT_FILE:
            raise VerificationError("Google Play verification is not configured.")
        url = f"{API}/{settings.GOOGLE_PLAY_PACKAGE_NAME}/purchases/subscriptionsv2/tokens/{purchase_token}"
        response = self._session().get(url, timeout=15)
        if response.status_code != 200:
            logger.warning("Play verification failed %s: %s", response.status_code, response.text[:300])
            raise VerificationError("Purchase could not be verified with Google Play.")
        return parse_subscription_v2(response.json())

    def acknowledge(self, product_id: str, purchase_token: str) -> None:
        url = (f"{API}/{settings.GOOGLE_PLAY_PACKAGE_NAME}/purchases/subscriptions/"
               f"{product_id}/tokens/{purchase_token}:acknowledge")
        response = self._session().post(url, json={}, timeout=15)
        if response.status_code not in (200, 204):
            logger.warning("Play acknowledge failed %s: %s", response.status_code, response.text[:300])


class FakeGooglePlayClient:
    """Development-only verifier: tokens look like ``fake:<product_id>:<org_id>``."""

    def get_subscription(self, purchase_token: str) -> PurchaseState:
        try:
            _, product_id, org_id = purchase_token.split(":", 2)
        except ValueError:
            raise VerificationError("Invalid fake token.")
        return PurchaseState(
            product_id=product_id, status=SubscriptionStatus.ACTIVE,
            expires_at=timezone.now() + timedelta(days=30), auto_renewing=True, acknowledged=False,
            linked_purchase_token="", obfuscated_account_id=org_id, raw={"fake": True},
        )

    def acknowledge(self, product_id: str, purchase_token: str) -> None:
        return None


def get_client():
    return FakeGooglePlayClient() if settings.BILLING_FAKE_VERIFIER else GooglePlayClient()
