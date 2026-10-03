package app.cleaningproof.push

import app.cleaningproof.BuildConfig
import app.cleaningproof.data.remote.ApiService
import app.cleaningproof.data.remote.DeviceRequest
import com.google.firebase.messaging.FirebaseMessaging
import kotlinx.coroutines.tasks.await

/**
 * Binds this device's FCM token to whoever is signed in. Best effort: push is
 * optional (no google-services.json in dev builds) and must never block auth.
 */
object PushTokens {
    private suspend fun current(): String? = runCatching { FirebaseMessaging.getInstance().token.await() }.getOrNull()

    suspend fun register(api: ApiService) {
        val token = current() ?: return
        runCatching { api.registerDevice(DeviceRequest(token, appVersion = BuildConfig.VERSION_NAME)) }
    }

    /** Stop pushes for the signed-out user reaching this (possibly shared) device. */
    suspend fun unregister(api: ApiService) {
        val token = current() ?: return
        runCatching { api.unregisterDevice(DeviceRequest(token, appVersion = BuildConfig.VERSION_NAME)) }
    }
}
