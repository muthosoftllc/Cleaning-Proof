from django.contrib import admin

from .models import Customer, Property


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ["name", "organization", "email"]
    search_fields = ["name", "email"]


@admin.register(Property)
class PropertyAdmin(admin.ModelAdmin):
    list_display = ["name", "organization", "customer", "city", "is_active"]
    search_fields = ["name", "address_line1"]
    filter_horizontal = ["assigned_cleaners"]
