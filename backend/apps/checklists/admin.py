from django.contrib import admin

from .models import ChecklistSection, ChecklistTask, ChecklistTemplate


class SectionInline(admin.TabularInline):
    model = ChecklistSection
    extra = 0


@admin.register(ChecklistTemplate)
class ChecklistTemplateAdmin(admin.ModelAdmin):
    list_display = ["name", "organization", "property", "is_archived"]
    inlines = [SectionInline]


@admin.register(ChecklistTask)
class ChecklistTaskAdmin(admin.ModelAdmin):
    list_display = ["title", "section", "is_required", "requires_photo", "position"]
