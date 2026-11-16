from datetime import UTC, datetime, timedelta
from pathlib import Path

from consonance.core.curriculum import ITEMS, UNITS, rebuild_schedule, recommended_unit
from consonance.core.db import Attempt, AttemptLog
from consonance.core.practice_log import summarize_practice


def make_attempt(number: int, *, clean: bool = True, latency: float = 1000) -> Attempt:
    return Attempt(
        "session",
        "sight",
        "note:treble:C4",
        (60,),
        (60,),
        clean,
        1,
        latency,
        timestamp_utc=(datetime(2026, 1, 1, tzinfo=UTC) + timedelta(hours=number)).isoformat(),
    )


def test_accuracy_without_fluency_does_not_master() -> None:
    slow = rebuild_schedule([make_attempt(i, latency=2000) for i in range(10)])
    assert not slow["note:treble:C4"].mastered
    assert slow["note:treble:C4"].box == 1
    clean = rebuild_schedule([make_attempt(i, clean=i != 2) for i in range(10)])
    assert clean["note:treble:C4"].mastered
    assert clean["note:treble:C4"].rolling_accuracy == 0.9
    assert not rebuild_schedule([make_attempt(i) for i in range(9)])["note:treble:C4"].mastered
    reset = rebuild_schedule([make_attempt(0), make_attempt(1, clean=False)])
    assert reset["note:treble:C4"].box == 1
    assert datetime.fromisoformat(reset["note:treble:C4"].due_at_utc).hour == 5


def test_schedule_is_rebuildable_from_durable_attempts(tmp_path: Path) -> None:
    log = AttemptLog(tmp_path / "p.db")
    sid = log.start_session("sight")
    for i in range(10):
        a = make_attempt(i)
        from dataclasses import replace

        log.append(replace(a, session_id=sid))
    log.rebuild_schedule()
    before = log.schedules()
    log.connection.execute("DELETE FROM item_schedule")
    log.rebuild_schedule()
    assert log.schedules() == before
    log.close()


def test_curriculum_is_open_unique_and_phrases_vary() -> None:
    assert len(UNITS) == 8
    assert sum(len(u.items) for u in UNITS) == len(ITEMS)
    assert ITEMS["note:treble:C4"] != ITEMS["note:bass:C4"]
    phrase = ITEMS["phrase:treble:C:steps"]
    assert phrase.atoms(0) != phrase.atoms(1)
    assert recommended_unit({}) == 1
    for item in ITEMS.values():
        if item.mode != "song":
            assert item.atoms()


def test_local_practice_minutes_streak_and_drills() -> None:
    now = datetime(2026, 1, 7, 12, tzinfo=UTC)
    sessions = [(f"2026-01-0{i}T10:00:00+00:00", 120.0, "sight") for i in (5, 6, 7)]
    result = summarize_practice(sessions, now)
    assert result.minutes_today == 2
    assert result.streak == 3
    assert result.drills_today == ("sight",)
    assert len(result.seven_days) == 7
