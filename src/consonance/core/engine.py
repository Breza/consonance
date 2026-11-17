"""Session state machine. Callers own time, devices, persistence, threads, and randomness."""

import random
from dataclasses import dataclass, replace
from enum import StrEnum

from consonance.core.builtin_scores import BUILTIN_SCORES
from consonance.core.curriculum import ITEMS, CurriculumItem, StudyConfig, items_for
from consonance.core.drills.base import (
    Drill,
    DrillView,
    GameState,
    Marks,
    PracticeResult,
    Prompt,
    Pulse,
)
from consonance.core.drills.games import EchoDrill, RushDrill, rush_pool
from consonance.core.drills.rhythm_round import RhythmDrill
from consonance.core.drills.sequence import EarDrill, KeysDrill, SightDrill, TechniqueDrill
from consonance.core.drills.song_drill import SongDrill
from consonance.core.input_and_grading import (
    MidiEvent,
    PianoStateTracker,
    SoftPedalTap,
    UntimedEvaluator,
)
from consonance.core.midi_output import OutputNote, Settings
from consonance.core.notation_layout import StaffLayout
from consonance.core.song_session import SongConfig, SongSession

__all__ = [
    "Action",
    "Command",
    "GameConfig",
    "PracticeEngine",
    "PracticeResult",
    "Prompt",
    "RenderSnapshot",
]

SCENES = ("keys", "sight", "rush", "rhythm", "technique", "ear", "echo", "song")
STUDY_DRILLS: dict[str, type[KeysDrill | SightDrill | RhythmDrill | TechniqueDrill | EarDrill]] = {
    "keys": KeysDrill,
    "sight": SightDrill,
    "rhythm": RhythmDrill,
    "technique": TechniqueDrill,
    "ear": EarDrill,
}


class Action(StrEnum):
    """What a caller can ask the engine to do."""

    PLAY = "Play"
    PAUSE = "Pause"
    REPLAY = "Replay"
    SEEK = "Seek"
    SWITCH_SCENE = "SwitchScene"
    PANIC = "Panic"
    STOP = "Stop"
    NEXT = "Next"
    HINT = "Hint"


@dataclass(frozen=True)
class Command:
    """One request to the engine; ``scene`` and ``value`` matter only to some actions."""

    action: Action
    scene: str = "sight"
    value: float = 0
    item_id: str = ""


@dataclass(frozen=True)
class GameConfig:
    """A request to set up one of the games at a chosen level."""

    game: str
    level: int = 0
    show_call: bool = True

    def __post_init__(self) -> None:
        """Reject unknown games."""
        if self.game not in ("rush", "echo"):
            raise ValueError("Unknown game")


@dataclass(frozen=True)
class RenderSnapshot:
    """An immutable description of one frame, safe to hand to another thread."""

    scene: str = "sight"
    running: bool = False
    held: frozenset[int] = frozenset()
    expected: frozenset[int] = frozenset()
    layout: StaffLayout | None = None
    status: str = "Ready when you are"
    prompt_index: int = 0
    completed: int = 0
    beat: float = 0
    wall_time: float = 0
    error: str = ""
    graph: tuple[float, ...] = ()
    velocity_graph: tuple[float, ...] = ()
    tempo_scale: float = 1.0
    allowed: frozenset[int] = frozenset()
    marks: Marks = ()
    playhead: float | None = None
    scrolling: bool = False
    title: str = ""
    set_title: str = ""
    instruction: str = ""
    prompt_text: str = ""
    chips: tuple[str, ...] = ()
    pulse: Pulse | None = None
    reveal: bool = False
    lit: frozenset[int] = frozenset()
    game: GameState | None = None
    beats_per_second: float = 0.0
    progress: float | None = None
    fingering: str = "starts"
    assisted: bool = False
    feedback: str = ""
    feedback_at: float = 0.0
    midi_in: str = ""
    midi_out: str = ""
    channel_hint: int | None = None


class PracticeEngine:
    """Own the piano state and the active drill, and turn both into render snapshots.

    Without a random source every queue runs in a fixed order, which keeps the engine
    fully deterministic; the application supplies one so that prompts are shuffled.
    """

    def __init__(self, rng: random.Random | None = None) -> None:
        """Start in the Sight-Reader on the landmark notes."""
        self.piano = PianoStateTracker()
        self.rng = rng
        self.bests: dict[str, float] = {}
        self.new_bests: dict[str, float] = {}
        self.output: list[OutputNote] = []
        self.results: list[PracticeResult] = []
        self.release_requested = False
        self.completed = 0
        self._settings = Settings()
        self._now = 0.0
        self._feedback = ("", 0.0)
        self._set_title = ""
        self.drill: Drill = self._default("sight")

    # --- the services drills use -------------------------------------------------------

    @property
    def settings(self) -> Settings:
        """Return the settings in force."""
        return self._settings

    @settings.setter
    def settings(self, value: Settings) -> None:
        """Adopt new settings, including inside a running song."""
        self._settings = value
        drill = getattr(self, "drill", None)
        if isinstance(drill, SongDrill):
            drill.session.settings = value

    def play(self, note: OutputNote) -> None:
        """Queue a note for the piano to sound."""
        self.output.append(note)

    def click(self, at: float, downbeat: bool) -> None:
        """Queue a metronome click, if the metronome is on."""
        note = self._settings.click(at, downbeat)
        if note is not None:
            self.output.append(note)

    def silence(self) -> None:
        """Ask for every computer-owned note to be released before new output is sent."""
        self.release_requested = True

    def record(self, result: PracticeResult) -> None:
        """Queue a result for the attempt log, stamped with the mode that produced it."""
        self.results.append(replace(result, mode=result.mode or self.drill.scene))
        self.completed += 1

    def flash(self, kind: str, now: float) -> None:
        """Remember the latest good/ok/bad moment for the views to animate."""
        self._feedback = (kind, now)

    def new_best(self, key: str, value: float) -> bool:
        """Keep ``value`` as a personal best if it beats the stored one."""
        if value <= self.bests.get(key, 0):
            return False
        self.bests[key] = value
        self.new_bests[key] = value
        return True

    # --- what callers read ---------------------------------------------------------------

    @property
    def scene(self) -> str:
        """Return the identifier of the active practice mode."""
        return self.drill.scene

    @property
    def running(self) -> bool:
        """Report whether the active drill is in progress."""
        return self.drill.running

    @property
    def engaged(self) -> bool:
        """Report whether something timed is under way."""
        return self.drill.engaged

    @property
    def status(self) -> str:
        """Return the active drill's one-line status."""
        return self.drill.status

    @property
    def evaluator(self) -> UntimedEvaluator | None:
        """Return the untimed evaluator currently listening, if any."""
        return self.drill.evaluator

    @property
    def prompt(self) -> Prompt:
        """Return the active drill's current prompt."""
        return self.drill.prompt

    @property
    def song(self) -> SongSession | None:
        """Return the song session when Song Studio is active."""
        return self.drill.session if isinstance(self.drill, SongDrill) else None

    @property
    def study_items(self) -> tuple[CurriculumItem, ...]:
        """Return the items of the active study set, if the drill has one."""
        items = getattr(self.drill, "items", ())
        return tuple(items)

    # --- choosing what to practise ---------------------------------------------------------

    def _default(self, scene: str) -> Drill:
        """Build the drill a mode opens with when nothing specific was requested."""
        if scene == "keys":
            return KeysDrill(self, items_for("keys", 1))
        if scene == "rush":
            return RushDrill(self, rush_pool(1), level=1)
        if scene == "rhythm":
            return RhythmDrill(self, items_for("rhythm", 1))
        if scene == "technique":
            return TechniqueDrill(self, (ITEMS["tech:rh:C_pentascale"],))
        if scene == "ear":
            return EarDrill(self, tuple(i for i in items_for("ear", 3) if i.kind == "ear_note"))
        if scene == "echo":
            return EchoDrill(self, 1)
        if scene == "song":
            return SongDrill(self, SongConfig(BUILTIN_SCORES[0].compile()))
        if scene == "sight":
            return SightDrill(self, items_for("sight", 1))
        raise ValueError(f"Unknown practice mode: {scene}")

    def _replace(self, drill: Drill, title: str = "") -> None:
        """Leave the current drill cleanly and install another."""
        self.drill.abandon(self._now)
        self.release_requested = True
        self.drill = drill
        self._set_title = title
        self._feedback = ("", 0.0)

    def configure_study(self, config: StudyConfig) -> None:
        """Practise a chosen set of curriculum items in their own mode."""
        mode = config.items[0].mode
        if mode not in STUDY_DRILLS:
            raise ValueError("Songs are configured with a SongConfig")
        self._replace(STUDY_DRILLS[mode](self, config.items, config.title), config.title)

    def configure_song(self, config: SongConfig) -> None:
        """Load a piece into Song Studio."""
        self._replace(SongDrill(self, config))

    def configure_game(self, config: GameConfig) -> None:
        """Set up Note Rush or Melody Echo at a chosen level."""
        if config.game == "rush":
            self._replace(RushDrill(self, rush_pool(config.level), level=config.level))
        else:
            self._replace(EchoDrill(self, config.level, config.show_call))

    # --- driving the drill -----------------------------------------------------------------

    def command(self, command: Command, now: float) -> None:
        """Carry out one request at monotonic time ``now``."""
        self._now = now
        action = command.action
        if action == Action.SWITCH_SCENE:
            self._replace(self._default(command.scene))
        elif action == Action.PLAY:
            self.drill.play(now)
        elif action == Action.REPLAY:
            self.drill.replay(now)
        elif action in (Action.PAUSE, Action.STOP, Action.PANIC):
            self.drill.pause(now)
        elif action == Action.NEXT:
            self.drill.skip(now)
        elif action == Action.HINT:
            self.drill.hint(now)
        elif action == Action.SEEK and isinstance(self.drill, SongDrill):
            self.drill.seek(command.value, now)

    def abandon(self) -> None:
        """Record an incomplete answer before the active drill is discarded."""
        self.drill.abandon(self._now)

    def process_midi(self, event: MidiEvent) -> None:
        """Apply a timestamped MIDI event to the current practice state."""
        actions = self.piano.process(event)
        tapped = any(isinstance(a, SoftPedalTap) for a in actions)
        if tapped and self.drill.scene in ("ear", "echo"):
            self.drill.replay(event.timestamp)
        self.drill.midi(event, actions, event.timestamp)

    def advance_to(self, now: float) -> None:
        """Advance scheduled state to the supplied monotonic time in seconds."""
        self._now = now
        self.drill.tick(now)

    def snapshot(self) -> RenderSnapshot:
        """Return an immutable description of the current render state."""
        view: DrillView = self.drill.view(self._now)
        kind, at = self._feedback
        return RenderSnapshot(
            scene=self.drill.scene,
            running=self.drill.running,
            held=frozenset(int(p) for p in self.piano.physically_held),
            expected=view.expected,
            layout=view.layout,
            status=self.drill.status,
            prompt_index=view.prompt_index,
            completed=self.completed,
            beat=view.beat,
            wall_time=self._now,
            graph=view.graph,
            velocity_graph=view.velocity_graph,
            tempo_scale=view.tempo_scale,
            allowed=view.allowed,
            marks=view.marks,
            playhead=view.playhead,
            scrolling=view.scrolling,
            title=view.title,
            set_title=self._set_title,
            instruction=view.instruction,
            prompt_text=view.prompt_text,
            chips=view.chips,
            pulse=view.pulse,
            reveal=view.reveal,
            lit=view.lit,
            game=view.game,
            beats_per_second=view.beats_per_second,
            progress=view.progress,
            fingering=view.fingering,
            assisted=view.assisted,
            feedback=kind,
            feedback_at=at,
        )
