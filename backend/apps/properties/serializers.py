from django.contrib.auth import get_user_model
from rest_framework import serializers

from apps.checklists.models import ChecklistTemplate
from apps.core.serializers import OrgRelatedField

from .models import Customer, Property


class CustomerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Customer
        fields = ["id", "name", "email", "phone", "notes", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]


class OrgMemberField(serializers.PrimaryKeyRelatedField):
    """User field limited to active members of the caller's organization."""

    def get_queryset(self):
        org = self.context.get("organization")
        if org is None:
            return get_user_model().objects.none()
        return get_user_model().objects.filter(
            memberships__organization=org, memberships__is_active=True
        )


class PropertySerializer(serializers.ModelSerializer):
    customer = OrgRelatedField(queryset=Customer.objects.all(), allow_null=True, required=False)
    default_checklist = OrgRelatedField(
        queryset=ChecklistTemplate.objects.all(), allow_null=True, required=False
    )
    assigned_cleaners = OrgMemberField(many=True, required=False)
    customer_name = serializers.CharField(source="customer.name", read_only=True, default=None)

    class Meta:
        model = Property
        fields = [
            "id", "customer", "customer_name", "name", "address_line1", "address_line2", "city",
            "region", "postal_code", "country", "latitude", "longitude", "cleaning_instructions",
            "access_notes", "default_checklist", "assigned_cleaners", "is_active",
            "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]
