"""Job domain services. Views stay thin; business rules live here."""

import hashlib
import io
import logging
from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.core.files.base import ContentFile
from django.db import IntegrityError, transaction
from django.utils import timezone
from PIL import Image, ImageOps
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError

from apps.billing.entitlements import Entitlements
from apps.notifications.services import NotificationKind, notify, notify_managers
from apps.organizations.models import Membership

from .models import Issue, Job, JobStatus, JobTask, Photo, RecurringSchedule
from .recurrence import occurrences

logger = logging.getLogger(__name__)

DISPLAY_SIZE = (800, 800)
# Formats we accept as evidence originals, with the extension they're stored
# under. Anything else (SVG, TIFF, GIF, polyglots) is refused.
ALLOWED_PHOTO_FORMATS = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp"}


# --------------------------------------------------------------------------
# Access
# --------------------------------------------------------------------------
def membership_for(job: Job, user) -> Membership | None:
    return Membership.objects.filter(organization_id=job.organization_id, user=user, is_active=True).first()


def can_work_on(job: Job, user, membership: Membership | None) -> bool:
    """Managers can work on any job in their org; cleaners only on their own."""
    if membership is None or not membership.is_active:
        return False
    if membership.is_manager:
        return True
    return membership.is_cleaner and job.assigned_to_id == user.id


# --------------------------------------------------------------------------
# Jobs
# --------------------------------------------------------------------------
def snapshot_checklist(job: Job) -> None:
    """Copy the template's sections/tasks onto the job (one bulk insert)."""
    template = job.checklist_template
    if template is None:
        return
    JobTask.objects.bulk_create(
        JobTask(
            job=job,
            section_name=section.name,
            section_position=section.position,
            title=task.title,
            instructions=task.instructions,
            is_required=task.is_required,
            requires_photo=task.requires_photo,
            position=task.position,
        )
        for section in template.sections.prefetch_related("tasks")
        for task in section.tasks.all()
    )


@transaction.atomic
def create_job(
    *,
    organization,
    property,
    scheduled_start,
    created_by=None,
    checklist_template=None,
    assigned_to=None,
    recurring_schedule=None,
    **fields,
) -> Job:
    Entitlements.for_org(organization).check_can_create_job(scheduled_start)
    job = Job.objects.create(
        organization=organization,
        property=property,
        scheduled_start=scheduled_start,
        checklist_template=checklist_template or property.default_checklist,
        assigned_to=assigned_to,
        recurring_schedule=recurring_schedule,
        created_by=created_by,
        **fields,
    )
    snapshot_checklist(job)
    if assigned_to is not None:
        notify_assignment(job, recurring=recurring_schedule is not None)
    return job


def notify_assignment(job: Job, recurring: bool = False) -> None:
    when = timezone.localtime(job.scheduled_start).strftime("%a %d %b, %H:%M")
    notify(
        job.assigned_to,
        NotificationKind.RECURRING_JOB_CREATED if recurring else NotificationKind.JOB_ASSIGNED,
        title="New job assigned",
        body=f"{job.display_title} — {when}",
        organization=job.organization,
        data={"job_id": str(job.id)},
    )


def generate_recurring_jobs(days_ahead: int = 14, today=None) -> int:
    """Create upcoming jobs for every active schedule.

    Idempotent: existing occurrences are loaded once per schedule, and the
    ``unique_recurring_occurrence`` constraint backs this up under concurrency.
    """
    today = today or timezone.localdate()
    horizon = today + timedelta(days=days_ahead)
    now = timezone.now()
    created = 0
    schedules = RecurringSchedule.objects.filter(
        is_active=True, property__is_active=True, organization__deleted_at__isnull=True
    ).select_related("property__default_checklist", "organization", "assigned_to", "checklist_template")
    for schedule in schedules.iterator(chunk_size=200):
        starts = [s for s in occurrences(schedule, today, horizon) if s >= now]
        if not starts:
            continue
        existing = set(
            Job.objects.filter(recurring_schedule=schedule, scheduled_start__in=starts).values_list(
                "scheduled_start", flat=True
            )
        )
        for start in starts:
            if start in existing:
                continue
            try:
                with transaction.atomic():
                    create_job(
                        organization=schedule.organization,
                        property=schedule.property,
                        scheduled_start=start,
                        scheduled_end=start + timedelta(minutes=schedule.duration_minutes),
                        checklist_template=schedule.checklist_template,
                        assigned_to=schedule.assigned_to,
                        recurring_schedule=schedule,
                        title=schedule.title,
                    )
                created += 1
            except IntegrityError:
                continue  # created concurrently
            except ValidationError as exc:  # plan limit reached for this org
                logger.info("Skipping recurring jobs for schedule %s: %s", schedule.pk, exc.detail)
                break
    return created


def job_completed_side_effects(job: Job) -> None:
    from apps.reports.services import finalize_report_if_ready

    who = job.completed_by.display_name if job.completed_by else "cleaner"
    notify_managers(
        job.organization,
        NotificationKind.JOB_COMPLETED,
        title="Job completed",
        body=f"{job.display_title} completed by {who}",
        data={"job_id": str(job.id)},
        exclude=job.completed_by,
    )
    finalize_report_if_ready(job)


# --------------------------------------------------------------------------
# Photo evidence
# --------------------------------------------------------------------------
def _sha256(django_file) -> str:
    digest = hashlib.sha256()
    for chunk in django_file.chunks():
        digest.update(chunk)
    django_file.seek(0)
    return digest.hexdigest()


@dataclass(frozen=True)
class _InspectedImage:
    extension: str
    width: int
    height: int
    display_copy: ContentFile


def _inspect_image(django_file) -> _InspectedImage:
    """Validate the upload and produce a compressed, EXIF-free display copy.

    The original (with its metadata) stays private as evidence; reports only
    ever show the re-encoded copy, so GPS EXIF never leaks to customers.
    """
    try:
        with Image.open(django_file) as img:
            fmt = img.format
            img.verify()
        if fmt not in ALLOWED_PHOTO_FORMATS:
            raise ValidationError({"file": "Upload a JPEG, PNG or WebP photo."})
        django_file.seek(0)
        with Image.open(django_file) as img:
            img = ImageOps.exif_transpose(img)
            width, height = img.size
            img = img.convert("RGB")
            img.thumbnail(DISPLAY_SIZE)
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=80, optimize=True)
    except (OSError, SyntaxError, ValueError, Image.DecompressionBombError):
        raise ValidationError({"file": "Not a valid image."}) from None
    finally:
        django_file.seek(0)
    return _InspectedImage(ALLOWED_PHOTO_FORMATS[fmt], width, height, ContentFile(buf.getvalue()))


@dataclass(frozen=True)
class PhotoIngestResult:
    photo: Photo
    created: bool


class PhotoConflict(Exception):
    """The upload can't be accepted *yet* or *ever* under this id (HTTP 409)."""


def ingest_photo(
    *, user, job_id, photo_id, file, client_sha256=None, job_task_id=None, issue_id=None, **fields
) -> PhotoIngestResult:
    """Store one evidence photo. Idempotent on the client-generated ``photo_id``.

    Raises NotFound/PermissionDenied (access), ValidationError (bad file or
    checksum: the device should keep the file and retry) or PhotoConflict.
    """
    if file.size > settings.MAX_PHOTO_UPLOAD_BYTES:
        raise ValidationError({"file": "Photo is too large."})
    job = Job.objects.select_related("organization").filter(pk=job_id).first()
    membership = membership_for(job, user) if job is not None else None
    if membership is None:
        raise NotFound("Job not found.")  # outsiders can't probe other tenants' job ids
    if not can_work_on(job, user, membership):
        raise PermissionDenied("Job not assigned to you.")

    existing = Photo.objects.filter(pk=photo_id).first()
    if existing is not None:
        if existing.job_id != job.id:
            raise PhotoConflict("Photo id already used.")
        return PhotoIngestResult(existing, created=False)

    job_task = issue = None
    if job_task_id:
        job_task = JobTask.objects.filter(pk=job_task_id, job=job).first()
        if job_task is None:
            raise ValidationError({"job_task": "Task does not belong to this job."})
    if issue_id:
        issue = Issue.objects.filter(pk=issue_id, job=job).first()
        if issue is None:
            raise PhotoConflict("Issue not synced yet.")  # device retries after pushing the issue

    digest = _sha256(file)
    if client_sha256 and client_sha256.lower() != digest:
        raise ValidationError({"sha256": "Checksum mismatch; upload again."})
    image = _inspect_image(file)

    with transaction.atomic():
        photo = Photo(
            id=photo_id,
            job=job,
            organization=job.organization,
            uploaded_by=user,
            sha256=digest,
            width=image.width,
            height=image.height,
            size_bytes=file.size,
            job_task=job_task,
            issue=issue,
            **fields,
        )
        photo.file.save(f"original.{image.extension}", file, save=False)
        photo.thumbnail.save("display.jpg", image.display_copy, save=False)
        try:
            with transaction.atomic():
                photo.save(force_insert=True)
        except IntegrityError:
            # Concurrent retry of the same upload won the race.
            photo.file.delete(save=False)
            photo.thumbnail.delete(save=False)
            return PhotoIngestResult(Photo.objects.get(pk=photo_id), created=False)
        Job.objects.filter(pk=job.pk).update(updated_at=timezone.now())
        if job.status == JobStatus.COMPLETED:
            from apps.reports.services import finalize_report_if_ready

            transaction.on_commit(lambda: finalize_report_if_ready(job))
    return PhotoIngestResult(photo, created=True)
