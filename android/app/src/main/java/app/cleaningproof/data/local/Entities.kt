package app.cleaningproof.data.local

import androidx.room.Entity
import androidx.room.Index
import androidx.room.PrimaryKey

object JobStatus {
    const val SCHEDULED = "scheduled"
    const val IN_PROGRESS = "in_progress"
    const val COMPLETED = "completed"
    const val CANCELLED = "cancelled"
}

object TaskStatus {
    const val PENDING = "pending"
    const val DONE = "done"
    const val SKIPPED = "skipped"
}

object PhotoKind {
    const val BEFORE = "before"
    const val AFTER = "after"
    const val TASK = "task"
    const val ISSUE = "issue"
    const val OTHER = "other"
}

/** Upload lifecycle of a locally captured photo. Evidence is never deleted
 *  before the server has confirmed it (UPLOADED). */
object UploadState {
    const val PENDING = "pending"
    const val UPLOADED = "uploaded"
    const val FAILED = "failed" // permanent server rejection; kept and shown to the user
}

@Entity(tableName = "jobs", indices = [Index("scheduledStart")])
data class JobEntity(
    @PrimaryKey val id: String,
    val organizationId: String,
    val title: String,
    val propertyName: String,
    val propertyAddress: String,
    val cleaningInstructions: String,
    val accessNotes: String,
    val instructions: String,
    val scheduledStart: Long,
    val scheduledEnd: Long?,
    val status: String,
    val startedAt: Long?,
    val completedAt: Long?,
    val notes: String,
    val reportNumber: String?,
    val reportStatus: String?,
    val reportShareUrl: String?,
    val serverUpdatedAt: String
)

@Entity(tableName = "tasks", indices = [Index("jobId")])
data class TaskEntity(
    @PrimaryKey val id: String,
    val jobId: String,
    val sectionName: String,
    val sectionPosition: Int,
    val title: String,
    val instructions: String,
    val isRequired: Boolean,
    val requiresPhoto: Boolean,
    val position: Int,
    val status: String,
    val note: String,
    val updatedAt: Long?
)

@Entity(tableName = "issues", indices = [Index("jobId")])
data class IssueEntity(
    @PrimaryKey val id: String,
    val jobId: String,
    val room: String,
    val description: String,
    val severity: String,
    val phase: String,
    val resolution: String,
    val reportedAt: Long
)

@Entity(tableName = "photos", indices = [Index("jobId"), Index("uploadState")])
data class PhotoEntity(
    @PrimaryKey val id: String,
    val jobId: String,
    val taskId: String?,
    val issueId: String?,
    val kind: String,
    val room: String,
    /** App-private file; null for photos that only exist on the server. */
    val localPath: String?,
    val remoteThumbUrl: String?,
    val sha256: String?,
    val capturedAt: Long,
    val latitude: Double?,
    val longitude: Double?,
    val uploadState: String,
    val attempts: Int = 0,
    val lastError: String? = null
)

/** One queued offline change, pushed to /sync/push/ in [seq] order. */
@Entity(tableName = "mutations", indices = [Index("jobId"), Index(value = ["mutationId"], unique = true)])
data class MutationEntity(
    @PrimaryKey(autoGenerate = true) val seq: Long = 0,
    val mutationId: String,
    val jobId: String,
    val type: String,
    val payloadJson: String,
    val clientTimestamp: Long,
    val state: String = STATE_PENDING,
    val detail: String? = null
) {
    companion object {
        const val STATE_PENDING = "pending"

        /** Server refused it; kept so the user can see what didn't apply. */
        const val STATE_REJECTED = "rejected"
    }
}
