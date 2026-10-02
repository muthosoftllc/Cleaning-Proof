from .models import AuditEvent


def _client_ip(request):
    if request is None:
        return None
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return forwarded.split(",")[0].strip() or None
    return request.META.get("REMOTE_ADDR")


def record_event(request, action, target=None, organization=None, **metadata):
    user = getattr(request, "user", None)
    return AuditEvent.objects.create(
        organization=organization,
        actor=user if user is not None and user.is_authenticated else None,
        action=action,
        target_type=type(target).__name__ if target is not None else "",
        target_id=str(getattr(target, "pk", "")) if target is not None else "",
        metadata=metadata,
        ip_address=_client_ip(request),
    )
