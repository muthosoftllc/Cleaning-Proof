"""Signed, expiring URLs for private evidence files.

Raw storage paths are never exposed. Clients get a URL that embeds a signed
reference to the file; it stops working after ``SIGNED_URL_MAX_AGE_SECONDS``.
"""

from django.conf import settings
from django.core import signing
from django.urls import reverse

SALT = "cleaningproof.file"


def sign_file(kind: str, object_id) -> str:
    return signing.dumps({"k": kind, "id": str(object_id)}, salt=SALT, compress=True)


def unsign_file(token: str, max_age: int | None = None) -> dict:
    return signing.loads(token, salt=SALT, max_age=max_age or settings.SIGNED_URL_MAX_AGE_SECONDS)


def file_url(kind: str, object_id, request=None) -> str:
    path = reverse("signed-file", kwargs={"token": sign_file(kind, object_id)})
    if request is not None:
        return request.build_absolute_uri(path)
    return f"{settings.PUBLIC_BASE_URL}{path}"
