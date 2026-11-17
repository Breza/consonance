"""Practice-day aggregation uses the caller's local calendar, including the current session."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta


@dataclass(frozen=True)
class PracticeDay:
    """Today's practice at a glance, with the last week for context."""

    minutes_today: float
    streak: int
    seven_days: tuple[tuple[str, float], ...]
    drills_today: tuple[str, ...]


def local_midnight_utc(now: datetime) -> str:
    """Return the start of the caller's local day as a UTC ISO timestamp for log queries."""
    return now.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(UTC).isoformat()


def summarize_practice(sessions: list[tuple[str, float, str]], now: datetime) -> PracticeDay:
    """Total practice per local day; a streak counts consecutive days with any practice.

    Today does not break a streak before it has been practised: the streak then runs up to
    yesterday.
    """
    totals: dict[str, float] = {}
    drills: set[str] = set()
    for started, seconds, mode in sessions:
        day = datetime.fromisoformat(started).astimezone(now.tzinfo).date().isoformat()
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
    streak = 0
    cursor = now.date()
    if totals.get(cursor.isoformat(), 0) == 0:
        cursor -= timedelta(days=1)
    while totals.get(cursor.isoformat(), 0) > 0:
        streak += 1
        cursor -= timedelta(days=1)
    return PracticeDay(totals.get(now.date().isoformat(), 0), streak, seven, tuple(sorted(drills)))
