package app.cleaningproof.data.repo

import app.cleaningproof.camera.EvidenceStore
import app.cleaningproof.data.remote.ApiService
import app.cleaningproof.data.remote.LoginRequest
import app.cleaningproof.data.remote.RefreshRequest
import app.cleaningproof.data.remote.RegisterRequest
import app.cleaningproof.data.remote.SessionStore
import app.cleaningproof.data.remote.TokenResponse
import app.cleaningproof.push.PushTokens
import kotlinx.coroutines.withTimeoutOrNull

/** Another user still has evidence on this device that hasn't reached the server. */
class UnsyncedWorkOnDevice(val ownerName: String?) : Exception(
    "This phone has unsynced work from ${ownerName ?: "another user"}. " +
        "They need to sign in and sync before someone else can use it."
)

class AuthRepository(
    private val api: ApiService,
    private val session: SessionStore,
    private val jobs: JobRepository,
    private val evidence: EvidenceStore
) {

    suspend fun login(email: String, password: String) =
        startSession(api.login(LoginRequest(email.trim(), password)), fallbackName = email)

    suspend fun register(email: String, password: String, name: String, business: String) =
        startSession(api.register(RegisterRequest(email.trim(), password, name, business)), fallbackName = name)

    /**
     * Shared devices are common (one company phone per van). Local data
     * belongs to exactly one user: switching users wipes it, but never while
     * the previous user still has evidence the server hasn't accepted.
     */
    private suspend fun startSession(tokens: TokenResponse, fallbackName: String) {
        val userId = tokens.user?.id
        val previousOwner = session.userId
        if (previousOwner != null && userId != null && previousOwner != userId) {
            if (jobs.hasUnsyncedWork()) {
                tokens.refresh?.let { runCatching { api.logout(RefreshRequest(it)) } }
                throw UnsyncedWorkOnDevice(session.userName)
            }
            jobs.wipeLocalData(evidence.rootDir)
            session.lastPull = null
        }
        session.saveTokens(tokens.access, tokens.refresh)
        session.userId = userId
        session.userName = tokens.user?.fullName?.ifBlank { null } ?: tokens.user?.email ?: fallbackName
        selectDefaultOrganization()
        PushTokens.register(api)
    }

    private suspend fun selectDefaultOrganization() {
        val orgs = api.organizations().results
        val current = orgs.firstOrNull { it.id == session.organizationId } ?: orgs.firstOrNull()
        if (current?.id != session.organizationId) session.lastPull = null
        session.organizationId = current?.id
        session.role = current?.role
    }

    /**
     * Revoke the refresh token server-side (best effort: offline logout still
     * works locally). Local evidence is kept so nothing unsynced is lost.
     */
    suspend fun logout() {
        withTimeoutOrNull(LOGOUT_TIMEOUT_MS) {
            PushTokens.unregister(api)
            session.refreshToken?.let { runCatching { api.logout(RefreshRequest(it)) } }
        }
        session.clear()
    }

    private companion object {
        const val LOGOUT_TIMEOUT_MS = 3_000L
    }
}
