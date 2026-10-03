package app.cleaningproof.data.repo

import androidx.room.withTransaction
import app.cleaningproof.data.local.AppDatabase
import app.cleaningproof.data.local.IssueEntity
import app.cleaningproof.data.local.JobEntity
import app.cleaningproof.data.local.JobStatus
import app.cleaningproof.data.local.MutationEntity
import app.cleaningproof.data.local.PhotoEntity
import app.cleaningproof.data.local.TaskEntity
import app.cleaningproof.data.local.TaskStatus
import app.cleaningproof.data.local.UploadState
import app.cleaningproof.data.remote.JobDto
import app.cleaningproof.data.remote.PullResponse
import app.cleaningproof.sync.SyncScheduler
import app.cleaningproof.util.isoToMillis
import app.cleaningproof.util.toIso
import java.io.File
import java.util.UUID
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.add
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import kotlinx.serialization.json.putJsonArray

/**
 * Local-first job execution. Every user action is written to Room *and*
 * queued as a mutation in the same transaction, then a sync is scheduled.
 * The UI only ever reads Room, so the app behaves identically offline.
 */
private const val COMPLETED_RETENTION_MS = 14L * 24 * 60 * 60 * 1000

class JobRepository(
    private val db: AppDatabase,
    private val sync: SyncScheduler,
    private val now: () -> Long = System::currentTimeMillis
) {
    fun observeJobs(from: Long, to: Long) = db.jobs().observeBetween(from, to)
    fun observeInProgress() = db.jobs().observeInProgress()
    fun observeJob(id: String) = db.jobs().observe(id)
    fun observeTasks(jobId: String) = db.tasks().observeForJob(jobId)
    fun observeIssues(jobId: String) = db.issues().observeForJob(jobId)
    fun observePhotos(jobId: String) = db.photos().observeForJob(jobId)
    fun observePendingMutations() = db.mutations().observePendingCount()
    fun observePendingPhotos() = db.photos().observePendingCount()
    fun observeRejected() = db.mutations().observeRejected()

    suspend fun startJob(jobId: String, latitude: Double?, longitude: Double?, accuracy: Float?) {
        val ts = now()
        db.withTransaction {
            db.jobs().markStarted(jobId, JobStatus.IN_PROGRESS, ts)
            enqueue(
                jobId,
                "job.start",
                ts,
                buildJsonObject {
                    put("started_at", ts.toIso())
                    latitude?.let { put("latitude", it) }
                    longitude?.let { put("longitude", it) }
                    accuracy?.let { put("accuracy_m", it) }
                }
            )
        }
        sync.requestSync()
    }

    /** One tap: pending -> done -> pending. Long-press callers pass SKIPPED explicitly. */
    suspend fun setTaskStatus(task: TaskEntity, status: String, note: String = task.note) {
        val ts = now()
        db.withTransaction {
            // Tapping a task implicitly starts a scheduled job (queued first, so order is preserved).
            val job = db.jobs().get(task.jobId)
            if (job?.status == JobStatus.SCHEDULED) {
                db.jobs().markStarted(task.jobId, JobStatus.IN_PROGRESS, ts)
                enqueue(task.jobId, "job.start", ts, buildJsonObject { put("started_at", ts.toIso()) })
            }
            db.tasks().update(task.id, status, note, ts)
            enqueue(
                task.jobId,
                "task.update",
                ts,
                buildJsonObject {
                    put("task_id", task.id)
                    put("status", status)
                    put("note", note)
                    if (status == TaskStatus.DONE) put("completed_at", ts.toIso())
                }
            )
        }
        sync.requestSync()
    }

    suspend fun saveIssue(issue: IssueEntity) {
        val ts = now()
        db.withTransaction {
            db.issues().upsert(issue)
            enqueue(
                issue.jobId,
                "issue.upsert",
                ts,
                buildJsonObject {
                    put("id", issue.id)
                    put("room", issue.room)
                    put("description", issue.description)
                    put("severity", issue.severity)
                    put("phase", issue.phase)
                    put("resolution", issue.resolution)
                    put("reported_at", issue.reportedAt.toIso())
                }
            )
        }
        sync.requestSync()
    }

    suspend fun saveNotes(jobId: String, notes: String) {
        val ts = now()
        db.withTransaction {
            db.jobs().updateNotes(jobId, notes)
            enqueue(jobId, "job.notes", ts, buildJsonObject { put("notes", notes) })
        }
        sync.requestSync()
    }

    /** Registers a captured photo; the file is already compressed and stored privately. */
    suspend fun addPhoto(photo: PhotoEntity) {
        db.photos().upsert(photo)
        sync.requestPhotoUpload()
    }

    /**
     * Finishing declares every photo id captured for the job, so the server
     * only finalizes the report once all of them have arrived.
     */
    suspend fun finishJob(jobId: String, notes: String, latitude: Double?, longitude: Double?): Result<Unit> {
        val missing = db.tasks().forJob(jobId).count { it.isRequired && it.status == TaskStatus.PENDING }
        if (missing > 0) return Result.failure(IllegalStateException("$missing required task(s) left"))
        val ts = now()
        db.withTransaction {
            val photoIds = db.photos().idsForJob(jobId)
            db.jobs().markCompleted(jobId, JobStatus.COMPLETED, ts, notes)
            enqueue(
                jobId,
                "job.finish",
                ts,
                buildJsonObject {
                    put("completed_at", ts.toIso())
                    put("notes", notes)
                    latitude?.let { put("latitude", it) }
                    longitude?.let { put("longitude", it) }
                    putJsonArray("photo_ids") { photoIds.forEach { add(it) } }
                }
            )
        }
        sync.requestSync()
        return Result.success(Unit)
    }

    private suspend fun enqueue(jobId: String, type: String, ts: Long, payload: JsonObject) {
        db.mutations().insert(
            MutationEntity(
                mutationId = UUID.randomUUID().toString(),
                jobId = jobId,
                type = type,
                payloadJson = payload.toString(),
                clientTimestamp = ts
            )
        )
    }

    /**
     * Merge a pull into Room. Jobs with unsynced local changes keep their
     * local execution state (status, tasks, notes); only office-owned fields
     * (schedule, property info, report) are refreshed. Local photos are never
     * touched here.
     */
    suspend fun applyPull(organizationId: String, pull: PullResponse) {
        val releasedFiles = db.withTransaction { mergePull(organizationId, pull) }
        // File I/O after the transaction commits; only server-confirmed photos are released.
        releasedFiles.forEach { File(it).delete() }
    }

    private suspend fun mergePull(organizationId: String, pull: PullResponse): List<String> {
        for (dto in pull.jobs) {
            val local = db.jobs().get(dto.id)
            val dirty = db.mutations().pendingCountForJob(dto.id) > 0
            val entity = dto.toEntity(organizationId)
            if (local != null && dirty) {
                db.jobs().upsert(
                    entity.copy(
                        status = local.status,
                        startedAt = local.startedAt,
                        completedAt = local.completedAt,
                        notes = local.notes
                    )
                )
                continue
            }
            db.jobs().upsert(entity)
            db.tasks().deleteForJob(dto.id)
            db.tasks().upsertAll(
                dto.tasks.map {
                    TaskEntity(
                        id = it.id, jobId = dto.id, sectionName = it.sectionName,
                        sectionPosition = it.sectionPosition, title = it.title, instructions = it.instructions,
                        isRequired = it.isRequired, requiresPhoto = it.requiresPhoto, position = it.position,
                        status = it.status, note = it.note, updatedAt = null
                    )
                }
            )
            db.issues().upsertAll(
                dto.issues.map {
                    IssueEntity(
                        id = it.id,
                        jobId = dto.id,
                        room = it.room,
                        description = it.description,
                        severity = it.severity,
                        phase = it.phase,
                        resolution = it.resolution,
                        reportedAt = it.reportedAt.isoToMillis()
                    )
                }
            )
            dto.photos.forEach {
                // Server-only photos (e.g. taken on another device); local ones are kept as-is.
                db.photos().insertIfAbsent(
                    PhotoEntity(
                        id = it.id, jobId = dto.id, taskId = it.jobTask, issueId = it.issue, kind = it.kind,
                        room = it.room, localPath = null, remoteThumbUrl = it.thumbnailUrl, sha256 = null,
                        capturedAt = it.capturedAt.isoToMillis(), latitude = null, longitude = null,
                        uploadState = UploadState.UPLOADED
                    )
                )
            }
        }
        // Jobs reassigned or cancelled elsewhere, and completed jobs past the
        // retention window, leave the device -- unless they still hold unsynced work.
        val active = pull.activeJobIds.toSet()
        val keepCompletedSince = now() - COMPLETED_RETENTION_MS
        val released = mutableListOf<String>()
        for (id in db.jobs().allIds()) {
            val job = db.jobs().get(id) ?: continue
            val recentlyFinished = job.status == JobStatus.COMPLETED && (job.completedAt ?: 0) > keepCompletedSince
            val hasUnsynced = db.mutations().pendingCountForJob(id) > 0 || db.photos().pendingCountForJob(id) > 0
            if ((id in active && job.status != JobStatus.COMPLETED) || recentlyFinished || hasUnsynced) continue
            released += db.photos().uploadedLocalPaths(id)
            db.photos().deleteUploadedForJob(id)
            db.tasks().deleteForJob(id)
            db.issues().deleteForJob(id)
            db.jobs().delete(id)
        }
        return released
    }

    /** True if this device holds evidence or changes the server hasn't accepted. */
    suspend fun hasUnsyncedWork(): Boolean = db.mutations().totalCount() > 0 || db.photos().unconfirmedCount() > 0

    /** Remove every trace of the previous user's data (used when another user signs in). */
    suspend fun wipeLocalData(evidenceDir: File) = withContext(Dispatchers.IO) {
        db.clearAllTables() // manages its own transaction; must not run inside one
        evidenceDir.deleteRecursively()
    }

    private fun JobDto.toEntity(organizationId: String) = JobEntity(
        id = id,
        organizationId = organizationId,
        title = title.ifBlank { property.name },
        propertyName = property.name,
        propertyAddress = listOf(property.addressLine1, property.city).filter { it.isNotBlank() }.joinToString(", "),
        cleaningInstructions = property.cleaningInstructions,
        accessNotes = property.accessNotes,
        instructions = instructions,
        scheduledStart = scheduledStart.isoToMillis(),
        scheduledEnd = scheduledEnd?.isoToMillis(),
        status = status,
        startedAt = startedAt?.isoToMillis(),
        completedAt = completedAt?.isoToMillis(),
        notes = notes,
        reportNumber = report?.number,
        reportStatus = report?.status,
        reportShareUrl = report?.shareUrl,
        serverUpdatedAt = updatedAt
    )
}
