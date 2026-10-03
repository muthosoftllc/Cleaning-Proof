"""Request helpers shared by API views, public pages and the audit log."""

import uuid

from django.conf import settings
from rest_framework.exceptions import ValidationError


def client_ip(request) -> str | None:
    """The caller's IP address, honouring only *trusted* proxies.

    ``X-Forwarded-For`` is client-controlled. We only read it when
    ``TRUSTED_PROXY_COUNT`` proxies (e.g. 1 for Nginx, 2 for CDN + Nginx) sit in
    front of the app, and then take the entry those proxies appended. Trusting
    the left-most entry would let anyone dodge rate limits or forge audit IPs.
    """
    hops = settings.TRUSTED_PROXY_COUNT
    if hops > 0:
        forwarded = [p.strip() for p in request.META.get("HTTP_X_FORWARDED_FOR", "").split(",") if p.strip()]
        if len(forwarded) >= hops:
            return forwarded[-hops]
    return request.META.get("REMOTE_ADDR") or None


def uuid_param(request, name: str) -> uuid.UUID | None:
    """Parse an optional UUID query parameter, answering 400 (not 500) on garbage."""
    raw = request.query_params.get(name)
    if not raw:
        return None
    try:
        return uuid.UUID(raw)
    except ValueError:
        raise ValidationError({name: "Must be a valid UUID."}) from None
