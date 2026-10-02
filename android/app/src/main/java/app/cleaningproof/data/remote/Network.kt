package app.cleaningproof.data.remote

import app.cleaningproof.BuildConfig
import java.util.concurrent.TimeUnit
import kotlinx.serialization.json.Json
import okhttp3.Authenticator
import okhttp3.Interceptor
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response
import okhttp3.Route
import okhttp3.logging.HttpLoggingInterceptor
import retrofit2.Retrofit
import retrofit2.converter.kotlinx.serialization.asConverterFactory

val AppJson = Json {
    ignoreUnknownKeys = true
    explicitNulls = false
    encodeDefaults = true
}

/** Adds the bearer token and the active organization header. */
class AuthInterceptor(private val session: SessionStore) : Interceptor {
    override fun intercept(chain: Interceptor.Chain): Response {
        val builder = chain.request().newBuilder()
        session.accessToken?.let { builder.header("Authorization", "Bearer $it") }
        session.organizationId?.let { builder.header("X-Organization", it) }
        return chain.proceed(builder.build())
    }
}

/** On 401, rotates the refresh token once and retries. A failed refresh logs out. */
class TokenAuthenticator(private val session: SessionStore, private val baseUrl: String) : Authenticator {
    private val client = OkHttpClient.Builder().callTimeout(30, TimeUnit.SECONDS).build()

    @Synchronized
    override fun authenticate(route: Route?, response: Response): Request? {
        if (response.request.header("X-Retried") != null) return null
        val sentToken = response.request.header("Authorization")?.removePrefix("Bearer ")
        if (sentToken != null && sentToken != session.accessToken) {
            // Another request already refreshed.
            return retry(response)
        }
        val refresh = session.refreshToken ?: return null
        val body = AppJson.encodeToString(RefreshRequest.serializer(), RefreshRequest(refresh))
            .toRequestBody("application/json".toMediaType())
        val result = runCatching {
            client.newCall(Request.Builder().url(baseUrl + "auth/refresh/").post(body).build()).execute()
        }.getOrNull() ?: return null // offline: keep tokens, try later
        result.use {
            if (it.code == 401 || it.code == 400) {
                session.clear()
                return null
            }
            if (!it.isSuccessful) return null
            val tokens = AppJson.decodeFromString(TokenResponse.serializer(), it.body!!.string())
            session.saveTokens(tokens.access, tokens.refresh)
        }
        return retry(response)
    }

    private fun retry(response: Response): Request =
        response.request.newBuilder()
            .header("Authorization", "Bearer ${session.accessToken}")
            .header("X-Retried", "1")
            .build()
}

fun buildApi(session: SessionStore): ApiService {
    val baseUrl = BuildConfig.API_BASE_URL
    val client = OkHttpClient.Builder()
        .addInterceptor(AuthInterceptor(session))
        .authenticator(TokenAuthenticator(session, baseUrl))
        .connectTimeout(20, TimeUnit.SECONDS)
        .readTimeout(60, TimeUnit.SECONDS)
        .writeTimeout(120, TimeUnit.SECONDS) // photo uploads on slow connections
        .apply {
            if (BuildConfig.DEBUG) {
                addInterceptor(HttpLoggingInterceptor().setLevel(HttpLoggingInterceptor.Level.BASIC))
            }
        }
        .build()
    return Retrofit.Builder()
        .baseUrl(baseUrl)
        .client(client)
        .addConverterFactory(AppJson.asConverterFactory("application/json".toMediaType()))
        .build()
        .create(ApiService::class.java)
}
