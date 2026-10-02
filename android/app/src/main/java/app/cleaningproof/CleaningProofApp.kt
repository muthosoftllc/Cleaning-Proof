package app.cleaningproof

import android.app.Application
import androidx.work.Configuration
import app.cleaningproof.push.PushService

class CleaningProofApp : Application(), Configuration.Provider {
    lateinit var container: AppContainer
        private set

    override val workManagerConfiguration: Configuration
        get() = Configuration.Builder().setMinimumLoggingLevel(android.util.Log.INFO).build()

    override fun onCreate() {
        super.onCreate()
        container = AppContainer(this)
        PushService.createChannels(this)
        if (container.session.loggedIn.value) {
            container.syncScheduler.schedulePeriodic()
            // Resume anything left in the queue from a previous session.
            container.syncScheduler.requestSync()
            container.syncScheduler.requestPhotoUpload()
        }
    }
}
