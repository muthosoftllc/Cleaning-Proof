# Code review — October 2026

A full review of the MVP for security, performance, readability and maintainability. Every finding below is fixed in the same change and, where testable, covered by a regression test (`backend/tests/test_security.py` unless noted).

## Critical

| # | Finding | Impact | Fix |
|---|---------|--------|-----|
| 1 | **ReportLab markup injection in PDFs.** Task titles, notes, issue text and names went into `Paragraph` markup unescaped. | A cleaner could embed any server-readable image (including other tenants' photos) or a remote URL (SSRF) into a customer PDF, or break PDF generation with malformed tags. Demonstrated before fixing. | All user text escaped via one helper; images loaded only from our storage. |
| 2 | **`SELECT … FOR UPDATE` over nullable joins.** Report finalization locked a query with `select_related` across nullable FKs. | PostgreSQL rejects this, so **completing any job would fail in production**. SQLite in local tests hid it (12 failures when run on Postgres). | Lock only the job row (`of=("self",)`); the test suite now runs on PostgreSQL in CI and was run on both engines here. |
| 3 | **Django 5.1 was end-of-life** (Dec 2025). | No security patches. | Upgraded to Django 5.2 LTS; dependencies pinned and audited (`pip-audit`: no known vulnerabilities). |
| 4 | **Customer approval never worked in real browsers.** The report page set `<meta name="referrer" content="no-referrer">`, which makes browsers send `Origin: null` on form posts; Django's CSRF check rejected every approval and "report a problem". The test client sends no `Origin`, so tests passed. Found by driving the page in Chromium. | The customer half of the product loop was broken. | Referrer policy `same-origin` (the share token still never leaks cross-site); verified end-to-end in a headless browser, policy pinned by a test. |

## High

| # | Finding | Fix |
|---|---------|-----|
| 5 | `X-Forwarded-For` trusted unconditionally: rate limits bypassable and audit IPs forgeable. | Honoured only for `TRUSTED_PROXY_COUNT` proxies; DRF `NUM_PROXIES` aligned. |
| 6 | Rate limits stored in per-process memory: ineffective across Gunicorn workers. | Redis cache via `REDIS_URL` (added to compose). |
| 7 | Cleaners could bypass required tasks with `job.finish {"force": true}`. | `force` honoured for owners and admins only. |
| 8 | Sync payloads were loosely validated (unbounded notes and photo lists, unchecked coordinates). | One serializer per mutation type; invalid input is rejected per mutation. |
| 9 | Logout didn't revoke refresh tokens; account deletion left all sessions valid. | `POST /auth/logout/`, and session revocation on deletion. |
| 10 | Brand colour and timezone weren't strictly validated (CSS injection on public pages, PDF crash). | Strict `#RRGGBB` and IANA timezone validators on the models. |
| 11 | Play purchase tokens and product ids were interpolated raw into Google API URL paths. | Validated (known products, token charset) and URL-encoded. |
| 12 | Android: a different user signing in on a shared phone saw the previous user's jobs, including door codes. | Local data is bound to one user: wiped on switch, refused while unsynced evidence exists. |
| 13 | Android: push tokens were registered only on first install, so after login no pushes arrived; after logout pushes kept arriving. | Token registered on sign-in, unregistered on sign-out. |

## Medium

- Malformed query parameters (`?property=abc`, `?days=x`) caused 500s → strict parsing, 400s.
- Mutation idempotency used a global primary key on a client-generated id → keyed per user; concurrent retries return `duplicate`.
- Photo uploads accepted any Pillow-readable format and stored everything as `.jpg` → JPEG/PNG/WebP allowlist, stored under the verified extension; signed files are served with a sandboxing CSP and strict content types.
- Outsiders received 403 vs 404 for jobs in other tenants (id probing) → 404.
- Public approval could record two signatures under concurrency → conditional update, first approval wins.
- Inline scripts on public pages prevented a strict CSP → JS moved to a static file; CSP and other hardening headers added.
- RTDN authenticated only by a URL secret (which ends up in logs) → Pub/Sub OIDC verification, secret kept as fallback.
- Nested checklist writes were unbounded → capped sections and tasks per request.
- Public pages answered `HEAD` with 405, breaking link previews in WhatsApp/Slack/iMessage → `HEAD` allowed (and not counted as a view).

## Performance

- Push notifications and PDF rendering ran synchronously at the end of requests (up to 10 s per FCM call) → background pool after commit (`apps/core/tasks.py`), a single seam to swap for Celery.
- Sync pull computed `missing_photo_ids` with one query per job → uses the prefetch.
- Report snapshots re-queried photos and issues → built from prefetched data.
- Recurring job generation issued one `EXISTS` per occurrence → one query per schedule.
- Photos were decoded twice per upload (DRF `ImageField` + our check) → decoded once.
- Pull cursor now overlaps by 5 s so racing commits are never missed.

## Maintainability

- Role groups were monkey-patched onto the `Role` enum → explicit `ALL_ROLES`, `MANAGER_ROLES`, `FIELD_ROLES`, `READER_ROLES` constants.
- Business logic moved out of views (`ingest_photo`, sync handlers); report views split into `api.py` (staff) and `public.py` (anonymous).
- The PDF renderer is split into one method per section.
- Ruff (incl. bugbear and bandit security rules) and format checks enforced in CI; Dependabot enabled.
- Test fixtures isolated per class (each class has its own media root); 89 tests pass on SQLite and PostgreSQL.

## Known limits (not changed here)

- The Android app could not be compiled in the review environment (Google's Maven repository is blocked). Kotlin parses and is formatted cleanly; CI is the first full build.
- Background tasks are best-effort in-process threads. Move to a queue when volume justifies it.
