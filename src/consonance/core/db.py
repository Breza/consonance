"""Append-only attempts and rebuildable projections. Each append commits immediately."""

import json
import sqlite3
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

if TYPE_CHECKING:
    from consonance.core.curriculum import ItemSchedule


def utc_now() -> str:
    """Return the current instant as an ISO-8601 UTC timestamp."""
    return datetime.now(UTC).isoformat()


@dataclass(frozen=True)
class Attempt:
    """One answered (or abandoned) prompt, exactly as it happened."""

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


# WAL with synchronous=NORMAL survives an application crash without an fsync per commit,
# which keeps saving an attempt well under a millisecond on the realtime thread.
SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
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
CREATE INDEX IF NOT EXISTS attempts_time ON attempt_log(timestamp_utc);
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
_UPSERT = (
    "INSERT INTO item_schedule VALUES (?,?,?,?,?,?) ON CONFLICT(item_id) DO UPDATE SET "
    "box=excluded.box, due_at_utc=excluded.due_at_utc, rolling_accuracy=excluded.rolling_accuracy, "
    "rolling_median_ms=excluded.rolling_median_ms, mastered=excluded.mastered"
)


def _attempt(row: sqlite3.Row) -> Attempt:
    """Rebuild an attempt from its stored row."""
    return Attempt(
        row["session_id"],
        row["mode"],
        row["item_id"],
        tuple(json.loads(row["expected_pitches_json"])),
        tuple(json.loads(row["played_pitches_json"])),
        bool(row["is_first_try_correct"]),
        row["probe_count"],
        row["response_ms"],
        row["timing_error_ms"],
        row["chord_spread_ms"],
        tuple(json.loads(row["velocities_json"])),
        row["prompt_json"],
        row["timestamp_utc"],
        row["attempt_id"],
    )


def _schedule(row: sqlite3.Row) -> "ItemSchedule":
    """Rebuild an item's review state from its stored row."""
    from consonance.core.curriculum import ItemSchedule

    return ItemSchedule(
        row["item_id"],
        row["box"],
        row["due_at_utc"],
        row["rolling_accuracy"],
        row["rolling_median_ms"],
        bool(row["mastered"]),
    )


class AttemptLog:
    """Own a connection on the calling thread; use separate instances for worker and GUI."""

    def __init__(self, path: Path) -> None:
        """Open (creating if needed) the practice database at ``path``."""
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(SCHEMA)

    def start_session(self, mode: str, at: str | None = None) -> str:
        """Record the start of a practice session and return its identifier."""
        session = uuid4().hex
        with self.connection:
            self.connection.execute(
                "INSERT INTO practice_sessions(session_id,started_at_utc,mode) VALUES (?,?,?)",
                (session, at or utc_now(), mode),
            )
        return session

    def end_session(self, session: str, active_seconds: float, summary: str = "{}") -> None:
        """Close a session with its final active time."""
        with self.connection:
            self.connection.execute(
                "UPDATE practice_sessions SET ended_at_utc=?,active_seconds=?,summary_json=? "
                "WHERE session_id=?",
                (utc_now(), active_seconds, summary, session),
            )

    def checkpoint_session(self, session: str, active_seconds: float) -> None:
        """Save a running session's active time so a crash loses at most a few seconds."""
        with self.connection:
            self.connection.execute(
                "UPDATE practice_sessions SET active_seconds=? WHERE session_id=?",
                (active_seconds, session),
            )

    def sessions(self) -> list[tuple[str, float, str]]:
        """Return (start, active seconds, mode) for every recorded session."""
        return [
            (r["started_at_utc"], r["active_seconds"], r["mode"])
            for r in self.connection.execute("SELECT * FROM practice_sessions")
        ]

    def append(self, attempt: Attempt) -> None:
        """Durably append one attempt; the log is never edited afterwards."""
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
            int(data["is_first_try_correct"]),
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

    def attempts(self, item_id: str | None = None) -> list[Attempt]:
        """Return attempts oldest first, for one item or for the whole log."""
        if item_id is None:
            rows = self.connection.execute(
                "SELECT * FROM attempt_log ORDER BY timestamp_utc, rowid"
            )
        else:
            rows = self.connection.execute(
                "SELECT * FROM attempt_log WHERE item_id=? ORDER BY timestamp_utc, rowid",
                (item_id,),
            )
        return [_attempt(r) for r in rows]

    def schedule_states(self) -> dict[str, "ItemSchedule"]:
        """Return the stored review state of every item that has one."""
        return {
            r["item_id"]: _schedule(r)
            for r in self.connection.execute("SELECT * FROM item_schedule")
        }

    def schedules(self) -> dict[str, tuple[int, str, float, float, bool]]:
        """Return each item's review state as a plain tuple keyed by item."""
        return {
            item: (s.box, s.due_at_utc, s.rolling_accuracy, s.rolling_median_ms, s.mastered)
            for item, s in self.schedule_states().items()
        }

    def _store(self, states: Iterable["ItemSchedule"]) -> None:
        """Write review states inside the caller's transaction."""
        self.connection.executemany(
            _UPSERT,
            [
                (
                    s.item_id,
                    s.box,
                    s.due_at_utc,
                    s.rolling_accuracy,
                    s.rolling_median_ms,
                    int(s.mastered),
                )
                for s in states
            ],
        )

    def rebuild_schedule(self) -> None:
        """Recompute every item's review state from the complete attempt log."""
        from consonance.core.curriculum import SCHEDULE_VERSION, rebuild_schedule

        states = rebuild_schedule(self.attempts())
        with self.connection:
            self.connection.execute("DELETE FROM item_schedule")
            self._store(states.values())
            self.connection.execute(
                "INSERT INTO preferences VALUES ('schedule_version', ?) "
                "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",
                (json.dumps(SCHEDULE_VERSION),),
            )

    def ensure_schedule_current(self) -> bool:
        """Rebuild the schedule once if it was written by older scheduling rules."""
        from consonance.core.curriculum import SCHEDULE_VERSION

        if self.preference_value("schedule_version", 0) == SCHEDULE_VERSION:
            return False
        self.rebuild_schedule()
        return True

    def update_schedule(self, attempt: Attempt) -> None:
        """Fold one just-appended attempt into its item's review state.

        This touches only that item's row and reads only its latest few attempts, so the
        cost of saving an answer does not grow with the size of the log.
        """
        from consonance.core.curriculum import WINDOW, advance_schedule, countable

        if not countable(attempt):
            return
        recent: list[Attempt] = []
        cursor = self.connection.execute(
            "SELECT * FROM attempt_log WHERE item_id=? ORDER BY timestamp_utc DESC, rowid DESC",
            (attempt.item_id,),
        )
        for row in cursor:
            candidate = _attempt(row)
            if countable(candidate):
                recent.append(candidate)
                if len(recent) == WINDOW:
                    break
        cursor.close()
        stored = self.connection.execute(
            "SELECT * FROM item_schedule WHERE item_id=?", (attempt.item_id,)
        ).fetchone()
        previous = _schedule(stored) if stored else None
        with self.connection:
            self._store([advance_schedule(previous, recent[::-1])])

    def practiced_since(self, since_utc: str) -> set[str]:
        """Return the items attempted at or after an instant."""
        rows = self.connection.execute(
            "SELECT DISTINCT item_id FROM attempt_log WHERE timestamp_utc>=?", (since_utc,)
        )
        return {r[0] for r in rows}

    def first_seen_since(self, since_utc: str) -> set[str]:
        """Return the items whose very first attempt happened at or after an instant."""
        rows = self.connection.execute(
            "SELECT item_id FROM attempt_log GROUP BY item_id HAVING MIN(timestamp_utc)>=?",
            (since_utc,),
        )
        return {r[0] for r in rows}

    def set_preference(self, key: str, value_json: str) -> None:
        """Store a JSON-encoded preference, replacing any earlier value."""
        json.loads(value_json)
        with self.connection:
            self.connection.execute(
                "INSERT INTO preferences VALUES (?,?) "
                "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",
                (key, value_json),
            )

    def preference(self, key: str) -> str | None:
        """Return a preference's raw JSON text, or None if it was never set."""
        row = self.connection.execute("SELECT value_json FROM preferences WHERE key=?", (key,))
        result = row.fetchone()
        return str(result[0]) if result else None

    def preference_value(self, key: str, default: Any = None) -> Any:
        """Return a decoded preference, or ``default`` if it is missing or unreadable."""
        raw = self.preference(key)
        if raw is None:
            return default
        try:
            return json.loads(raw)
        except ValueError:
            return default

    def preferences_with_prefix(self, prefix: str) -> dict[str, Any]:
        """Return every decoded preference whose key starts with ``prefix``."""
        result: dict[str, Any] = {}
        for key, raw in self.connection.execute("SELECT key, value_json FROM preferences"):
            if str(key).startswith(prefix):
                try:
                    result[str(key)] = json.loads(raw)
                except ValueError:
                    continue
        return result

    def close(self) -> None:
        """Close the database connection."""
        self.connection.close()
