# Roadmap

## MVP status

| Area | Backend | Android |
|------|---------|---------|
| Authentication (register/login/refresh, account deletion) | ✅ | ✅ login/register |
| Organizations, roles, invitations | ✅ | – (accept flow via API, UI later) |
| Customers & properties | ✅ | read (assigned) |
| Checklist templates (sections, required/optional, reorder, duplicate, property-specific, starters) | ✅ | read (snapshotted on job) |
| Jobs + task completion | ✅ | ✅ tap/long-press-to-skip |
| Camera / photos (before, after, task, room, issue) | ✅ idempotent, checksummed | ✅ CameraX rapid capture, compression |
| Issues / damage | ✅ | ✅ |
| Offline support + sync | ✅ protocol + conflict rules | ✅ Room queue + WorkManager |
| Professional report + shareable link | ✅ web, approve/sign, report problem | ✅ share sheet |
| Verification page + QR | ✅ | – |
| Basic PDF | ✅ (Pro+) | link |
| Push notifications | ✅ FCM HTTP v1 + inbox | ✅ channels, deep link to job |
| Google Play subscription | ✅ verify, acknowledge, RTDN, entitlements | ✅ BillingManager (paywall UI pending) |
| Recurring jobs | ✅ generator + API (Pro+) | – |
| Dashboard metrics | ✅ API | – |

## Next (still MVP-scoped)

1. Owner screens in the app: create a job, manage properties, templates, team, and a paywall using `BillingManager`.
2. On-site customer signature pad (the backend endpoint `POST /jobs/<id>/signature/` already exists).
3. A report email/SMS to the customer on completion ("Cleaning completed: View Cleaning Proof").
4. Clean up uploaded local photo files after N days.
5. Instrumented tests for sync on a device or emulator, and a Postgres-backed load test of `/sync/push/`.

## Deliberately deferred

Advanced analytics, customer ratings, complex scheduling, multiple currencies and tax, AI, chat, route optimization, large enterprise features, and a desktop/web dashboard. The Django admin covers back-office needs for now.
