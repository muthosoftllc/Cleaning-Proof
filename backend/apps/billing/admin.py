from django.contrib import admin

from .models import Subscription


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ["organization", "plan", "status", "expires_at", "auto_renewing", "last_verified_at"]
    list_filter = ["plan", "status"]
    exclude = ["purchase_token", "linked_purchase_token"]
