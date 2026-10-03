from apps.core.http import client_ip

from .models import AuditEvent


def record_event(request, action, target=None, organization=None, **metadata):
    """Append an audit entry. ``metadata`` must never contain secrets or PII
    beyond what the action inherently concerns."""
    user = getattr(request, "user", None)
    return AuditEvent.objects.create(
        organization=organization,
        actor=user if user is not None and user.is_authenticated else None,
        action=action,
        target_type=type(target).__name__ if target is not None else "",
        target_id=str(getattr(target, "pk", "")) if target is not None else "",
        metadata=metadata,
        ip_address=client_ip(request) if request is not None else None,
    )
