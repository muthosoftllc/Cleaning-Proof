"""Public, account-free pages: the customer report, sign-off and verification.

Everything here is reachable by anyone holding a link, so: rate limited,
minimal data, no raw storage URLs (only signed, expiring ones), and user
content rendered through Django's auto-escaping templates.
"""

import base64
import binascii
import io

from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import F
from django.http import Http404, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST, require_safe
from PIL import Image

from apps.billing.entitlements import Entitlements
from apps.core.http import client_ip
from apps.core.ratelimit import ratelimit
from apps.core.signed_urls import file_url
from apps.jobs.models import Signature
from apps.notifications.services import NotificationKind, notify_managers
from apps.organizations.audit import record_event
from apps.organizations.models import HEX_COLOR

from .models import CustomerFeedback, Report, ReportStatus

DEFAULT_BRAND = "#0F766E"
MAX_SIGNATURE_BYTES = 300_000
MAX_NAME = 150
MAX_MESSAGE = 2000


def _public_report(token: str) -> Report:
    report = (
        Report.objects.select_related("organization", "job")
        .filter(share_token=token, organization__deleted_at__isnull=True)
        .exclude(status=ReportStatus.REVOKED)
        .first()
    )
    if report is None:
        raise Http404
    return report


def _brand_color(snapshot: dict) -> str:
    """Only a strict #RRGGBB value ever reaches the page's CSS."""
    color = snapshot.get("company", {}).get("brand_color") or ""
    try:
        HEX_COLOR(color)
        return color
    except Exception:
        return DEFAULT_BRAND


def _report_page_context(report: Report, request) -> dict:
    """View model for the template, built without mutating the stored snapshot."""
    snapshot = report.snapshot
    photos = [{**p, "thumb_url": file_url("photo_thumb", p["id"], request)} for p in snapshot.get("photos", [])]
    groups = {"before": [], "after": [], "other": []}
    by_issue: dict[str, list] = {}
    for photo in photos:
        if photo.get("issue_id"):
            by_issue.setdefault(photo["issue_id"], []).append(photo)
        else:
            groups.get(photo["kind"], groups["other"]).append(photo)
    issues = [{**issue, "photos": by_issue.get(issue["id"], [])} for issue in snapshot.get("issues", [])]
    org = report.organization
    return {
        "report": report,
        "s": {**snapshot, "issues": issues},
        "photo_groups": groups,
        "logo_url": file_url("org_logo", org.id, request) if org.logo else None,
        "brand": _brand_color(snapshot),
        "pdf_available": bool(report.pdf) and Entitlements.for_org(org).has("pdf_reports"),
        "submitted": request.GET.get("submitted"),
    }


def _back_to_report(token: str, outcome: str):
    return redirect(f"{reverse('public-report', kwargs={'token': token})}?submitted={outcome}")


@require_safe
@ratelimit("report_view", limit=120, period=60)
def public_report(request, token):
    report = _public_report(token)
    if request.method == "GET":  # HEAD comes from link previewers, not readers
        Report.objects.filter(pk=report.pk).update(view_count=F("view_count") + 1, last_viewed_at=timezone.now())
    return render(request, "reports/public_report.html", _report_page_context(report, request))


@require_safe
@ratelimit("report_pdf", limit=30, period=60)
def public_report_pdf(request, token):
    report = _public_report(token)
    if not report.pdf:
        raise Http404
    return redirect(file_url("report_pdf", report.id, request))


def _decode_signature(data_url: str) -> ContentFile | None:
    """Accept only a small, valid PNG data URL from the signature canvas."""
    prefix = "data:image/png;base64,"
    if not data_url.startswith(prefix) or len(data_url) > MAX_SIGNATURE_BYTES * 4 // 3 + len(prefix) + 4:
        return None
    try:
        raw = base64.b64decode(data_url[len(prefix) :], validate=True)
        with Image.open(io.BytesIO(raw)) as img:
            if img.format != "PNG":
                return None
            img.verify()
    except (binascii.Error, ValueError, OSError, SyntaxError, Image.DecompressionBombError):
        return None
    return ContentFile(raw)


@require_POST
@ratelimit("report_action", limit=20, period=3600, methods=("POST",))
def public_report_approve(request, token):
    report = _public_report(token)
    name = (request.POST.get("name") or "").strip()[:MAX_NAME]
    if not name:
        return _back_to_report(token, "missing-name")
    image = _decode_signature(request.POST.get("signature", ""))
    now = timezone.now()
    with transaction.atomic():
        # Conditional update: the first approval wins, concurrent ones no-op.
        approved = Report.objects.filter(pk=report.pk, approved_at__isnull=True).update(
            approved_at=now, approved_by_name=name, updated_at=now
        )
        if approved:
            signature = Signature(
                job=report.job,
                signer_name=name,
                source=Signature.Source.REMOTE,
                signed_at=now,
                ip_address=client_ip(request),
            )
            if image is not None:
                signature.image.save("signature.png", image, save=False)
            signature.save()
            record_event(request, "report.customer_approved", report, organization=report.organization)
            notify_managers(
                report.organization,
                NotificationKind.CUSTOMER_APPROVED,
                title="Customer approved the cleaning",
                body=f"{report.number} approved by {name}",
                data={"report_id": str(report.id), "job_id": str(report.job_id)},
            )
    return _back_to_report(token, "approved")


@require_POST
@ratelimit("report_action", limit=20, period=3600, methods=("POST",))
def public_report_feedback(request, token):
    report = _public_report(token)
    message = (request.POST.get("message") or "").strip()[:MAX_MESSAGE]
    if not message:
        return _back_to_report(token, "missing-message")
    CustomerFeedback.objects.create(
        organization=report.organization,
        report=report,
        kind=CustomerFeedback.Kind.ISSUE,
        name=(request.POST.get("name") or "").strip()[:MAX_NAME],
        message=message,
        ip_address=client_ip(request),
    )
    notify_managers(
        report.organization,
        NotificationKind.CUSTOMER_ISSUE,
        title="Customer reported an issue",
        body=f"{report.number}: {message[:120]}",
        data={"report_id": str(report.id), "job_id": str(report.job_id)},
    )
    return _back_to_report(token, "feedback")


def verification_payload(report: Report | None) -> dict:
    """Deliberately minimal: proves existence and integrity, nothing private."""
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


@require_safe
@ratelimit("verify", limit=60, period=60)
def verify_report(request, number):
    number = number.upper()[:20]
    report = (
        Report.objects.filter(number=number, organization__deleted_at__isnull=True)
        .only("number", "status", "revision", "snapshot", "finalized_at", "content_hash")
        .first()
    )
    payload = verification_payload(report)
    status = 200 if payload["exists"] else 404
    if request.GET.get("format") == "json" or "application/json" in request.headers.get("Accept", ""):
        return JsonResponse(payload, status=status)
    return render(request, "reports/verify.html", {"v": payload, "number": number}, status=status)
