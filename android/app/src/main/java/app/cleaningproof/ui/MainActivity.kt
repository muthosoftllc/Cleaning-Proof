package app.cleaningproof.ui

import android.Manifest
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.navigation.NavType
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import androidx.navigation.navArgument
import app.cleaningproof.CleaningProofApp
import app.cleaningproof.push.PushService
import app.cleaningproof.ui.camera.CameraScreen
import app.cleaningproof.ui.job.JobScreen
import app.cleaningproof.ui.jobs.JobsScreen
import app.cleaningproof.ui.login.LoginScreen
import app.cleaningproof.ui.theme.CleaningProofTheme

class MainActivity : ComponentActivity() {
    private val openJobId = mutableStateOf<String?>(null)

    private val notificationPermission =
        registerForActivityResult(ActivityResultContracts.RequestPermission()) { }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        openJobId.value = intent.getStringExtra(PushService.EXTRA_JOB_ID)
        if (Build.VERSION.SDK_INT >= 33) notificationPermission.launch(Manifest.permission.POST_NOTIFICATIONS)
        val container = (application as CleaningProofApp).container

        setContent {
            CleaningProofTheme {
                val nav = rememberNavController()
                val loggedIn by container.session.loggedIn.collectAsStateWithLifecycle()
                val pendingJob by openJobId

                LaunchedEffect(loggedIn) {
                    if (!loggedIn && nav.currentDestination?.route != Routes.LOGIN) {
                        nav.navigate(Routes.LOGIN) { popUpTo(0) }
                    }
                }
                LaunchedEffect(pendingJob, loggedIn) {
                    val id = pendingJob
                    if (loggedIn && id != null) {
                        nav.navigate(Routes.job(id))
                        openJobId.value = null
                    }
                }

                NavHost(nav, startDestination = if (loggedIn) Routes.JOBS else Routes.LOGIN) {
                    composable(Routes.LOGIN) {
                        LoginScreen(onLoggedIn = {
                            container.syncScheduler.schedulePeriodic()
                            container.syncScheduler.requestSync()
                            nav.navigate(Routes.JOBS) { popUpTo(0) }
                        })
                    }
                    composable(Routes.JOBS) {
                        JobsScreen(onOpenJob = { nav.navigate(Routes.job(it)) })
                    }
                    composable(
                        "job/{jobId}",
                        arguments = listOf(navArgument("jobId") { type = NavType.StringType })
                    ) { entry ->
                        JobScreen(
                            jobId = entry.arguments!!.getString("jobId")!!,
                            onBack = { nav.popBackStack() },
                            onCamera = { args -> nav.navigate(args.route()) }
                        )
                    }
                    composable(
                        "camera/{jobId}?kind={kind}&room={room}&taskId={taskId}&issueId={issueId}",
                        arguments = listOf(
                            navArgument("jobId") { type = NavType.StringType },
                            navArgument("kind") {
                                type = NavType.StringType
                                defaultValue = "other"
                            },
                            navArgument("room") {
                                type = NavType.StringType
                                defaultValue = ""
                            },
                            navArgument("taskId") {
                                type = NavType.StringType
                                nullable = true
                                defaultValue = null
                            },
                            navArgument("issueId") {
                                type = NavType.StringType
                                nullable = true
                                defaultValue = null
                            }
                        )
                    ) { entry ->
                        val a = entry.arguments!!
                        CameraScreen(
                            args = CameraArgs(
                                jobId = a.getString("jobId")!!,
                                kind = a.getString("kind")!!,
                                room = a.getString("room")!!,
                                taskId = a.getString("taskId"),
                                issueId = a.getString("issueId")
                            ),
                            onDone = { nav.popBackStack() }
                        )
                    }
                }
            }
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        intent.getStringExtra(PushService.EXTRA_JOB_ID)?.let { openJobId.value = it }
    }
}

object Routes {
    const val LOGIN = "login"
    const val JOBS = "jobs"
    fun job(id: String) = "job/$id"
}

data class CameraArgs(
    val jobId: String,
    val kind: String,
    val room: String = "",
    val taskId: String? = null,
    val issueId: String? = null
) {
    fun route(): String = buildString {
        append("camera/$jobId?kind=$kind&room=${Uri.encode(room)}")
        taskId?.let { append("&taskId=$it") }
        issueId?.let { append("&issueId=$it") }
    }
}
