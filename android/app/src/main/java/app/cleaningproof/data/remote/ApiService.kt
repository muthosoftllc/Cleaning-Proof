package app.cleaningproof.data.remote

import okhttp3.MultipartBody
import okhttp3.RequestBody
import retrofit2.Response
import retrofit2.http.Body
import retrofit2.http.GET
import retrofit2.http.HTTP
import retrofit2.http.Multipart
import retrofit2.http.POST
import retrofit2.http.Part
import retrofit2.http.PartMap
import retrofit2.http.Query

interface ApiService {
    @POST("auth/login/")
    suspend fun login(@Body body: LoginRequest): TokenResponse

    @POST("auth/register/")
    suspend fun register(@Body body: RegisterRequest): TokenResponse

    /** Revokes the refresh token server-side. */
    @POST("auth/logout/")
    suspend fun logout(@Body body: RefreshRequest): Response<Unit>

    @GET("organizations/")
    suspend fun organizations(): Page<OrganizationDto>

    @GET("sync/pull/")
    suspend fun pull(@Query("since") since: String?): PullResponse

    @POST("sync/push/")
    suspend fun push(@Body body: PushRequest): PushResponse

    /** Idempotent by the client-generated photo id: 201 new, 200 already stored. */
    @Multipart
    @POST("photos/")
    suspend fun uploadPhoto(
        @PartMap fields: Map<String, @JvmSuppressWildcards RequestBody>,
        @Part file: MultipartBody.Part
    ): Response<PhotoDto>

    @POST("devices/")
    suspend fun registerDevice(@Body body: DeviceRequest): Response<Unit>

    @HTTP(method = "DELETE", path = "devices/", hasBody = true)
    suspend fun unregisterDevice(@Body body: DeviceRequest): Response<Unit>

    @GET("billing/")
    suspend fun billing(): BillingStatusDto

    @POST("billing/google-play/verify/")
    suspend fun verifyPurchase(@Body body: VerifyPurchaseRequest): BillingStatusDto
}
