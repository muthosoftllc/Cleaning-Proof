package app.cleaningproof.ui.job

import android.Manifest
import android.content.Intent
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.CameraAlt
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.CloudUpload
import androidx.compose.material.icons.filled.PhotoCamera
import androidx.compose.material.icons.filled.RadioButtonUnchecked
import androidx.compose.material.icons.filled.RemoveCircle
import androidx.compose.material.icons.filled.ReportProblem
import androidx.compose.material.icons.filled.Share
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import app.cleaningproof.data.local.JobStatus
import app.cleaningproof.data.local.PhotoEntity
import app.cleaningproof.data.local.PhotoKind
import app.cleaningproof.data.local.TaskEntity
import app.cleaningproof.data.local.TaskStatus
import app.cleaningproof.data.local.UploadState
import app.cleaningproof.ui.CameraArgs
import app.cleaningproof.ui.containerViewModel
import app.cleaningproof.ui.jobs.StatusLabel
import app.cleaningproof.ui.theme.Done
import app.cleaningproof.ui.theme.Warn
import app.cleaningproof.util.formatDateTime
import coil.compose.AsyncImage
import java.io.File

/**
 * Job execution: one scrolling screen, top to bottom in the order work
 * happens. Tap a task to tick it; long-press to skip with a reason; camera
 * buttons sit next to what they document.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun JobScreen(jobId: String, onBack: () -> Unit, onCamera: (CameraArgs) -> Unit) {
    val vm = containerViewModel(key = jobId) { JobViewModel(it, jobId) }
    val state by vm.state.collectAsStateWithLifecycle()
    val snackbar = remember { SnackbarHostState() }
    var showIssue by rememberSaveable { mutableStateOf(false) }
    var showFinish by rememberSaveable { mutableStateOf(false) }
    var skipping by remember { mutableStateOf<TaskEntity?>(null) }
    var notes by rememberSaveable(state.job?.id) { mutableStateOf(state.job?.notes.orEmpty()) }
    val locationPermission = rememberLauncherForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) {
        vm.start()
    }

    LaunchedEffect(Unit) { vm.messages.collect { snackbar.showSnackbar(it) } }
    LaunchedEffect(state.job?.notes) { if (notes.isEmpty()) notes = state.job?.notes.orEmpty() }

    val job = state.job
    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text(job?.title ?: "") },
                navigationIcon = { IconButton(onClick = onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Back") } },
                actions = {
                    job?.let {
                        StatusLabel(it.status)
                        Spacer(Modifier.width(12.dp))
                    }
                }
            )
        },
        snackbarHost = { SnackbarHost(snackbar) }
    ) { padding ->
        if (job == null) return@Scaffold
        val editable = job.status == JobStatus.SCHEDULED || job.status == JobStatus.IN_PROGRESS
        LazyColumn(
            contentPadding = PaddingValues(
                start = 12.dp,
                end = 12.dp,
                top = padding.calculateTopPadding() + 8.dp,
                bottom = 32.dp
            ),
            verticalArrangement = Arrangement.spacedBy(12.dp)
        ) {
            item { HeaderCard(state) }

            if (job.status == JobStatus.SCHEDULED) {
                item {
                    Button(
                        onClick = {
                            locationPermission.launch(
                                arrayOf(
                                    Manifest.permission.ACCESS_FINE_LOCATION,
                                    Manifest.permission.ACCESS_COARSE_LOCATION
                                )
                            )
                        },
                        modifier = Modifier.fillMaxWidth().height(56.dp)
                    ) { Text("Start job") }
                }
            }

            item {
                PhotoStrip("Before photos", state.beforePhotos, enabled = editable) {
                    onCamera(CameraArgs(jobId, PhotoKind.BEFORE))
                }
            }

            state.sections.forEach { section ->
                item(key = "section-${section.name}") {
                    Card(Modifier.fillMaxWidth()) {
                        Column(Modifier.padding(vertical = 8.dp)) {
                            Row(Modifier.padding(horizontal = 16.dp), verticalAlignment = Alignment.CenterVertically) {
                                Text(
                                    section.name,
                                    style = MaterialTheme.typography.titleMedium,
                                    modifier = Modifier.weight(1f)
                                )
                                val sectionDone = section.tasks.count { it.status == TaskStatus.DONE }
                                Text(
                                    "$sectionDone/${section.tasks.size}",
                                    color = MaterialTheme.colorScheme.onSurfaceVariant
                                )
                                if (editable) {
                                    IconButton(onClick = {
                                        onCamera(CameraArgs(jobId, PhotoKind.TASK, room = section.name))
                                    }) {
                                        Icon(Icons.Filled.PhotoCamera, "Photo of ${section.name}")
                                    }
                                }
                            }
                            section.tasks.forEach { task ->
                                TaskRow(
                                    task = task,
                                    enabled = editable,
                                    onTap = { vm.toggle(task) },
                                    onLongPress = { skipping = task },
                                    onPhoto = {
                                        onCamera(CameraArgs(jobId, PhotoKind.TASK, section.name, taskId = task.id))
                                    }
                                )
                            }
                            if (section.photos.isNotEmpty()) {
                                Thumbnails(section.photos, Modifier.padding(horizontal = 16.dp, vertical = 8.dp))
                            }
                        }
                    }
                }
            }

            item {
                PhotoStrip("After photos", state.afterPhotos, enabled = editable) {
                    onCamera(CameraArgs(jobId, PhotoKind.AFTER))
                }
            }

            item {
                Card(Modifier.fillMaxWidth()) {
                    Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Text(
                                "Issues & existing damage",
                                style = MaterialTheme.typography.titleMedium,
                                modifier = Modifier.weight(1f)
                            )
                            if (editable) {
                                TextButton(onClick = { showIssue = true }) {
                                    Icon(Icons.Filled.ReportProblem, null)
                                    Spacer(Modifier.width(4.dp))
                                    Text("Report")
                                }
                            }
                        }
                        if (state.issues.isEmpty()) {
                            Text(
                                "None recorded. Document anything already damaged — it protects you and the customer.",
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant
                            )
                        }
                        state.issues.forEach { (issue, photos) ->
                            HorizontalDivider()
                            Row(verticalAlignment = Alignment.CenterVertically) {
                                Column(Modifier.weight(1f)) {
                                    Text(
                                        "${issue.room.ifBlank {
                                            "General"
                                        }} · ${issue.severity}",
                                        fontWeight = FontWeight.SemiBold
                                    )
                                    Text(issue.description)
                                }
                                if (editable) {
                                    IconButton(onClick = {
                                        onCamera(CameraArgs(jobId, PhotoKind.ISSUE, issue.room, issueId = issue.id))
                                    }) { Icon(Icons.Filled.CameraAlt, "Photo of issue") }
                                }
                            }
                            if (photos.isNotEmpty()) Thumbnails(photos)
                        }
                    }
                }
            }

            item {
                OutlinedTextField(
                    value = notes,
                    onValueChange = {
                        notes = it
                        vm.onNotesChanged(it)
                    },
                    label = { Text("Notes for the customer (optional)") },
                    enabled = editable,
                    minLines = 2,
                    modifier = Modifier.fillMaxWidth()
                )
            }

            item {
                if (editable) {
                    Button(
                        onClick = { showFinish = true },
                        enabled = state.requiredLeft == 0,
                        modifier = Modifier.fillMaxWidth().height(56.dp)
                    ) {
                        Text(
                            if (state.requiredLeft ==
                                0
                            ) {
                                "Finish job"
                            } else {
                                "${state.requiredLeft} required task(s) left"
                            }
                        )
                    }
                } else if (job.status == JobStatus.COMPLETED) {
                    ReportCard(job.reportNumber, job.reportShareUrl, job.reportStatus, state.pendingUploads)
                }
            }
        }
    }

    if (showIssue) {
        IssueDialog(
            rooms = state.sections.map { it.name },
            onDismiss = { showIssue = false },
            onSave = { room, description, severity, phase, takePhoto ->
                val id = vm.saveIssue(room, description, severity, phase)
                showIssue = false
                if (takePhoto) onCamera(CameraArgs(jobId, PhotoKind.ISSUE, room, issueId = id))
            }
        )
    }
    skipping?.let { task ->
        SkipDialog(task, onDismiss = { skipping = null }, onSkip = { reason ->
            vm.skip(task, reason)
            skipping = null
        })
    }
    if (showFinish) {
        AlertDialog(
            onDismissRequest = { showFinish = false },
            title = { Text("Finish this job?") },
            text = {
                Text(
                    "${state.done}/${state.total} tasks done · ${state.beforePhotos.size} before / " +
                        "${state.afterPhotos.size} after photos · ${state.issues.size} issue(s).\n\n" +
                        "The report is created automatically and finalized once all photos have uploaded."
                )
            },
            confirmButton = {
                Button(onClick = {
                    showFinish = false
                    vm.finish(notes) {}
                }) { Text("Finish") }
            },
            dismissButton = { TextButton(onClick = { showFinish = false }) { Text("Keep working") } }
        )
    }
}

@Composable
private fun HeaderCard(state: JobUiState) {
    val job = state.job ?: return
    var showAccess by rememberSaveable { mutableStateOf(false) }
    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Text(job.propertyName, style = MaterialTheme.typography.titleLarge)
            if (job.propertyAddress.isNotBlank()) {
                Text(
                    job.propertyAddress,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
            Text("Scheduled ${job.scheduledStart.formatDateTime()}", style = MaterialTheme.typography.bodySmall)
            if (state.total > 0) {
                LinearProgressIndicator(
                    progress = { state.done.toFloat() / state.total },
                    modifier = Modifier.fillMaxWidth().padding(top = 4.dp)
                )
                Text("${state.done} of ${state.total} tasks", style = MaterialTheme.typography.bodySmall)
            }
            listOf(job.instructions, job.cleaningInstructions).filter { it.isNotBlank() }.forEach {
                Text(it, style = MaterialTheme.typography.bodyMedium)
            }
            if (job.accessNotes.isNotBlank()) {
                TextButton(onClick = { showAccess = !showAccess }, contentPadding = PaddingValues(0.dp)) {
                    Text(if (showAccess) "Hide access details" else "Show access details")
                }
                if (showAccess) Text(job.accessNotes, fontWeight = FontWeight.SemiBold)
            }
        }
    }
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun TaskRow(
    task: TaskEntity,
    enabled: Boolean,
    onTap: () -> Unit,
    onLongPress: () -> Unit,
    onPhoto: () -> Unit
) {
    Row(
        Modifier
            .fillMaxWidth()
            .combinedClickable(enabled = enabled, onClick = onTap, onLongClick = onLongPress)
            .padding(horizontal = 16.dp, vertical = 10.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        val (icon, tint) = when (task.status) {
            TaskStatus.DONE -> Icons.Filled.CheckCircle to Done
            TaskStatus.SKIPPED -> Icons.Filled.RemoveCircle to Warn
            else -> Icons.Filled.RadioButtonUnchecked to MaterialTheme.colorScheme.outline
        }
        Icon(icon, task.status, tint = tint, modifier = Modifier.size(28.dp))
        Spacer(Modifier.width(12.dp))
        Column(Modifier.weight(1f)) {
            Text(task.title + if (task.isRequired) "" else " (optional)")
            if (task.note.isNotBlank()) Text(task.note, style = MaterialTheme.typography.bodySmall, color = Warn)
            if (task.instructions.isNotBlank()) {
                Text(
                    task.instructions,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
        }
        if (task.requiresPhoto && enabled) {
            IconButton(onClick = onPhoto) {
                Icon(Icons.Filled.PhotoCamera, "Photo required", tint = MaterialTheme.colorScheme.primary)
            }
        }
    }
}

@Composable
private fun PhotoStrip(title: String, photos: List<PhotoEntity>, enabled: Boolean, onCapture: () -> Unit) {
    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(16.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(title, style = MaterialTheme.typography.titleMedium, modifier = Modifier.weight(1f))
                Text("${photos.size}", color = MaterialTheme.colorScheme.onSurfaceVariant)
                Spacer(Modifier.width(8.dp))
                if (enabled) {
                    FilledTonalButton(onClick = onCapture) {
                        Icon(Icons.Filled.CameraAlt, null)
                        Spacer(Modifier.width(6.dp))
                        Text("Take")
                    }
                }
            }
            if (photos.isNotEmpty()) Thumbnails(photos, Modifier.padding(top = 8.dp))
        }
    }
}

@Composable
private fun Thumbnails(photos: List<PhotoEntity>, modifier: Modifier = Modifier) {
    LazyRow(modifier, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
        items(photos, key = { it.id }) { photo ->
            PhotoThumb(photo)
        }
    }
}

@Composable
private fun PhotoThumb(photo: PhotoEntity) {
    Box {
        AsyncImage(
            model = photo.localPath?.let(::File) ?: photo.remoteThumbUrl,
            contentDescription = "${photo.kind} photo",
            contentScale = ContentScale.Crop,
            modifier = Modifier.size(72.dp).clip(RoundedCornerShape(8.dp))
        )
        if (photo.uploadState == UploadState.PENDING) {
            Icon(
                Icons.Filled.CloudUpload,
                "Waiting to upload",
                tint = Warn,
                modifier = Modifier.size(18.dp).align(Alignment.TopEnd)
            )
        }
    }
}

@Composable
private fun ReportCard(number: String?, shareUrl: String?, status: String?, pendingUploads: Int) {
    val context = LocalContext.current
    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text("Cleaning proof", style = MaterialTheme.typography.titleMedium)
            when {
                pendingUploads > 0 -> Text(
                    "$pendingUploads photo(s) still uploading. The report finalizes automatically."
                )
                number == null -> Text("Report will appear once this phone syncs.")
                else -> Text("Report $number" + if (status == "final") " · verified" else " · finalizing")
            }
            if (shareUrl != null) {
                OutlinedButton(onClick = {
                    val send = Intent(Intent.ACTION_SEND)
                        .setType("text/plain")
                        .putExtra(Intent.EXTRA_TEXT, "Cleaning completed — view your Cleaning Proof: $shareUrl")
                    context.startActivity(Intent.createChooser(send, "Send report"))
                }, modifier = Modifier.fillMaxWidth()) {
                    Icon(Icons.Filled.Share, null)
                    Spacer(Modifier.width(6.dp))
                    Text("Send to customer")
                }
            }
        }
    }
}
