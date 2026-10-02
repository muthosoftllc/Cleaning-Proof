from django.db import transaction
from django.utils import timezone
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.billing.entitlements import Entitlements
from apps.core.permissions import OrgRolePermission, resolve_membership

from .audit import record_event
from .models import AuditEvent, Invitation, Membership, Organization, Role
from .serializers import (
    AcceptInvitationSerializer,
    AuditEventSerializer,
    InvitationSerializer,
    MembershipSerializer,
    OrganizationSerializer,
)


class OrganizationViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """Organizations the caller belongs to. Creating one makes the caller owner."""

    serializer_class = OrganizationSerializer
    permission_classes = [IsAuthenticated]

    def _memberships(self):
        return Membership.objects.filter(
            user=self.request.user, is_active=True, organization__deleted_at__isnull=True
        )

    def get_queryset(self):
        return Organization.objects.filter(id__in=self._memberships().values("organization_id"))

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["roles_by_org"] = dict(self._memberships().values_list("organization_id", "role"))
        return context

    @transaction.atomic
    def perform_create(self, serializer):
        org = serializer.save()
        Membership.objects.create(organization=org, user=self.request.user, role=Role.OWNER)
        record_event(self.request, "organization.created", org, organization=org)

    def perform_update(self, serializer):
        membership = self._memberships().filter(organization=serializer.instance).first()
        if membership is None or not membership.is_manager:
            raise PermissionDenied("Only owners and admins can edit the organization.")
        org = serializer.save()
        record_event(self.request, "organization.updated", org, organization=org)

    def create(self, request, *args, **kwargs):
        response = super().create(request, *args, **kwargs)
        response.data["role"] = Role.OWNER
        return response


class MembershipViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.UpdateModelMixin, viewsets.GenericViewSet
):
    """Team members of the current organization."""

    serializer_class = MembershipSerializer
    permission_classes = [OrgRolePermission]
    read_roles = Role.MANAGERS | {Role.VIEWER}

    def get_queryset(self):
        membership = resolve_membership(self.request)
        return Membership.objects.filter(organization=membership.organization).select_related("user")

    def perform_update(self, serializer):
        caller = resolve_membership(self.request)
        target = serializer.instance
        new_role = serializer.validated_data.get("role", target.role)
        deactivating = serializer.validated_data.get("is_active", True) is False
        touches_owner = target.role == Role.OWNER or new_role == Role.OWNER
        if touches_owner and caller.role != Role.OWNER:
            raise PermissionDenied("Only owners can change owner memberships.")
        if target.role == Role.OWNER and (new_role != Role.OWNER or deactivating):
            others = Membership.objects.filter(
                organization=target.organization, role=Role.OWNER, is_active=True
            ).exclude(pk=target.pk)
            if not others.exists():
                raise ValidationError("An organization must keep at least one owner.")
        instance = serializer.save()
        record_event(
            self.request, "membership.updated", instance, organization=caller.organization,
            role=instance.role, is_active=instance.is_active,
        )


class InvitationViewSet(
    mixins.ListModelMixin, mixins.CreateModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    """Invite cleaners/admins by email. The token is delivered out of band
    (email/SMS/share sheet) and accepted from the app."""

    serializer_class = InvitationSerializer
    permission_classes = [OrgRolePermission]
    read_roles = Role.MANAGERS
    write_roles = Role.MANAGERS
    action_roles = {"accept": Role.ALL}

    def get_permissions(self):
        if self.action == "accept":
            return [IsAuthenticated()]
        return super().get_permissions()

    def get_queryset(self):
        return Invitation.objects.filter(organization=resolve_membership(self.request).organization)

    def get_serializer_context(self):
        context = super().get_serializer_context()
        if self.action != "accept":
            context["membership"] = resolve_membership(self.request)
        return context

    def perform_create(self, serializer):
        org = resolve_membership(self.request).organization
        if serializer.validated_data.get("role") != Role.VIEWER:
            Entitlements.for_org(org).check_can_add_member()
        invitation = serializer.save(organization=org, invited_by=self.request.user)
        record_event(self.request, "invitation.created", invitation, organization=org, email=invitation.email)

    @action(detail=True, methods=["post"])
    def revoke(self, request, pk=None):
        invitation = self.get_object()
        invitation.revoked_at = timezone.now()
        invitation.save(update_fields=["revoked_at", "updated_at"])
        return Response(InvitationSerializer(invitation, context=self.get_serializer_context()).data)

    @action(detail=False, methods=["post"])
    @transaction.atomic
    def accept(self, request):
        serializer = AcceptInvitationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            invitation = Invitation.objects.select_for_update().get(token=serializer.validated_data["token"])
        except Invitation.DoesNotExist:
            raise ValidationError({"token": "Invalid invitation."})
        if not invitation.is_pending:
            raise ValidationError({"token": "This invitation is no longer valid."})
        if invitation.email != request.user.email:
            raise PermissionDenied("This invitation was sent to a different email address.")
        membership, _ = Membership.objects.update_or_create(
            organization=invitation.organization,
            user=request.user,
            defaults={"role": invitation.role, "is_active": True},
        )
        invitation.accepted_at = timezone.now()
        invitation.save(update_fields=["accepted_at", "updated_at"])
        record_event(request, "invitation.accepted", invitation, organization=invitation.organization)
        return Response(
            {"organization": str(invitation.organization_id), "role": membership.role},
            status=status.HTTP_200_OK,
        )


class AuditEventViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = AuditEventSerializer
    permission_classes = [OrgRolePermission]
    read_roles = Role.MANAGERS

    def get_queryset(self):
        org = resolve_membership(self.request).organization
        return AuditEvent.objects.filter(organization=org).select_related("actor")
