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
            {"product_id": pid, "plan": code, "plan_name": PLANS[code].name}
            for pid, code in PRODUCT_PLANS.items()
        ]
        return Response(data)


class VerifyPurchaseSerializer(serializers.Serializer):
    product_id = serializers.CharField(max_length=100)
    purchase_token = serializers.CharField(max_length=512)


class GooglePlayVerifyView(APIView):
    """Called by the app right after a successful Play purchase."""

    permission_classes = [OrgRolePermission]
    write_roles = {Role.OWNER}

    def post(self, request):
        serializer = VerifyPurchaseSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        org = resolve_membership(request).organization
        subscription = sync_purchase(
            serializer.validated_data["purchase_token"], organization=org, user=request.user,
            expected_product=serializer.validated_data["product_id"],
        )
        record_event(request, "billing.purchase_verified", subscription, organization=org,
                     plan=subscription.plan, status=subscription.status)
        return Response(Entitlements.for_org(org).as_dict())


class GooglePlayRTDNView(APIView):
    """Real-time developer notifications via a Cloud Pub/Sub push subscription.

    Configure the push endpoint as ``/api/v1/billing/google-play/rtdn/?token=<GOOGLE_PLAY_RTDN_TOKEN>``.
    The notification itself is not trusted: we only use it as a hint to
    re-verify the token with Google.
    """

    permission_classes = [AllowAny]
    authentication_classes: list = []
    throttle_classes: list = []

    def post(self, request):
        expected = settings.GOOGLE_PLAY_RTDN_TOKEN
        if not expected or not constant_time_compare(request.query_params.get("token", ""), expected):
            return Response(status=status.HTTP_403_FORBIDDEN)
        try:
            payload = json.loads(base64.b64decode(request.data["message"]["data"]))
        except (KeyError, TypeError, ValueError, binascii.Error):
            return Response(status=status.HTTP_204_NO_CONTENT)  # ack malformed messages
        notification = payload.get("subscriptionNotification")
        if notification and notification.get("purchaseToken"):
            try:
                sync_purchase(notification["purchaseToken"])
            except Exception:
                logger.exception("RTDN processing failed")
                # Non-2xx makes Pub/Sub retry later.
                return Response(status=status.HTTP_503_SERVICE_UNAVAILABLE)
        return Response(status=status.HTTP_204_NO_CONTENT)
