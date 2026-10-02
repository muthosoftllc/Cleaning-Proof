package app.cleaningproof.sync

import android.content.Context
import android.util.Log
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters
import app.cleaningproof.CleaningProofApp
import app.cleaningproof.data.remote.AppJson
import app.cleaningproof.data.remote.MutationDto
import app.cleaningproof.data.remote.PushRequest
import app.cleaningproof.util.toIso
import java.io.IOException
import kotlinx.serialization.json.JsonObject
import retrofit2.HttpException

/**
 * Local data -> sync queue -> server, then server -> local.
 *
 * Mutations are pushed strictly in order. Each result is handled
 * individually: accepted ones leave the queue, rejected ones stay (marked)
 * so the cleaner can see exactly what the office refused. Nothing is dropped
 * silently.
 */
class SyncWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {

    override suspend fun doWork(): Result {
        val container = (applicationContext as CleaningProofApp).container
        val session = container.session
        if (!session.loggedIn.value) return Result.success()
        val db = container.db
        val api = container.api

        return try {
            while (true) {
                val batch = db.mutations().pending(limit = 100)
                if (batch.isEmpty()) break
                val response = api.push(
                    PushRequest(
                        batch.map {
                            MutationDto(
                                id = it.mutationId,
                                type = it.type,
                                jobId = it.jobId,
                                clientTimestamp = it.clientTimestamp.toIso(),
                                payload = AppJson.decodeFromString(JsonObject.serializer(), it.payloadJson)
                            )
                        }
                    )
                )
                // Defensive: never spin if the server answered for none of the batch.
                val answered = response.results.map { it.id }.toSet()
                if (batch.none { it.mutationId in answered }) return Result.retry()
                for (result in response.results) {
                    when (result.status) {
                        "applied", "duplicate", "ignored_stale" -> db.mutations().delete(result.id)
                        else -> db.mutations().markRejected(result.id, result.detail)
                    }
                }
            }
            val orgId = session.organizationId
            if (orgId != null) {
                val pull = api.pull(since = session.lastPull)
                container.jobs.applyPull(orgId, pull)
                session.lastPull = pull.serverTime
            }
            container.syncScheduler.requestPhotoUpload()
            Result.success()
        } catch (e: IOException) {
            Result.retry() // offline or flaky connection
        } catch (e: HttpException) {
            Log.w(TAG, "Sync failed: HTTP ${e.code()}")
            if (e.code() == 401 || e.code() in 400..499) Result.failure() else Result.retry()
        }
    }

    private companion object {
        const val TAG = "SyncWorker"
    }
}
