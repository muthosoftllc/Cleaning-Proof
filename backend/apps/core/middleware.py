from django.conf import settings

# Public pages only load same-origin scripts/styles/images. Inline styles are
# allowed (brand colour, layout), inline scripts are not.
DEFAULT_CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; form-action 'self'; frame-ancestors 'none'; base-uri 'none'; object-src 'none'"
)


class SecurityHeadersMiddleware:
    """Baseline browser hardening headers not covered by Django's SecurityMiddleware."""

    def __init__(self, get_response):
        self.get_response = get_response
        self.csp = getattr(settings, "CONTENT_SECURITY_POLICY", DEFAULT_CSP)

    def __call__(self, request):
        response = self.get_response(request)
        response.headers.setdefault("Content-Security-Policy", self.csp)
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=()")
        response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        response.headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")
        return response
