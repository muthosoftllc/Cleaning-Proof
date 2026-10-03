package app.cleaningproof

import android.content.Context
import app.cleaningproof.billing.BillingManager
import app.cleaningproof.camera.EvidenceStore
import app.cleaningproof.data.local.AppDatabase
import app.cleaningproof.data.remote.SessionStore
import app.cleaningproof.data.remote.buildApi
import app.cleaningproof.data.repo.AuthRepository
import app.cleaningproof.data.repo.JobRepository
import app.cleaningproof.location.LocationProvider
import app.cleaningproof.sync.SyncScheduler

/** Manual dependency container: small enough that a DI framework isn't worth it yet. */
class AppContainer(context: Context) {
    val session = SessionStore(context)
    val db = AppDatabase.build(context)
    val api = buildApi(session)
    val syncScheduler = SyncScheduler(context)
    val jobs = JobRepository(db, syncScheduler)
    val evidence = EvidenceStore(context)
    val auth = AuthRepository(api, session, jobs, evidence)
    val location = LocationProvider(context)
    val billing by lazy { BillingManager(context, api, session) }
}
