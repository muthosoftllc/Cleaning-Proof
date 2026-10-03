"""Authenticated report API for owners and staff."""

from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from apps.billing.entitlements import Entitlements
from apps.core.ids import generate_share_token
from apps.core.permissions import OrgRolePermission, resolve_membership
from apps.organizations.audit import record_event
from apps.organizations.models import MANAGER_ROLES

from .models import Report, ReportStatus
from .serializers import FinalizeSerializer, ReportSerializer
from .services import finalize_report_if_ready, generate_pdf


class ReportViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = ReportSerializer
    permission_classes = [OrgRolePermission]
    write_roles = MANAGER_ROLES

    def get_queryset(self):
        membership = resolve_membership(self.request)
        qs = (
            Report.objects.filter(organization=membership.organization)
            .select_related("job")
            .prefetch_related("feedback")
        )
        if membership.is_cleaner:
            qs = qs.filter(job__assigned_to=self.request.user)
        return qs

    @action(detail=True, methods=["post"])
    def finalize(self, request, pk=None):
        """Finalize now, even if some declared photos never arrived."""
        report = self.get_object()
        serializer = FinalizeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        report = finalize_report_if_ready(report.job, force=serializer.validated_data["force"])
        record_event(
            request,
            "report.finalized",
            report,
            organization=report.organization,
            forced=serializer.validated_data["force"],
        )
        return Response(self.get_serializer(report).data)

    @action(detail=True, methods=["post"], url_path="rotate-link")
    def rotate_link(self, request, pk=None):
        """Invalidate the current customer link and issue a new one."""
        report = self.get_object()
        report.share_token = generate_share_token()
        report.save(update_fields=["share_token", "updated_at"])
        record_event(request, "report.link_rotated", report, organization=report.organization)
        return Response(self.get_serializer(report).data)

    @action(detail=True, methods=["post"])
    def revoke(self, request, pk=None):
        report = self.get_object()
        report.status = ReportStatus.REVOKED
        report.save(update_fields=["status", "updated_at"])
        record_event(request, "report.revoked", report, organization=report.organization)
        return Response(self.get_serializer(report).data)

    @action(detail=True, methods=["post"])
    def pdf(self, request, pk=None):
        report = self.get_object()
        Entitlements.for_org(report.organization).require("pdf_reports")
        if report.status != ReportStatus.FINAL:
            raise ValidationError("The report isn't final yet.")
        report = generate_pdf(report.pk)
        return Response(self.get_serializer(report).data)
