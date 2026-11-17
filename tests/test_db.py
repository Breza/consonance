import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from consonance.core.curriculum import SCHEDULE_VERSION
from consonance.core.db import Attempt, AttemptLog
from consonance.core.midi_output import Settings


def test_durable_append_only_log(tmp_path: Path) -> None:
    """Verify durable append only log."""
    log = AttemptLog(tmp_path / "practice.db")
    session = log.start_session("sight")
    attempt = Attempt(session, "sight", "note:treble:C4", (60,), (60,), True, 1, 900)
    log.append(attempt)
    log.close()
    log = AttemptLog(tmp_path / "practice.db")
    assert log.attempts() == [attempt]
    with pytest.raises(Exception, match="append only"):
        log.connection.execute("DELETE FROM attempt_log")
    log.close()


def test_attempts_can_be_read_for_one_item(tmp_path: Path) -> None:
    """Verify attempts can be read for one item."""
    log = AttemptLog(tmp_path / "practice.db")
    session = log.start_session("sight")
    first = Attempt(session, "sight", "note:treble:C4", (60,), (60,), True, 1, 900)
    second = Attempt(session, "sight", "note:treble:G4", (67,), (67,), True, 1, 800)
    log.append(first)
    log.append(second)
    assert log.attempts("note:treble:G4") == [second]
    assert log.attempts("nothing") == []
    log.close()


def test_schedule_version_triggers_one_rebuild(tmp_path: Path) -> None:
    """Verify schedule version triggers one rebuild."""
    log = AttemptLog(tmp_path / "practice.db")
    session = log.start_session("sight")
    log.append(Attempt(session, "sight", "note:treble:C4", (60,), (60,), True, 1, 900))
    assert log.schedule_states() == {}
    assert log.ensure_schedule_current()
    assert log.schedule_states()["note:treble:C4"].box == 2
    assert log.preference_value("schedule_version") == SCHEDULE_VERSION
    assert not log.ensure_schedule_current()
    log.close()


def test_updating_one_item_leaves_the_others_alone(tmp_path: Path) -> None:
    """Verify updating one item leaves the others alone."""
    log = AttemptLog(tmp_path / "practice.db")
    session = log.start_session("sight")
    for item in ("note:treble:C4", "note:treble:G4"):
        attempt = Attempt(session, "sight", item, (60,), (60,), True, 1, 900)
        log.append(attempt)
        log.update_schedule(attempt)
    before = log.schedule_states()["note:treble:C4"]
    miss = Attempt(session, "sight", "note:treble:G4", (67,), (66, 67), False, 2, 900)
    log.append(miss)
    log.update_schedule(miss)
    states = log.schedule_states()
    assert states["note:treble:C4"] == before
    assert states["note:treble:G4"].box == 1 and states["note:treble:G4"].rolling_accuracy == 0.5
    blameless = replace(miss, attempt_id="x", prompt_json='{"blameless": true}')
    log.append(blameless)
    log.update_schedule(blameless)
    assert log.schedule_states() == states
    log.close()


def test_day_queries_and_preferences(tmp_path: Path) -> None:
    """Verify day queries and preferences."""
    log = AttemptLog(tmp_path / "practice.db")
    session = log.start_session("sight")
    now = datetime(2026, 5, 2, 12, tzinfo=UTC)
    for item, when in (
        ("note:treble:C4", now - timedelta(days=2)),
        ("note:treble:C4", now),
        ("note:treble:G4", now),
    ):
        log.append(
            Attempt(session, "sight", item, (60,), (60,), True, 1, timestamp_utc=when.isoformat())
        )
    midnight = (now - timedelta(hours=12)).isoformat()
    assert log.practiced_since(midnight) == {"note:treble:C4", "note:treble:G4"}
    assert log.first_seen_since(midnight) == {"note:treble:G4"}
    log.set_preference("best:rush:1", json.dumps(23))
    log.set_preference("best:echo:0", json.dumps(7))
    log.set_preference("settings", json.dumps({"tempo_bpm": 90}))
    assert log.preferences_with_prefix("best:") == {"best:rush:1": 23, "best:echo:0": 7}
    assert log.preference_value("missing", "fallback") == "fallback"
    assert Settings.from_json(log.preference("settings")).tempo_bpm == 90
    with pytest.raises(ValueError):
        log.set_preference("bad", "{not json")
    log.close()


def test_saved_settings_survive_unknown_and_invalid_fields() -> None:
    """Verify saved settings survive unknown and invalid fields."""
    raw = json.dumps(
        {"tempo_bpm": 96, "from_a_newer_version": 1, "user_channel": 3, "metronome": "Kazoo"}
    )
    settings = Settings.from_json(raw)
    assert (settings.tempo_bpm, settings.user_channel, settings.metronome) == (96, 3, "Woodblock")
    assert Settings.from_json("not json") == Settings() == Settings.from_json(None)
    assert Settings.from_json('{"tempo_bpm": "fast", "show_names": true}').show_names
    clash = Settings.from_json(json.dumps({"user_channel": 1, "visual_offset_ms": -40}))
    assert clash.user_channel == 0 and clash.visual_offset_ms == -40
    assert Settings(show_names=True).assisted and not Settings().assisted
    assert Settings().same_routing(Settings(tempo_bpm=120))
    assert not Settings().same_routing(Settings(metronome="Off"))
