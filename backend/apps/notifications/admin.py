from django.contrib import admin

from .models import Device, Notification


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ["created_at", "user", "kind", "title", "read_at", "pushed_at"]
    list_filter = ["kind"]


@admin.register(Device)
class DeviceAdmin(admin.ModelAdmin):
    list_display = ["user", "platform", "app_version", "last_seen_at"]
