from django.db.models import Q
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.core.http import uuid_param
from apps.core.viewsets import OrgScopedViewSet

from .defaults import create_default_templates
from .models import ChecklistTemplate
from .serializers import ChecklistTemplateSerializer, DuplicateTemplateSerializer


class ChecklistTemplateViewSet(OrgScopedViewSet):
    queryset = ChecklistTemplate.objects.prefetch_related("sections__tasks")
    serializer_class = ChecklistTemplateSerializer
    audit_prefix = "checklist"

    def get_queryset(self):
        qs = super().get_queryset()
        if self.request.query_params.get("include_archived") != "true":
            qs = qs.filter(is_archived=False)
        if property_id := uuid_param(self.request, "property"):
            # Generic templates plus the ones specific to this property.
            qs = qs.filter(Q(property__isnull=True) | Q(property_id=property_id))
        return qs

    @action(detail=True, methods=["post"])
    def duplicate(self, request, pk=None):
        template = self.get_object()
        serializer = DuplicateTemplateSerializer(data=request.data, context=self.get_serializer_context())
        serializer.is_valid(raise_exception=True)
        copy = template.duplicate(**serializer.validated_data)
        self._audit("duplicated", copy)
        return Response(self.get_serializer(copy).data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=["post"], url_path="install-defaults")
    def install_defaults(self, request):
        """Seed starter templates so a new business can run a job in minutes."""
        templates = create_default_templates(self.organization)
        return Response(self.get_serializer(templates, many=True).data, status=status.HTTP_201_CREATED)
