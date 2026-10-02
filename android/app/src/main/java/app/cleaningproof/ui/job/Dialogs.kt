package app.cleaningproof.ui.job

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.FilterChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import app.cleaningproof.data.local.TaskEntity

private val SEVERITIES = listOf("low" to "Minor", "medium" to "Moderate", "high" to "Severe")
private val PHASES = listOf(
    "before_cleaning" to "Was already there",
    "during_cleaning" to "Found while cleaning"
)
private val SKIP_REASONS = listOf("Not accessible", "Not needed", "Customer request", "Out of supplies")

@OptIn(ExperimentalLayoutApi::class)
@Composable
fun IssueDialog(
    rooms: List<String>,
    onDismiss: () -> Unit,
    onSave: (room: String, description: String, severity: String, phase: String, takePhoto: Boolean) -> Unit
) {
    var room by rememberSaveable { mutableStateOf(rooms.firstOrNull().orEmpty()) }
    var description by rememberSaveable { mutableStateOf("") }
    var severity by rememberSaveable { mutableStateOf("low") }
    var phase by rememberSaveable { mutableStateOf("before_cleaning") }

    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Report an issue") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text("Room", style = MaterialTheme.typography.labelLarge)
                FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    (rooms + "Other").forEach { FilterChip(room == it, { room = it }, label = { Text(it) }) }
                }
                OutlinedTextField(
                    description,
                    { description = it },
                    label = { Text("What did you find?") },
                    placeholder = { Text("e.g. Stain on carpet by the window") },
                    minLines = 2,
                    modifier = Modifier.fillMaxWidth()
                )
                FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    SEVERITIES.forEach { (value, label) ->
                        FilterChip(severity == value, { severity = value }, label = { Text(label) })
                    }
                }
                FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    PHASES.forEach { (value, label) ->
                        FilterChip(phase == value, { phase = value }, label = { Text(label) })
                    }
                }
            }
        },
        confirmButton = {
            Button(enabled = description.isNotBlank(), onClick = { onSave(room, description, severity, phase, true) }) {
                Text("Save + photo")
            }
        },
        dismissButton = {
            OutlinedButton(enabled = description.isNotBlank(), onClick = {
                onSave(room, description, severity, phase, false)
            }) {
                Text("Save")
            }
        }
    )
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
fun SkipDialog(task: TaskEntity, onDismiss: () -> Unit, onSkip: (String) -> Unit) {
    var reason by rememberSaveable { mutableStateOf("") }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Skip \"${task.title}\"?") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    SKIP_REASONS.forEach { FilterChip(reason == it, { reason = it }, label = { Text(it) }) }
                }
                OutlinedTextField(reason, {
                    reason = it
                }, label = { Text("Reason") }, modifier = Modifier.fillMaxWidth())
            }
        },
        confirmButton = { Button(enabled = reason.isNotBlank(), onClick = { onSkip(reason) }) { Text("Skip task") } },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel") } }
    )
}
