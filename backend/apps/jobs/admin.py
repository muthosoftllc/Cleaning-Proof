from django.contrib import admin

from .models import Issue, Job, JobTask, Photo, RecurringSchedule, Signature


class JobTaskInline(admin.TabularInline):
    model = JobTask
    extra = 0
    fields = ["section_name", "title", "status", "completed_at"]


@admin.register(Job)
class JobAdmin(admin.ModelAdmin):
    list_display = ["__str__", "organization", "assigned_to", "scheduled_start", "status"]
    list_filter = ["status"]
    raw_id_fields = ["property", "assigned_to", "checklist_template", "recurring_schedule"]
    inlines = [JobTaskInline]


@admin.register(Photo)
class PhotoAdmin(admin.ModelAdmin):
    list_display = ["id", "job", "kind", "captured_at", "size_bytes"]
    raw_id_fields = ["job", "job_task", "issue"]


@admin.register(Issue)
class IssueAdmin(admin.ModelAdmin):
    list_display = ["description", "job", "severity", "phase", "resolution"]
    raw_id_fields = ["job"]


admin.site.register(Signature)
admin.site.register(RecurringSchedule)
