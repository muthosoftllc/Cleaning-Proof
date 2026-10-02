from django.contrib import admin

from .models import CustomerFeedback, Report


@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    list_display = ["number", "organization", "status", "revision", "finalized_at", "approved_at", "view_count"]
    list_filter = ["status"]
    search_fields = ["number"]
    readonly_fields = ["snapshot", "content_hash"]
    exclude = ["share_token"]


@admin.register(CustomerFeedback)
class CustomerFeedbackAdmin(admin.ModelAdmin):
    list_display = ["created_at", "report", "kind", "name", "resolved_at"]
