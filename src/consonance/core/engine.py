"""Session state machine. Callers own time, devices, persistence, and threads."""

import json
from dataclasses import dataclass
from enum import StrEnum
from fractions import Fraction

from consonance.core.builtin_scores import BUILTIN_SCORES, COORDINATION_SCORE
from consonance.core.curriculum import ITEMS, CurriculumItem, StudyConfig
from consonance.core.input_and_grading import (
    HoldRelease,
    MidiEvent,
    NoteOn,
    PianoStateTracker,
    SoftPedalTap,
    UntimedEvaluator,
    spread_label,
)
from consonance.core.midi_output import OutputNote, Settings
from consonance.core.notation import Clef, KeySignature, NotatedAtom, TimeSignature, natural
from consonance.core.notation_layout import StaffLayout, layout_measures, layout_staff
from consonance.core.rhythm import DurationGrade, ExpectedStrike, TimedGrader
from consonance.core.song_session import SongConfig, SongSession
from consonance.core.technique import measure_evenness


class Action(StrEnum):
    PLAY = "Play"
    PAUSE = "Pause"
    REPLAY = "Replay"
    SEEK = "Seek"
    SWITCH_SCENE = "SwitchScene"
    PANIC = "Panic"
    STOP = "Stop"


@dataclass(frozen=True)
class Command:
    action: Action
    scene: str = "sight"
    value: float = 0
    item_id: str = ""


@dataclass(frozen=True)
class Prompt:
    item_id: str
    atoms: tuple[NotatedAtom, ...]
    clef: Clef = Clef.TREBLE
    key: KeySignature = KeySignature()
    time: TimeSignature = TimeSignature()


@dataclass(frozen=True)
class PracticeResult:
    item_id: str
    expected: tuple[int, ...]
    played: tuple[int, ...]
    first_try: bool
    response_ms: float | None
    spread_ms: float | None
    velocities: tuple[int, ...]
    timing_error_ms: float | None = None
    details: str = "{}"


@dataclass(frozen=True)
class RenderSnapshot:
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


def landmark_prompts() -> tuple[Prompt, ...]:
    return tuple(
        Prompt(f"note:{clef}:{name}", (NotatedAtom((natural(name),)),), clef)
        for clef, name in (
            (Clef.TREBLE, "G4"),
            (Clef.BASS, "F3"),
            (Clef.TREBLE, "C4"),
            (Clef.BASS, "C4"),
        )
    )


class PracticeEngine:
    def __init__(self) -> None:
        self.piano = PianoStateTracker()
        self.scene = "sight"
        self.running = False
        self.prompts = landmark_prompts()
        self.index = 0
        self.phrase_index = 0
        self.completed = 0
        self.evaluator: UntimedEvaluator | None = None
        self.results: list[PracticeResult] = []
        self.status = "Press Play, then play the notes on your piano"
        self.settings = Settings()
        self.output: list[OutputNote] = []
        self.release_requested = False
        self.grader: TimedGrader | None = None
        self._phrase_played: list[int] = []
        self._phrase_velocities: list[int] = []
        self._phrase_clean = True
        self._phrase_wrong_count = 0
        self._phrase_started = 0.0
        self._now = 0.0
        self._rhythm_start = 0.0
        self._rhythm_end = 0.0
        self._onsets: list[float] = []
        self._touch_velocities: list[int] = []
        self._fingers: list[int] = []
        self._rhythm_played: list[int] = []
        self._rhythm_velocities: list[int] = []
        self.graph: tuple[float, ...] = ()
        self.velocity_graph: tuple[float, ...] = ()
        self.song: SongSession | None = None
        self._song_layout: StaffLayout | None = None
        self.study_items: tuple[CurriculumItem, ...] = ()
        self._variation = 0
        self._retry: list[tuple[int, int]] = []
        self._selected_item_id = ""
        self._rhythm_atoms: tuple[NotatedAtom, ...] = ()
        self._rhythm_time = TimeSignature()

    def configure_study(self, config: StudyConfig) -> None:
        self.abandon()
        self.study_items = config.items
        self.scene = config.items[0].mode
        self.index = 0
        self._retry.clear()
        self._selected_item_id = config.items[0].item_id
        self.running = False
        self.release_requested = True
        self.status = f"{config.items[0].title} • press Play"

    def configure_song(self, config: SongConfig) -> None:
        self.study_items = ()
        self._selected_item_id = ""
        self.song = SongSession(config, self.settings, self.piano)
        score = next(
            (
                s
                for s in (*BUILTIN_SCORES, COORDINATION_SCORE)
                if s.song_id == config.timeline.song_id
            ),
            None,
        )
        self._song_layout = (
            layout_measures(tuple((m.right, m.left) for m in score.measures), score.key, score.time)
            if score
            else None
        )
        self.scene = "song"
        self.running = False
        self.release_requested = True

    def _collect_song(self) -> None:
        song = self.song
        if song is None:
            return
        self.output.extend(song.output)
        song.output.clear()
        self.release_requested |= song.release_requested
        song.release_requested = False
        self.running = song.active
        self.status = song.status
        for r in song.results:
            hand_name = (
                "both" if len(song.config.hands) == 2 else next(iter(song.config.hands)).value
            )
            full = song.config.start_measure == 1 and song.end >= song.config.timeline.end_beat
            section = (
                "all"
                if full
                else (f"{song.config.start_measure}-{song.config.end_measure or 'end'}")
            )
            self.results.append(
                PracticeResult(
                    song.config.item_id
                    or f"song:{song.config.timeline.song_id}:{section}:{hand_name}",
                    r.expected,
                    r.played,
                    r.clean,
                    r.response_ms,
                    r.spread_ms,
                    r.velocities,
                    r.timing_error_ms,
                    json.dumps(
                        {
                            "hit_accuracy": r.accuracy,
                            "tempo_scale": r.tempo_scale,
                            "mode": song.config.mode,
                        }
                    ),
                )
            )
            self.completed += 1
        song.results.clear()

    @property
    def prompt(self) -> Prompt:
        if self.study_items:
            item = self.study_items[self.index % len(self.study_items)]
            return Prompt(
                item.item_id,
                item.atoms(self._variation),
                item.clef,
                KeySignature(item.key_fifths),
                item.time,
            )
        return self.prompts[self.index % len(self.prompts)]

    def _activate(self, now: float) -> None:
        self._variation += 1
        self._phrase_started = now
        self._phrase_played = []
        self._phrase_velocities = []
        self._phrase_clean = True
        self._phrase_wrong_count = 0
        self._onsets = []
        self._touch_velocities = []
        self._fingers = []
        self.phrase_index = 0
        self._next_atom(now)
        if self.scene == "ear":
            self._ear_prompt(now)
        elif self.scene == "technique" and not self.settings.technique_self_paced:
            seconds = 60 / self.settings.tempo_bpm
            for i in range(len(self.prompt.atoms)):
                click = self.settings.click(now + i * seconds, i == 0)
                if click:
                    self.output.append(click)

    def _next_atom(self, now: float) -> None:
        atom = self.prompt.atoms[self.phrase_index]
        self.evaluator = UntimedEvaluator(frozenset(p.midi for p in atom.pitches), now)

    def _ear_prompt(self, now: float) -> None:
        self.release_requested = True
        for i, atom in enumerate(self.prompt.atoms):
            for pitch in atom.pitches:
                self.output.append(
                    OutputNote(
                        now + i * 0.65, pitch.midi, 0.55, channel=self.settings.piano_channel
                    )
                )
        self.status = "Listen, then play what you hear • R / soft pedal replays freely"

    def _start_rhythm(self, now: float) -> None:
        seconds = 60 / self.settings.tempo_bpm
        self._rhythm_time = self.prompt.time
        bar = self._rhythm_time.numerator
        self._rhythm_atoms = (
            self.prompt.atoms * 2
            if self.study_items
            else tuple(
                NotatedAtom((natural("C4"),), Fraction(d)) for d in (1, 1, 2, 0.5, 0.5, 1, 2)
            )
        )
        self._rhythm_start = now + bar * seconds
        beat = 0.0
        strikes: list[ExpectedStrike] = []
        for atom in self._rhythm_atoms:
            duration = float(atom.duration)
            if atom.pitches:
                strikes.append(
                    ExpectedStrike(60, self._rhythm_start + beat * seconds, duration * seconds)
                )
            beat += duration
        self.grader = TimedGrader(tuple(strikes), self.settings.midi_judge_offset_ms)
        self._rhythm_end = (
            max(
                n.at
                + max(
                    n.duration + max(0.12, 0.30 * n.duration),
                    0.135 + self.settings.midi_judge_offset_ms / 1000,
                )
                for n in strikes
            )
            + 0.001
        )
        self._rhythm_played = []
        self._rhythm_velocities = []
        self.evaluator = None
        for i in range(bar * 3):
            click = self.settings.click(now + i * seconds, i % bar == 0)
            if click is not None:
                self.output.append(click)
        self.status = "One bar count-in, then play C4 with the notation"

    def command(self, command: Command, now: float) -> None:
        self._now = now
        if self.scene == "song" and self.song and command.action != Action.SWITCH_SCENE:
            if command.action == Action.PLAY:
                self.song.play(now)
            elif command.action == Action.REPLAY:
                self.song.ramp.streak = 0
                self.song.restart(now)
            elif command.action in (Action.PAUSE, Action.STOP):
                self.song.pause(now)
            elif command.action == Action.SEEK:
                self.song.seek(command.value, now)
            self._collect_song()
            return
        if command.action == Action.SWITCH_SCENE:
            self.abandon()
            self.study_items = ()
            self._selected_item_id = ""
            self._retry.clear()
            self.scene = command.scene
            self.running = False
            self.index = 0
            self.grader = None
            if self.scene == "song":
                self.configure_song(SongConfig(BUILTIN_SCORES[0].compile()))
            if self.scene == "ear":
                self.prompts = tuple(
                    Prompt(f"ear:note:{i + 1}", (NotatedAtom((natural(n),)),))
                    for i, n in enumerate(("C4", "D4", "E4", "F4", "G4"))
                )
            elif self.scene == "technique":
                self.study_items = (ITEMS["tech:rh:C_pentascale"],)
                self.prompts = (
                    Prompt(
                        "tech:rh:C_pentascale",
                        tuple(
                            NotatedAtom((natural(n),))
                            for n in ("C4", "D4", "E4", "F4", "G4", "F4", "E4", "D4", "C4")
                        ),
                    ),
                )
            else:
                self.prompts = landmark_prompts()
            self.release_requested = True
            self.status = "Press Play to begin"
        elif command.action in (Action.PLAY, Action.REPLAY):
            self.release_requested = True
            if self.scene == "ear" and command.action == Action.REPLAY and self.evaluator:
                self._ear_prompt(now)
                return
            if self.running:
                self.abandon()
            self.running = True
            if self.scene == "rhythm":
                self._start_rhythm(now)
            else:
                self._activate(now)
        elif command.action in (Action.PAUSE, Action.STOP):
            self.abandon()
            self.running = False
            self.release_requested = True
            self.status = "Paused • every completed attempt is saved"

    def abandon(self) -> None:
        if self.scene == "song" and self.song and self.song.active:
            self.song.pause(self._now)
            self._collect_song()
        if self.scene == "rhythm" and self.running and self.grader is not None:
            self.results.append(
                PracticeResult(
                    self.prompt.item_id if self.study_items else "rhythm:4/4:pulse",
                    tuple(n.pitch for n in self.grader.expected),
                    tuple(self._rhythm_played),
                    False,
                    None,
                    None,
                    tuple(self._rhythm_velocities),
                    self.grader.mean_error_ms,
                    json.dumps({"incomplete": True, "hit_accuracy": self.grader.accuracy}),
                )
            )
            self.grader = None
            self.completed += 1
        if self.evaluator is not None and (self.evaluator.played or self._phrase_played):
            e = self.evaluator
            self.results.append(
                PracticeResult(
                    self.prompt.item_id,
                    tuple(p.midi for a in self.prompt.atoms for p in a.pitches),
                    tuple(self._phrase_played) + tuple(e.played),
                    False,
                    None,
                    e.chord_spread_ms,
                    tuple(self._phrase_velocities + e.velocities),
                    details='{"incomplete":true}',
                )
            )
            self.completed += 1
        self.evaluator = None
        self._phrase_played = []
        self._phrase_velocities = []

    def process_midi(self, event: MidiEvent) -> None:
        actions = self.piano.process(event)
        if self.scene == "song" and self.song:
            self.song.process_midi(event, any(isinstance(a, SoftPedalTap) for a in actions))
            self._collect_song()
            return
        if self.scene == "ear" and any(isinstance(a, SoftPedalTap) for a in actions):
            self.command(Command(Action.REPLAY), event.timestamp)
        if self.scene == "rhythm" and self.running and self.grader is not None:
            if isinstance(event, NoteOn) and event.velocity:
                hit = self.grader.strike(event.pitch, event.timestamp)
                self._rhythm_played.append(event.pitch)
                self._rhythm_velocities.append(event.velocity)
                self.status = f"{hit.grade} • {hit.error_ms or 0:+.0f}ms"
            for action in actions:
                if isinstance(action, HoldRelease):
                    self.grader.release(action.pitch, action.started, action.ended)
            return
        if not self.running or self.evaluator is None:
            return
        if self.evaluator.process(event, self.piano):
            e = self.evaluator
            self._phrase_played.extend(e.played)
            self._phrase_velocities.extend(e.velocities)
            self._phrase_clean &= e.is_first_try_correct
            self._phrase_wrong_count += e.wrong_pitch_count
            self._onsets.append(max(press.timestamp for press in e.strikes.values()))
            atom = self.prompt.atoms[self.phrase_index]
            self._touch_velocities.extend(e.strikes[p.midi].velocity for p in atom.pitches)
            self._fingers.extend(atom.fingering or (1,) * len(atom.pitches))
            if (
                self.scene == "technique"
                and self.settings.technique_self_paced
                and len(self._onsets) == 2
            ):
                seconds = max(0.15, self._onsets[1] - self._onsets[0])
                for i in range(len(self.prompt.atoms) - 2):
                    click = self.settings.click(event.timestamp + (i + 1) * seconds, False)
                    if click:
                        self.output.append(click)
            self.phrase_index += 1
            if self.phrase_index < len(self.prompt.atoms):
                self._next_atom(event.timestamp)
                return
            spread = e.chord_spread_ms
            details = json.dumps(
                {
                    "wrong_pitch_count": self._phrase_wrong_count,
                    "notation": [[str(p) for p in a.pitches] for a in self.prompt.atoms],
                    "clef": self.prompt.clef.value,
                    "key_fifths": self.prompt.key.fifths,
                    "transitions_ms": [
                        (b - a) * 1000 for a, b in zip(self._onsets, self._onsets[1:], strict=False)
                    ],
                }
            )
            if self.scene == "technique":
                metrics = measure_evenness(tuple(self._onsets), tuple(self._touch_velocities))
                self.graph = metrics.intervals_ms
                self.velocity_graph = tuple(float(v) for v in self._touch_velocities)
                by_finger = {
                    f: [
                        v
                        for finger, v in zip(self._fingers, self._touch_velocities, strict=True)
                        if finger == f
                    ]
                    for f in set(self._fingers)
                }
                weakest = min(by_finger, key=lambda f: sum(by_finger[f]) / len(by_finger[f]))
                details = json.dumps(
                    {
                        "ioi_sd_ms": metrics.ioi_sd_ms,
                        "velocity_sd": metrics.velocity_sd,
                        "hit_accuracy": float(self._phrase_clean),
                        "tempo_bpm": self.settings.tempo_bpm,
                        "velocities_by_finger": by_finger,
                    }
                )
                self.status = (
                    f"{metrics.label} • IOI SD {metrics.ioi_sd_ms:.1f}ms"
                    f" • Velocity SD {metrics.velocity_sd:.1f}"
                    f" • Lightest touch: finger {weakest}"
                )
            elif self.scene == "ear":
                self.status = f"Found in {len(self._phrase_played)} strikes • " + (
                    "clean first try" if self._phrase_clean else "probes recorded"
                )
            else:
                self.status = "Clean first try" if self._phrase_clean else "Found it • keep going"
            self.results.append(
                PracticeResult(
                    self.prompt.item_id,
                    tuple(p.midi for a in self.prompt.atoms for p in a.pitches),
                    tuple(self._phrase_played),
                    self._phrase_clean,
                    (event.timestamp - self._phrase_started) * 1000,
                    spread,
                    tuple(self._phrase_velocities),
                    details=details,
                )
            )
            if spread is not None:
                self.status += f" • {spread:.0f}ms {spread_label(spread)}"
            self.completed += 1
            if not self._phrase_clean:
                self._retry.append(
                    (
                        self.completed + 3,
                        self.index % max(1, len(self.study_items) or len(self.prompts)),
                    )
                )
            self.index += 1
            if self._retry and self._retry[0][0] <= self.completed:
                _, self.index = self._retry.pop(0)
            if self.scene in ("technique", "ear"):
                self.evaluator = None
                self.running = False
            else:
                self._activate(event.timestamp)
        elif isinstance(event, NoteOn) and event.pitch not in self.evaluator.must_strike:
            self.status = "Try again • release the extra key"

    def advance_to(self, now: float) -> None:
        self._now = now
        if self.scene == "song" and self.song:
            self.song.advance_to(now)
            self._collect_song()
            return
        if self.running and self.scene == "rhythm" and self.grader:
            self.grader.advance_to(now)
            if now >= self._rhythm_end:
                g = self.grader
                for i in g.hits:
                    if i not in g.holds:
                        g.holds[i] = DurationGrade.LONG
                self.status = (
                    f"{g.accuracy:.0%} hits • Mean {g.mean_error_ms:+.0f}ms "
                    f"{'rushing' if g.mean_error_ms < 0 else 'dragging'}"
                    f" • Jitter {g.jitter_ms:.1f}ms • "
                    f"{sum(v == DurationGrade.OK for v in g.holds.values())} holds OK"
                )
                self.results.append(
                    PracticeResult(
                        self.prompt.item_id if self.study_items else "rhythm:4/4:pulse",
                        (60,) * len(g.expected),
                        tuple(self._rhythm_played),
                        g.accuracy >= 0.9 and all(h == DurationGrade.OK for h in g.holds.values()),
                        None,
                        None,
                        tuple(self._rhythm_velocities),
                        g.mean_error_ms,
                        json.dumps(
                            {
                                "hit_accuracy": g.accuracy,
                                "jitter_ms": g.jitter_ms,
                                "tempo_bpm": self.settings.tempo_bpm,
                                "stray_count": len(g.strays),
                                "attacks": [
                                    {
                                        "pitch": n.pitch,
                                        "duration_s": n.duration,
                                        "grade": g.hits[i].grade.value,
                                        "error_ms": g.hits[i].error_ms,
                                        "hold_ms": g.hold_ms.get(i),
                                        "hold_grade": g.holds[i].value,
                                    }
                                    for i, n in enumerate(g.expected)
                                ],
                            }
                        ),
                    )
                )
                self.completed += 1
                self.running = False
                self.release_requested = True

    def snapshot(self) -> RenderSnapshot:
        rest = (NotatedAtom((), Fraction(4)),)
        prompt = self.prompt
        layout: StaffLayout | None = layout_staff(
            prompt.atoms if prompt.clef == Clef.TREBLE else rest,
            prompt.atoms if prompt.clef == Clef.BASS else rest,
            prompt.key,
            prompt.time,
        )
        if self.scene == "rhythm":
            atoms = self._rhythm_atoms or tuple(
                NotatedAtom((natural("C4"),), Fraction(d)) for d in (1, 1, 2, 0.5, 0.5, 1, 2)
            )
            measures: list[tuple[tuple[NotatedAtom, ...], tuple[NotatedAtom, ...]]] = []
            group: list[NotatedAtom] = []
            total = Fraction()
            for atom in atoms:
                group.append(atom)
                total += atom.duration
                if total == self._rhythm_time.beats:
                    measures.append((tuple(group), (NotatedAtom((), self._rhythm_time.beats),)))
                    group, total = [], Fraction()
            layout = layout_measures(tuple(measures), time=self._rhythm_time)
        if self.scene == "ear":
            layout = None
        if self.scene == "technique":
            first = (self.phrase_index // 4) * 4
            atoms = prompt.atoms[first : first + 4]
            item = (
                self.study_items[self.index % len(self.study_items)] if self.study_items else None
            )
            if item and item.hand == "both":
                rh = tuple(NotatedAtom((a.pitches[0],), a.duration) for a in atoms)
                lh = tuple(NotatedAtom((a.pitches[1],), a.duration) for a in atoms)
                layout = layout_staff(rh, lh, prompt.key)
            else:
                layout = layout_staff(
                    atoms if prompt.clef == Clef.TREBLE else rest,
                    atoms if prompt.clef == Clef.BASS else rest,
                    prompt.key,
                )
        beat = 0.0
        if self.scene == "song" and self.song:
            song = self.song
            beat = song.transport.beat_at(self._now)
            score = next(
                (
                    s
                    for s in (*BUILTIN_SCORES, COORDINATION_SCORE)
                    if s.song_id == song.config.timeline.song_id
                ),
                None,
            )
            if score:
                layout = self._song_layout
            else:
                layout = None
        return RenderSnapshot(
            self.scene,
            self.running,
            frozenset(self.piano.physically_held),
            frozenset(self.evaluator.must_strike) if self.evaluator else frozenset(),
            layout,
            self.status,
            self.phrase_index,
            self.completed,
            beat=beat,
            wall_time=self._now,
            graph=self.graph,
            velocity_graph=self.velocity_graph,
            tempo_scale=self.song.transport.tempo_scale
            if self.scene == "song" and self.song
            else 1,
        )
