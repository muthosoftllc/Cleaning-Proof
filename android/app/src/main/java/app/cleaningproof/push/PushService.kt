package app.cleaningproof.push

import android.Manifest
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import app.cleaningproof.BuildConfig
import app.cleaningproof.CleaningProofApp
import app.cleaningproof.R
import app.cleaningproof.data.remote.DeviceRequest
import app.cleaningproof.ui.MainActivity
import com.google.firebase.messaging.FirebaseMessagingService
import com.google.firebase.messaging.RemoteMessage
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch

class PushService : FirebaseMessagingService() {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    override fun onNewToken(token: String) {
        val container = (application as CleaningProofApp).container
        if (!container.session.loggedIn.value) return
        scope.launch {
            runCatching { container.api.registerDevice(DeviceRequest(token, appVersion = BuildConfig.VERSION_NAME)) }
        }
    }

    override fun onMessageReceived(message: RemoteMessage) {
        val container = (application as CleaningProofApp).container
        // Any server event may change assigned jobs: refresh in the background.
        container.syncScheduler.requestSync()
        val title = message.notification?.title ?: message.data["title"] ?: return
        val body = message.notification?.body ?: message.data["body"].orEmpty()
        val kind = message.data["kind"].orEmpty()
        val channel = if (kind.startsWith("job_") || kind == "recurring_job_created") CHANNEL_JOBS else CHANNEL_REPORTS
        show(this, title, body, channel, message.data["job_id"])
    }

    companion object {
        const val CHANNEL_JOBS = "jobs"
        const val CHANNEL_REPORTS = "reports"
        const val EXTRA_JOB_ID = "job_id"

        fun createChannels(context: Context) {
            val manager = context.getSystemService(NotificationManager::class.java)
            manager.createNotificationChannel(
                NotificationChannel(
                    CHANNEL_JOBS,
                    context.getString(R.string.channel_jobs),
                    NotificationManager.IMPORTANCE_HIGH
                )
            )
            manager.createNotificationChannel(
                NotificationChannel(
                    CHANNEL_REPORTS,
                    context.getString(R.string.channel_reports),
                    NotificationManager.IMPORTANCE_DEFAULT
                )
            )
        }

        fun show(context: Context, title: String, body: String, channel: String, jobId: String?) {
            if (ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS) !=
                PackageManager.PERMISSION_GRANTED
            ) {
                return
            }
            val intent = Intent(context, MainActivity::class.java)
                .addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP or Intent.FLAG_ACTIVITY_CLEAR_TOP)
                .putExtra(EXTRA_JOB_ID, jobId)
            val pending = PendingIntent.getActivity(
                context,
                (jobId ?: title).hashCode(),
                intent,
                PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
            )
            val notification = NotificationCompat.Builder(context, channel)
                .setSmallIcon(R.drawable.ic_launcher)
                .setContentTitle(title)
                .setContentText(body)
                .setAutoCancel(true)
                .setContentIntent(pending)
                .build()
            NotificationManagerCompat.from(context).notify((jobId ?: title).hashCode(), notification)
        }
    }
}
