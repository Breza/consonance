"""Practice-day aggregation uses the caller's local calendar, including the current session."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta


@dataclass(frozen=True)
class PracticeDay:
    """Today's practice at a glance, with the last week for context."""

    minutes_today: float
    lesson_days_90: int
    seven_days: tuple[tuple[str, float], ...]
    drills_today: tuple[str, ...]
    lesson_dates_90: tuple[str, ...]


def local_midnight_utc(now: datetime) -> str:
    """Return the start of the caller's local day as a UTC ISO timestamp for log queries."""
    return now.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(UTC).isoformat()


def summarize_practice(
    sessions: list[tuple[str, float, str]],
    now: datetime,
    completed_at: Sequence[str] = (),
    *,
    localize: Callable[[datetime], datetime] | None = None,
) -> PracticeDay:
    """Total minutes and distinct lesson days, including today and the previous 89 dates.

    Only supplied completion timestamps establish lesson days; idle or abandoned sessions
    still contribute their actual practice minutes. All dates use the caller's timezone.
    """
    convert = localize if localize is not None else lambda instant: instant.astimezone(now.tzinfo)
    totals: dict[str, float] = {}
    drills: set[str] = set()
    for started, seconds, mode in sessions:
        day = convert(datetime.fromisoformat(started)).date().isoformat()
        totals[day] = totals.get(day, 0) + seconds / 60
        if day == now.date().isoformat() and seconds > 0:
            drills.add(mode)
    seven = tuple(
        (
            (now.date() - timedelta(days=i)).isoformat(),
            totals.get((now.date() - timedelta(days=i)).isoformat(), 0.0),
        )
        for i in range(6, -1, -1)
    )
    first = now.date() - timedelta(days=89)
    dates = set()
    for timestamp in completed_at:
        instant = convert(datetime.fromisoformat(timestamp))
        if first <= instant.date() <= now.date() and instant <= now:
            dates.add(instant.date().isoformat())
    return PracticeDay(
        totals.get(now.date().isoformat(), 0),
        len(dates),
        seven,
        tuple(sorted(drills)),
        tuple(sorted(dates)),
    )
