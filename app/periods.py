"""
Pay-period arithmetic shared by planning, wallet and recurring logic.

A *period* is identified by its start date:
    monthly -> the 1st of the month
    weekly  -> the Monday of the ISO week (Turkish weeks start on Monday)
"""
import calendar
from datetime import date, datetime, timedelta

from app.models import PeriodType


def period_start(day: date, period_type: PeriodType) -> date:
    if period_type == PeriodType.WEEKLY:
        return day - timedelta(days=day.weekday())
    return day.replace(day=1)


def period_end_exclusive(start: date, period_type: PeriodType) -> date:
    if period_type == PeriodType.WEEKLY:
        return start + timedelta(days=7)
    return shift_period(start, 1, period_type)


def period_bounds(start: date, period_type: PeriodType) -> tuple[datetime, datetime]:
    """[start, end) as naive local datetimes."""
    end = period_end_exclusive(start, period_type)
    return datetime(start.year, start.month, start.day), datetime(end.year, end.month, end.day)


def days_in_period(start: date, period_type: PeriodType) -> int:
    if period_type == PeriodType.WEEKLY:
        return 7
    return calendar.monthrange(start.year, start.month)[1]


def shift_period(start: date, delta: int, period_type: PeriodType) -> date:
    if period_type == PeriodType.WEEKLY:
        return start + timedelta(weeks=delta)
    total = start.year * 12 + (start.month - 1) + delta
    year, month0 = divmod(total, 12)
    return date(year, month0 + 1, 1)


def period_label_tr(start: date, period_type: PeriodType) -> str:
    from app.motivation_texts import MONTHS_TR

    if period_type == PeriodType.WEEKLY:
        end = start + timedelta(days=6)
        if start.month == end.month:
            return f"{start.day}–{end.day} {MONTHS_TR[start.month - 1]} {start.year}"
        return f"{start.day} {MONTHS_TR[start.month - 1]} – {end.day} {MONTHS_TR[end.month - 1]} {end.year}"
    return f"{MONTHS_TR[start.month - 1]} {start.year}"
