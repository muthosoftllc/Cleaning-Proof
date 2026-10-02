# Cleaning Proof

Cleaning Proof is an Android-first SaaS for professional cleaners and cleaning companies. It records what was cleaned, when, by whom and in what condition, then produces a proof-of-cleaning report the customer can open without installing anything.

> Turn "trust me, I cleaned it" into verifiable, professional evidence.

The product loop is **Job → Checklist → Evidence → Completion → Proof → Customer → Repeat.**

## Repository layout

| Path | What it is |
|------|------------|
| [`backend/`](backend) | Django + DRF API, the public report and verification pages, PDF generation, billing |
| [`android/`](android) | Kotlin + Jetpack Compose field app (offline-first; Room, WorkManager, CameraX) |
| [`docs/`](docs) | Product spec, architecture, API, sync protocol, security, roadmap |
| `docker-compose.yml` | Postgres + API + scheduler for local or single-host deployment |

## Quick start (backend)

```bash
cd backend
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
export DJANGO_DEBUG=1 BILLING_FAKE_VERIFIER=1
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver 0.0.0.0:8000
python manage.py test          # 60 tests: tenancy, roles, sync conflicts, reports, billing
```

With Docker: `cp backend/.env.example backend/.env` (set `DJANGO_DEBUG=1` locally), then `docker compose up --build`.

Try the main flow with the API:

1. `POST /api/v1/auth/register/` with `organization_name` to create an owner account and organization.
2. `POST /api/v1/checklists/install-defaults/` to add the "Standard Residential" and "Airbnb Turnover" templates.
3. `POST /api/v1/customers/`, `POST /api/v1/properties/`, then `POST /api/v1/jobs/`.
4. The cleaner's app pushes offline changes to `/api/v1/sync/push/` and uploads photos to `/api/v1/photos/`.
5. Once the job is finished, the report shows up at `/report/<token>/`, and the public verification page at `/r/CP-2026-XXXXXX/`.

## Quick start (Android)

Open `android/` in Android Studio (Ladybug or newer, JDK 17). The debug build talks to `http://10.0.2.2:8000/api/v1/`, which is the host machine as seen from the emulator. Push notifications need `android/app/google-services.json`. That file is not committed, and the app builds and runs without it.

```bash
cd android && ./gradlew assembleDebug testDebugUnitTest
```

## Documentation

- [Product spec](docs/PRODUCT.md): what we're building and why
- [Architecture](docs/ARCHITECTURE.md): components, data model, key decisions
- [API](docs/API.md): endpoint reference
- [Offline sync](docs/SYNC.md): the queue, conflict rules, and the "never lose evidence" guarantees
- [Security & privacy](docs/SECURITY.md)
- [Roadmap](docs/ROADMAP.md): MVP status and what is deliberately deferred
