"""Minimal Firebase Cloud Messaging HTTP v1 client.

Without FCM credentials configured, pushes are logged instead of sent so the
rest of the system (and the in-app notification list) works in development.
"""

import logging
from functools import lru_cache

from django.conf import settings

logger = logging.getLogger(__name__)
FCM_SCOPE = "https://www.googleapis.com/auth/firebase.messaging"


@lru_cache(maxsize=1)
def _session():
    from google.auth.transport.requests import AuthorizedSession
    from google.oauth2 import service_account

    credentials = service_account.Credentials.from_service_account_file(
        settings.FCM_SERVICE_ACCOUNT_FILE, scopes=[FCM_SCOPE]
    )
    return AuthorizedSession(credentials)


def send_push(token: str, title: str, body: str, data: dict) -> bool | None:
    """Returns True on success, False if the token is invalid (caller should
    delete it), None on transient failure or when FCM isn't configured."""
    if not (settings.FCM_PROJECT_ID and settings.FCM_SERVICE_ACCOUNT_FILE):
        logger.info("FCM not configured; would push %r to %s…", title, token[:12])
        return None
    url = f"https://fcm.googleapis.com/v1/projects/{settings.FCM_PROJECT_ID}/messages:send"
    message = {
        "message": {
            "token": token,
            "notification": {"title": title, "body": body},
            "data": {k: str(v) for k, v in data.items()},
            "android": {"priority": "high"},
        }
    }
    try:
        response = _session().post(url, json=message, timeout=10)
    except Exception:  # network errors must never break the request flow
        logger.exception("FCM send failed")
        return None
    if response.status_code == 200:
        return True
    if response.status_code == 404 or "UNREGISTERED" in response.text:
        return False
    logger.warning("FCM error %s: %s", response.status_code, response.text[:300])
    return None
