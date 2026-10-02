import secrets

from django.utils import timezone

# Crockford-style alphabet without 0/O/1/I/L/U to avoid read-back mistakes.
REPORT_ID_ALPHABET = "23456789ABCDEFGHJKMNPQRSTVWXYZ"


def generate_report_number(length: int = 6) -> str:
    """Human-friendly public report ID, e.g. ``CP-2026-8F42K9``."""
    suffix = "".join(secrets.choice(REPORT_ID_ALPHABET) for _ in range(length))
    return f"CP-{timezone.now().year}-{suffix}"


def generate_share_token() -> str:
    """Unguessable token for the customer-facing report link."""
    return secrets.token_urlsafe(24)
