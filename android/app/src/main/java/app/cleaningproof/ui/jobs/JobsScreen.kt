package app.cleaningproof.ui.jobs

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Logout
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Tab
import androidx.compose.material3.TabRow
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.ViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewModelScope
import app.cleaningproof.AppContainer
import app.cleaningproof.data.local.JobEntity
import app.cleaningproof.data.local.JobStatus
import app.cleaningproof.ui.components.SyncStatusChip
import app.cleaningproof.ui.containerViewModel
import app.cleaningproof.ui.theme.Done
import app.cleaningproof.ui.theme.Warn
import app.cleaningproof.util.formatTime
import java.time.LocalDate
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

class JobsViewModel(private val container: AppContainer) : ViewModel() {
    private val zone = ZoneId.systemDefault()
    private fun startOfDay(date: LocalDate) = date.atStartOfDay(zone).toInstant().toEpochMilli()
    private val today = LocalDate.now()

    val todayJobs = container.jobs.observeJobs(startOfDay(today), startOfDay(today.plusDays(1)) - 1)
    val upcomingJobs = container.jobs.observeJobs(startOfDay(today.plusDays(1)), startOfDay(today.plusDays(31)))
    val inProgress = container.jobs.observeInProgress()
    val pendingChanges = container.jobs.observePendingMutations()
    val pendingPhotos = container.jobs.observePendingPhotos()
    val rejected = container.jobs.observeRejected()
    val userName = container.session.userName

    fun refresh() = container.syncScheduler.requestSync()
    fun logout() {
        viewModelScope.launch { container.auth.logout() }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun JobsScreen(onOpenJob: (String) -> Unit) {
    val vm = containerViewModel { JobsViewModel(it) }
    val today by vm.todayJobs.collectAsStateWithLifecycle(emptyList())
    val upcoming by vm.upcomingJobs.collectAsStateWithLifecycle(emptyList())
    val inProgress by vm.inProgress.collectAsStateWithLifecycle(emptyList())
    val pendingChanges by vm.pendingChanges.collectAsStateWithLifecycle(0)
    val pendingPhotos by vm.pendingPhotos.collectAsStateWithLifecycle(0)
    val rejected by vm.rejected.collectAsStateWithLifecycle(emptyList())
    var tab by remember { mutableIntStateOf(0) }
    var refreshing by remember { mutableStateOf(false) }

    LaunchedEffect(Unit) { vm.refresh() }
    LaunchedEffect(refreshing) {
        if (refreshing) {
            delay(1500)
            refreshing = false
        }
    }

    Scaffold(topBar = {
        TopAppBar(
            title = { Text(vm.userName?.let { "Hi, ${it.substringBefore(' ')}" } ?: "Your jobs") },
            actions = {
                SyncStatusChip(pendingChanges, pendingPhotos, onClick = vm::refresh)
                IconButton(onClick = vm::logout) { Icon(Icons.AutoMirrored.Filled.Logout, "Sign out") }
            }
        )
    }) { padding ->
        Column(Modifier.padding(padding)) {
            if (rejected.isNotEmpty()) {
                Card(
                    colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.errorContainer),
                    modifier = Modifier.fillMaxWidth().padding(12.dp)
                ) {
                    Text(
                        "${rejected.size} change(s) were not accepted by the office: " +
                            rejected.first().detail.orEmpty() + " Your evidence is still saved on this phone.",
                        Modifier.padding(12.dp)
                    )
                }
            }
            TabRow(selectedTabIndex = tab) {
                Tab(tab == 0, { tab = 0 }, text = { Text("Today (${today.size})") })
                Tab(tab == 1, { tab = 1 }, text = { Text("Upcoming (${upcoming.size})") })
            }
            PullToRefreshBox(
                isRefreshing = refreshing,
                onRefresh = {
                    refreshing = true
                    vm.refresh()
                },
                modifier = Modifier.fillMaxSize()
            ) {
                val list = if (tab == 0) (inProgress + today).distinctBy { it.id } else upcoming
                LazyColumn(
                    contentPadding = PaddingValues(12.dp),
                    verticalArrangement = Arrangement.spacedBy(10.dp),
                    modifier = Modifier.fillMaxSize()
                ) {
                    if (list.isEmpty()) {
                        item {
                            Text(
                                if (tab == 0) "No jobs today. Pull down to refresh." else "Nothing scheduled yet.",
                                Modifier.padding(24.dp),
                                color = MaterialTheme.colorScheme.onSurfaceVariant
                            )
                        }
                    }
                    items(list, key = { it.id }) { job -> JobCard(job, showDate = tab == 1) { onOpenJob(job.id) } }
                }
            }
        }
    }
}

private val dayFormat = DateTimeFormatter.ofPattern("EEE d MMM")

@Composable
private fun JobCard(job: JobEntity, showDate: Boolean, onClick: () -> Unit) {
    Card(Modifier.fillMaxWidth().clickable(onClick = onClick)) {
        Row(Modifier.padding(16.dp), verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.width(72.dp)) {
                Text(job.scheduledStart.formatTime(), fontWeight = FontWeight.Bold)
                if (showDate) {
                    val date = java.time.Instant.ofEpochMilli(job.scheduledStart).atZone(ZoneId.systemDefault())
                    Text(dayFormat.format(date), style = MaterialTheme.typography.bodySmall)
                }
            }
            Column(Modifier.weight(1f)) {
                Text(job.title, style = MaterialTheme.typography.titleMedium)
                if (job.propertyAddress.isNotBlank()) {
                    Text(
                        job.propertyAddress,
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
            }
            Spacer(Modifier.width(8.dp))
            StatusLabel(job.status)
        }
    }
}

@Composable
fun StatusLabel(status: String) {
    val (text, color) = when (status) {
        JobStatus.IN_PROGRESS -> "In progress" to Warn
        JobStatus.COMPLETED -> "Done" to Done
        JobStatus.CANCELLED -> "Cancelled" to MaterialTheme.colorScheme.error
        else -> "Scheduled" to MaterialTheme.colorScheme.onSurfaceVariant
    }
    Text(text, color = color, style = MaterialTheme.typography.labelLarge)
}
