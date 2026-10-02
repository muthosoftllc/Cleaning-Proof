# Security & privacy

| Requirement | Implementation |
|-------------|----------------|
| HTTPS | `SECURE_SSL_REDIRECT`, HSTS and secure cookies when `DJANGO_DEBUG=0`. The Android release build forbids cleartext traffic, and debug allows it only for `10.0.2.2`/`localhost` |
| Auth | JWT access tokens (30 min) and rotating refresh tokens (60 days, so offline cleaners stay signed in) with a blacklist after rotation. Tokens are stored in `EncryptedSharedPreferences` |
| Object-level authorization | `OrgScopedViewSet` + `OrgRolePermission`. Cleaners are additionally limited to their assigned jobs and properties. Sync checks each job's membership and assignment |
| Organization isolation | Every query is filtered by the active membership's organization, and foreign keys from clients are validated against the same organization (`OrgRelatedField`, `OrgMemberField`) |
| Private photo storage | Files are never routed publicly. Clients get `/files/<signed-token>/` URLs that expire (15 min by default, `django.core.signing`). Use a **private** bucket for object storage |
| No EXIF leakage | Reports show re-encoded thumbnails with no metadata. Originals, including GPS EXIF, stay private as evidence |
| Upload safety | Images are verified with Pillow, there is a decompression-bomb limit and a size cap, and a client SHA-256 is checked |
| Rate limiting | DRF throttles (auth: 20/min, plus user and anonymous limits) and a cache-based limiter on public report, verification and customer-action pages |
| Audit log | `AuditEvent` records org, membership, invitation, job, report, billing and account events with actor and IP. Read-only in the admin |
| Subscription validation | Purchase tokens are verified with the Google Play Developer API on the server. `obfuscatedAccountId` must match the organization, and RTDN messages are only a hint to re-verify |
| Minimal customer data | A customer has a name and optional contact details. Public pages show property name + city only, never the street address, access notes or customer contact details |
| Account/data deletion | `DELETE /api/v1/auth/me/` anonymizes the user, deactivates memberships, and schedules deletion of organizations where they were the sole owner |
| Backups | `allowBackup=false` and data-extraction rules exclude the database, files and prefs from cloud backup and device transfer |

## Before launch

- Write and publish the privacy policy and terms (`/privacy`, `/terms`). GDPR: lawful basis, a processor agreement for business customers, retention periods for photos.
- Add a purge job that hard-deletes organizations whose `deleted_at` is past the grace period, including their stored files.
- Move the cache to Redis so rate limits are shared across workers.
- Add a Content-Security-Policy header for public pages.
- Put a CDN/WAF in front of the public report routes.
