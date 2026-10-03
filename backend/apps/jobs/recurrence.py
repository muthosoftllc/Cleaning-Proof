"""Expand a RecurringSchedule into concrete occurrence datetimes."""

import calendar
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from .models import Frequency


def _monthly_day(schedule, d: date) -> int:
    wanted = schedule.day_of_month or schedule.start_date.day
    return min(wanted, calendar.monthrange(d.year, d.month)[1])


def occurs_on(schedule, d: date) -> bool:
    if d < schedule.start_date or (schedule.end_date and d > schedule.end_date):
        return False
    weekdays = schedule.weekdays or [schedule.start_date.weekday()]
    if schedule.frequency == Frequency.DAILY:
        return True
    if schedule.frequency == Frequency.CUSTOM:
        return (d - schedule.start_date).days % max(1, schedule.interval_days) == 0
    if schedule.frequency == Frequency.WEEKLY:
        return d.weekday() in weekdays
    if schedule.frequency == Frequency.BIWEEKLY:
        anchor = schedule.start_date - timedelta(days=schedule.start_date.weekday())
        return d.weekday() in weekdays and ((d - anchor).days // 7) % 2 == 0
    if schedule.frequency == Frequency.MONTHLY:
        return d.day == _monthly_day(schedule, d)
    return False


def occurrences(schedule, start: date, end: date) -> list[datetime]:
    """Aware datetimes for every occurrence in [start, end] (inclusive), in the
    schedule's own timezone so 09:00 stays 09:00 across DST changes."""
    tz = ZoneInfo(schedule.timezone or "UTC")
    result = []
    d = start
    while d <= end:
        if occurs_on(schedule, d):
            result.append(datetime.combine(d, schedule.start_time, tzinfo=tz))
        d += timedelta(days=1)
    return result
