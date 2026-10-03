# Offline sync

Cleaners often have little or no signal inside buildings. Everything in the job flow works offline (viewing jobs, checklists, ticking tasks, photos, notes, issues, finishing), and **no evidence is ever silently lost**.

```
UI action ─► Room (state) + mutation queue   [one transaction]
                      │
          WorkManager (network constraint, exponential backoff)
                      ▼
  POST /sync/push/  (mutations, in order)  ─► per-mutation result
  POST /photos/     (multipart, idempotent, SHA-256 checked)
  GET  /sync/pull/?since=<server_time>     ─► merge into Room
                      ▼
         server finalizes the report when all declared photos arrived
```

## Mutations

Each queued mutation is `{id (uuid), type, job_id, client_timestamp, payload}`.

| type | payload |
|------|---------|
| `job.start` | `started_at`, optional `latitude`, `longitude`, `accuracy_m` |
| `task.update` | `task_id`, `status` (`pending`/`done`/`skipped`), `note`, `completed_at` |
| `issue.upsert` | `id`, `room`, `description`, `severity`, `phase`, `resolution`, `reported_at` |
| `job.notes` | `notes`, `supply_notes` |
| `job.finish` | `completed_at`, `notes`, optional GPS, **`photo_ids`** (every photo captured for the job) |

The server answers each mutation with one of these statuses:

- `applied`: accepted.
- `duplicate`: this mutation id was already processed, so it was not applied again. The response includes `original_status`.
- `ignored_stale`: a newer change already exists. Safe to drop.
- `rejected` with `detail`: refused, and the device keeps it visible to the user. Malformed payloads (unknown task, invalid severity, oversized notes, bad coordinates) are rejected per mutation; they never fail the batch.

## Conflict rules

1. **Idempotency.** Mutation ids are recorded per user in `ProcessedMutation`, so a retry after a dropped response is harmless, and one user's ids can never collide with another's. Concurrent retries of the same mutation resolve to `duplicate`. Photos are keyed by a client UUID, and re-uploading returns `200` with the stored photo.
2. **Tasks use last-writer-wins on device time.** A change older than the stored `client_updated_at` is `ignored_stale`. Two devices editing the same task is rare, since jobs are assigned to one cleaner.
3. **Job status only moves forward**: scheduled → in_progress → completed. A stale `job.start` after completion is ignored.
4. **Cancelled jobs still accept evidence.** If the office cancels a job while the cleaner works offline, tasks, issues, notes and photos are still stored. Only the status change is rejected, with an explicit message.
5. **Evidence is append-only.** Sync never deletes photos or issues.
6. **Pull respects local work.** A job with unsynced local mutations keeps its local execution state, and only office-owned fields (schedule, property info, report link) are refreshed. Jobs that disappear from the assigned set are removed locally only if they have no pending mutations or photos.
7. **Ordering.** An issue photo uploaded before its `issue.upsert` has synced gets `409`, and the worker retries it later. A `task.update` that implicitly starts a job is queued after a `job.start`.

8. **Required tasks.** `job.finish` with open required tasks is rejected. `force: true` is honoured only for owners and admins.
9. **Pull cursor.** `server_time` lags real time by 5 seconds, so a commit racing the cursor is always delivered on the next pull. Re-delivery is harmless because merging is idempotent.

## Report finalization

`job.finish` declares `photo_ids`. The report exists right away (status `pending_evidence`, and the link works), but it only becomes `final` (hashed, PDF generated, office notified) once every declared photo has been received. If a device is lost, an owner or admin can finalize anyway (`POST /reports/<id>/finalize/ {"force": true}`), and the report then states how many photos never arrived.

## What the cleaner sees

- A sync chip that is always visible: "All synced", "3 photos waiting", and so on.
- A pending-upload badge on each thumbnail.
- A banner listing any change the office rejected. The data stays on the phone.
- Logging out revokes the session server-side and clears the tokens. Unsynced evidence stays and uploads after the next login.
- Shared phones: local data belongs to one user. Another user signing in wipes it, **unless** the previous user still has unsynced work, in which case the sign-in is refused with an explanation.
- Completed jobs leave the device 14 days after completion, once everything has synced.
