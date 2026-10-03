from django.db.models import Q
from rest_framework.decorators import action

from apps.billing.entitlements import Entitlements
from apps.core.viewsets import OrgScopedViewSet
from apps.organizations.models import READER_ROLES

from .models import Customer, Property
from .serializers import CustomerSerializer, PropertySerializer


class CustomerViewSet(OrgScopedViewSet):
    queryset = Customer.objects.all()
    serializer_class = CustomerSerializer
    read_roles = READER_ROLES
    audit_prefix = "customer"


class PropertyViewSet(OrgScopedViewSet):
    queryset = Property.objects.select_related("customer").prefetch_related("assigned_cleaners")
    serializer_class = PropertySerializer
    audit_prefix = "property"

    def scope_for_cleaner(self, qs):
        user = self.request.user
        return qs.filter(Q(assigned_cleaners=user) | Q(jobs__assigned_to=user)).distinct()

    def perform_create(self, serializer):
        if serializer.validated_data.get("is_active", True):
            Entitlements.for_org(self.organization).check_can_add_property()
        super().perform_create(serializer)

    def perform_update(self, serializer):
        if serializer.validated_data.get("is_active") and not serializer.instance.is_active:
            Entitlements.for_org(self.organization).check_can_add_property()
        super().perform_update(serializer)

    @action(detail=True, methods=["get"])
    def history(self, request, pk=None):
        """Cleaning history: past jobs with their report status."""
        from apps.jobs.serializers import JobSummarySerializer

        prop = self.get_object()
        jobs = prop.jobs.select_related("assigned_to", "report").order_by("-scheduled_start")
        if self.membership.is_cleaner:
            jobs = jobs.filter(assigned_to=request.user)
        page = self.paginate_queryset(jobs)
        data = JobSummarySerializer(page, many=True, context=self.get_serializer_context()).data
        return self.get_paginated_response(data)
