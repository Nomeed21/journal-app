"""Local-calendar helpers for the application's configured timezone."""
from datetime import datetime, timezone, timedelta

from backend.config import LOCAL_TZ_OFFSET_HOURS

def local_hour_now() -> int:
    """Current hour (0-23) in the app's configured local timezone."""
    return (datetime.now(timezone.utc) + timedelta(hours=LOCAL_TZ_OFFSET_HOURS)).hour

def local_date_today() -> str:
    """
    Current date (YYYY-MM-DD) in the app's configured local timezone.
    Use this (not datetime.now(timezone.utc).strftime(...)) for "today"
    boundaries the user actually experiences as a calendar day — entry
    duplicate-checks and daily-plan lookups. Journaling at, say, 1am local
    time is still "today" to the user even though it's already the next day
    in UTC; the old UTC-only check meant a morning entry written before
    ~8am local (UTC+8) could get silently bucketed as belonging to the
    *previous* local day's "already done" check, or vice versa near
    midnight, producing an incorrect "already exists" and skipping
    everything downstream of entry creation (XP, quest generation).
    Streak/quest date-bucketing elsewhere (calc_streak, _habit_quest_dates,
    predictive_analytics) intentionally stays in UTC — that's a much wider
    blast radius already keyed off stored UTC dates, and isn't the bug
    being fixed here.
    """
    return (datetime.now(timezone.utc) + timedelta(hours=LOCAL_TZ_OFFSET_HOURS)).strftime("%Y-%m-%d")

def local_date_from_iso(iso_ts: str) -> str:
    """
    Convert a stored UTC ISO timestamp (e.g. a completed_at value) into the
    local calendar date it falls on, using the same LOCAL_TZ_OFFSET_HOURS
    offset as local_date_today()/local_hour_now(). Use this instead of
    `iso_ts[:10]` anywhere a completion's date is bucketed by "which day
    the user experienced it as" — a quest completed at, say, 11pm-1am
    local time near midnight should land on the same local day as
    local_date_today() would report for "today", not get bucketed by its
    raw UTC calendar date.
    """
    dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
    return (dt + timedelta(hours=LOCAL_TZ_OFFSET_HOURS)).strftime("%Y-%m-%d")

def local_day_bounds_utc(days_offset: int = 0) -> tuple[str, str]:
    """
    Return (start_utc_iso, end_utc_iso) marking a local calendar day's
    boundaries, expressed in UTC — for filtering created_at (stored in UTC)
    by the local day the user actually means. days_offset=0 is today,
    -1 is yesterday, etc.
    """
    local_now      = datetime.now(timezone.utc) + timedelta(hours=LOCAL_TZ_OFFSET_HOURS)
    local_midnight = local_now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=days_offset)
    start_utc      = local_midnight - timedelta(hours=LOCAL_TZ_OFFSET_HOURS)
    end_utc        = start_utc + timedelta(days=1)
    return start_utc.isoformat(), end_utc.isoformat()

