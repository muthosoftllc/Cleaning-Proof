package app.cleaningproof.camera

import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Matrix
import androidx.exifinterface.media.ExifInterface
import java.io.File
import java.security.MessageDigest
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.TimeZone
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

data class StoredPhoto(val file: File, val sha256: String)

/**
 * Turns a raw camera capture into compact evidence: downscaled to
 * [MAX_EDGE] px, JPEG [QUALITY], orientation baked in, timestamp (and GPS if
 * the cleaner allowed it) written to EXIF, SHA-256 computed for the
 * server-side integrity check. Files live in app-private storage only.
 */
class EvidenceStore(private val context: Context) {

    /** Root of all stored evidence, for wiping a previous user's data. */
    val rootDir: File get() = File(context.filesDir, "evidence")

    fun newCaptureFile(): File =
        File(context.cacheDir, "capture").apply { mkdirs() }.let { File(it, "${System.nanoTime()}.jpg") }

    suspend fun store(
        raw: File,
        jobId: String,
        photoId: String,
        capturedAt: Long,
        latitude: Double?,
        longitude: Double?
    ): StoredPhoto = withContext(Dispatchers.IO) {
        val dir = File(context.filesDir, "evidence/$jobId").apply { mkdirs() }
        val out = File(dir, "$photoId.jpg")
        val bitmap = decodeScaled(raw)
        try {
            out.outputStream().use { bitmap.compress(Bitmap.CompressFormat.JPEG, QUALITY, it) }
        } finally {
            bitmap.recycle()
        }
        ExifInterface(out).apply {
            val stamp = SimpleDateFormat("yyyy:MM:dd HH:mm:ss", Locale.US).format(Date(capturedAt))
            setAttribute(ExifInterface.TAG_DATETIME_ORIGINAL, stamp)
            setAttribute(ExifInterface.TAG_OFFSET_TIME_ORIGINAL, utcOffset(capturedAt))
            if (latitude != null && longitude != null) setLatLong(latitude, longitude)
            setAttribute(ExifInterface.TAG_SOFTWARE, "Cleaning Proof")
            saveAttributes()
        }
        raw.delete()
        StoredPhoto(out, sha256(out))
    }

    private fun decodeScaled(raw: File): Bitmap {
        val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        BitmapFactory.decodeFile(raw.path, bounds)
        var sample = 1
        while (maxOf(bounds.outWidth, bounds.outHeight) / (sample * 2) >= MAX_EDGE) sample *= 2
        val decoded = BitmapFactory.decodeFile(raw.path, BitmapFactory.Options().apply { inSampleSize = sample })
            ?: error("Could not decode captured image")
        val scale = MAX_EDGE.toFloat() / maxOf(decoded.width, decoded.height)
        val matrix = Matrix().apply {
            val rotation = ExifInterface(raw).rotationDegrees
            if (rotation != 0) postRotate(rotation.toFloat())
            if (scale < 1f) postScale(scale, scale)
        }
        if (matrix.isIdentity) return decoded
        return Bitmap.createBitmap(decoded, 0, 0, decoded.width, decoded.height, matrix, true).also {
            if (it !== decoded) decoded.recycle()
        }
    }

    private fun utcOffset(at: Long): String {
        val minutes = TimeZone.getDefault().getOffset(at) / 60_000
        val sign = if (minutes >= 0) "+" else "-"
        return "%s%02d:%02d".format(Locale.US, sign, kotlin.math.abs(minutes) / 60, kotlin.math.abs(minutes) % 60)
    }

    companion object {
        const val MAX_EDGE = 2048
        const val QUALITY = 82

        fun sha256(file: File): String {
            val digest = MessageDigest.getInstance("SHA-256")
            file.inputStream().use { input ->
                val buffer = ByteArray(64 * 1024)
                while (true) {
                    val read = input.read(buffer)
                    if (read < 0) break
                    digest.update(buffer, 0, read)
                }
            }
            return digest.digest().joinToString("") { "%02x".format(it) }
        }
    }
}
