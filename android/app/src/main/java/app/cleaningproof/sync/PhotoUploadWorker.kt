package app.cleaningproof.sync

import android.content.Context
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters
import app.cleaningproof.CleaningProofApp
import app.cleaningproof.data.local.PhotoEntity
import app.cleaningproof.data.local.UploadState
import app.cleaningproof.util.toIso
import java.io.File
import java.io.IOException
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.RequestBody
import okhttp3.RequestBody.Companion.asRequestBody
import okhttp3.RequestBody.Companion.toRequestBody

/**
 * Uploads captured photos. Uploads are idempotent (client-generated id) and
 * checksummed (SHA-256), so a retry after a dropped connection can never
 * duplicate or corrupt evidence. Local files are only released once the
 * server confirms them.
 */
class PhotoUploadWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {

    override suspend fun doWork(): Result {
        val container = (applicationContext as CleaningProofApp).container
        if (!container.session.loggedIn.value) return Result.success()
        val db = container.db
        var needsRetry = false
        val attempted = mutableSetOf<String>()

        while (true) {
            val batch = db.photos().pending(limit = 10).filter { it.id !in attempted }
            if (batch.isEmpty()) break
            for (photo in batch) {
                attempted += photo.id
                when (upload(photo)) {
                    Outcome.DONE -> Unit
                    Outcome.RETRY_LATER -> needsRetry = true
                    Outcome.OFFLINE -> return Result.retry()
                }
            }
        }
        return if (needsRetry) Result.retry() else Result.success()
    }

    private enum class Outcome { DONE, RETRY_LATER, OFFLINE }

    private suspend fun upload(photo: PhotoEntity): Outcome {
        val container = (applicationContext as CleaningProofApp).container
        val dao = container.db.photos()
        val path = photo.localPath
        val file = path?.let(::File)
        if (file == null || !file.exists()) {
            dao.setState(photo.id, UploadState.FAILED, "Photo file is missing on this device")
            return Outcome.DONE
        }
        val fields = buildMap<String, RequestBody> {
            put("id", photo.id.text())
            put("job", photo.jobId.text())
            put("kind", photo.kind.text())
            put("room", photo.room.text())
            put("captured_at", photo.capturedAt.toIso().text())
            photo.taskId?.let { put("job_task", it.text()) }
            photo.issueId?.let { put("issue", it.text()) }
            photo.sha256?.let { put("sha256", it.text()) }
            photo.latitude?.let { put("latitude", "%.6f".format(java.util.Locale.US, it).text()) }
            photo.longitude?.let { put("longitude", "%.6f".format(java.util.Locale.US, it).text()) }
        }
        val part = MultipartBody.Part.createFormData(
            "file",
            "${photo.id}.jpg",
            file.asRequestBody("image/jpeg".toMediaType())
        )
        val response = try {
            container.api.uploadPhoto(fields, part)
        } catch (e: IOException) {
            return Outcome.OFFLINE
        }
        return when {
            response.isSuccessful -> {
                dao.markUploaded(photo.id, response.body()?.thumbnailUrl)
                Outcome.DONE
            }
            // Its issue hasn't synced yet, or a transient server problem: keep and retry.
            response.code() == 409 || response.code() >= 500 || response.code() == 429 -> Outcome.RETRY_LATER
            response.code() == 400 && photo.attempts < MAX_ATTEMPTS -> {
                dao.setState(photo.id, UploadState.PENDING, response.errorBody()?.string()?.take(300))
                Outcome.RETRY_LATER
            }
            else -> {
                // Permanent refusal (403/404/repeated 400). The file stays on the device.
                dao.setState(photo.id, UploadState.FAILED, "HTTP ${response.code()}")
                Outcome.DONE
            }
        }
    }

    private fun String.text(): RequestBody = toRequestBody("text/plain".toMediaType())

    private companion object {
        const val MAX_ATTEMPTS = 5
    }
}
