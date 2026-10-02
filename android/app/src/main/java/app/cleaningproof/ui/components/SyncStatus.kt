package app.cleaningproof.ui.components

import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CloudDone
import androidx.compose.material.icons.filled.CloudUpload
import androidx.compose.material3.AssistChip
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable

/** Always visible: cleaners must be able to trust that evidence has left the phone. */
@Composable
fun SyncStatusChip(pendingChanges: Int, pendingPhotos: Int, onClick: () -> Unit) {
    val synced = pendingChanges == 0 && pendingPhotos == 0
    AssistChip(
        onClick = onClick,
        leadingIcon = { Icon(if (synced) Icons.Filled.CloudDone else Icons.Filled.CloudUpload, null) },
        label = {
            Text(
                when {
                    synced -> "All synced"
                    pendingPhotos > 0 -> "$pendingPhotos photo(s) waiting"
                    else -> "$pendingChanges change(s) waiting"
                }
            )
        }
    )
}
