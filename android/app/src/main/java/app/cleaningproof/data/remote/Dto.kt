package app.cleaningproof.data.remote

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonObject

@Serializable
data class LoginRequest(val email: String, val password: String)

@Serializable
data class RefreshRequest(val refresh: String)

@Serializable
data class TokenResponse(val access: String, val refresh: String? = null, val user: UserDto? = null)

@Serializable
data class RegisterRequest(
    val email: String,
    val password: String,
    @SerialName("full_name") val fullName: String = "",
    @SerialName("organization_name") val organizationName: String = ""
)

@Serializable
data class UserDto(val id: String, val email: String, @SerialName("full_name") val fullName: String = "")

@Serializable
data class OrganizationDto(val id: String, val name: String, val role: String? = null)

@Serializable
data class Page<T>(val count: Int, val results: List<T>)

@Serializable
data class PropertyBriefDto(
    val id: String,
    val name: String,
    @SerialName("address_line1") val addressLine1: String = "",
    val city: String = "",
    @SerialName("cleaning_instructions") val cleaningInstructions: String = "",
    @SerialName("access_notes") val accessNotes: String = ""
)

@Serializable
data class TaskDto(
    val id: String,
    @SerialName("section_name") val sectionName: String,
    @SerialName("section_position") val sectionPosition: Int,
    val title: String,
    val instructions: String = "",
    @SerialName("is_required") val isRequired: Boolean,
    @SerialName("requires_photo") val requiresPhoto: Boolean,
    val position: Int,
    val status: String,
    val note: String = ""
)

@Serializable
data class IssueDto(
    val id: String,
    val room: String = "",
    val description: String,
    val severity: String,
    val phase: String,
    val resolution: String,
    @SerialName("reported_at") val reportedAt: String
)

@Serializable
data class PhotoDto(
    val id: String,
    val kind: String,
    @SerialName("job_task") val jobTask: String? = null,
    val issue: String? = null,
    val room: String = "",
    @SerialName("captured_at") val capturedAt: String,
    @SerialName("thumbnail_url") val thumbnailUrl: String? = null
)

@Serializable
data class ReportBriefDto(
    val number: String,
    val status: String,
    @SerialName("share_url") val shareUrl: String,
    @SerialName("verify_url") val verifyUrl: String,
    @SerialName("pdf_url") val pdfUrl: String? = null
)

@Serializable
data class JobDto(
    val id: String,
    val title: String = "",
    @SerialName("property_detail") val property: PropertyBriefDto,
    @SerialName("scheduled_start") val scheduledStart: String,
    @SerialName("scheduled_end") val scheduledEnd: String? = null,
    val status: String,
    val instructions: String = "",
    val notes: String = "",
    @SerialName("started_at") val startedAt: String? = null,
    @SerialName("completed_at") val completedAt: String? = null,
    val tasks: List<TaskDto> = emptyList(),
    val issues: List<IssueDto> = emptyList(),
    val photos: List<PhotoDto> = emptyList(),
    val report: ReportBriefDto? = null,
    @SerialName("updated_at") val updatedAt: String
)

@Serializable
data class PullResponse(
    @SerialName("server_time") val serverTime: String,
    val jobs: List<JobDto>,
    @SerialName("active_job_ids") val activeJobIds: List<String>
)

@Serializable
data class MutationDto(
    val id: String,
    val type: String,
    @SerialName("job_id") val jobId: String,
    @SerialName("client_timestamp") val clientTimestamp: String,
    val payload: JsonObject
)

@Serializable
data class PushRequest(val mutations: List<MutationDto>)

@Serializable
data class MutationResult(
    val id: String,
    val status: String,
    val detail: String? = null,
    @SerialName("original_status") val originalStatus: String? = null
)

@Serializable
data class PushResponse(val results: List<MutationResult>)

@Serializable
data class DeviceRequest(
    val token: String,
    val platform: String = "android",
    @SerialName("app_version") val appVersion: String
)

@Serializable
data class VerifyPurchaseRequest(
    @SerialName("product_id") val productId: String,
    @SerialName("purchase_token") val purchaseToken: String
)

@Serializable
data class BillingStatusDto(
    val plan: String,
    @SerialName("plan_name") val planName: String,
    val features: List<String>
)
