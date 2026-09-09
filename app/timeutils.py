"""
Single source of truth for "what day is it" — always in the configured
app timezone (`SCHEDULER_TIMEZONE`, default Europe/Istanbul), never the
host's local clock. A UTC cloud server must still roll the day over at
Turkish midnight, run the 08:00 message at Turkish 08:00, and snapshot the
right month at 00:30 on the 1st.

Transaction timestamps are stored as *naive local wall-clock time* in this
timezone; `to_local_naive` normalizes any client-supplied datetime to that.
"""
from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.config import settings


def app_tz() -> ZoneInfo:
    return ZoneInfo(settings.SCHEDULER_TIMEZONE)


def local_now() -> datetime:
    return datetime.now(app_tz())


def local_now_naive() -> datetime:
    return local_now().replace(tzinfo=None)


def local_today() -> date:
    return local_now().date()


def to_local_naive(value: datetime) -> datetime:
    """Aware -> converted to app tz and stripped; naive -> assumed already local."""
    if value.tzinfo is None:
        return value
    return value.astimezone(app_tz()).replace(tzinfo=None)
