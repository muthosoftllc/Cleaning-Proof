import hashlib
import json
import logging

from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone

from apps.billing.entitlements import Entitlements
from apps.jobs.models import Job, JobStatus, TaskStatus
from apps.notifications.services import NotificationKind, notify_managers

from .models import Report, ReportStatus

logger = logging.getLogger(__name__)


def _iso(dt):
    return dt.isoformat() if dt else None


def build_snapshot(job: Job, report: Report) -> dict:
    """Everything the report displays, frozen. No customer contact details,
    no street address beyond what identifies the property, no GPS EXIF."""
    org = job.organization
    prop = job.property
    sections: dict[str, list] = {}
    for task in job.tasks.all().order_by("section_position", "position"):
        sections.setdefault(task.section_name, []).append({
            "id": str(task.id),
            "title": task.title,
            "status": task.status,
            "required": task.is_required,
            "note": task.note,
            "completed_at": _iso(task.completed_at),
        })
    photos = [
        {
            "id": str(p.id),
            "kind": p.kind,
            "room": p.room or (p.job_task.section_name if p.job_task else ""),
            "task_id": str(p.job_task_id) if p.job_task_id else None,
            "issue_id": str(p.issue_id) if p.issue_id else None,
            "caption": p.caption,
            "captured_at": _iso(p.captured_at),
            "sha256": p.sha256,
            "has_location": p.latitude is not None,
        }
        for p in job.photos.select_related("job_task").order_by("captured_at")
    ]
    issues = [
        {
            "id": str(i.id),
            "room": i.room,
            "description": i.description,
            "severity": i.severity,
            "phase": i.get_phase_display(),
            "resolution": i.get_resolution_display(),
            "reported_at": _iso(i.reported_at),
        }
        for i in job.issues.all().order_by("reported_at")
    ]
    tasks_flat = [t for ts in sections.values() for t in ts]
    return {
        "report_number": report.number,
        "revision": report.revision,
        "company": {
            "name": org.name,
            "contact_email": org.contact_email,
            "contact_phone": org.contact_phone,
            "website": org.website,
            "brand_color": org.brand_color,
            "has_logo": bool(org.logo),
        },
        "property": {"name": prop.name, "city": prop.city},
        "customer": {"name": prop.customer.name if prop.customer else ""},
        "job": {
            "id": str(job.id),
            "title": job.display_title,
            "scheduled_start": _iso(job.scheduled_start),
            "started_at": _iso(job.started_at),
            "completed_at": _iso(job.completed_at),
            "duration_minutes": job.duration_minutes,
            "cleaner": job.completed_by.display_name if job.completed_by else (
                job.assigned_to.display_name if job.assigned_to else ""),
            "location_verified": job.start_latitude is not None or job.end_latitude is not None,
            "notes": job.notes,
        },
        "checklist": [{"section": name, "tasks": tasks} for name, tasks in sections.items()],
        "summary": {
            "tasks_total": len(tasks_flat),
            "tasks_done": sum(1 for t in tasks_flat if t["status"] == TaskStatus.DONE),
            "tasks_skipped": sum(1 for t in tasks_flat if t["status"] == TaskStatus.SKIPPED),
            "photos": len(photos),
            "issues": len(issues),
        },
        "photos": photos,
        "issues": issues,
        "missing_photo_ids": job.missing_photo_ids,
        "signatures": [
            {"signer_name": s.signer_name, "source": s.get_source_display(), "signed_at": _iso(s.signed_at)}
            for s in job.signatures.all()
        ],
        "generated_at": _iso(timezone.now()),
    }


def hash_snapshot(snapshot: dict) -> str:
    canonical = json.dumps(snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@transaction.atomic
def finalize_report_if_ready(job: Job, force: bool = False) -> Report | None:
    """Create/refresh the job's report.

    The report exists (and its link works) as soon as the job is completed,
    but it is only *final* — hashed, PDF'd and announced — once every photo
    the device declared at finish has been uploaded. ``force`` finalizes
    anyway (e.g. a lost device), and the report states which photos never
    arrived.
    """
    job = Job.objects.select_for_update().select_related(
        "organization", "property__customer", "completed_by", "assigned_to"
    ).get(pk=job.pk)
    if job.status != JobStatus.COMPLETED:
        return None
    report, created = Report.objects.get_or_create(job=job, defaults={"organization": job.organization})
    if report.status == ReportStatus.REVOKED:
        return report

    ready = force or not job.missing_photo_ids
    was_final = report.status == ReportStatus.FINAL
    if was_final:
        # Evidence arriving after finalization produces a new, visible revision.
        new_snapshot = build_snapshot(job, report)
        if new_snapshot["photos"] == report.snapshot.get("photos") and \
                new_snapshot["signatures"] == report.snapshot.get("signatures"):
            return report
        report.revision += 1

    report.snapshot = build_snapshot(job, report)
    report.generated_at = timezone.now()
    if ready:
        report.status = ReportStatus.FINAL
        report.finalized_at = report.finalized_at or timezone.now()
        report.content_hash = hash_snapshot(report.snapshot)
    report.save()

    if ready:
        if Entitlements.for_org(job.organization).has("pdf_reports"):
            transaction.on_commit(lambda: generate_pdf(report.pk))
        if not was_final:
            notify_managers(
                job.organization, NotificationKind.REPORT_GENERATED,
                title="Cleaning report ready",
                body=f"{report.number} — {job.display_title}",
                data={"job_id": str(job.id), "report_id": str(report.id)},
            )
    return report


def generate_pdf(report_id) -> Report:
    from .pdf import render_report_pdf

    report = Report.objects.select_related("organization").get(pk=report_id)
    try:
        content = render_report_pdf(report)
    except Exception:
        logger.exception("PDF generation failed for %s", report.number)
        return report
    if report.pdf:
        report.pdf.delete(save=False)
    report.pdf.save(f"{report.number}.pdf", ContentFile(content), save=False)
    Report.objects.filter(pk=report.pk).update(pdf=report.pdf.name)
    return report
