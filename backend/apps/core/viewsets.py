from rest_framework import viewsets

from apps.organizations.audit import record_event

from .permissions import OrgRolePermission, resolve_membership


class OrgScopedViewSet(viewsets.ModelViewSet):
    """Base viewset enforcing organization-level data isolation.

    * Every query is filtered to the caller's organization.
    * New objects are always created inside the caller's organization.
    * Subclasses may narrow further for cleaners via ``scope_for_cleaner``.
    """

    permission_classes = [OrgRolePermission]
    audit_prefix: str | None = None

    @property
    def membership(self):
        return resolve_membership(self.request)

    @property
    def organization(self):
        return self.membership.organization

    def get_queryset(self):
        qs = super().get_queryset().filter(organization=self.organization)
        if self.membership.is_cleaner:
            qs = self.scope_for_cleaner(qs)
        return qs

    def scope_for_cleaner(self, qs):
        return qs

    def get_serializer_context(self):
        context = super().get_serializer_context()
        if self.request and self.request.user.is_authenticated:
            context["organization"] = self.organization
            context["membership"] = self.membership
        return context

    def perform_create(self, serializer):
        instance = serializer.save(organization=self.organization)
        self._audit("created", instance)

    def perform_update(self, serializer):
        instance = serializer.save()
        self._audit("updated", instance)

    def perform_destroy(self, instance):
        self._audit("deleted", instance)
        instance.delete()

    def _audit(self, verb, instance):
        if self.audit_prefix:
            record_event(self.request, f"{self.audit_prefix}.{verb}", instance, organization=self.organization)
