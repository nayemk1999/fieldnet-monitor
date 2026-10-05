"""The only place the server reads time.

In TEST_MODE the clock is a row in the database so every process (API, worker,
tests) sees the same value. Outside TEST_MODE it is the real UTC clock.
"""
from datetime import datetime

from django.conf import settings
from django.utils import timezone


def now() -> datetime:
    if settings.TEST_MODE:
        from core.models import TestState

        state = TestState.objects.filter(pk=1).values_list("now", flat=True).first()
        if state is not None:
            return state
    return timezone.now()


def set_now(value: datetime) -> None:
    from core.models import TestState

    TestState.objects.update_or_create(pk=1, defaults={"now": value})
