# API reference (v1)

Base URL: `/api/v1/`. Authenticate with `Authorization: Bearer <access>`. Org-scoped endpoints also take `X-Organization: <org uuid>`. The header can be left out when the user belongs to exactly one organization.

Errors use standard DRF bodies. A **402** with `code: plan_limit` means the organization's plan doesn't allow the action.

## Auth

| Method | Path | Notes |
|--------|------|-------|
| POST | `auth/register/` | `email, password, full_name?, organization_name?`. Returns `user, access, refresh` |
| POST | `auth/login/` | `email, password`. Returns `access, refresh, user` |
| POST | `auth/refresh/` | `refresh`. Returns rotated `access, refresh` |
| GET/PATCH/DELETE | `auth/me/` | The DELETE anonymizes the account (GDPR) |

## Organization & team

| Method | Path | Roles |
|--------|------|-------|
| GET/POST | `organizations/` | Any authenticated user. Creating an org makes the caller its owner |
| PATCH | `organizations/<id>/` | owner, admin |
| GET/PATCH | `members/`, `members/<id>/` | owner, admin (owners only for owner changes; the last owner is protected); viewers can read |
| GET/POST | `invitations/` | owner, admin. The response includes `token` to share with the invitee |
| POST | `invitations/<id>/revoke/` | owner, admin |
| POST | `invitations/accept/` | The invitee (email must match): `{token}` |
| GET | `audit-events/` | owner, admin |

## Customers, properties, checklists

| Method | Path | Notes |
|--------|------|-------|
| CRUD | `customers/` | Managers. Viewers can read |
| CRUD | `properties/` | Managers write. Cleaners see only assigned properties or ones they have jobs at |
| GET | `properties/<id>/history/` | Past jobs with report numbers |
| CRUD | `checklists/` | Nested `sections[].tasks[]`, replaced as a whole on PUT. Order in the array sets the position. `?property=<id>` lists generic + property-specific templates |
| POST | `checklists/<id>/duplicate/` | `{name?, property?}` |
| POST | `checklists/install-defaults/` | Adds the starter templates |

## Jobs

| Method | Path | Notes |
|--------|------|-------|
| GET | `jobs/` | Summary list. Filters: `status`, `property`, `assigned_to=me|<id>`, `when=today|upcoming|overdue`, `from`, `to` |
| POST | `jobs/` | `property, scheduled_start, assigned_to?, checklist_template?` (defaults to the property's), `scheduled_end?, title?, instructions?` |
| GET | `jobs/<id>/` | Full detail: property brief, tasks, issues, photos (signed URLs), signatures, progress, report |
| PATCH | `jobs/<id>/` | Scheduled or in-progress jobs only. Reassigning notifies the new cleaner |
| DELETE | `jobs/<id>/` | Only scheduled jobs without evidence |
| POST | `jobs/<id>/cancel/` | `{reason?}` |
| POST | `jobs/<id>/signature/` | Multipart `id, signer_name, image, signed_at` (on-site sign-off) |
| CRUD | `schedules/` | Recurring schedules (Pro+): `frequency=daily|weekly|biweekly|monthly|custom`, `weekdays[0..6]`, `day_of_month`, `interval_days`, `start_time`, `timezone`, `start_date`, `end_date` |
| GET | `dashboard/` | Today, upcoming, overdue, counts and 30-day metrics (`?days=`) |

## Offline sync & evidence

| Method | Path | Notes |
|--------|------|-------|
| GET | `sync/pull/?since=<iso>` | `{server_time, jobs[], active_job_ids[]}` for the caller's assigned jobs |
| POST | `sync/push/` | `{mutations:[...]}` up to 500. Returns `{results:[{id,status,detail?}]}`. See [SYNC.md](SYNC.md) |
| POST | `photos/` | Multipart: `id, job, file, captured_at, kind, job_task?, issue?, room?, caption?, latitude?, longitude?, sha256?`. Returns 201 (new), 200 (already stored), 409 (issue not synced yet), 400 (checksum mismatch or invalid image) |
| GET | `photos/?job=<id>` | List. There is no delete endpoint |

## Reports

| Method | Path | Notes |
|--------|------|-------|
| GET | `reports/`, `reports/<id>/` | Includes `snapshot`, `content_hash`, `share_url`, `verify_url`, `pdf_url`, customer feedback |
| POST | `reports/<id>/finalize/` | `{force: true}` finalizes with missing photos recorded |
| POST | `reports/<id>/rotate-link/` | Invalidates the customer link and issues a new one |
| POST | `reports/<id>/revoke/` | The verification page then shows "Revoked" |
| POST | `reports/<id>/pdf/` | Regenerates the PDF (Pro+) |

### Public (no account)

| Path | What |
|------|------|
| `/report/<token>/` | Customer report page: approve + optional drawn signature, report a problem, download the PDF |
| `/r/<CP-YYYY-XXXXXX>/` | Verification page. `?format=json` returns `{exists, valid, status, company, property, city, completed_at, content_hash, revision}` |
| `/files/<signed-token>/` | Expiring file access (photos, signatures, PDFs, logos) |

## Notifications & billing

| Method | Path | Notes |
|--------|------|-------|
| POST/DELETE | `devices/` | `{token, platform, app_version}` (FCM) |
| GET | `notifications/?unread=true` | In-app inbox |
| POST | `notifications/<id>/read/`, `notifications/read-all/` | |
| GET | `billing/` | Plan, features, limits, usage, subscription, product ids |
| POST | `billing/google-play/verify/` | Owner only. `{product_id, purchase_token}` |
| POST | `billing/google-play/rtdn/?token=<secret>` | Cloud Pub/Sub push endpoint |
