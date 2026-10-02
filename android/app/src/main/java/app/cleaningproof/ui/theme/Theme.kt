package app.cleaningproof.ui.theme

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

val Brand = Color(0xFF0F766E)
val Done = Color(0xFF15803D)
val Warn = Color(0xFFB45309)
val Bad = Color(0xFFB91C1C)

private val Light = lightColorScheme(
    primary = Brand,
    onPrimary = Color.White,
    primaryContainer = Color(0xFFCCF0EA),
    onPrimaryContainer = Color(0xFF00201C),
    secondary = Color(0xFF4A635F),
    surface = Color(0xFFFAFDFB),
    background = Color(0xFFF5F7F7)
)

private val Dark = darkColorScheme(
    primary = Color(0xFF7ED8C9),
    onPrimary = Color(0xFF003731),
    primaryContainer = Color(0xFF005048),
    secondary = Color(0xFFB1CCC6)
)

@Composable
fun CleaningProofTheme(content: @Composable () -> Unit) {
    MaterialTheme(colorScheme = if (isSystemInDarkTheme()) Dark else Light, content = content)
}
