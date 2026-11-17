"""Completion days, honest insights, and reversible practice bookmarks."""

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

from consonance.core.builtin_scores import BUILTIN_SCORES
from consonance.core.db import Attempt, AttemptLog
from consonance.core.home import available_steps, reading_insight, restore_song, song_bookmark
from consonance.core.notation import Hand
from consonance.core.plan import Plan, PlanStep
from consonance.core.practice_log import summarize_practice
from consonance.core.song_session import SongConfig


def test_ninety_days_are_inclusive_deduplicated_and_do_not_reset_after_gaps() -> None:
    """Include today and day 89, ignore day 90 and future timestamps, and tolerate gaps."""
    now = datetime(2026, 11, 17, 12, tzinfo=UTC)
    timestamps = [(now - timedelta(days=d)).isoformat() for d in (0, 0, 3, 40, 89, 90, -1)]
    summary = summarize_practice([], now, timestamps)
    assert summary.lesson_days_90 == 4
    assert len(summary.lesson_dates_90) == 4
    assert summarize_practice([], now + timedelta(days=1), timestamps[:-1]).lesson_days_90 == 3
    assert summarize_practice([(now.isoformat(), 100.0, "keys")], now).lesson_days_90 == 0


def test_lesson_days_use_local_calendar_boundaries() -> None:
    """UTC midnight does not create two days for an evening learner in New York."""
    zone = timezone(timedelta(hours=-5))
    now = datetime(2026, 11, 17, 12, tzinfo=zone)
    summary = summarize_practice(
        [], now, ("2026-11-17T00:30:00+00:00", "2026-11-17T03:30:00+00:00")
    )
    assert summary.lesson_days_90 == 1
    assert summary.lesson_dates_90 == ("2026-11-16",)


def test_historical_dst_does_not_drop_the_first_hour_of_the_ninety_day_window() -> None:
    """An explicitly supplied timezone resolver can apply summer and winter offsets."""

    def localize(instant: datetime) -> datetime:
        """Model New York's fall 2026 transition without relying on installed zone data."""
        hours = -4 if instant < datetime(2026, 11, 1, 6, tzinfo=UTC) else -5
        return instant.astimezone(timezone(timedelta(hours=hours)))

    now = localize(datetime(2026, 11, 17, 17, tzinfo=UTC))
    summary = summarize_practice([], now, ("2026-08-20T04:30:00+00:00",), localize=localize)
    assert summary.lesson_dates_90 == ("2026-08-20",)


def test_completion_evidence_excludes_abandons_but_includes_assisted_and_mistaken_answers(
    tmp_path: Path,
) -> None:
    """Count actual finished answers rather than app visits, elapsed time, or perfection."""
    log = AttemptLog(tmp_path / "practice.sqlite3")
    now = datetime(2026, 11, 17, 12, tzinfo=UTC)
    session = log.start_session("keys", now.isoformat())
    for i, details in enumerate(
        (
            {},
            {"assisted": True},
            {"incomplete": True},
            {"incomplete": True, "blameless": True},
            {"game": True},
        )
    ):
        log.append(
            Attempt(
                session,
                "keys",
                "key:C4",
                (60,),
                (60,),
                False,
                2,
                prompt_json=json.dumps(details),
                timestamp_utc=(now - timedelta(days=i)).isoformat(),
            )
        )
    summary = summarize_practice(log.sessions(), now, log.completed_at("2026-01-01"))
    assert summary.lesson_days_90 == 3
    assert summary.minutes_today == 0
    log.close()


def test_connection_changes_recommendations_without_hiding_the_library() -> None:
    """An unplugged recommendation uses silent reading; a connected piano can train ears."""
    quiet = PlanStep("new", "sight", "Reading", "", ("note:treble:G4",))
    audio = PlanStep("review", "ear", "Listen", "", ("ear:note:1",))
    plan = Plan((audio, quiet), 1, 3, 1)
    assert available_steps(plan, False, False) == (quiet,)
    assert available_steps(plan, True, False) == (quiet,)
    assert available_steps(plan, True, True) == (audio, quiet)
    assert plan.steps == (audio, quiet)


def test_piece_bookmarks_keep_hands_section_tempo_and_loop_choices() -> None:
    """Restore a real configuration, rejecting stale songs and impossible sections."""
    timeline = BUILTIN_SCORES[0].compile()
    config = SongConfig(timeline, "Tempo", frozenset({Hand.LEFT}), 0.85, 2, 3, True, True)
    bookmark = song_bookmark(config)
    assert restore_song(bookmark, [timeline]) == config
    assert restore_song(bookmark, []) is None
    assert restore_song({**bookmark, "start_measure": 999}, [timeline]) is None
    assert restore_song({**bookmark, "hand": "invalid"}, [timeline]) is None


def test_reading_insights_need_comparable_evidence_and_steady_accuracy() -> None:
    """Never infer improvement from tiny samples, hints, or falling first-try accuracy."""
    attempts = [
        Attempt("s", "sight", "note:treble:G4", (67,), (67,), True, 1, 2000 if i < 5 else 1400)
        for i in range(10)
    ]
    assert reading_insight(attempts) is not None
    assert reading_insight(attempts[:9]) is None
    assert reading_insight([replace(a, prompt_json='{"assisted":true}') for a in attempts]) is None
    assert (
        reading_insight([replace(a, prompt_json='{"incomplete":true}') for a in attempts]) is None
    )
    assert (
        reading_insight([replace(a, is_first_try_correct=i < 5) for i, a in enumerate(attempts)])
        is None
    )
