# Security & privacy

| Requirement | Implementation |
|-------------|----------------|
| HTTPS | `SECURE_SSL_REDIRECT`, HSTS and secure, HttpOnly cookies when `DJANGO_DEBUG=0`. The Android release build forbids cleartext traffic, and debug allows it only for `10.0.2.2`/`localhost` |
| Auth | JWT access tokens (30 min) and rotating refresh tokens (60 days, so offline cleaners stay signed in) with a blacklist after rotation. `POST /auth/logout/` revokes a refresh token, and account deletion revokes every session. Tokens are stored in `EncryptedSharedPreferences` |
| Object-level authorization | `OrgScopedViewSet` + `OrgRolePermission`. Cleaners are additionally limited to their assigned jobs and properties. Sync and photo upload check membership and assignment per job; outsiders get 404 so job ids can't be probed |
| Organization isolation | Every query is filtered by the active membership's organization, and foreign keys from clients are validated against the same organization (`OrgRelatedField`, `OrgMemberField`) |
| Untrusted input | Every sync payload goes through a serializer (types, enums, lengths, coordinate ranges). Query parameters are parsed strictly (bad input is 400, not 500). Nested checklist writes are size-capped |
| PDF generation | User text is escaped before entering ReportLab markup (`apps/reports/pdf.py: esc`). Unescaped, a task note could embed server files or remote URLs into a customer's PDF, or break rendering |
| Private photo storage | Files are never routed publicly. Clients get `/files/<signed-token>/` URLs that expire (15 min by default). Served with a strict content-type allowlist, `nosniff`, a sandboxing CSP and `no-referrer`. Use a **private** bucket for object storage |
| Upload safety | Only JPEG, PNG and WebP; Pillow verification, a decompression-bomb pixel limit set process-wide, a 15 MB cap, and a client SHA-256 check. Originals are stored under their *verified* extension |
| No EXIF leakage | Reports show re-encoded display copies with no metadata. Originals, including GPS EXIF, stay private as evidence |
| Browser hardening | Public pages send a Content-Security-Policy with no inline scripts (JS is a static file), `frame-ancestors 'none'`, Permissions-Policy, COOP/CORP. Brand colours are validated as strict `#RRGGBB` before reaching CSS |
| Rate limiting | DRF throttles (auth: 20/min, plus user and anonymous limits) and a cache-based limiter on public pages. In production the cache **must** be Redis (`REDIS_URL`) so limits are shared across workers |
| Client IP | `X-Forwarded-For` is only honoured for `TRUSTED_PROXY_COUNT` proxies. Trusting it blindly would let anyone bypass rate limits or forge audit-log IPs |
| Audit log | `AuditEvent` records org, membership, invitation, job, report, billing and account events with actor and IP. Read-only in the admin |
| Subscription validation | Purchase tokens are verified with the Google Play Developer API on the server; tokens and product ids are validated and URL-encoded before use. `obfuscatedAccountId` must match the organization. RTDN pushes are authenticated with Pub/Sub OIDC tokens (shared secret as fallback) and only trigger re-verification |
| Minimal customer data | Public pages show property name + city only, never the street address, access notes or customer contact details |
| Account/data deletion | `DELETE /api/v1/auth/me/` anonymizes the user, revokes sessions, deactivates memberships, and schedules deletion of organizations where they were the sole owner |
| Shared devices | Local data belongs to one user. A different user signing in wipes it, but is refused while the previous user has unsynced evidence. Logout unregisters the device from push |
| Backups | `allowBackup=false` and data-extraction rules exclude the database, files and prefs from cloud backup and device transfer |
| Logging | No Gunicorn access log and `django.request` at ERROR: URLs carry report share tokens and signed-file tokens. Log at the proxy with those paths redacted |
| Supply chain | Exact dependency pins, `pip-audit` and Ruff's bandit rules in CI, Dependabot for pip, Gradle and Actions. Django is on the 5.2 LTS line |

## Before launch

- Publish the privacy policy and terms (`/privacy`, `/terms`). GDPR: lawful basis, a processor agreement for business customers, retention periods for photos.
- Add a purge job that hard-deletes organizations whose `deleted_at` is past the grace period, including their stored files.
- Store invitation tokens hashed, and add password reset and change flows.
- Consider SQLCipher for the Android database (it holds access notes such as door codes) and certificate pinning for the API host.
- Put a CDN/WAF in front of the public report routes.

See [SECURITY_REVIEW.md](SECURITY_REVIEW.md) for the findings of the October 2026 review.
