package app.cleaningproof.data.local

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import androidx.room.Upsert
import kotlinx.coroutines.flow.Flow

@Dao
interface JobDao {
    @Query(
        "SELECT * FROM jobs WHERE scheduledStart BETWEEN :from AND :to AND status != 'cancelled' ORDER BY scheduledStart"
    )
    fun observeBetween(from: Long, to: Long): Flow<List<JobEntity>>

    @Query("SELECT * FROM jobs WHERE status = 'in_progress' ORDER BY scheduledStart")
    fun observeInProgress(): Flow<List<JobEntity>>

    @Query("SELECT * FROM jobs WHERE id = :id")
    fun observe(id: String): Flow<JobEntity?>

    @Query("SELECT * FROM jobs WHERE id = :id")
    suspend fun get(id: String): JobEntity?

    @Query("SELECT id FROM jobs")
    suspend fun allIds(): List<String>

    @Upsert
    suspend fun upsert(job: JobEntity)

    @Query("UPDATE jobs SET status = :status, startedAt = COALESCE(startedAt, :startedAt) WHERE id = :id")
    suspend fun markStarted(id: String, status: String, startedAt: Long)

    @Query("UPDATE jobs SET status = :status, completedAt = :completedAt, notes = :notes WHERE id = :id")
    suspend fun markCompleted(id: String, status: String, completedAt: Long, notes: String)

    @Query("UPDATE jobs SET notes = :notes WHERE id = :id")
    suspend fun updateNotes(id: String, notes: String)

    @Query("DELETE FROM jobs WHERE id = :id")
    suspend fun delete(id: String)
}

@Dao
interface TaskDao {
    @Query("SELECT * FROM tasks WHERE jobId = :jobId ORDER BY sectionPosition, position")
    fun observeForJob(jobId: String): Flow<List<TaskEntity>>

    @Query("SELECT * FROM tasks WHERE jobId = :jobId")
    suspend fun forJob(jobId: String): List<TaskEntity>

    @Query("UPDATE tasks SET status = :status, note = :note, updatedAt = :updatedAt WHERE id = :id")
    suspend fun update(id: String, status: String, note: String, updatedAt: Long)

    @Upsert
    suspend fun upsertAll(tasks: List<TaskEntity>)

    @Query("DELETE FROM tasks WHERE jobId = :jobId")
    suspend fun deleteForJob(jobId: String)
}

@Dao
interface IssueDao {
    @Query("SELECT * FROM issues WHERE jobId = :jobId ORDER BY reportedAt")
    fun observeForJob(jobId: String): Flow<List<IssueEntity>>

    @Upsert
    suspend fun upsert(issue: IssueEntity)

    @Upsert
    suspend fun upsertAll(issues: List<IssueEntity>)

    @Query("DELETE FROM issues WHERE jobId = :jobId")
    suspend fun deleteForJob(jobId: String)
}

@Dao
interface PhotoDao {
    @Query("SELECT * FROM photos WHERE jobId = :jobId ORDER BY capturedAt")
    fun observeForJob(jobId: String): Flow<List<PhotoEntity>>

    @Query("SELECT id FROM photos WHERE jobId = :jobId")
    suspend fun idsForJob(jobId: String): List<String>

    @Query("SELECT * FROM photos WHERE uploadState = 'pending' ORDER BY capturedAt LIMIT :limit")
    suspend fun pending(limit: Int = 20): List<PhotoEntity>

    @Query("SELECT COUNT(*) FROM photos WHERE uploadState = 'pending'")
    fun observePendingCount(): Flow<Int>

    @Query("SELECT COUNT(*) FROM photos WHERE jobId = :jobId AND uploadState = 'pending'")
    suspend fun pendingCountForJob(jobId: String): Int

    /** Evidence that hasn't been confirmed by the server (pending or refused). */
    @Query("SELECT COUNT(*) FROM photos WHERE uploadState != 'uploaded'")
    suspend fun unconfirmedCount(): Int

    @Query("SELECT localPath FROM photos WHERE jobId = :jobId AND uploadState = 'uploaded' AND localPath IS NOT NULL")
    suspend fun uploadedLocalPaths(jobId: String): List<String>

    @Query("DELETE FROM photos WHERE jobId = :jobId AND uploadState = 'uploaded'")
    suspend fun deleteUploadedForJob(jobId: String)

    @Insert(onConflict = OnConflictStrategy.IGNORE)
    suspend fun insertIfAbsent(photo: PhotoEntity)

    @Upsert
    suspend fun upsert(photo: PhotoEntity)

    @Query("UPDATE photos SET uploadState = :state, attempts = attempts + 1, lastError = :error WHERE id = :id")
    suspend fun setState(id: String, state: String, error: String?)

    @Query("UPDATE photos SET uploadState = 'uploaded', remoteThumbUrl = :thumbUrl, lastError = NULL WHERE id = :id")
    suspend fun markUploaded(id: String, thumbUrl: String?)
}

@Dao
interface MutationDao {
    @Query("SELECT * FROM mutations WHERE state = 'pending' ORDER BY seq LIMIT :limit")
    suspend fun pending(limit: Int = 100): List<MutationEntity>

    @Query("SELECT COUNT(*) FROM mutations WHERE state = 'pending'")
    fun observePendingCount(): Flow<Int>

    @Query("SELECT * FROM mutations WHERE state = 'rejected' ORDER BY seq DESC")
    fun observeRejected(): Flow<List<MutationEntity>>

    @Query("SELECT COUNT(*) FROM mutations WHERE jobId = :jobId AND state = 'pending'")
    suspend fun pendingCountForJob(jobId: String): Int

    /** Pending or rejected: both still hold work the server doesn't have. */
    @Query("SELECT COUNT(*) FROM mutations")
    suspend fun totalCount(): Int

    @Insert
    suspend fun insert(mutation: MutationEntity)

    @Query("DELETE FROM mutations WHERE mutationId = :mutationId")
    suspend fun delete(mutationId: String)

    @Query("UPDATE mutations SET state = 'rejected', detail = :detail WHERE mutationId = :mutationId")
    suspend fun markRejected(mutationId: String, detail: String?)
}
