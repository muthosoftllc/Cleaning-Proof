"""Django settings for the Cleaning Proof backend.

All environment-specific values come from environment variables so the same
image runs locally, in CI and in production. Secure defaults: anything that
weakens security must be switched on explicitly.
"""

import os
import sys
from datetime import timedelta
from pathlib import Path

import dj_database_url

BASE_DIR = Path(__file__).resolve().parent.parent


def env_bool(name: str, default: bool = False) -> bool:
    return os.environ.get(name, str(default)).lower() in {"1", "true", "yes", "on"}


def env_list(name: str, default: str = "") -> list[str]:
    return [item.strip() for item in os.environ.get(name, default).split(",") if item.strip()]


def env_int(name: str, default: int) -> int:
    return int(os.environ.get(name, default))


TESTING = "test" in sys.argv[1:2]


DEBUG = env_bool("DJANGO_DEBUG", False)
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "")
if not SECRET_KEY:
    if not DEBUG:
        raise RuntimeError("DJANGO_SECRET_KEY must be set when DJANGO_DEBUG is off")
    SECRET_KEY = "dev-insecure-secret-key"  # noqa: S105 - local development only, refused when DEBUG is off

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS")

# Public base URL used for share links, verification URLs and QR codes.
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/")

# Number of reverse proxies in front of the app that append to
# X-Forwarded-For (Nginx = 1). 0 = trust nothing and use REMOTE_ADDR.
TRUSTED_PROXY_COUNT = env_int("TRUSTED_PROXY_COUNT", 0)

# Unguessable admin path reduces credential-stuffing noise; e.g. "ops-7f3k/".
ADMIN_URL = os.environ.get("DJANGO_ADMIN_URL", "admin/")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "rest_framework_simplejwt.token_blacklist",
    "apps.core",
    "apps.accounts",
    "apps.organizations",
    "apps.properties",
    "apps.checklists",
    "apps.jobs",
    "apps.reports",
    "apps.notifications",
    "apps.billing",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "apps.core.middleware.SecurityHeadersMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": dj_database_url.parse(
        os.environ.get("DATABASE_URL") or f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
        conn_max_age=env_int("DB_CONN_MAX_AGE", 60),
        conn_health_checks=True,
    )
}

# Rate limits and throttles live in the cache, so production needs a cache
# shared by all workers (Redis). Local memory is per-process: dev/tests only.
if os.environ.get("REDIS_URL"):
    CACHES = {
        "default": {"BACKEND": "django.core.cache.backends.redis.RedisCache", "LOCATION": os.environ["REDIS_URL"]}
    }
else:
    CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}

AUTH_USER_MODEL = "accounts.User"
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]

# Evidence (photos, signatures, PDFs) is private. MEDIA_URL is intentionally not
# routed publicly: files are only reachable through signed, expiring URLs
# (see apps.core.signed_urls).
MEDIA_ROOT = Path(os.environ.get("MEDIA_ROOT", BASE_DIR / "media"))
STORAGES = {
    "default": {"BACKEND": os.environ.get("DEFAULT_FILE_STORAGE", "django.core.files.storage.FileSystemStorage")},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}
SIGNED_URL_MAX_AGE_SECONDS = env_int("SIGNED_URL_MAX_AGE_SECONDS", 15 * 60)
MAX_PHOTO_UPLOAD_BYTES = env_int("MAX_PHOTO_UPLOAD_BYTES", 15 * 1024 * 1024)
MAX_IMAGE_PIXELS = env_int("MAX_IMAGE_PIXELS", 60_000_000)  # decompression-bomb guard
DATA_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 2 * 1024 * 1024  # larger uploads stream to disk

# Slow side effects (push, PDF) run on a background pool after commit; inline
# in tests so behaviour is deterministic. See apps.core.tasks.
BACKGROUND_TASKS_INLINE = env_bool("BACKGROUND_TASKS_INLINE", TESTING)

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.LimitOffsetPagination",
    "PAGE_SIZE": 50,
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.UserRateThrottle",
        "rest_framework.throttling.AnonRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "user": os.environ.get("THROTTLE_USER", "2000/hour"),
        "anon": os.environ.get("THROTTLE_ANON", "200/hour"),
        "auth": os.environ.get("THROTTLE_AUTH", "20/minute"),
        "public_report": os.environ.get("THROTTLE_PUBLIC_REPORT", "120/minute"),
        "public_action": os.environ.get("THROTTLE_PUBLIC_ACTION", "20/hour"),
    },
    "NUM_PROXIES": TRUSTED_PROXY_COUNT,
    "TEST_REQUEST_DEFAULT_FORMAT": "json",
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=int(os.environ.get("JWT_ACCESS_MINUTES", 30))),
    # Long refresh lifetime: cleaners may be offline for days.
    "REFRESH_TOKEN_LIFETIME": timedelta(days=int(os.environ.get("JWT_REFRESH_DAYS", 60))),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "AUTH_HEADER_TYPES": ("Bearer",),
    "UPDATE_LAST_LOGIN": True,
}

# Security hardening for production.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = env_bool("DJANGO_SECURE_SSL_REDIRECT", not DEBUG)
SESSION_COOKIE_SECURE = not DEBUG
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_HTTPONLY = True  # forms embed the token; JS never needs the cookie
CSRF_COOKIE_SAMESITE = "Lax"
SECURE_HSTS_SECONDS = 0 if DEBUG else 60 * 60 * 24 * 30
SECURE_HSTS_INCLUDE_SUBDOMAINS = not DEBUG
SECURE_HSTS_PRELOAD = env_bool("DJANGO_HSTS_PRELOAD", False)
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"

# Push notifications (Firebase Cloud Messaging HTTP v1). Leave blank to log only.
FCM_PROJECT_ID = os.environ.get("FCM_PROJECT_ID", "")
FCM_SERVICE_ACCOUNT_FILE = os.environ.get("FCM_SERVICE_ACCOUNT_FILE", "")

# Google Play Billing verification.
GOOGLE_PLAY_PACKAGE_NAME = os.environ.get("GOOGLE_PLAY_PACKAGE_NAME", "app.cleaningproof")
GOOGLE_PLAY_SERVICE_ACCOUNT_FILE = os.environ.get("GOOGLE_PLAY_SERVICE_ACCOUNT_FILE", "")
# RTDN (Pub/Sub push) authentication. Preferred: Pub/Sub OIDC tokens; set the
# audience configured on the push subscription and the service account it
# signs as. Fallback: a shared secret in the push URL (?token=...).
GOOGLE_PLAY_RTDN_AUDIENCE = os.environ.get("GOOGLE_PLAY_RTDN_AUDIENCE", "")
GOOGLE_PLAY_RTDN_SERVICE_ACCOUNT = os.environ.get("GOOGLE_PLAY_RTDN_SERVICE_ACCOUNT", "")
GOOGLE_PLAY_RTDN_TOKEN = os.environ.get("GOOGLE_PLAY_RTDN_TOKEN", "")
# Only for local development: accept purchase tokens without calling Google.
BILLING_FAKE_VERIFIER = env_bool("BILLING_FAKE_VERIFIER", False)

if TESTING:
    # Fast hashing keeps the test suite quick; never used outside tests.
    PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    # Signed-file tokens and report share tokens live in URLs; keep request
    # lines out of app logs (access logs belong to the proxy, with redaction).
    "loggers": {"django.request": {"level": "ERROR"}},
    "root": {"handlers": ["console"], "level": os.environ.get("LOG_LEVEL", "INFO")},
}
