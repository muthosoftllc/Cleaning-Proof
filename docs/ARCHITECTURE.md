# Architecture

```
 Android app (Kotlin/Compose)                     Backend (Django + DRF)                   Customer (browser)
 ┌────────────────────────────┐   HTTPS/JWT   ┌──────────────────────────────┐   HTTPS   ┌──────────────────┐
 │ UI ── reads only ──► Room  │ ────────────► │ /api/v1/*  (org-scoped REST) │ ◄──────── │ /report/<token>/ │
 │  │ writes                ▲ │  sync push    │ /sync/push  /sync/pull       │           │ /r/<CP-id>/      │
 │  ▼                       │ │  photo upload │ reports: snapshot+hash+PDF   │           └──────────────────┘
 │ Repository ─► mutation  │ │               │ billing: Play verification   │
 │   queue (Room) ──► WorkManager ──────────► │ notifications: FCM           │──► FCM ──► devices
 │ CameraX ─► compress ─► app-private files   │ Postgres · private storage   │
 └────────────────────────────┘               └──────────────────────────────┘
```

## Backend apps (`backend/apps/`)

| App | Responsibility |
|-----|----------------|
| `core` | UUID base models, org-scoped viewset, role permission, signed file URLs, rate limiter, trusted client IP, security headers, background tasks |
| `accounts` | Email-based `User`, register/login/refresh (JWT), account deletion (anonymize) |
| `organizations` | `Organization`, `Membership` (roles), `Invitation`, append-only `AuditEvent` |
| `properties` | `Customer`, `Property` (address, instructions, private access notes, default checklist, assigned cleaners) |
| `checklists` | `ChecklistTemplate` → `ChecklistSection` → `ChecklistTask`; duplicate; starter templates |
| `jobs` | `Job`, `JobTask` (snapshot), `Photo`, `Issue`, `Signature`, `RecurringSchedule`, sync protocol, dashboard |
| `reports` | `Report` (number, share token, frozen snapshot, SHA-256, PDF), customer approval/feedback, verification. `api.py` serves staff; `public.py` serves anonymous customers |
| `notifications` | `Notification` inbox + `Device` tokens, FCM HTTP v1 sender |
| `billing` | Plan catalogue, server-side `Entitlements`, `Subscription`, Google Play verification + RTDN |

### Key decisions

- **Tenant isolation by construction.** Every org-owned model carries `organization`. `OrgScopedViewSet` filters every queryset by the caller's membership and sets the organization on create, and `OrgRelatedField` stops cross-tenant references such as a job pointing at another org's property. The active org comes from the `X-Organization` header and is checked against an active membership.
- **Client-generated UUIDs.** Jobs, tasks, issues, photos and mutations all use UUID primary keys, so the device can create records offline and replay uploads idempotently.
- **Jobs snapshot their checklist.** Creating a job copies the template's tasks into `JobTask`, so editing a template later never rewrites the history of past jobs.
- **Evidence is append-only.** There is no photo delete endpoint. Issues are updated, never deleted, by sync.
- **Reports are frozen and hashed.** When a report becomes final, `snapshot` holds everything it shows, including each photo's SHA-256, and `content_hash` is the SHA-256 of the canonical JSON. A late photo produces a visible new *revision* instead of silently changing the report.
- **Server-authoritative plans.** `Entitlements.for_org()` is the only place limits are decided. The app only displays what `/billing/` returns.
- **Thin views, fat services.** Views parse input and map errors to HTTP; rules live in services (`jobs/services.py`, `jobs/sync.py`, `reports/services.py`) where they're testable without HTTP.
- **No Celery yet.** Slow side effects (push, PDF) go through `apps.core.tasks.run_after_commit`: a small per-process thread pool that runs after the transaction commits (inline in tests). It's the single seam to replace with a queue. Scheduled work runs as management commands (`generate_recurring_jobs`, `send_job_reminders`) from the `scheduler` service.
- **PostgreSQL is the reference database.** CI runs the suite on Postgres; SQLite is for quick local runs only.

### Data model (simplified)

```
Organization ─┬─ Membership(user, role) ─ User
              ├─ Invitation
              ├─ Customer ─── Property ─┬─ default ChecklistTemplate
              │                         └─ assigned_cleaners (User)
              ├─ ChecklistTemplate ─ Section ─ Task
              ├─ RecurringSchedule ─► generates Jobs
              ├─ Job ─┬─ JobTask (snapshot)     ├─ Photo (sha256, thumb w/o EXIF)
              │       ├─ Issue ─ Photo          ├─ Signature
              │       └─ Report ─ CustomerFeedback
              ├─ Subscription
              └─ AuditEvent
```

## Android app (`android/app/src/main/java/app/cleaningproof/`)

| Package | Responsibility |
|---------|----------------|
| `data.local` | Room entities (jobs, tasks, issues, photos, **mutations**) and DAOs |
| `data.remote` | Retrofit API, DTOs, JWT auth interceptor + refresh authenticator, encrypted session store |
| `data.repo` | `JobRepository`: local-first actions; each write and its queued mutation share one transaction. Merges pulls |
| `sync` | `SyncWorker` (push queue in order, then pull), `PhotoUploadWorker` (idempotent, checksummed), `SyncScheduler` |
| `camera` | `EvidenceStore`: downscale to 2048 px, JPEG q82, EXIF timestamp/GPS, SHA-256, app-private storage |
| `location` | Optional GPS fix with timeout; never blocks the cleaner |
| `push` | FCM service, notification channels |
| `billing` | Play Billing v7; the purchase token is sent to the backend with `obfuscatedAccountId = organizationId` |
| `ui` | Compose screens: login, jobs (Today/Upcoming + sync status), job execution, rapid camera |

The UI never talks to the network. It reads Room, so the app behaves the same with or without a connection. See [SYNC.md](SYNC.md).
