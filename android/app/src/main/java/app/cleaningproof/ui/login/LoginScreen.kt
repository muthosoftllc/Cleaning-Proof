package app.cleaningproof.ui.login

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import app.cleaningproof.data.repo.AuthRepository
import app.cleaningproof.data.repo.UnsyncedWorkOnDevice
import app.cleaningproof.ui.containerViewModel
import kotlinx.coroutines.launch
import retrofit2.HttpException

class LoginViewModel(private val auth: AuthRepository) : ViewModel() {
    var email by mutableStateOf("")
    var password by mutableStateOf("")
    var name by mutableStateOf("")
    var business by mutableStateOf("")
    var registering by mutableStateOf(false)
    var busy by mutableStateOf(false)
        private set
    var error by mutableStateOf<String?>(null)
        private set

    fun submit(onSuccess: () -> Unit) {
        if (busy) return
        busy = true
        error = null
        viewModelScope.launch {
            runCatching {
                if (registering) auth.register(email, password, name, business) else auth.login(email, password)
            }.onSuccess { onSuccess() }
                .onFailure {
                    error = when {
                        it is UnsyncedWorkOnDevice -> it.message
                        it is HttpException && it.code() == 401 -> "Wrong email or password."
                        it is HttpException && it.code() == 400 -> "Please check the details and try again."
                        it is HttpException && it.code() == 429 -> "Too many attempts. Try again in a minute."
                        else -> "Can't reach the server. Check your connection."
                    }
                }
            busy = false
        }
    }
}

@Composable
fun LoginScreen(onLoggedIn: () -> Unit) {
    val vm = containerViewModel { LoginViewModel(it.auth) }
    Scaffold { padding ->
        Column(
            Modifier
                .fillMaxSize()
                .padding(padding)
                .imePadding()
                .verticalScroll(rememberScrollState())
                .padding(24.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp)
        ) {
            Text(
                "Cleaning Proof",
                style = MaterialTheme.typography.headlineMedium,
                color = MaterialTheme.colorScheme.primary
            )
            Text(
                if (vm.registering) "Create your business account" else "Sign in to see your jobs",
                style = MaterialTheme.typography.bodyLarge
            )
            if (vm.registering) {
                OutlinedTextField(
                    vm.name,
                    { vm.name = it },
                    label = { Text("Your name") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth()
                )
                OutlinedTextField(
                    vm.business,
                    { vm.business = it },
                    label = { Text("Business name") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth()
                )
            }
            OutlinedTextField(
                vm.email,
                { vm.email = it },
                label = { Text("Email") },
                singleLine = true,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Email),
                modifier = Modifier.fillMaxWidth()
            )
            OutlinedTextField(
                vm.password,
                { vm.password = it },
                label = { Text("Password") },
                singleLine = true,
                visualTransformation = PasswordVisualTransformation(),
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password),
                modifier = Modifier.fillMaxWidth()
            )
            vm.error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
            Button(
                onClick = { vm.submit(onLoggedIn) },
                enabled = !vm.busy && vm.email.isNotBlank() && vm.password.length >= 8,
                modifier = Modifier.fillMaxWidth().height(52.dp)
            ) {
                if (vm.busy) {
                    CircularProgressIndicator(Modifier.height(20.dp), strokeWidth = 2.dp)
                } else {
                    Text(if (vm.registering) "Create account" else "Sign in")
                }
            }
            TextButton(onClick = { vm.registering = !vm.registering }) {
                Text(if (vm.registering) "I already have an account" else "New business? Create an account")
            }
            Text(
                "Cleaners: ask your company to invite you with your email address.",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
        }
    }
}
