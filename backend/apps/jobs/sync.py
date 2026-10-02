"""Offline sync protocol.

The device records every change as a *mutation* in a local queue and pushes
them in order. Each mutation has a client-generated UUID, so replays are
idempotent. Conflict rules (see docs/SYNC.md):

* Evidence is append-only: photos and issues are never deleted by sync.
* Task status: last writer wins by device timestamp (``client_updated_at``).
* Job status only moves forward: scheduled -> in_progress -> completed.
  A cancelled job still accepts evidence (tasks, issues, notes) but not
  status transitions.
* Rejections are explicit and returned per mutation, never silent; the
  device keeps rejected data and shows it to the user.
"""
import uuid
from dataclasses import dataclass
from datetime import timezone as dt_timezone

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import serializers

from apps.organizations.models import Membership

from .models import Issue, Job, JobStatus, ProcessedMutation, TaskStatus
from .services import can_work_on, job_completed_side_effects

APPLIED = "applied"
DUPLICATE = "duplicate"
IGNORED_STALE = "ignored_stale"
REJECTED = "rejected"


class MutationSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    type = serializers.ChoiceField(
        choices=["job.start", "job.finish", "job.notes", "task.update", "issue.upsert"]
    )
    job_id = serializers.UUIDField()
    client_timestamp = serializers.DateTimeField()
    payload = serializers.DictField(default=dict)


class PushSerializer(serializers.Serializer):
    mutations = MutationSerializer(many=True, max_length=500)


@dataclass
class Result:
    status: str
    detail: str = ""

    def as_dict(self, mutation_id):
        data = {"id": str(mutation_id), "status": self.status}
        if self.detail:
            data["detail"] = self.detail
        return data


def _dt(payload, key, default=None):
    value = payload.get(key)
    if not value:
        return default
    parsed = parse_datetime(value) if isinstance(value, str) else None
    if parsed is None:
        raise ValueError(f"Invalid datetime for {key}")
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, dt_timezone.utc)
    return parsed


def _uuid(value):
    try:
        return uuid.UUID(str(value))
    except ValueError:
        return None


def _coord(payload, key):
    value = payload.get(key)
    return None if value is None else round(float(value), 6)


def _apply_job_start(job, user, ts, payload):
    if job.status == JobStatus.CANCELLED:
        return Result(REJECTED, "Job was cancelled by the office.")
    if job.status != JobStatus.SCHEDULED:
        return Result(IGNORED_STALE, "Already started.")
    job.status = JobStatus.IN_PROGRESS
    job.started_at = _dt(payload, "started_at", ts)
    job.started_by = user
    job.start_latitude = _coord(payload, "latitude")
    job.start_longitude = _coord(payload, "longitude")
    job.location_accuracy_m = payload.get("accuracy_m")
    job.save()
    return Result(APPLIED)


def _apply_job_finish(job, user, ts, payload):
    if job.status == JobStatus.CANCELLED:
        return Result(REJECTED, "Job was cancelled by the office; your evidence is still saved.")
    if job.status == JobStatus.COMPLETED:
        return Result(IGNORED_STALE, "Already completed.")
    incomplete = job.tasks.filter(is_required=True, status=TaskStatus.PENDING)
    if incomplete.exists() and not payload.get("force"):
        return Result(REJECTED, f"{incomplete.count()} required task(s) not completed.")
    now_ts = _dt(payload, "completed_at", ts)
    if job.started_at is None:
        job.started_at = now_ts
        job.started_by = user
    job.status = JobStatus.COMPLETED
    job.completed_at = now_ts
    job.completed_by = user
    job.end_latitude = _coord(payload, "latitude")
    job.end_longitude = _coord(payload, "longitude")
    job.expected_photo_ids = [str(pid) for pid in payload.get("photo_ids", [])]
    if "notes" in payload:
        job.notes = payload["notes"] or ""
    job.save()
    transaction.on_commit(lambda: job_completed_side_effects(job))
    return Result(APPLIED)


def _apply_job_notes(job, user, ts, payload):
    fields = []
    for key in ("notes", "supply_notes"):
        if key in payload:
            setattr(job, key, payload[key] or "")
            fields.append(key)
    if fields:
        job.save(update_fields=fields + ["updated_at"])
    return Result(APPLIED)


def _apply_task_update(job, user, ts, payload):
    task_id = _uuid(payload.get("task_id"))
    task = job.tasks.select_for_update().filter(pk=task_id).first() if task_id else None
    if task is None:
        return Result(REJECTED, "Unknown task.")
    status = payload.get("status")
    if status not in TaskStatus.values:
        return Result(REJECTED, "Invalid task status.")
    if task.client_updated_at and task.client_updated_at >= ts:
        return Result(IGNORED_STALE, "A newer change is already recorded.")
    task.status = status
    task.note = (payload.get("note") or "")[:500]
    task.client_updated_at = ts
    if status == TaskStatus.DONE:
        task.completed_at = _dt(payload, "completed_at", ts)
        task.completed_by = user
    else:
        task.completed_at = None
        task.completed_by = None
    task.save()
    Job.objects.filter(pk=job.pk).update(updated_at=timezone.now())
    return Result(APPLIED)


def _apply_issue_upsert(job, user, ts, payload):
    issue_id = _uuid(payload.get("id"))
    if issue_id is None or not payload.get("description"):
        return Result(REJECTED, "Issue id and description are required.")
    fields = {
        key: payload[key]
        for key in ("room", "description", "severity", "phase", "resolution")
        if key in payload
    }
    issue = Issue.objects.select_for_update().filter(pk=issue_id).first()
    if issue is not None:
        if issue.job_id != job.id:
            return Result(REJECTED, "Issue belongs to another job.")
        if issue.client_updated_at and issue.client_updated_at >= ts:
            return Result(IGNORED_STALE, "A newer change is already recorded.")
        for key, value in fields.items():
            setattr(issue, key, value)
    else:
        issue = Issue(
            id=issue_id, job=job, organization=job.organization, reported_by=user,
            reported_at=_dt(payload, "reported_at", ts), **fields,
        )
    issue.client_updated_at = ts
    try:
        issue.full_clean(exclude=["organization", "job", "reported_by"], validate_unique=False)
    except DjangoValidationError as exc:
        return Result(REJECTED, f"Invalid issue: {'; '.join(exc.messages)}")
    issue.save()
    Job.objects.filter(pk=job.pk).update(updated_at=timezone.now())
    return Result(APPLIED)


HANDLERS = {
    "job.start": _apply_job_start,
    "job.finish": _apply_job_finish,
    "job.notes": _apply_job_notes,
    "task.update": _apply_task_update,
    "issue.upsert": _apply_issue_upsert,
}


def apply_mutation(user, mutation: dict) -> dict:
    mutation_id = mutation["id"]
    existing = ProcessedMutation.objects.filter(pk=mutation_id, user=user).first()
    if existing is not None:
        return {**existing.result, "status": DUPLICATE, "original_status": existing.result["status"]}

    with transaction.atomic():
        job = Job.objects.select_for_update().filter(pk=mutation["job_id"]).first()
        membership = None
        if job is not None:
            membership = Membership.objects.filter(
                organization_id=job.organization_id, user=user, is_active=True
            ).first()
        if job is None or not can_work_on(job, user, membership):
            # Not recorded as processed: if access is restored later (e.g. the
            # job is reassigned back), the device can retry.
            return Result(REJECTED, "Job not found or not assigned to you.").as_dict(mutation_id)
        try:
            result = HANDLERS[mutation["type"]](job, user, mutation["client_timestamp"], mutation["payload"])
        except (ValueError, TypeError) as exc:
            result = Result(REJECTED, str(exc))
        data = result.as_dict(mutation_id)
        ProcessedMutation.objects.create(id=mutation_id, user=user, type=mutation["type"], result=data)
    return data
