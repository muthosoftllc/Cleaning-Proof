package app.cleaningproof.util

import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.time.format.FormatStyle

fun Long.toIso(): String = Instant.ofEpochMilli(this).toString()

fun String.isoToMillis(): Long = Instant.parse(normalizeIso(this)).toEpochMilli()

/** Django emits offsets like "+00:00"; Instant.parse wants "Z" or an offset it can read. */
private fun normalizeIso(value: String): String =
    if (value.endsWith("+00:00")) {
        value.removeSuffix("+00:00") + "Z"
    } else {
        java.time.OffsetDateTime.parse(value).toInstant().toString()
    }

private val timeFormat = DateTimeFormatter.ofLocalizedTime(FormatStyle.SHORT)
private val dateTimeFormat = DateTimeFormatter.ofLocalizedDateTime(FormatStyle.MEDIUM, FormatStyle.SHORT)

fun Long.formatTime(): String = timeFormat.format(Instant.ofEpochMilli(this).atZone(ZoneId.systemDefault()))
fun Long.formatDateTime(): String = dateTimeFormat.format(Instant.ofEpochMilli(this).atZone(ZoneId.systemDefault()))
