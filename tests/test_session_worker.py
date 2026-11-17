import sqlite3
import time
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from consonance.core.curriculum import ITEMS, StudyConfig
from consonance.core.engine import Action, Command, GameConfig
from consonance.core.midi_output import Settings
from consonance.io.session_worker import ConnectPorts, RealtimeSessionWorker


class FakePorts:
    """Stand in for the MIDI ports: record what is sent and fail on request."""

    def __init__(self) -> None:
        """Start unplugged."""
        self.input_name = ""
        self.output_name = ""
        self.sent: list[tuple[int, ...]] = []
        self.fail = False

    def connect(
        self, input_name: str, output_name: str, receive: Callable[[tuple[int, ...], float], None]
    ) -> None:
        """Pretend to open ports; a name containing ``missing`` cannot be opened."""
        self.close()
        if "missing" in input_name:
            raise OSError("no such port")
        self.input_name, self.output_name = input_name, output_name

    def send_bytes(self, data: tuple[int, ...]) -> None:
        """Record a message, or fail as an unplugged cable would."""
        if self.fail:
            raise OSError("device removed")
        self.sent.append(data)

    def close(self) -> None:
        """Forget the open ports."""
        self.input_name = self.output_name = ""


class Rig:
    """A running worker with its fake ports and database path."""

    def __init__(self, path: Path) -> None:
        """Start the worker thread."""
        self.path = path
        self.ports = FakePorts()
        self.worker = RealtimeSessionWorker(path, ports_factory=lambda: self.ports)
        self.worker.start()

    def until(self, condition: Callable[[], bool], seconds: float = 4.0) -> None:
        """Wait for the worker to reach a state, failing the test if it never does."""
        deadline = time.perf_counter() + seconds
        while not condition():
            assert time.perf_counter() < deadline, f"timed out; last status: {self.worker.latest}"
            time.sleep(0.004)

    def tap(self, pitch: int, channel: int = 0) -> None:
        """Send a short note as the piano would."""
        self.worker.receive((0x90 | channel, pitch, 80))
        self.worker.receive((0x80 | channel, pitch, 0))

    def rows(self, query: str) -> list[tuple[object, ...]]:
        """Read from the practice database on a connection of our own."""
        connection = sqlite3.connect(self.path)
        try:
            return list(connection.execute(query))
        finally:
            connection.close()


@pytest.fixture
def rig(tmp_path: Path) -> Iterator[Rig]:
    """Provide a running worker and always stop it afterwards."""
    running = Rig(tmp_path / "practice.sqlite3")
    try:
        yield running
    finally:
        running.worker.close()


def test_attempts_schedule_and_sessions_are_saved_as_they_happen(rig: Rig) -> None:
    """Verify attempts schedule and sessions are saved as they happen."""
    rig.until(lambda: rig.worker.latest.scene == "sight" and bool(rig.worker.latest.title))
    assert rig.rows("SELECT count(*) FROM practice_sessions") == [(0,)]  # nothing to record yet
    rig.worker.submit(StudyConfig((ITEMS["key:C"], ITEMS["key:D"]), "Two keys"))
    rig.worker.submit(Command(Action.PLAY))
    rig.until(lambda: rig.worker.latest.running and rig.worker.latest.scene == "keys")
    assert rig.worker.latest.set_title == "Two keys"
    for count in (1, 2, 3):

        def prompt_shown(answered: int = count - 1) -> bool:
            """Snapshots trail the engine by a few milliseconds: wait for the next prompt."""
            latest = rig.worker.latest
            return latest.completed == answered and bool(latest.expected)

        def saved_so_far(wanted: int = count) -> bool:
            """Report whether the answer just given has reached the database."""
            return rig.worker.saved == wanted

        rig.until(prompt_shown)
        rig.tap(60 if rig.worker.latest.title == "Find C" else 62)
        rig.until(saved_so_far)
    saved = rig.rows("SELECT mode, item_id, is_first_try_correct FROM attempt_log ORDER BY rowid")
    assert [row[0] for row in saved] == ["keys"] * 3 and all(row[2] == 1 for row in saved)
    assert {row[1] for row in saved} == {"key:C", "key:D"}
    assert len(rig.rows("SELECT * FROM item_schedule")) == 2
    rig.worker.submit(Command(Action.SWITCH_SCENE, "sight"))
    rig.until(lambda: rig.worker.latest.scene == "sight")
    sessions = rig.rows("SELECT mode, active_seconds, ended_at_utc FROM practice_sessions")
    assert len(sessions) == 1 and sessions[0][0] == "keys" and sessions[0][2] is not None
    assert isinstance(sessions[0][1], float) and sessions[0][1] > 0


def test_connection_state_and_a_wrong_input_channel_are_reported(rig: Rig) -> None:
    """Verify connection state and a wrong input channel are reported."""
    rig.worker.submit(ConnectPorts("Piano 0", "Piano 1"))
    rig.until(lambda: rig.worker.latest.midi_in == "Piano 0")
    assert rig.worker.latest.midi_out == "Piano 1" and not rig.worker.latest.error
    rig.tap(60, channel=3)
    rig.until(lambda: rig.worker.latest.channel_hint == 3)
    rig.tap(60, channel=1)  # the computer's own piano channel echoing back is not a hint
    rig.worker.submit(Settings(user_channel=3))
    rig.until(lambda: rig.worker.latest.channel_hint is None)
    rig.tap(64, channel=3)
    rig.worker.submit(Command(Action.PLAY))
    rig.until(lambda: rig.worker.latest.running)
    rig.worker.receive((0x93, 67, 80))
    rig.until(lambda: rig.worker.latest.held == frozenset({67}))
    rig.worker.submit(ConnectPorts("missing 0", ""))
    rig.until(lambda: "Could not open the MIDI port" in rig.worker.latest.error)
    assert rig.worker.latest.midi_in == "" and rig.worker.latest.held == frozenset()


def test_losing_the_output_closes_the_ports_and_pauses_practice(rig: Rig) -> None:
    """Verify losing the output closes the ports and pauses practice."""
    rig.worker.submit(ConnectPorts("Piano 0", "Piano 1"))
    rig.worker.submit(Command(Action.SWITCH_SCENE, "ear"))
    rig.worker.submit(Command(Action.PLAY))
    rig.until(lambda: any(message[0] == 0x91 for message in rig.ports.sent))
    assert rig.worker.latest.running
    rig.ports.fail = True
    rig.worker.submit(Command(Action.REPLAY))
    rig.until(lambda: "stopped responding" in rig.worker.latest.error)
    rig.until(lambda: not rig.worker.latest.running)
    assert rig.worker.latest.midi_out == "" and rig.worker.latest.midi_in == ""
    rig.ports.fail = False
    rig.worker.submit(Command(Action.PLAY))  # carrying on clears the message
    rig.until(lambda: rig.worker.latest.running and not rig.worker.latest.error)
    rig.worker.submit(ConnectPorts("Piano 0", "Piano 1"))
    rig.until(lambda: rig.worker.latest.midi_out == "Piano 1" and not rig.worker.latest.error)


def test_panic_silences_every_channel_and_forgets_stuck_keys(rig: Rig) -> None:
    """Verify panic silences every channel and forgets stuck keys."""
    rig.worker.submit(ConnectPorts("", "Piano 1"))
    rig.worker.receive((0x90, 60, 80))  # a key whose release never arrives
    rig.until(lambda: rig.worker.latest.held == frozenset({60}))
    rig.ports.sent.clear()
    rig.worker.submit(Command(Action.PANIC))
    rig.until(lambda: rig.worker.latest.held == frozenset())
    rig.until(lambda: len(rig.ports.sent) >= 32)
    for channel in range(16):
        assert (0xB0 | channel, 123, 0) in rig.ports.sent
        assert (0xB0 | channel, 64, 0) in rig.ports.sent


def test_computer_output_never_uses_the_players_channel(rig: Rig) -> None:
    """Verify computer output never uses the players channel."""
    rig.worker.submit(ConnectPorts("", "Piano 1"))
    rig.worker.submit(Settings(tempo_bpm=200))
    rig.worker.submit(StudyConfig((ITEMS["rhythm:4/4:quarters"],)))
    rig.worker.submit(Command(Action.PLAY))
    rig.until(lambda: sum(message[0] == 0x99 for message in rig.ports.sent) >= 12, seconds=6.0)
    rig.until(lambda: not rig.worker.latest.running, seconds=6.0)
    notes = [message for message in rig.ports.sent if message[0] & 0xF0 in (0x80, 0x90)]
    assert notes and all(message[0] & 0x0F == 9 for message in notes)
    assert rig.rows("SELECT is_first_try_correct FROM attempt_log") == [(0,)]


def test_a_game_best_is_stored_for_next_time(tmp_path: Path) -> None:
    """Verify a game best is stored for next time."""
    first = Rig(tmp_path / "practice.sqlite3")
    try:
        first.worker.submit(GameConfig("echo", 0))
        first.worker.submit(Command(Action.PLAY))
        first.until(lambda: bool(first.worker.latest.expected))
        first.tap(min(first.worker.latest.expected))
        first.until(lambda: first.worker.latest.status.startswith("Echoed 1"))
        first.worker.submit(Command(Action.PAUSE))
        first.until(lambda: first.worker.latest.game is not None and first.worker.latest.game.over)
        first.until(lambda: first.worker.saved == 1)
    finally:
        first.worker.close()
    assert first.rows("SELECT value_json FROM preferences WHERE key='best:echo:0'") == [("1",)]
    assert first.rows("SELECT mode, item_id FROM attempt_log") == [("echo", "echo:0")]
    assert first.rows("SELECT count(*) FROM item_schedule") == [(0,)]
    second = Rig(tmp_path / "practice.sqlite3")
    try:
        second.worker.submit(GameConfig("echo", 0))
        second.until(lambda: second.worker.latest.game is not None)
        game = second.worker.latest.game
        assert game is not None and game.best == 1
    finally:
        second.worker.close()
