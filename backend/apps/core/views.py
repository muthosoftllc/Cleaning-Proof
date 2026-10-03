"""Serving private evidence files behind signed, expiring URLs."""

import mimetypes

from django.core import signing
from django.http import FileResponse, Http404
from django.views.decorators.cache import cache_control
from django.views.decorators.http import require_GET

from .signed_urls import unsign_file

# Only these types are ever served; anything else is sent as opaque bytes.
SAFE_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp", "application/pdf"}


def _resolve_file(kind: str, object_id):
    # Imported lazily to keep core free of app-level imports at module load.
    from apps.jobs.models import Photo, Signature
    from apps.organizations.models import Organization
    from apps.reports.models import Report

    def photo_display():
        photo = Photo.objects.only("file", "thumbnail").get(pk=object_id)
        return photo.thumbnail or photo.file

    resolvers = {
        "photo": lambda: Photo.objects.only("file").get(pk=object_id).file,
        "photo_thumb": photo_display,
        "signature": lambda: Signature.objects.only("image").get(pk=object_id).image,
        "report_pdf": lambda: Report.objects.only("pdf").get(pk=object_id).pdf,
        "org_logo": lambda: Organization.objects.only("logo").get(pk=object_id).logo,
    }
    resolver = resolvers.get(kind)
    if resolver is None:
        raise Http404
    try:
        return resolver()
    except (Photo.DoesNotExist, Signature.DoesNotExist, Report.DoesNotExist, Organization.DoesNotExist, ValueError):
        raise Http404 from None


@require_GET
@cache_control(private=True, max_age=300)
def signed_file(request, token: str):
    try:
        payload = unsign_file(token)
    except signing.BadSignature:  # includes SignatureExpired
        raise Http404 from None
    field = _resolve_file(payload.get("k"), payload.get("id"))
    if not field:
        raise Http404
    content_type, _ = mimetypes.guess_type(field.name)
    if content_type not in SAFE_CONTENT_TYPES:
        content_type = "application/octet-stream"
    response = FileResponse(field.open("rb"), content_type=content_type)
    # User-supplied bytes: never sniffed, never scripted, never leak the URL.
    response["X-Content-Type-Options"] = "nosniff"
    response["Content-Security-Policy"] = "default-src 'none'; sandbox"
    response["Referrer-Policy"] = "no-referrer"
    return response
