package app.cleaningproof.data.remote

import android.content.Context
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow

/** Tokens and session state in encrypted preferences (Android Keystore backed). */
class SessionStore(context: Context) {
    private val prefs = EncryptedSharedPreferences.create(
        context,
        "session",
        MasterKey.Builder(context).setKeyScheme(MasterKey.KeyScheme.AES256_GCM).build(),
        EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
        EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM
    )

    private val _loggedIn = MutableStateFlow(accessToken != null)
    val loggedIn: StateFlow<Boolean> = _loggedIn

    val accessToken: String? get() = prefs.getString(KEY_ACCESS, null)
    val refreshToken: String? get() = prefs.getString(KEY_REFRESH, null)

    var organizationId: String?
        get() = prefs.getString(KEY_ORG, null)
        set(value) = prefs.edit().putString(KEY_ORG, value).apply()

    var role: String?
        get() = prefs.getString(KEY_ROLE, null)
        set(value) = prefs.edit().putString(KEY_ROLE, value).apply()

    var userName: String?
        get() = prefs.getString(KEY_NAME, null)
        set(value) = prefs.edit().putString(KEY_NAME, value).apply()

    /** Server time of the last successful pull; the next pull asks for changes since then. */
    var lastPull: String?
        get() = prefs.getString(KEY_LAST_PULL, null)
        set(value) = prefs.edit().putString(KEY_LAST_PULL, value).apply()

    fun saveTokens(access: String, refresh: String?) {
        val editor = prefs.edit().putString(KEY_ACCESS, access)
        if (refresh != null) editor.putString(KEY_REFRESH, refresh)
        editor.apply()
        _loggedIn.value = true
    }

    /** Clears credentials only. Local evidence is kept so nothing captured offline is lost;
     *  it uploads after the next login. */
    fun clear() {
        prefs.edit().remove(KEY_ACCESS).remove(KEY_REFRESH).apply()
        _loggedIn.value = false
    }

    private companion object {
        const val KEY_ACCESS = "access"
        const val KEY_REFRESH = "refresh"
        const val KEY_ORG = "org"
        const val KEY_ROLE = "role"
        const val KEY_NAME = "name"
        const val KEY_LAST_PULL = "last_pull"
    }
}
