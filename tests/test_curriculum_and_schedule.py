import itertools
import json
import random
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

from consonance.core.curriculum import (
    ITEMS,
    UNITS,
    item_status,
    items_for,
    rebuild_schedule,
    recommended_unit,
    song_item_id,
    unit_progress,
)
from consonance.core.db import Attempt, AttemptLog
from consonance.core.practice_log import local_midnight_utc, summarize_practice

START = datetime(2026, 1, 1, tzinfo=UTC)


def make_attempt(
    number: float,
    *,
    clean: bool = True,
    latency: float = 1000,
    item: str = "note:treble:C4",
    details: str = "{}",
) -> Attempt:
    """Build an attempt ``number`` hours after the start of the test calendar."""
    return Attempt(
        "session",
        ITEMS[item].mode if item in ITEMS else "sight",
        item,
        (60,),
        (60,),
        clean,
        1,
        latency,
        prompt_json=details,
        timestamp_utc=(START + timedelta(hours=number)).isoformat(),
    )


def test_accuracy_without_fluency_does_not_master() -> None:
    """Verify accuracy without fluency does not master."""
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


def test_a_single_sitting_promotes_an_item_only_once() -> None:
    """Verify a single sitting promotes an item only once."""
    cram = [make_attempt(i / 720) for i in range(12)]  # twelve clean answers in a minute
    state = rebuild_schedule(cram)["note:treble:C4"]
    assert state.box == 2
    assert datetime.fromisoformat(state.due_at_utc) == START + timedelta(days=1)
    assert state.mastered  # fluency is still judged on the ten most recent answers


def test_reviews_when_due_climb_the_boxes() -> None:
    """Verify reviews when due climb the boxes."""
    days = (0, 1, 4, 11)
    state = rebuild_schedule([make_attempt(24 * d) for d in days])["note:treble:C4"]
    assert state.box == 5
    assert datetime.fromisoformat(state.due_at_utc) == START + timedelta(days=11 + 21)
    early = rebuild_schedule([make_attempt(0), make_attempt(2)])["note:treble:C4"]
    assert early.box == 2 and datetime.fromisoformat(early.due_at_utc) == START + timedelta(days=1)
    slow = rebuild_schedule([make_attempt(0), make_attempt(30, latency=1700)])["note:treble:C4"]
    assert slow.box == 2
    assert datetime.fromisoformat(slow.due_at_utc) == START + timedelta(hours=34)


def test_blameless_assisted_and_game_attempts_never_move_the_schedule() -> None:
    """Verify blameless assisted and game attempts never move the schedule."""
    attempts = [
        make_attempt(0),
        make_attempt(1, clean=False, details='{"incomplete": true, "blameless": true}'),
        make_attempt(2, details='{"assisted": true}'),
        make_attempt(3, item="rush:1", details='{"game": true, "score": 12}'),
    ]
    states = rebuild_schedule(attempts)
    assert set(states) == {"note:treble:C4"}
    assert states["note:treble:C4"].box == 2 and states["note:treble:C4"].rolling_accuracy == 1.0
    blamed = rebuild_schedule(
        [make_attempt(0), make_attempt(1, clean=False, details='{"incomplete": true}')]
    )
    assert blamed["note:treble:C4"].box == 1


def test_schedule_is_rebuildable_from_durable_attempts(tmp_path: Path) -> None:
    """Verify schedule is rebuildable from durable attempts."""
    log = AttemptLog(tmp_path / "p.db")
    sid = log.start_session("sight")
    for i in range(10):
        log.append(replace(make_attempt(i), session_id=sid))
    log.rebuild_schedule()
    before = log.schedules()
    log.connection.execute("DELETE FROM item_schedule")
    log.rebuild_schedule()
    assert log.schedules() == before
    log.close()


def test_incremental_schedule_updates_equal_a_full_replay(tmp_path: Path) -> None:
    """Verify incremental schedule updates equal a full replay."""
    rng = random.Random(8)
    ids = [i.item_id for i in UNITS[0].items] + ["rhythm:4/4:eighths", "song:ode_to_joy:all:rh"]
    extras = (
        "{}",
        '{"incomplete": true, "blameless": true}',
        json.dumps({"hit_accuracy": 0.95, "jitter_ms": 9, "tempo_bpm": 72, "mode": "Tempo"}),
    )
    log = AttemptLog(tmp_path / "p.db")
    sid = log.start_session("sight")
    hours = 0.0
    for _ in range(600):
        hours += rng.choice((0.001, 0.01, 2, 30, 200))
        attempt = replace(
            make_attempt(
                hours,
                clean=rng.random() < 0.85,
                latency=rng.choice((700.0, 1500.0, 2600.0)),
                item=rng.choice(ids),
                details=rng.choice(extras),
            ),
            session_id=sid,
        )
        log.append(attempt)
        log.update_schedule(attempt)
    incremental = log.schedule_states()
    log.rebuild_schedule()
    assert incremental == log.schedule_states()
    assert not log.ensure_schedule_current()
    log.close()


def test_curriculum_is_open_unique_and_phrases_vary() -> None:
    """Verify curriculum is open unique and phrases vary."""
    assert len(UNITS) == 8
    assert sum(len(u.items) for u in UNITS) == len(ITEMS) == 152
    assert ITEMS["note:treble:C4"] != ITEMS["note:bass:C4"]
    phrase = ITEMS["phrase:treble:C:steps"]
    assert phrase.atoms(0) != phrase.atoms(1)
    assert recommended_unit({}) == 1
    for item in ITEMS.values():
        if item.mode != "song":
            assert item.atoms()
        assert item.title and item.item_id in {i.item_id for i in UNITS[item.unit - 1].items}
    assert {i.mode for i in ITEMS.values()} == {
        "keys",
        "sight",
        "rhythm",
        "technique",
        "ear",
        "song",
    }
    assert all(any(i.mode == mode for i in items_for(mode)) for mode in ("keys", "ear"))


def test_steps_and_skips_phrases_are_what_their_names_say() -> None:
    """Verify steps and skips phrases are what their names say."""

    def leaps(item_id: str) -> set[int]:
        """Collect every melodic distance, in staff steps, across all variations."""
        item = ITEMS[item_id]
        return {
            abs(a.pitches[0].diatonic - b.pitches[0].diatonic)
            for variation in range(item.variations)
            for a, b in itertools.pairwise(item.atoms(variation))
        }

    for clef in ("treble", "bass"):
        assert leaps(f"phrase:{clef}:C:steps") == {1}
        assert max(leaps(f"phrase:{clef}:C:skips")) >= 2
        steps, skips = ITEMS[f"phrase:{clef}:C:steps"], ITEMS[f"phrase:{clef}:C:skips"]
        assert {steps.atoms(v) for v in range(steps.variations)}.isdisjoint(
            {skips.atoms(v) for v in range(skips.variations)}
        )
    # Every variation stays inside the item's five-finger position and key.
    for item in ITEMS.values():
        if item.kind == "phrase":
            low = item.atoms(0)[0].pitches[0].diatonic - 4
            for variation in range(item.variations):
                for atom in item.atoms(variation):
                    assert low <= atom.pitches[0].diatonic <= low + 8
    flats = {
        str(p) for v in range(11) for a in ITEMS["phrase:bass:Bb:steps"].atoms(v) for p in a.pitches
    }
    assert {"Bb2", "Eb3"} <= flats and not {"B2", "E3"} & flats


def test_patterns_end_on_a_long_note_with_fingering() -> None:
    """Verify patterns end on a long note with fingering."""
    penta = ITEMS["tech:rh:C_pentascale"].atoms()
    assert [a.fingering[0] for a in penta] == [1, 2, 3, 4, 5, 4, 3, 2, 1]
    assert [float(a.duration) for a in penta] == [1] * 8 + [4]
    scale = ITEMS["scale:rh:F_major"].atoms()
    assert [a.fingering[0] for a in scale[:8]] == [1, 2, 3, 4, 1, 2, 3, 4]
    assert str(scale[3].pitches[0]) == "Bb4" and len(scale) == 15 and scale[-1].duration == 2
    both = ITEMS["coord:contrary:C"].atoms()
    assert [str(p) for p in both[0].pitches] == ["C4", "G3"] and both[0].fingering == (1, 1)
    assert ITEMS["phrase:treble:G:cancellation"].target_fluency_ms == 3800


def test_song_passes_are_logged_under_curriculum_identities() -> None:
    """Verify song passes are logged under curriculum identities."""
    assert song_item_id("ode_to_joy", "rh") == "song:ode_to_joy:all:rh"
    assert song_item_id("coordination", "both") == "coord:ostinato:C"
    assert song_item_id("ode_to_joy", "lh") == "song:ode_to_joy:all:lh"
    assert song_item_id("ode_to_joy", "rh", "3-4") == "song:ode_to_joy:3-4:rh"
    assert "song:ode_to_joy:all:lh" not in ITEMS and "song:ode_to_joy:all:both" in ITEMS


def test_progress_and_status_follow_the_schedule() -> None:
    """Verify progress and status follow the schedule."""
    attempts = [
        make_attempt(i / 60, item=item.item_id) for item in UNITS[0].items for i in range(10)
    ]
    for item in UNITS[0].items:
        if item.mode == "rhythm":
            ok = json.dumps({"hit_accuracy": 1.0, "jitter_ms": 5, "tempo_bpm": 72})
            attempts += [make_attempt(1 + i / 60, item=item.item_id, details=ok) for i in range(10)]
    states = rebuild_schedule(sorted(attempts, key=lambda a: a.timestamp_utc))
    assert unit_progress(states)[0] == (18, 18)
    assert recommended_unit(states) == 2
    soon = START + timedelta(hours=3)
    assert item_status("note:treble:G4", states, soon) == "mastered"
    assert item_status("note:treble:G4", states, START + timedelta(days=2)) == "due"
    assert item_status("note:treble:D4", states, soon) == "new"


def test_local_practice_minutes_streak_and_drills() -> None:
    """Verify local practice minutes streak and drills."""
    now = datetime(2026, 1, 7, 12, tzinfo=UTC)
    sessions = [(f"2026-01-0{i}T10:00:00+00:00", 120.0, "sight") for i in (5, 6, 7)]
    result = summarize_practice(sessions, now)
    assert result.minutes_today == 2
    assert result.streak == 3
    assert result.drills_today == ("sight",)
    assert len(result.seven_days) == 7
    assert local_midnight_utc(now) == "2026-01-07T00:00:00+00:00"
