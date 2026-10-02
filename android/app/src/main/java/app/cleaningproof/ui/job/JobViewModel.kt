package app.cleaningproof.ui.job

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import app.cleaningproof.AppContainer
import app.cleaningproof.data.local.IssueEntity
import app.cleaningproof.data.local.JobEntity
import app.cleaningproof.data.local.PhotoEntity
import app.cleaningproof.data.local.TaskEntity
import app.cleaningproof.data.local.TaskStatus
import java.util.UUID
import kotlinx.coroutines.FlowPreview
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.debounce
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch

data class Section(val name: String, val tasks: List<TaskEntity>, val photos: List<PhotoEntity>)

data class JobUiState(
    val job: JobEntity? = null,
    val sections: List<Section> = emptyList(),
    val beforePhotos: List<PhotoEntity> = emptyList(),
    val afterPhotos: List<PhotoEntity> = emptyList(),
    val issues: List<Pair<IssueEntity, List<PhotoEntity>>> = emptyList(),
    val done: Int = 0,
    val total: Int = 0,
    val requiredLeft: Int = 0,
    val pendingUploads: Int = 0
)

@OptIn(FlowPreview::class)
class JobViewModel(private val container: AppContainer, private val jobId: String) : ViewModel() {
    private val repo = container.jobs

    val state: StateFlow<JobUiState> = combine(
        repo.observeJob(jobId),
        repo.observeTasks(jobId),
        repo.observeIssues(jobId),
        repo.observePhotos(jobId)
    ) { job, tasks, issues, photos ->
        val byTask = photos.filter { it.taskId != null }.groupBy { it.taskId }
        val sections = tasks.groupBy { it.sectionName }.map { (name, sectionTasks) ->
            Section(
                name = name,
                tasks = sectionTasks,
                photos = photos.filter { it.kind == "task" && it.taskId == null && it.room == name } +
                    sectionTasks.flatMap { byTask[it.id].orEmpty() }
            )
        }
        JobUiState(
            job = job,
            sections = sections,
            beforePhotos = photos.filter { it.kind == "before" },
            afterPhotos = photos.filter { it.kind == "after" },
            issues = issues.map { issue -> issue to photos.filter { it.issueId == issue.id } },
            done = tasks.count { it.status == TaskStatus.DONE },
            total = tasks.size,
            requiredLeft = tasks.count { it.isRequired && it.status == TaskStatus.PENDING },
            pendingUploads = photos.count { it.uploadState == "pending" }
        )
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), JobUiState())

    val messages = MutableSharedFlow<String>(extraBufferCapacity = 4)
    private val notes = MutableStateFlow<String?>(null)

    init {
        viewModelScope.launch {
            notes.debounce(800).collect { text -> if (text != null) repo.saveNotes(jobId, text) }
        }
    }

    fun start() = viewModelScope.launch {
        val location = container.location.current()
        repo.startJob(jobId, location?.latitude, location?.longitude, location?.accuracy)
    }

    fun toggle(task: TaskEntity) = viewModelScope.launch {
        repo.setTaskStatus(task, if (task.status == TaskStatus.DONE) TaskStatus.PENDING else TaskStatus.DONE)
    }

    fun skip(task: TaskEntity, reason: String) = viewModelScope.launch {
        repo.setTaskStatus(task, TaskStatus.SKIPPED, reason)
    }

    fun onNotesChanged(text: String) {
        notes.value = text
    }

    fun saveIssue(room: String, description: String, severity: String, phase: String): String {
        val id = UUID.randomUUID().toString()
        viewModelScope.launch {
            repo.saveIssue(
                IssueEntity(
                    id = id,
                    jobId = jobId,
                    room = room,
                    description = description.trim(),
                    severity = severity,
                    phase = phase,
                    resolution = "unchanged",
                    reportedAt = System.currentTimeMillis()
                )
            )
        }
        return id
    }

    fun finish(notesText: String, onDone: () -> Unit) = viewModelScope.launch {
        val location = container.location.current()
        repo.finishJob(jobId, notesText, location?.latitude, location?.longitude)
            .onSuccess { onDone() }
            .onFailure { messages.tryEmit(it.message ?: "Can't finish yet") }
    }
}
