import hashlib
import io
import logging
from datetime import timedelta

from django.core.files.base import ContentFile
from django.db import IntegrityError, transaction
from django.utils import timezone
from PIL import Image, ImageOps
from rest_framework.exceptions import ValidationError

from apps.billing.entitlements import Entitlements
from apps.notifications.services import NotificationKind, notify, notify_managers

from .models import Job, JobStatus, JobTask, Photo, RecurringSchedule
from .recurrence import occurrences

logger = logging.getLogger(__name__)

THUMBNAIL_SIZE = (800, 800)
Image.MAX_IMAGE_PIXELS = 60_000_000  # guard against decompression bombs


def snapshot_checklist(job: Job) -> None:
    """Copy the template's sections/tasks onto the job."""
    template = job.checklist_template
    if template is None:
        return
    tasks = []
    for section in template.sections.prefetch_related("tasks"):
        for task in section.tasks.all():
            tasks.append(
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
            )
    JobTask.objects.bulk_create(tasks)


@transaction.atomic
def create_job(*, organization, property, scheduled_start, created_by=None, checklist_template=None,
               assigned_to=None, recurring_schedule=None, **fields) -> Job:
    Entitlements.for_org(organization).check_can_create_job(scheduled_start)
    if checklist_template is None:
        checklist_template = property.default_checklist
    job = Job.objects.create(
        organization=organization,
        property=property,
        scheduled_start=scheduled_start,
        checklist_template=checklist_template,
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
    """Create upcoming jobs for every active schedule. Idempotent: an
    occurrence that already has a job is skipped (DB constraint)."""
    today = today or timezone.localdate()
    horizon = today + timedelta(days=days_ahead)
    created = 0
    schedules = RecurringSchedule.objects.filter(is_active=True, organization__deleted_at__isnull=True)
    for schedule in schedules.select_related("property", "organization", "assigned_to", "checklist_template"):
        if not schedule.property.is_active:
            continue
        for start in occurrences(schedule, today, horizon):
            if start < timezone.now():
                continue
            if Job.objects.filter(recurring_schedule=schedule, scheduled_start=start).exists():
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
            except ValidationError as exc:  # plan limit reached
                logger.info("Skipping recurring job for %s: %s", schedule.pk, exc.detail)
                break
    return created


def sha256_of(django_file) -> str:
    digest = hashlib.sha256()
    for chunk in django_file.chunks():
        digest.update(chunk)
    django_file.seek(0)
    return digest.hexdigest()


def build_thumbnail(django_file) -> tuple[ContentFile, int, int]:
    """Validate the image and produce a compressed, EXIF-free display copy.

    The original (with its metadata) stays private as evidence; reports only
    ever show the re-encoded copy, so GPS EXIF never leaks to customers.
    """
    try:
        with Image.open(django_file) as img:
            img.verify()
        django_file.seek(0)
        with Image.open(django_file) as img:
            img = ImageOps.exif_transpose(img)
            width, height = img.size
            img = img.convert("RGB")
            img.thumbnail(THUMBNAIL_SIZE)
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=80, optimize=True)
    except (OSError, SyntaxError, Image.DecompressionBombError) as exc:
        raise ValidationError({"file": f"Not a valid image: {exc}"})
    finally:
        django_file.seek(0)
    return ContentFile(buf.getvalue()), width, height


@transaction.atomic
def store_photo(*, job: Job, user, file, client_sha256: str | None = None, **fields) -> Photo:
    digest = sha256_of(file)
    if client_sha256 and client_sha256.lower() != digest:
        # Corrupted in transit: refuse so the device keeps it and retries.
        raise ValidationError({"sha256": "Checksum mismatch; upload again."})
    thumb, width, height = build_thumbnail(file)
    photo = Photo(
        job=job, organization=job.organization, uploaded_by=user, sha256=digest,
        width=width, height=height, size_bytes=file.size, **fields,
    )
    photo.file.save("photo.jpg", file, save=False)
    photo.thumbnail.save("thumb.jpg", thumb, save=False)
    photo.save()
    Job.objects.filter(pk=job.pk).update(updated_at=timezone.now())
    return photo


def job_completed_side_effects(job: Job) -> None:
    from apps.reports.services import finalize_report_if_ready

    notify_managers(
        job.organization,
        NotificationKind.JOB_COMPLETED,
        title="Job completed",
        body=f"{job.display_title} completed by {job.completed_by.display_name if job.completed_by else 'cleaner'}",
        data={"job_id": str(job.id)},
        exclude=job.completed_by,
    )
    finalize_report_if_ready(job)


def can_work_on(job: Job, user, membership) -> bool:
    if membership is None or not membership.is_active:
        return False
    if membership.is_manager:
        return True
    return membership.is_cleaner and job.assigned_to_id == user.id


def active_statuses():
    return [JobStatus.SCHEDULED, JobStatus.IN_PROGRESS]
