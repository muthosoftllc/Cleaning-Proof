from django.db import transaction
from django.utils import timezone

from .fcm import send_push
from .models import Device, Notification, NotificationKind

__all__ = ["NotificationKind", "notify", "notify_managers"]


def _push(notification_id):
    notification = Notification.objects.select_related("user").get(pk=notification_id)
    data = {**notification.data, "kind": notification.kind, "notification_id": str(notification.id)}
    delivered = False
    for device in Device.objects.filter(user=notification.user):
        result = send_push(device.token, notification.title, notification.body, data)
        if result is False:
            device.delete()
        delivered = delivered or bool(result)
    if delivered:
        Notification.objects.filter(pk=notification_id).update(pushed_at=timezone.now())


def notify(user, kind, *, title, body="", organization=None, data=None):
    if user is None or not user.is_active:
        return None
    notification = Notification.objects.create(
        user=user, kind=kind, title=title, body=body[:500], organization=organization, data=data or {}
    )
    # Push after commit so a rolled-back transaction never sends a push.
    # TODO: move to a Celery task once push volume warrants a worker.
    transaction.on_commit(lambda: _push(notification.id))
    return notification


def notify_managers(organization, kind, *, title, body="", data=None, exclude=None):
    from apps.organizations.models import Membership, Role

    memberships = Membership.objects.filter(
        organization=organization, role__in=Role.MANAGERS, is_active=True
    ).select_related("user")
    for membership in memberships:
        if exclude is not None and membership.user_id == exclude.id:
            continue
        notify(membership.user, kind, title=title, body=body, organization=organization, data=data)
