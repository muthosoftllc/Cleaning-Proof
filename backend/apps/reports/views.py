import base64
import binascii
import io

from django.core.files.base import ContentFile
from django.db.models import F
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from PIL import Image
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from apps.billing.entitlements import Entitlements
from apps.core.permissions import OrgRolePermission, resolve_membership
from apps.core.ratelimit import client_ip, ratelimit
from apps.core.signed_urls import file_url
from apps.core.ids import generate_share_token
from apps.jobs.models import Signature
from apps.notifications.services import NotificationKind, notify_managers
from apps.organizations.audit import record_event
from apps.organizations.models import Role

from .models import CustomerFeedback, Report, ReportStatus
from .serializers import FinalizeSerializer, ReportSerializer
from .services import finalize_report_if_ready, generate_pdf


# --------------------------------------------------------------------------
# Authenticated API (business owner / staff)
# --------------------------------------------------------------------------
class ReportViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = ReportSerializer
    permission_classes = [OrgRolePermission]
    write_roles = Role.MANAGERS

    def get_queryset(self):
        membership = resolve_membership(self.request)
        qs = Report.objects.filter(organization=membership.organization).select_related("job").prefetch_related("feedback")
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
        record_event(request, "report.finalized", report, organization=report.organization,
                     forced=serializer.validated_data["force"])
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


# --------------------------------------------------------------------------
# Public pages (customer, no account needed)
# --------------------------------------------------------------------------
def _public_report(token) -> Report:
    report = (
        Report.objects.select_related("organization", "job")
        .filter(share_token=token, organization__deleted_at__isnull=True)
        .first()
    )
    if report is None or report.status == ReportStatus.REVOKED:
        raise Http404
    return report


def _photo_groups(report, request):
    photos = report.snapshot.get("photos", [])
    for photo in photos:
        photo["thumb_url"] = file_url("photo_thumb", photo["id"], request)
    groups = {"before": [], "after": [], "other": []}
    for photo in photos:
        groups.get(photo["kind"], groups["other"]).append(photo)
    return groups


@ratelimit("report_view", limit=120, period=60)
def public_report(request, token):
    report = _public_report(token)
    Report.objects.filter(pk=report.pk).update(view_count=F("view_count") + 1, last_viewed_at=timezone.now())
    snapshot = report.snapshot
    issue_photos = {}
    for photo in snapshot.get("photos", []):
        if photo.get("issue_id"):
            issue_photos.setdefault(photo["issue_id"], []).append(photo)
    groups = _photo_groups(report, request)
    for issue in snapshot.get("issues", []):
        issue["photos"] = issue_photos.get(issue["id"], [])
    org = report.organization
    return render(request, "reports/public_report.html", {
        "report": report,
        "s": snapshot,
        "photo_groups": groups,
        "logo_url": file_url("org_logo", org.id, request) if org.logo else None,
        "brand": snapshot["company"].get("brand_color") or "#0F766E",
        "pdf_available": bool(report.pdf) and Entitlements.for_org(org).has("pdf_reports"),
        "submitted": request.GET.get("submitted"),
    })


@ratelimit("report_pdf", limit=30, period=60)
def public_report_pdf(request, token):
    report = _public_report(token)
    if not report.pdf:
        raise Http404
    return redirect(file_url("report_pdf", report.id, request))


def _decode_signature(data_url: str) -> ContentFile | None:
    if not data_url.startswith("data:image/png;base64,"):
        return None
    try:
        raw = base64.b64decode(data_url.split(",", 1)[1], validate=True)
    except (binascii.Error, ValueError):
        return None
    if len(raw) > 300_000:
        return None
    try:
        with Image.open(io.BytesIO(raw)) as img:
            img.verify()
    except Exception:
        return None
    return ContentFile(raw)


@require_http_methods(["POST"])
@ratelimit("report_action", limit=20, period=3600, methods=("POST",))
def public_report_approve(request, token):
    report = _public_report(token)
    name = (request.POST.get("name") or "").strip()[:150]
    if not name:
        return redirect(f"/report/{token}/?submitted=missing-name")
    if report.approved_at is None:
        image = _decode_signature(request.POST.get("signature", ""))
        signature = Signature(
            job=report.job, signer_name=name, source=Signature.Source.REMOTE,
            signed_at=timezone.now(), ip_address=client_ip(request) if client_ip(request) != "unknown" else None,
        )
        if image is not None:
            signature.image.save("signature.png", image, save=False)
        signature.save()
        report.approved_at = timezone.now()
        report.approved_by_name = name
        report.save(update_fields=["approved_at", "approved_by_name", "updated_at"])
        record_event(request, "report.customer_approved", report, organization=report.organization)
        notify_managers(
            report.organization, NotificationKind.CUSTOMER_APPROVED,
            title="Customer approved the cleaning", body=f"{report.number} approved by {name}",
            data={"report_id": str(report.id), "job_id": str(report.job_id)},
        )
    return redirect(f"/report/{token}/?submitted=approved")


@require_http_methods(["POST"])
@ratelimit("report_action", limit=20, period=3600, methods=("POST",))
def public_report_feedback(request, token):
    report = _public_report(token)
    message = (request.POST.get("message") or "").strip()[:2000]
    if not message:
        return redirect(f"/report/{token}/?submitted=missing-message")
    ip = client_ip(request)
    CustomerFeedback.objects.create(
        organization=report.organization, report=report, kind=CustomerFeedback.Kind.ISSUE,
        name=(request.POST.get("name") or "").strip()[:150], message=message,
        ip_address=None if ip == "unknown" else ip,
    )
    notify_managers(
        report.organization, NotificationKind.CUSTOMER_ISSUE,
        title="Customer reported an issue", body=f"{report.number}: {message[:120]}",
        data={"report_id": str(report.id), "job_id": str(report.job_id)},
    )
    return redirect(f"/report/{token}/?submitted=feedback")


def _verification_payload(report: Report | None) -> dict:
    if report is None:
        return {"exists": False}
    snap = report.snapshot
    return {
        "exists": True,
        "number": report.number,
        "status": report.status,
        "valid": report.status == ReportStatus.FINAL,
        "revision": report.revision,
        "company": snap.get("company", {}).get("name"),
        # Property name + city only; no street address, no customer details.
        "property": snap.get("property", {}).get("name"),
        "city": snap.get("property", {}).get("city"),
        "completed_at": snap.get("job", {}).get("completed_at"),
        "finalized_at": report.finalized_at.isoformat() if report.finalized_at else None,
        "content_hash": report.content_hash,
    }


@ratelimit("verify", limit=60, period=60)
def verify_report(request, number):
    report = Report.objects.filter(number=number.upper(), organization__deleted_at__isnull=True).first()
    payload = _verification_payload(report)
    if request.GET.get("format") == "json" or "application/json" in request.headers.get("Accept", ""):
        return JsonResponse(payload, status=200 if payload["exists"] else 404)
    return render(request, "reports/verify.html", {"v": payload, "number": number.upper()},
                  status=200 if payload["exists"] else 404)
