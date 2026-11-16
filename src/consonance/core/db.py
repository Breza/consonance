"""Append-only attempts and rebuildable projections. Each append commits immediately."""

import json
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(frozen=True)
class Attempt:
    session_id: str
    mode: str
    item_id: str
    expected_pitches: tuple[int, ...]
    played_pitches: tuple[int, ...]
    is_first_try_correct: bool
    probe_count: int
    response_ms: float | None = None
    timing_error_ms: float | None = None
    chord_spread_ms: float | None = None
    velocities: tuple[int, ...] = ()
    prompt_json: str = "{}"
    timestamp_utc: str = field(default_factory=utc_now)
    attempt_id: str = field(default_factory=lambda: uuid4().hex)


SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS practice_sessions (
 session_id TEXT PRIMARY KEY, started_at_utc TEXT NOT NULL, ended_at_utc TEXT,
 active_seconds REAL NOT NULL DEFAULT 0, mode TEXT NOT NULL, summary_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS attempt_log (
 attempt_id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES practice_sessions(session_id),
 timestamp_utc TEXT NOT NULL, mode TEXT NOT NULL, item_id TEXT NOT NULL, prompt_json TEXT NOT NULL,
 expected_pitches_json TEXT NOT NULL, played_pitches_json TEXT NOT NULL,
 is_first_try_correct INTEGER NOT NULL CHECK(is_first_try_correct IN (0,1)),
 probe_count INTEGER NOT NULL, response_ms REAL, timing_error_ms REAL, chord_spread_ms REAL,
 velocities_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS attempts_item ON attempt_log(item_id, timestamp_utc);
CREATE TABLE IF NOT EXISTS item_schedule (
 item_id TEXT PRIMARY KEY, box INTEGER NOT NULL CHECK(box BETWEEN 1 AND 5),
 due_at_utc TEXT NOT NULL,
 rolling_accuracy REAL NOT NULL, rolling_median_ms REAL NOT NULL, mastered INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS preferences (key TEXT PRIMARY KEY, value_json TEXT NOT NULL);
CREATE TRIGGER IF NOT EXISTS no_attempt_update BEFORE UPDATE ON attempt_log
 BEGIN SELECT RAISE(ABORT, 'attempt_log is append only'); END;
CREATE TRIGGER IF NOT EXISTS no_attempt_delete BEFORE DELETE ON attempt_log
 BEGIN SELECT RAISE(ABORT, 'attempt_log is append only'); END;
"""


class AttemptLog:
    """Own a connection on the calling thread; use separate instances for worker and GUI."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(SCHEMA)

    def start_session(self, mode: str, at: str | None = None) -> str:
        session = uuid4().hex
        with self.connection:
            self.connection.execute(
                "INSERT INTO practice_sessions(session_id,started_at_utc,mode) VALUES (?,?,?)",
                (session, at or utc_now(), mode),
            )
        return session

    def end_session(self, session: str, active_seconds: float, summary: str = "{}") -> None:
        with self.connection:
            self.connection.execute(
                "UPDATE practice_sessions SET ended_at_utc=?,active_seconds=?,summary_json=? "
                "WHERE session_id=?",
                (utc_now(), active_seconds, summary, session),
            )

    def checkpoint_session(self, session: str, active_seconds: float) -> None:
        with self.connection:
            self.connection.execute(
                "UPDATE practice_sessions SET active_seconds=? WHERE session_id=?",
                (active_seconds, session),
            )

    def rebuild_schedule(self) -> None:
        from consonance.core.curriculum import rebuild_schedule

        states = rebuild_schedule(self.attempts())
        with self.connection:
            self.connection.execute("DELETE FROM item_schedule")
            self.connection.executemany(
                "INSERT INTO item_schedule VALUES (?,?,?,?,?,?)",
                [
                    (
                        s.item_id,
                        s.box,
                        s.due_at_utc,
                        s.rolling_accuracy,
                        s.rolling_median_ms,
                        s.mastered,
                    )
                    for s in states.values()
                ],
            )

    def schedules(self) -> dict[str, tuple[int, str, float, float, bool]]:
        return {
            r["item_id"]: (
                r["box"],
                r["due_at_utc"],
                r["rolling_accuracy"],
                r["rolling_median_ms"],
                bool(r["mastered"]),
            )
            for r in self.connection.execute("SELECT * FROM item_schedule")
        }

    def sessions(self) -> list[tuple[str, float, str]]:
        return [
            (r["started_at_utc"], r["active_seconds"], r["mode"])
            for r in self.connection.execute("SELECT * FROM practice_sessions")
        ]

    def append(self, attempt: Attempt) -> None:
        data = asdict(attempt)
        values = (
            data["attempt_id"],
            data["session_id"],
            data["timestamp_utc"],
            data["mode"],
            data["item_id"],
            data["prompt_json"],
            json.dumps(data["expected_pitches"]),
            json.dumps(data["played_pitches"]),
            data["is_first_try_correct"],
            data["probe_count"],
            data["response_ms"],
            data["timing_error_ms"],
            data["chord_spread_ms"],
            json.dumps(data["velocities"]),
        )
        with self.connection:
            self.connection.execute(
                "INSERT INTO attempt_log VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", values
            )

    def attempts(self) -> list[Attempt]:
        rows = self.connection.execute("SELECT * FROM attempt_log ORDER BY timestamp_utc, rowid")
        return [
            Attempt(
                session_id=r["session_id"],
                mode=r["mode"],
                item_id=r["item_id"],
                expected_pitches=tuple(json.loads(r["expected_pitches_json"])),
                played_pitches=tuple(json.loads(r["played_pitches_json"])),
                is_first_try_correct=bool(r["is_first_try_correct"]),
                probe_count=r["probe_count"],
                response_ms=r["response_ms"],
                timing_error_ms=r["timing_error_ms"],
                chord_spread_ms=r["chord_spread_ms"],
                velocities=tuple(json.loads(r["velocities_json"])),
                prompt_json=r["prompt_json"],
                timestamp_utc=r["timestamp_utc"],
                attempt_id=r["attempt_id"],
            )
            for r in rows
        ]

    def set_preference(self, key: str, value_json: str) -> None:
        json.loads(value_json)
        with self.connection:
            self.connection.execute(
                "INSERT OR REPLACE INTO preferences VALUES (?,?)", (key, value_json)
            )

    def preference(self, key: str) -> str | None:
        row = self.connection.execute("SELECT value_json FROM preferences WHERE key=?", (key,))
        result = row.fetchone()
        return str(result[0]) if result else None

    def close(self) -> None:
        self.connection.close()
