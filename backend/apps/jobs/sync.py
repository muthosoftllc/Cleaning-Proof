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

Payloads are untrusted input: every handler validates through a serializer.
"""

from dataclasses import dataclass

from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework import serializers

from .models import (
    Issue,
    IssuePhase,
    IssueResolution,
    IssueSeverity,
    Job,
    JobStatus,
    ProcessedMutation,
    TaskStatus,
)
from .services import can_work_on, job_completed_side_effects, membership_for

APPLIED = "applied"
DUPLICATE = "duplicate"
IGNORED_STALE = "ignored_stale"
REJECTED = "rejected"

MAX_BATCH = 500
MAX_NOTES = 5000
MAX_PHOTOS_PER_JOB = 1000


# --------------------------------------------------------------------------
# Envelope
# --------------------------------------------------------------------------
class MutationSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    type = serializers.ChoiceField(choices=["job.start", "job.finish", "job.notes", "task.update", "issue.upsert"])
    job_id = serializers.UUIDField()
    client_timestamp = serializers.DateTimeField()
    payload = serializers.DictField(default=dict)


class PushSerializer(serializers.Serializer):
    mutations = MutationSerializer(many=True, max_length=MAX_BATCH)


# --------------------------------------------------------------------------
# Payloads
# --------------------------------------------------------------------------
class _Location(serializers.Serializer):
    latitude = serializers.DecimalField(
        max_digits=9,
        decimal_places=6,
        required=False,
        allow_null=True,
        min_value=-90,
        max_value=90,
        coerce_to_string=False,
    )
    longitude = serializers.DecimalField(
        max_digits=9,
        decimal_places=6,
        required=False,
        allow_null=True,
        min_value=-180,
        max_value=180,
        coerce_to_string=False,
    )

    def to_internal_value(self, data):
        # Devices send full-precision doubles; round before decimal validation.
        data = dict(data)
        for key in ("latitude", "longitude"):
            if isinstance(data.get(key), float):
                data[key] = round(data[key], 6)
        return super().to_internal_value(data)


class JobStartPayload(_Location):
    started_at = serializers.DateTimeField(required=False)
    accuracy_m = serializers.FloatField(required=False, allow_null=True, min_value=0)


class JobFinishPayload(_Location):
    completed_at = serializers.DateTimeField(required=False)
    notes = serializers.CharField(required=False, allow_blank=True, max_length=MAX_NOTES)
    photo_ids = serializers.ListField(child=serializers.UUIDField(), required=False, max_length=MAX_PHOTOS_PER_JOB)
    force = serializers.BooleanField(required=False, default=False)


class JobNotesPayload(serializers.Serializer):
    notes = serializers.CharField(required=False, allow_blank=True, max_length=MAX_NOTES)
    supply_notes = serializers.CharField(required=False, allow_blank=True, max_length=MAX_NOTES)


class TaskUpdatePayload(serializers.Serializer):
    task_id = serializers.UUIDField()
    status = serializers.ChoiceField(choices=TaskStatus.choices)
    note = serializers.CharField(required=False, allow_blank=True, max_length=500, default="")
    completed_at = serializers.DateTimeField(required=False)


class IssueUpsertPayload(serializers.Serializer):
    id = serializers.UUIDField()
    description = serializers.CharField(max_length=2000)
    room = serializers.CharField(required=False, allow_blank=True, max_length=100)
    severity = serializers.ChoiceField(choices=IssueSeverity.choices, required=False)
    phase = serializers.ChoiceField(choices=IssuePhase.choices, required=False)
    resolution = serializers.ChoiceField(choices=IssueResolution.choices, required=False)
    reported_at = serializers.DateTimeField(required=False)


@dataclass(frozen=True)
class Result:
    status: str
    detail: str = ""

    def as_dict(self, mutation_id) -> dict:
        data = {"id": str(mutation_id), "status": self.status}
        if self.detail:
            data["detail"] = self.detail
        return data


@dataclass(frozen=True)
class Context:
    job: Job
    user: object
    is_manager: bool
    ts: object  # device timestamp of the mutation


def _touch(job: Job) -> None:
    """Bump updated_at so the next pull ships this job to other devices."""
    Job.objects.filter(pk=job.pk).update(updated_at=timezone.now())


# --------------------------------------------------------------------------
# Handlers
# --------------------------------------------------------------------------
def _job_start(ctx: Context, data: dict) -> Result:
    job = ctx.job
    if job.status == JobStatus.CANCELLED:
        return Result(REJECTED, "Job was cancelled by the office.")
    if job.status != JobStatus.SCHEDULED:
        return Result(IGNORED_STALE, "Already started.")
    job.status = JobStatus.IN_PROGRESS
    job.started_at = data.get("started_at", ctx.ts)
    job.started_by = ctx.user
    job.start_latitude = data.get("latitude")
    job.start_longitude = data.get("longitude")
    job.location_accuracy_m = data.get("accuracy_m")
    job.save()
    return Result(APPLIED)


def _job_finish(ctx: Context, data: dict) -> Result:
    job = ctx.job
    if job.status == JobStatus.CANCELLED:
        return Result(REJECTED, "Job was cancelled by the office; your evidence is still saved.")
    if job.status == JobStatus.COMPLETED:
        return Result(IGNORED_STALE, "Already completed.")
    # Only managers may close a job with required tasks still open.
    pending_required = job.tasks.filter(is_required=True, status=TaskStatus.PENDING).count()
    if pending_required and not (data["force"] and ctx.is_manager):
        return Result(REJECTED, f"{pending_required} required task(s) not completed.")
    completed_at = data.get("completed_at", ctx.ts)
    if job.started_at is None:
        job.started_at, job.started_by = completed_at, ctx.user
    job.status = JobStatus.COMPLETED
    job.completed_at = completed_at
    job.completed_by = ctx.user
    job.end_latitude = data.get("latitude")
    job.end_longitude = data.get("longitude")
    job.expected_photo_ids = [str(pid) for pid in data.get("photo_ids", [])]
    if "notes" in data:
        job.notes = data["notes"]
    job.save()
    transaction.on_commit(lambda: job_completed_side_effects(job))
    return Result(APPLIED)


def _job_notes(ctx: Context, data: dict) -> Result:
    if data:
        for key, value in data.items():
            setattr(ctx.job, key, value)
        ctx.job.save(update_fields=[*data, "updated_at"])
    return Result(APPLIED)


def _task_update(ctx: Context, data: dict) -> Result:
    task = ctx.job.tasks.select_for_update().filter(pk=data["task_id"]).first()
    if task is None:
        return Result(REJECTED, "Unknown task.")
    if task.client_updated_at and task.client_updated_at >= ctx.ts:
        return Result(IGNORED_STALE, "A newer change is already recorded.")
    done = data["status"] == TaskStatus.DONE
    task.status = data["status"]
    task.note = data["note"]
    task.client_updated_at = ctx.ts
    task.completed_at = data.get("completed_at", ctx.ts) if done else None
    task.completed_by = ctx.user if done else None
    task.save()
    _touch(ctx.job)
    return Result(APPLIED)


def _issue_upsert(ctx: Context, data: dict) -> Result:
    issue_id = data.pop("id")
    issue = Issue.objects.select_for_update().filter(pk=issue_id).first()
    if issue is None:
        issue = Issue(
            id=issue_id,
            job=ctx.job,
            organization=ctx.job.organization,
            reported_by=ctx.user,
            reported_at=data.pop("reported_at", ctx.ts),
        )
    elif issue.job_id != ctx.job.id:
        return Result(REJECTED, "Issue belongs to another job.")
    elif issue.client_updated_at and issue.client_updated_at >= ctx.ts:
        return Result(IGNORED_STALE, "A newer change is already recorded.")
    data.pop("reported_at", None)  # immutable once recorded
    for key, value in data.items():
        setattr(issue, key, value)
    issue.client_updated_at = ctx.ts
    issue.save()
    _touch(ctx.job)
    return Result(APPLIED)


HANDLERS = {
    "job.start": (JobStartPayload, _job_start),
    "job.finish": (JobFinishPayload, _job_finish),
    "job.notes": (JobNotesPayload, _job_notes),
    "task.update": (TaskUpdatePayload, _task_update),
    "issue.upsert": (IssueUpsertPayload, _issue_upsert),
}


def _first_error(errors) -> str:
    field, messages = next(iter(errors.items()))
    message = messages[0] if isinstance(messages, list) and messages else messages
    return f"Invalid {field}: {message}"


def apply_mutation(user, mutation: dict) -> dict:
    """Apply one validated envelope (see MutationSerializer) and return its result."""
    mutation_id = mutation["id"]
    done = ProcessedMutation.objects.filter(user=user, mutation_id=mutation_id).only("result").first()
    if done is not None:
        return {**done.result, "status": DUPLICATE, "original_status": done.result["status"]}

    payload_serializer, handler = HANDLERS[mutation["type"]]
    try:
        with transaction.atomic():
            job = (
                Job.objects.select_for_update(of=("self",))
                .select_related("organization")
                .filter(pk=mutation["job_id"])
                .first()
            )
            membership = membership_for(job, user) if job is not None else None
            if job is None or not can_work_on(job, user, membership):
                # Not recorded: if access is restored later (e.g. reassigned back),
                # the device can retry the same mutation.
                return Result(REJECTED, "Job not found or not assigned to you.").as_dict(mutation_id)

            payload = payload_serializer(data=mutation["payload"])
            if payload.is_valid():
                ctx = Context(job=job, user=user, is_manager=membership.is_manager, ts=mutation["client_timestamp"])
                result = handler(ctx, dict(payload.validated_data))
            else:
                result = Result(REJECTED, _first_error(payload.errors))
            data = result.as_dict(mutation_id)
            ProcessedMutation.objects.create(user=user, mutation_id=mutation_id, type=mutation["type"], result=data)
    except IntegrityError:
        # The same mutation is being applied concurrently (device retried while
        # the first request was in flight); the other request owns the result.
        return {"id": str(mutation_id), "status": DUPLICATE}
    return data
