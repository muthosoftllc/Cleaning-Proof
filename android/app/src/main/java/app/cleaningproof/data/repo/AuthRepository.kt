package app.cleaningproof.data.repo

import app.cleaningproof.data.remote.ApiService
import app.cleaningproof.data.remote.LoginRequest
import app.cleaningproof.data.remote.RegisterRequest
import app.cleaningproof.data.remote.SessionStore

class AuthRepository(private val api: ApiService, private val session: SessionStore) {

    suspend fun login(email: String, password: String) {
        val tokens = api.login(LoginRequest(email.trim(), password))
        session.saveTokens(tokens.access, tokens.refresh)
        session.userName = tokens.user?.fullName?.ifBlank { null } ?: tokens.user?.email
        selectDefaultOrganization()
    }

    suspend fun register(email: String, password: String, name: String, business: String) {
        val tokens = api.register(RegisterRequest(email.trim(), password, name, business))
        session.saveTokens(tokens.access, tokens.refresh)
        session.userName = name.ifBlank { email }
        selectDefaultOrganization()
    }

    private suspend fun selectDefaultOrganization() {
        val orgs = api.organizations().results
        val current = orgs.firstOrNull { it.id == session.organizationId } ?: orgs.firstOrNull()
        if (current?.id != session.organizationId) session.lastPull = null
        session.organizationId = current?.id
        session.role = current?.role
    }

    fun logout() = session.clear()
}
