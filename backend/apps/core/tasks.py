"""Fire-and-forget background work, run after the current transaction commits.

Slow side effects (push notifications, PDF rendering) must not hold up the
request that triggered them. This is deliberately tiny: a bounded thread pool
per process. It is the single seam to replace with Celery/RQ once volume
justifies a broker; callers don't change.

Work submitted here is best-effort and idempotent by design: notifications are
persisted before pushing, and PDFs can be regenerated at any time.
"""

import logging
from concurrent.futures import ThreadPoolExecutor

from django.conf import settings
from django.db import close_old_connections, transaction

logger = logging.getLogger(__name__)
_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="cp-bg")


def _run(fn, args, kwargs):
    try:
        fn(*args, **kwargs)
    except Exception:
        logger.exception("Background task %s failed", getattr(fn, "__name__", fn))
    finally:
        close_old_connections()


def run_after_commit(fn, *args, **kwargs) -> None:
    def submit():
        if settings.BACKGROUND_TASKS_INLINE:
            fn(*args, **kwargs)  # tests and debugging: deterministic, errors surface
        else:
            _executor.submit(_run, fn, args, kwargs)

    transaction.on_commit(submit)
