"""Notifications: always persisted (in-app inbox), pushed best-effort.

Pushes run after commit on the background pool, so a slow FCM round-trip
never delays the request that triggered it, and a rolled-back transaction
never sends a push.
"""

from django.utils import timezone

from apps.core.tasks import run_after_commit

from .fcm import send_push
from .models import Device, Notification, NotificationKind

__all__ = ["NotificationKind", "notify", "notify_managers"]


def deliver_push(notification_id) -> None:
    notification = Notification.objects.select_related("user").filter(pk=notification_id).first()
    if notification is None or notification.pushed_at is not None:
        return
    data = {**notification.data, "kind": notification.kind, "notification_id": str(notification.id)}
    delivered = False
    for device in Device.objects.filter(user_id=notification.user_id):
        result = send_push(device.token, notification.title, notification.body, data)
        if result is False:
            device.delete()  # token revoked/uninstalled
        delivered = delivered or bool(result)
    if delivered:
        Notification.objects.filter(pk=notification_id).update(pushed_at=timezone.now())


def notify(user, kind, *, title, body="", organization=None, data=None):
    if user is None or not user.is_active:
        return None
    notification = Notification.objects.create(
        user=user, kind=kind, title=title[:150], body=body[:500], organization=organization, data=data or {}
    )
    run_after_commit(deliver_push, notification.id)
    return notification


def notify_managers(organization, kind, *, title, body="", data=None, exclude=None):
    from apps.organizations.models import MANAGER_ROLES, Membership

    managers = Membership.objects.filter(
        organization=organization, role__in=MANAGER_ROLES, is_active=True
    ).select_related("user")
    if exclude is not None:
        managers = managers.exclude(user_id=exclude.id)
    for membership in managers:
        notify(membership.user, kind, title=title, body=body, organization=organization, data=data)
