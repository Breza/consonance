"""The only owner of musical state; GUI reads an immutable snapshot reference."""

import json
import logging
import queue
import random
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Protocol

from consonance.core.curriculum import StudyConfig
from consonance.core.db import Attempt, AttemptLog
from consonance.core.engine import Action, Command, GameConfig, PracticeEngine, RenderSnapshot
from consonance.core.input_and_grading import NoteOn, normalize
from consonance.core.midi_output import MidiOutputLedger, Settings
from consonance.core.song_session import SongConfig
from consonance.io.midi_ports import MidiPorts

logger = logging.getLogger("consonance.worker")
TICK = 0.002
PUBLISH_EVERY = 0.008
CHECKPOINT_EVERY = 5.0
IDLE_AFTER = 30.0


@dataclass(frozen=True)
class ConnectPorts:
    """Ask the worker to open these ports; empty names unplug that direction."""

    input_name: str
    output_name: str


type Request = Command | ConnectPorts | Settings | SongConfig | StudyConfig | GameConfig


class Ports(Protocol):
    """The part of :class:`MidiPorts` the worker depends on, so tests can substitute it."""

    input_name: str
    output_name: str

    def connect(
        self, input_name: str, output_name: str, receive: Callable[[tuple[int, ...], float], None]
    ) -> None:
        """Open the named ports."""

    def send_bytes(self, data: tuple[int, ...]) -> None:
        """Send one raw MIDI message."""

    def close(self) -> None:
        """Close whichever ports are open."""


class _SessionBook:
    """Create practice-session rows only when there is something to record in them."""

    def __init__(self, log: AttemptLog) -> None:
        """Start with no open session."""
        self.log = log
        self.session: str | None = None
        self.mode = ""
        self.active = 0.0
        self._saved = 0.0

    def session_for(self, mode: str) -> str:
        """Return the open session for ``mode``, starting one if necessary."""
        if self.session is not None and self.mode != mode:
            self.close()
        if self.session is None:
            self.session = self.log.start_session(mode)
            self.mode = mode
        return self.session

    def checkpoint(self, mode: str) -> None:
        """Save accrued practice time if at least a second has been added."""
        if self.active - self._saved >= 1.0:
            self.log.checkpoint_session(self.session_for(mode), self.active)
            self._saved = self.active

    def close(self, mode: str = "") -> None:
        """End the open session, first creating one if only practice time was pending."""
        if self.session is None and self.active > 0 and mode:
            self.session_for(mode)
        if self.session is not None:
            self.log.end_session(self.session, self.active)
        self.session = None
        self.active = self._saved = 0.0


@dataclass
class _Link:
    """What the worker knows about the MIDI connection, for the snapshot."""

    error: str = ""
    seen_user_channel: bool = False
    other_channel: int | None = None


class RealtimeSessionWorker:
    """Run the practice engine on its own thread, about every two milliseconds.

    MIDI arrivals are timestamped on RtMidi's thread and queued; this thread applies them,
    advances the engine, dispatches output a few milliseconds ahead of time, saves attempts,
    and publishes an immutable snapshot for the interface to draw.
    """

    def __init__(
        self,
        db_path: Path,
        *,
        rng: random.Random | None = None,
        ports_factory: Callable[[], Ports] = MidiPorts,
    ) -> None:
        """Prepare a worker; nothing runs until :meth:`start`."""
        self.db_path = db_path
        self.input: queue.SimpleQueue[tuple[float, tuple[int, ...]]] = queue.SimpleQueue()
        self.commands: queue.SimpleQueue[Request] = queue.SimpleQueue()
        self.latest = RenderSnapshot()
        self.saved = 0
        self._rng = rng
        self._ports_factory = ports_factory
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="Consonance MIDI", daemon=True)

    def receive(self, data: tuple[int, ...], timestamp: float | None = None) -> None:
        """Queue raw input with its monotonic arrival timestamp."""
        arrival = time.perf_counter() if timestamp is None else timestamp
        self.input.put((arrival, data))

    def start(self) -> None:
        """Start the worker thread."""
        self._thread.start()

    def submit(self, command: Request) -> None:
        """Queue a request for the worker thread to carry out."""
        self.commands.put(command)

    def close(self) -> None:
        """Stop the worker and wait for it to save and release everything."""
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout=5)

    def _run(self) -> None:
        """Own session state, MIDI dispatch, and persistence on the worker thread."""
        log = AttemptLog(self.db_path)
        engine = PracticeEngine(self._rng)
        engine.bests = {
            key.removeprefix("best:"): float(value)
            for key, value in log.preferences_with_prefix("best:").items()
            if isinstance(value, int | float)
        }
        ports = self._ports_factory()
        ledger = MidiOutputLedger(ports.send_bytes)
        book = _SessionBook(log)
        link = _Link()
        last = next_tick = next_publish = next_checkpoint = last_input = time.perf_counter()
        try:
            while not self._stop.is_set():
                now = time.perf_counter()
                # Practice time accrues while a drill runs and the player is actually there.
                if engine.running and (engine.engaged or now - last_input <= IDLE_AFTER):
                    book.active += now - last
                last = now
                try:
                    acted = self._apply_requests(engine, ledger, ports, log, book, link, now)
                    if acted:
                        next_publish = now  # show the effect of a request without delay
                    if self._apply_input(engine, link) or acted:
                        last_input = now
                    engine.advance_to(now)
                except Exception as exc:
                    logger.exception("The practice engine failed")
                    link.error = f"Something went wrong ({exc}) • practice paused • see the log"
                    self._pause(engine, now)
                try:
                    self._dispatch(engine, ledger, now)
                except Exception:
                    logger.exception("MIDI output failed")
                    engine.output.clear()
                    ledger.forget()
                    ports.close()
                    link.error = "The piano stopped responding • check the cable, then reconnect"
                    self._pause(engine, now)
                self._persist(log, engine, book)
                if now >= next_checkpoint:
                    book.checkpoint(engine.scene)
                    next_checkpoint = now + CHECKPOINT_EVERY
                if now >= next_publish:
                    self._publish(engine, ports, link)
                    next_publish = now + PUBLISH_EVERY
                # time.sleep is a high-resolution wait; Event.wait would round up to ~15 ms.
                next_tick = max(next_tick + TICK, time.perf_counter())
                time.sleep(max(0.0, next_tick - time.perf_counter()))
        finally:
            try:
                engine.abandon()
                self._persist(log, engine, book)
                book.close(engine.scene)
            finally:
                log.close()
                try:
                    ledger.full_hardware_panic()
                except Exception:
                    logger.exception("Could not send the final MIDI cleanup")
                finally:
                    ports.close()

    @staticmethod
    def _pause(engine: PracticeEngine, now: float) -> None:
        """Pause practice after a failure, without letting a second failure escape."""
        try:
            engine.command(Command(Action.PAUSE), now)
        except Exception:
            logger.exception("Could not pause after a failure")

    @staticmethod
    def _dispatch(engine: PracticeEngine, ledger: MidiOutputLedger, now: float) -> None:
        """Release, schedule and send computer output for this tick."""
        if engine.release_requested:
            ledger.release_computer_notes()
            engine.release_requested = False
        for note in engine.output:
            try:
                ledger.schedule(note)
            except ValueError:
                logger.exception("Dropped an invalid output note: %r", note)
        engine.output.clear()
        ledger.advance_to(now)

    def _apply_requests(
        self,
        engine: PracticeEngine,
        ledger: MidiOutputLedger,
        ports: Ports,
        log: AttemptLog,
        book: _SessionBook,
        link: _Link,
        now: float,
    ) -> bool:
        """Carry out every queued request; return True if there was at least one."""
        acted = False
        while not self.commands.empty():
            request = self.commands.get()
            acted = True
            if isinstance(request, ConnectPorts):
                self._connect(request, engine, ledger, ports, link)
            elif isinstance(request, Settings):
                if not request.same_routing(engine.settings):
                    ledger.release_computer_notes()
                    link.seen_user_channel, link.other_channel = False, None
                engine.settings = request
                ledger.user_channel = request.user_channel
            elif isinstance(request, Command) and request.action == Action.PANIC:
                engine.command(Command(Action.PAUSE), now)
                engine.piano.reset()
                ledger.full_hardware_panic()
            elif isinstance(request, Command) and request.action != Action.SWITCH_SCENE:
                if request.action in (Action.PLAY, Action.REPLAY, Action.NEXT):
                    link.error = ""  # the player has moved on from whatever went wrong
                engine.command(request, now)
            else:
                # Anything that replaces the drill: save what the old one produced first.
                old_scene = engine.scene
                engine.abandon()
                self._persist(log, engine, book)
                book.close(old_scene)
                if isinstance(request, Command):
                    engine.command(request, now)
                elif isinstance(request, StudyConfig):
                    engine.configure_study(request)
                elif isinstance(request, SongConfig):
                    engine.configure_song(request)
                else:
                    engine.configure_game(request)
        return acted

    def _connect(
        self,
        request: ConnectPorts,
        engine: PracticeEngine,
        ledger: MidiOutputLedger,
        ports: Ports,
        link: _Link,
    ) -> None:
        """Switch MIDI ports, leaving the old output silent and no key believed held."""
        try:
            ledger.full_hardware_panic()
        except Exception:
            logger.exception("Could not silence the previous MIDI output")
        ledger.forget()
        link.error = ""
        try:
            ports.connect(request.input_name, request.output_name, self.receive)
        except Exception as exc:
            logger.exception("Could not open MIDI ports")
            link.error = f"Could not open the MIDI port • {exc}"
        engine.piano.reset()
        link.seen_user_channel, link.other_channel = False, None

    def _apply_input(self, engine: PracticeEngine, link: _Link) -> bool:
        """Feed queued MIDI input to the engine; return True if the player did anything."""
        played = False
        while not self.input.empty():
            timestamp, raw = self.input.get()
            event = normalize(raw, timestamp)
            if event is None:
                continue
            settings = engine.settings
            if event.channel == settings.user_channel:
                engine.process_midi(event)
                link.seen_user_channel = True
                played = True
            elif isinstance(event, NoteOn) and event.channel not in (
                settings.piano_channel,
                settings.metronome_channel,
            ):
                link.other_channel = event.channel
        return played

    def _persist(self, log: AttemptLog, engine: PracticeEngine, book: _SessionBook) -> None:
        """Commit pending attempt results and refresh the derived schedule."""
        for result in engine.results:
            mode = result.mode or engine.scene
            attempt = Attempt(
                book.session_for(mode),
                mode,
                result.item_id,
                result.expected,
                result.played,
                result.first_try,
                len(result.played),
                result.response_ms,
                result.timing_error_ms,
                result.spread_ms,
                result.velocities,
                result.details,
            )
            log.append(attempt)
            log.update_schedule(attempt)
            self.saved += 1
        engine.results.clear()
        for key, value in engine.new_bests.items():
            log.set_preference(f"best:{key}", json.dumps(value))
        engine.new_bests.clear()

    def _publish(self, engine: PracticeEngine, ports: Ports, link: _Link) -> None:
        """Replace the snapshot the interface reads."""
        try:
            snapshot = engine.snapshot()
        except Exception:
            logger.exception("Could not build a render snapshot")
            return
        hint = None if link.seen_user_channel else link.other_channel
        self.latest = replace(
            snapshot,
            error=link.error,
            midi_in=ports.input_name,
            midi_out=ports.output_name,
            channel_hint=hint,
        )
