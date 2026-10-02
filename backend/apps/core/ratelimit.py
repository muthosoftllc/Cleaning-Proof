"""Tiny cache-backed rate limiter for plain Django views (public report
pages). DRF views use DRF throttling instead."""
from functools import wraps

from django.core.cache import cache
from django.http import HttpResponse


def client_ip(request) -> str:
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "unknown")


def ratelimit(key: str, limit: int, period: int, methods=("GET", "POST")):
    def decorator(view):
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            if request.method in methods:
                cache_key = f"rl:{key}:{request.method}:{client_ip(request)}"
                cache.add(cache_key, 0, period)
                try:
                    count = cache.incr(cache_key)
                except ValueError:
                    cache.set(cache_key, 1, period)
                    count = 1
                if count > limit:
                    return HttpResponse("Too many requests. Please try again later.", status=429)
            return view(request, *args, **kwargs)

        return wrapped

    return decorator
