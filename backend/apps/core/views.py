from django.core import signing
from django.http import FileResponse, Http404
from django.views.decorators.cache import cache_control
from django.views.decorators.http import require_GET

from .signed_urls import unsign_file


def _resolve_file(kind: str, object_id):
    # Imported lazily to keep core free of app-level imports at module load.
    from apps.jobs.models import Photo, Signature
    from apps.organizations.models import Organization
    from apps.reports.models import Report

    try:
        if kind == "photo":
            return Photo.objects.get(pk=object_id).file
        if kind == "photo_thumb":
            photo = Photo.objects.get(pk=object_id)
            return photo.thumbnail or photo.file
        if kind == "signature":
            return Signature.objects.get(pk=object_id).image
        if kind == "report_pdf":
            return Report.objects.get(pk=object_id).pdf
        if kind == "org_logo":
            return Organization.objects.get(pk=object_id).logo
    except (Photo.DoesNotExist, Signature.DoesNotExist, Report.DoesNotExist, Organization.DoesNotExist):
        pass
    raise Http404


@require_GET
@cache_control(private=True, max_age=300)
def signed_file(request, token: str):
    try:
        payload = unsign_file(token)
    except signing.BadSignature:  # includes SignatureExpired
        raise Http404
    field = _resolve_file(payload["k"], payload["id"])
    if not field:
        raise Http404
    response = FileResponse(field.open("rb"))
    response["X-Content-Type-Options"] = "nosniff"
    return response
