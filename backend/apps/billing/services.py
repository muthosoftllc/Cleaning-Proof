import uuid

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.organizations.models import Organization

from .google_play import VerificationError, get_client
from .models import Subscription, SubscriptionStatus
from .plans import PRODUCT_PLANS


@transaction.atomic
def sync_purchase(purchase_token: str, organization=None, user=None, expected_product: str | None = None):
    """Verify a token with Google and upsert the Subscription.

    ``organization`` is given when the app reports a purchase; for RTDN it is
    looked up from the stored token or the obfuscated account id that the app
    set to the organization id at purchase time.
    """
    client = get_client()
    try:
        state = client.get_subscription(purchase_token)
    except VerificationError as exc:
        raise ValidationError({"purchase_token": str(exc)})

    if expected_product and state.product_id != expected_product:
        raise ValidationError({"product_id": "Product does not match the purchase."})
    plan = PRODUCT_PLANS.get(state.product_id)
    if plan is None:
        raise ValidationError({"product_id": "Unknown product."})

    existing = Subscription.objects.select_for_update().filter(purchase_token=purchase_token).first()
    if organization is None:
        if existing is not None:
            organization = existing.organization
        else:
            organization = _org_from_account_id(state.obfuscated_account_id)
            if organization is None:
                raise ValidationError("Cannot match purchase to an organization.")
    if state.obfuscated_account_id and state.obfuscated_account_id != str(organization.id):
        raise ValidationError("This purchase belongs to a different organization.")
    if existing is not None and existing.organization_id != organization.id:
        raise ValidationError("This purchase is already linked to another organization.")

    # Upgrades/downgrades issue a new token; retire the one it replaces.
    if state.linked_purchase_token:
        Subscription.objects.filter(
            purchase_token=state.linked_purchase_token, organization=organization
        ).update(status=SubscriptionStatus.EXPIRED, updated_at=timezone.now())

    subscription, _ = Subscription.objects.update_or_create(
        purchase_token=purchase_token,
        defaults={
            "organization": organization,
            "plan": plan,
            "product_id": state.product_id,
            "linked_purchase_token": state.linked_purchase_token,
            "status": state.status,
            "expires_at": state.expires_at,
            "auto_renewing": state.auto_renewing,
            "raw": state.raw,
            "last_verified_at": timezone.now(),
            **({"purchased_by": user} if user else {}),
        },
    )
    if not state.acknowledged and state.status == SubscriptionStatus.ACTIVE:
        client.acknowledge(state.product_id, purchase_token)
        subscription.acknowledged = True
        subscription.save(update_fields=["acknowledged", "updated_at"])
    return subscription


def _org_from_account_id(account_id: str):
    try:
        return Organization.objects.filter(pk=uuid.UUID(account_id)).first()
    except (ValueError, TypeError):
        return None
