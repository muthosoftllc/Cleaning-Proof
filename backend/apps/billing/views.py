import base64
import binascii
import json
import logging

from django.conf import settings
from django.utils.crypto import constant_time_compare
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import OrgRolePermission, resolve_membership
from apps.organizations.audit import record_event
from apps.organizations.models import Role

from .entitlements import Entitlements
from .plans import PLANS, PRODUCT_PLANS
from .services import sync_purchase

logger = logging.getLogger(__name__)


class BillingStatusView(APIView):
    permission_classes = [OrgRolePermission]

    def get(self, request):
        org = resolve_membership(request).organization
        data = Entitlements.for_org(org).as_dict()
        data["products"] = [
            {"product_id": pid, "plan": code, "plan_name": PLANS[code].name} for pid, code in PRODUCT_PLANS.items()
        ]
        return Response(data)


class VerifyPurchaseSerializer(serializers.Serializer):
    product_id = serializers.ChoiceField(choices=sorted(PRODUCT_PLANS))
    # Play tokens are opaque but URL-safe; anything else is rejected up front.
    purchase_token = serializers.RegexField(r"^[A-Za-z0-9._:\-]{8,512}$")


class GooglePlayVerifyView(APIView):
    """Called by the app right after a successful Play purchase."""

    permission_classes = [OrgRolePermission]
    write_roles = {Role.OWNER}

    def post(self, request):
        serializer = VerifyPurchaseSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        org = resolve_membership(request).organization
        subscription = sync_purchase(
            serializer.validated_data["purchase_token"],
            organization=org,
            user=request.user,
            expected_product=serializer.validated_data["product_id"],
        )
        record_event(
            request,
            "billing.purchase_verified",
            subscription,
            organization=org,
            plan=subscription.plan,
            status=subscription.status,
        )
        return Response(Entitlements.for_org(org).as_dict())


def _rtdn_authenticated(request) -> bool:
    """Authenticate a Pub/Sub push.

    Preferred: the OIDC token Pub/Sub attaches when the push subscription has
    authentication enabled (signed by Google, audience + service account
    checked). Fallback: a shared secret in the push URL.
    """
    audience = settings.GOOGLE_PLAY_RTDN_AUDIENCE
    if audience:
        header = request.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            return False
        try:
            from google.auth.transport import requests as google_requests
            from google.oauth2 import id_token

            claims = id_token.verify_oauth2_token(header[7:], google_requests.Request(), audience=audience)
        except ValueError:
            return False
        expected = settings.GOOGLE_PLAY_RTDN_SERVICE_ACCOUNT
        return bool(claims.get("email_verified")) and (not expected or claims.get("email") == expected)
    secret = settings.GOOGLE_PLAY_RTDN_TOKEN
    return bool(secret) and constant_time_compare(request.query_params.get("token", ""), secret)


class GooglePlayRTDNView(APIView):
    """Real-time developer notifications via a Cloud Pub/Sub push subscription.

    The notification itself is never trusted: it is only a hint to re-verify
    the purchase token with Google.
    """

    permission_classes = [AllowAny]
    authentication_classes: list = []
    throttle_classes: list = []

    def post(self, request):
        if not _rtdn_authenticated(request):
            return Response(status=status.HTTP_403_FORBIDDEN)
        try:
            payload = json.loads(base64.b64decode(request.data["message"]["data"]))
        except (KeyError, TypeError, ValueError, binascii.Error):
            return Response(status=status.HTTP_204_NO_CONTENT)  # ack malformed messages
        notification = payload.get("subscriptionNotification") if isinstance(payload, dict) else None
        if notification and notification.get("purchaseToken"):
            try:
                sync_purchase(notification["purchaseToken"])
            except Exception:
                logger.exception("RTDN processing failed")
                # Non-2xx makes Pub/Sub retry later.
                return Response(status=status.HTTP_503_SERVICE_UNAVAILABLE)
        return Response(status=status.HTTP_204_NO_CONTENT)
