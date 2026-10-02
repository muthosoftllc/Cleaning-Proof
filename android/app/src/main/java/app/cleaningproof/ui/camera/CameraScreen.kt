package app.cleaningproof.ui.camera

import android.Manifest
import android.content.pm.PackageManager
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.camera.core.ImageCapture
import androidx.camera.core.ImageCaptureException
import androidx.camera.view.CameraController
import androidx.camera.view.LifecycleCameraController
import androidx.camera.view.PreviewView
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.content.ContextCompat
import androidx.lifecycle.compose.LocalLifecycleOwner
import app.cleaningproof.data.local.PhotoEntity
import app.cleaningproof.data.local.UploadState
import app.cleaningproof.ui.CameraArgs
import app.cleaningproof.ui.appContainer
import java.util.UUID
import kotlinx.coroutines.launch

/**
 * Rapid evidence capture: the shutter stays live, every shot is compressed,
 * stored and queued for upload immediately. "Done" returns to the job.
 */
@Composable
fun CameraScreen(args: CameraArgs, onDone: () -> Unit) {
    val context = LocalContext.current
    val lifecycleOwner = LocalLifecycleOwner.current
    val container = appContainer()
    val scope = rememberCoroutineScope()
    var granted by remember {
        mutableStateOf(
            ContextCompat.checkSelfPermission(context, Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED
        )
    }
    val permission = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted = it }
    var count by remember { mutableIntStateOf(0) }
    var busy by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    var location by remember { mutableStateOf<android.location.Location?>(null) }

    LaunchedEffect(Unit) {
        if (!granted) permission.launch(Manifest.permission.CAMERA)
        location = container.location.current()
    }

    val controller = remember {
        LifecycleCameraController(context).apply {
            setEnabledUseCases(CameraController.IMAGE_CAPTURE)
            imageCaptureMode = ImageCapture.CAPTURE_MODE_MINIMIZE_LATENCY
        }
    }

    Box(Modifier.fillMaxSize().background(Color.Black)) {
        if (granted) {
            AndroidView(
                factory = { ctx ->
                    PreviewView(ctx).also {
                        it.controller = controller
                        controller.bindToLifecycle(lifecycleOwner)
                    }
                },
                modifier = Modifier.fillMaxSize()
            )
        } else {
            Column(
                Modifier.align(Alignment.Center).padding(24.dp),
                horizontalAlignment = Alignment.CenterHorizontally
            ) {
                Text("Camera access is needed to capture evidence.", color = Color.White)
                Button(onClick = { permission.launch(Manifest.permission.CAMERA) }) { Text("Allow camera") }
            }
        }

        Text(
            listOf(
                args.kind.replaceFirstChar {
                    it.uppercase()
                },
                args.room
            ).filter { it.isNotBlank() }.joinToString(" · "),
            color = Color.White,
            style = MaterialTheme.typography.titleMedium,
            modifier = Modifier.align(Alignment.TopCenter).statusBarsPadding().padding(16.dp)
        )

        Row(
            Modifier.align(Alignment.BottomCenter).fillMaxWidth().navigationBarsPadding().padding(24.dp),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically
        ) {
            Text("$count taken", color = Color.White, modifier = Modifier.size(width = 90.dp, height = 24.dp))
            Box(
                Modifier
                    .size(76.dp)
                    .border(4.dp, Color.White, CircleShape)
                    .padding(8.dp)
                    .background(if (busy) Color.Gray else Color.White, CircleShape)
                    .clickable(enabled = granted && !busy) {
                        busy = true
                        val raw = container.evidence.newCaptureFile()
                        val capturedAt = System.currentTimeMillis()
                        controller.takePicture(
                            ImageCapture.OutputFileOptions.Builder(raw).build(),
                            ContextCompat.getMainExecutor(context),
                            object : ImageCapture.OnImageSavedCallback {
                                override fun onImageSaved(output: ImageCapture.OutputFileResults) {
                                    scope.launch {
                                        val photoId = UUID.randomUUID().toString()
                                        runCatching {
                                            val stored = container.evidence.store(
                                                raw,
                                                args.jobId,
                                                photoId,
                                                capturedAt,
                                                location?.latitude,
                                                location?.longitude
                                            )
                                            container.jobs.addPhoto(
                                                PhotoEntity(
                                                    id = photoId, jobId = args.jobId, taskId = args.taskId,
                                                    issueId = args.issueId, kind = args.kind, room = args.room,
                                                    localPath = stored.file.path, remoteThumbUrl = null,
                                                    sha256 = stored.sha256, capturedAt = capturedAt,
                                                    latitude = location?.latitude, longitude = location?.longitude,
                                                    uploadState = UploadState.PENDING
                                                )
                                            )
                                        }.onSuccess {
                                            count++
                                        }.onFailure { error = "Couldn't save photo: ${it.message}" }
                                        busy = false
                                    }
                                }

                                override fun onError(exception: ImageCaptureException) {
                                    error = "Capture failed: ${exception.message}"
                                    busy = false
                                }
                            }
                        )
                    }
            )
            TextButton(onClick = onDone, modifier = Modifier.size(width = 90.dp, height = 48.dp)) {
                Text("Done", color = Color.White)
            }
        }

        error?.let {
            Text(
                it,
                color = Color.White,
                modifier = Modifier.align(Alignment.Center).background(Color(0xAA000000)).padding(12.dp)
            )
        }
    }
}
