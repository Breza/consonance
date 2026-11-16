"""The only owner of musical state; GUI reads an immutable snapshot reference."""

import queue
import threading
import time
from dataclasses import dataclass, replace
from pathlib import Path

from consonance.core.curriculum import StudyConfig
from consonance.core.db import Attempt, AttemptLog
from consonance.core.engine import Action, Command, PracticeEngine, RenderSnapshot
from consonance.core.input_and_grading import normalize
from consonance.core.midi_output import MidiOutputLedger, Settings
from consonance.core.song_session import SongConfig
from consonance.io.midi_ports import MidiPorts


@dataclass(frozen=True)
class ConnectPorts:
    input_name: str
    output_name: str


class RealtimeSessionWorker:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.input: queue.SimpleQueue[tuple[float, tuple[int, ...]]] = queue.SimpleQueue()
        self.commands: queue.SimpleQueue[
            Command | ConnectPorts | Settings | SongConfig | StudyConfig
        ] = queue.SimpleQueue()
        self.latest = RenderSnapshot()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="Consonance MIDI", daemon=True)

    def receive(self, data: tuple[int, ...], timestamp: float | None = None) -> None:
        arrival = time.perf_counter() if timestamp is None else timestamp
        self.input.put((arrival, data))

    def start(self) -> None:
        self._thread.start()

    def submit(self, command: Command | ConnectPorts | Settings | SongConfig | StudyConfig) -> None:
        self.commands.put(command)

    def close(self) -> None:
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout=5)

    def _run(self) -> None:
        log = AttemptLog(self.db_path)
        engine = PracticeEngine()
        ports = MidiPorts()
        ledger = MidiOutputLedger(ports.send_bytes)
        session = log.start_session(engine.scene)
        active = 0.0
        last = time.perf_counter()
        error = ""
        next_port_check = last
        next_checkpoint = last
        next_tick = last
        try:
            while not self._stop.is_set():
                now = time.perf_counter()
                if engine.running:
                    active += now - last
                last = now
                try:
                    while not self.commands.empty():
                        cmd = self.commands.get()
                        if isinstance(cmd, ConnectPorts):
                            ledger.full_hardware_panic()
                            ports.connect(cmd.input_name, cmd.output_name, self.receive)
                            error = ""
                        elif isinstance(cmd, Settings):
                            ledger.release_computer_notes()
                            engine.settings = cmd
                            if engine.song:
                                engine.song.settings = cmd
                            ledger.user_channel = cmd.user_channel
                        elif isinstance(cmd, SongConfig):
                            engine.abandon()
                            self._persist(log, engine, session)
                            engine.configure_song(cmd)
                        elif isinstance(cmd, StudyConfig):
                            engine.abandon()
                            self._persist(log, engine, session)
                            log.end_session(session, active)
                            engine.configure_study(cmd)
                            session = log.start_session(engine.scene)
                            active = 0
                        else:
                            if cmd.action == Action.SWITCH_SCENE:
                                engine.abandon()
                                self._persist(log, engine, session)
                                log.end_session(session, active)
                                engine.command(cmd, now)
                                session = log.start_session(engine.scene)
                                active = 0
                            elif cmd.action == Action.PANIC:
                                engine.command(Command(Action.PAUSE), now)
                                ledger.full_hardware_panic()
                            else:
                                engine.command(cmd, now)
                    while not self.input.empty():
                        timestamp, raw = self.input.get()
                        event = normalize(raw, timestamp)
                        if event is not None and event.channel == engine.settings.user_channel:
                            engine.process_midi(event)
                    engine.advance_to(now)
                    if engine.release_requested:
                        ledger.release_computer_notes()
                        engine.release_requested = False
                    for note in engine.output:
                        ledger.schedule(note)
                    engine.output.clear()
                    ledger.advance_to(now)
                    if now >= next_port_check:
                        next_port_check = now + 2
                        if ports.input is not None or ports.output is not None:
                            inputs, outputs = ports.names()
                            if (ports.input is not None and ports.input_name not in inputs) or (
                                ports.output is not None and ports.output.name not in outputs
                            ):
                                ledger.full_hardware_panic()
                                ports.close()
                                engine.command(Command(Action.PAUSE), now)
                                error = "MIDI disconnected • reconnect the piano"
                except Exception as exc:
                    error = str(exc)
                    try:
                        ledger.full_hardware_panic()
                    except Exception:
                        pass
                    ports.close()
                    engine.command(Command(Action.PAUSE), now)
                self._persist(log, engine, session)
                if now >= next_checkpoint:
                    log.checkpoint_session(session, active)
                    next_checkpoint = now + 1
                self.latest = replace(engine.snapshot(), error=error)
                next_tick = max(next_tick + 0.002, time.perf_counter())
                self._stop.wait(max(0.0, next_tick - time.perf_counter()))
        finally:
            engine.abandon()
            self._persist(log, engine, session)
            log.end_session(session, active)
            log.close()
            try:
                ledger.full_hardware_panic()
            finally:
                ports.close()

    @staticmethod
    def _persist(log: AttemptLog, engine: PracticeEngine, session: str) -> None:
        changed = bool(engine.results)
        for r in engine.results:
            log.append(
                Attempt(
                    session,
                    engine.scene,
                    r.item_id,
                    r.expected,
                    r.played,
                    r.first_try,
                    len(r.played),
                    r.response_ms,
                    r.timing_error_ms,
                    r.spread_ms,
                    r.velocities,
                    r.details,
                )
            )
        engine.results.clear()
        if changed:
            log.rebuild_schedule()
