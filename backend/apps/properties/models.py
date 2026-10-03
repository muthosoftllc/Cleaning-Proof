from django.conf import settings
from django.db import models

from apps.core.models import OrgScopedModel


class Customer(OrgScopedModel):
    """The person/business the cleaning is done for. Keep this minimal:
    only what's needed to deliver reports."""

    name = models.CharField(max_length=150)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=40, blank=True)
    notes = models.TextField(blank=True)

    class Meta(OrgScopedModel.Meta):
        ordering = ["name"]

    def __str__(self):
        return self.name


class Property(OrgScopedModel):
    customer = models.ForeignKey(Customer, on_delete=models.SET_NULL, null=True, blank=True, related_name="properties")
    name = models.CharField(max_length=150, help_text="e.g. 'Apartment #204'")
    address_line1 = models.CharField(max_length=200, blank=True)
    address_line2 = models.CharField(max_length=200, blank=True)
    city = models.CharField(max_length=100, blank=True)
    region = models.CharField(max_length=100, blank=True)
    postal_code = models.CharField(max_length=20, blank=True)
    country = models.CharField(max_length=2, blank=True, help_text="ISO 3166-1 alpha-2")
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    cleaning_instructions = models.TextField(blank=True)
    # Door codes, lockbox, alarm. Visible to assigned staff only; never on reports.
    access_notes = models.TextField(blank=True)
    default_checklist = models.ForeignKey(
        "checklists.ChecklistTemplate", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    assigned_cleaners = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, related_name="assigned_properties")
    is_active = models.BooleanField(default=True)

    class Meta(OrgScopedModel.Meta):
        ordering = ["name"]
        verbose_name_plural = "properties"

    def __str__(self):
        return self.name

    @property
    def short_address(self) -> str:
        return ", ".join(p for p in [self.address_line1, self.city] if p)
