"""Untimed drills that walk through a prompt one note or chord at a time."""

import json
from collections.abc import Sequence
from typing import Any

from consonance.core.curriculum import CurriculumItem
from consonance.core.drills.base import (
    Actions,
    Drill,
    DrillView,
    Host,
    Marks,
    PracticeResult,
    Prompt,
    Pulse,
)
from consonance.core.input_and_grading import MidiEvent, NoteOn, UntimedEvaluator, spread_label
from consonance.core.midi_output import OutputNote
from consonance.core.notation import PIANO_HIGH, PIANO_LOW, Clef, KeySignature, NotatedAtom
from consonance.core.notation_layout import (
    StaffLayout,
    group_measures,
    layout_card,
    layout_measures,
)
from consonance.core.prompt_queue import PromptQueue
from consonance.core.technique import measure_evenness

ANY_OCTAVE_KINDS = frozenset({"key_class", "chord_class"})


class SequenceDrill(Drill):
    """A queue of prompts, each answered atom by atom with an untimed evaluator."""

    auto_advance = True  # present the next prompt the instant this one is answered
    shuffled = True
    repeat_on_play = False  # after an answer, Play repeats the prompt instead of moving on
    preview_first = False  # show a newly selected prompt and wait for Play
    auto_hint = True
    assistable = True  # note names or key hints give this drill's answers away
    start_text = "Go ahead • play it on your piano"

    def __init__(self, host: Host, items: Sequence[CurriculumItem], title: str = "") -> None:
        """Create the drill over a non-empty set of items of one mode."""
        super().__init__(host)
        self.items = tuple(items)
        self.set_title = title
        self.queue = PromptQueue(len(self.items), host.rng if self.shuffled else None)
        self.answered = 0
        self.clean_count = 0
        self.streak = 0
        self.best_streak = 0
        self._cleared: set[int] = set()
        self._variation = -1
        self._finished = False
        self._missed = False
        self._evaluator: UntimedEvaluator | None = None
        self.phrase_index = 0
        self._played: list[int] = []
        self._velocities: list[int] = []
        self._clean = True
        self._wrong_count = 0
        self._misses = 0
        self._onsets: list[float] = []
        self._touch: list[int] = []
        self._fingers: list[int] = []
        self._revealed = False
        self._hinted = False
        self._started = 0.0
        self._spread: float | None = None
        self._prompt = self._build_prompt()
        self._layout = self._build_layout()
        self.status = f"{self._prompt.title} • press Play"

    @property
    def item(self) -> CurriculumItem:
        """Return the curriculum item currently being presented."""
        return self.items[self.queue.current]

    @property
    def prompt(self) -> Prompt:
        """Return the current prompt."""
        return self._prompt

    @property
    def evaluator(self) -> UntimedEvaluator | None:
        """Return the evaluator listening for the current note or chord."""
        return self._evaluator

    def _build_prompt(self) -> Prompt:
        """Turn the current item into a prompt, choosing a fresh variation if it has any."""
        item = self.item
        if item.variations > 1 and self.host.rng is not None:
            choice = self.host.rng.randrange(item.variations)
            self._variation = (
                choice if choice != self._variation else (choice + 1) % item.variations
            )
        else:
            self._variation += 1
        return Prompt(
            item.item_id,
            item.atoms(self._variation),
            item.clef,
            KeySignature(item.key_fifths),
            item.time,
            item.title,
            item.prompt,
            item.answer,
        )

    def _build_layout(self) -> StaffLayout | None:
        """Lay the current prompt out as an untimed reading card."""
        return layout_card(self._prompt.atoms, self._prompt.clef, self._prompt.key)

    def _arm(self, now: float) -> None:
        """Listen for the note or chord at the current position in the prompt."""
        atom = self._prompt.atoms[self.phrase_index]
        self._evaluator = UntimedEvaluator(
            frozenset(p.midi for p in atom.pitches),
            now,
            any_octave=self.item.kind in ANY_OCTAVE_KINDS,
        )
        self._misses = 0

    def _activate(self, now: float) -> None:
        """Begin (or begin again) answering the current prompt."""
        self.phrase_index = 0
        self._played, self._velocities = [], []
        self._clean, self._wrong_count = True, 0
        self._onsets, self._touch, self._fingers = [], [], []
        self._revealed = self._hinted = False
        self._spread = None
        self._started = now
        self._finished = False
        self.running = True
        self._arm(now)
        self.on_activate(now)

    def _advance(self) -> None:
        """Move the queue on and prepare the next prompt."""
        self.queue.advance(missed=self._missed)
        self._missed = False
        self._finished = False
        self._prompt = self._build_prompt()
        self._layout = self._build_layout()

    def play(self, now: float) -> None:
        """Start the current prompt, or continue to the next after an answer."""
        if self._finished and not self.repeat_on_play:
            self._advance()
        elif self.running:
            self.abandon(now)
        self.host.silence()
        self.status = self.start_text
        self._activate(now)

    def replay(self, now: float) -> None:
        """Start the same prompt again from its first note."""
        self.abandon(now)
        self.host.silence()
        self.status = self.start_text
        self._activate(now)

    def skip(self, now: float) -> None:
        """Move to the next prompt without answering this one."""
        was_active = self.running or self._finished
        self.abandon(now)
        self._advance()
        self.host.silence()
        if was_active and not self.preview_first:
            self.status = "Skipped • here is the next one"
            self._activate(now)
        else:
            self.running = False
            self.status = f"{self._prompt.title} • press Play"

    def hint(self, now: float) -> None:
        """Show the answer on the keyboard; the attempt no longer counts as clean."""
        if self.running and self._evaluator is not None:
            self._revealed = self._hinted = True
            self.status = "The answer is lit on the keyboard • this one will come back later"

    def midi(self, event: MidiEvent, actions: Actions, now: float) -> None:
        """Feed one input event to the evaluator and react to a right or wrong key."""
        evaluator = self._evaluator
        if not self.running or evaluator is None:
            return
        if evaluator.process(event, self.host.piano):
            self._atom_done(event.timestamp)
        elif isinstance(event, NoteOn) and not evaluator.accepts(event.pitch):
            self._misses += 1
            self.host.flash("bad", event.timestamp)
            self.status = "Not that one • let go and try again"
            limit = self.host.settings.auto_hint_misses
            if self.auto_hint and limit and self._misses >= limit:
                self._revealed = True
                self.status = "Not that one • the answer is now lit on the keyboard"

    def _atom_done(self, now: float) -> None:
        """Bank one answered note or chord, then move within or beyond the prompt."""
        evaluator = self._evaluator
        assert evaluator is not None
        atom = self._prompt.atoms[self.phrase_index]
        self._played.extend(int(p) for p in evaluator.played)
        self._velocities.extend(evaluator.velocities)
        self._clean &= evaluator.is_first_try_correct
        self._wrong_count += evaluator.wrong_pitch_count
        self._onsets.append(max(press.timestamp for press in evaluator.strikes.values()))
        self._touch.extend(evaluator.strikes[p.midi].velocity for p in atom.pitches)
        self._fingers.extend(atom.fingering or (1,) * len(atom.pitches))
        self._spread = evaluator.chord_spread_ms
        self.phrase_index += 1
        self.on_atom(now)
        if self.phrase_index < len(self._prompt.atoms):
            self._arm(now)
        else:
            self._complete(now)

    def _expected(self) -> tuple[int, ...]:
        """Return every pitch of the prompt, in order, for the attempt log."""
        return tuple(int(p.midi) for a in self._prompt.atoms for p in a.pitches)

    def _complete(self, now: float) -> None:
        """Log the finished prompt, update the running tally, and move on or stop."""
        clean = self._clean and not self._hinted
        response = (now - self._started) * 1000
        details: dict[str, Any] = {
            "wrong_pitch_count": self._wrong_count,
            "notation": [[str(p) for p in a.pitches] for a in self._prompt.atoms],
            "clef": self._prompt.clef.value,
            "key_fifths": self._prompt.key.fifths,
            "transitions_ms": [
                (b - a) * 1000 for a, b in zip(self._onsets, self._onsets[1:], strict=False)
            ],
        }
        details.update(self.extra_details())
        if self._hinted:
            details["hint"] = True
        if self.assistable and self.host.settings.assisted:
            details["assisted"] = True
        self.host.record(
            PracticeResult(
                self._prompt.item_id,
                self._expected(),
                tuple(self._played),
                clean,
                response,
                self._spread,
                tuple(self._velocities),
                details=json.dumps(details),
            )
        )
        self.answered += 1
        if clean:
            self.clean_count += 1
            self.streak += 1
            self.best_streak = max(self.best_streak, self.streak)
            self._cleared.add(self.queue.current)
        else:
            self.streak = 0
        self.status = self.summary(clean, response)
        if self._spread is not None:
            self.status += f" • chord landed {spread_label(self._spread).lower()}"
            self.status += f" ({self._spread:.0f} ms)"
        self.host.flash("good" if clean else "ok", now)
        self._evaluator = None
        self._missed = not clean
        self.on_complete(now, clean)
        if self.auto_advance and self.running:
            self._advance()
            self._activate(now)
        elif not self.auto_advance:
            self.running = False
            self._finished = True

    def abandon(self, now: float) -> None:
        """Log a started-but-unfinished prompt; with no wrong notes it carries no blame."""
        evaluator = self._evaluator
        if self.running and evaluator is not None and (evaluator.played or self._played):
            wrong = self._wrong_count + evaluator.wrong_pitch_count
            details: dict[str, Any] = {"incomplete": True, "wrong_pitch_count": wrong}
            if wrong == 0 or (self.assistable and self.host.settings.assisted):
                details["blameless"] = True
            self.host.record(
                PracticeResult(
                    self._prompt.item_id,
                    self._expected(),
                    tuple(self._played) + tuple(int(p) for p in evaluator.played),
                    False,
                    None,
                    evaluator.chord_spread_ms,
                    tuple(self._velocities + evaluator.velocities),
                    details=json.dumps(details),
                )
            )
        self._evaluator = None

    def on_activate(self, now: float) -> None:
        """Hook: called when a prompt starts."""

    def on_atom(self, now: float) -> None:
        """Hook: called after each answered note or chord."""

    def on_complete(self, now: float, clean: bool) -> None:
        """Hook: called after a prompt is logged, before the queue moves."""

    def extra_details(self) -> dict[str, Any]:
        """Hook: return drill-specific measurements to store with the attempt."""
        return {}

    def summary(self, clean: bool, response_ms: float) -> str:
        """Hook: describe a finished prompt for the status line."""
        spelled = " ".join("+".join(str(p) for p in a.pitches) for a in self._prompt.atoms)
        if clean:
            return f"Clean first try • {spelled} in {response_ms / 1000:.1f} s"
        return f"Found it • that was {spelled}"

    def prompt_text(self) -> str:
        """Hook: return the large text prompt, for drills that are not read from a staff."""
        return ""

    def show_layout(self) -> bool:
        """Hook: report whether the staff should be visible right now."""
        return True

    def _expected_keys(self) -> frozenset[int]:
        """Return every key that would count as correct right now."""
        evaluator = self._evaluator
        if evaluator is None:
            return frozenset()
        if evaluator.any_octave:
            return frozenset(p for p in range(PIANO_LOW, PIANO_HIGH + 1) if evaluator.accepts(p))
        return frozenset(int(p) for p in evaluator.must_strike)

    def _marks(self) -> Marks:
        """Colour the notes already answered and the one being asked for."""
        if not self.running or len(self._prompt.atoms) < 2:
            return ()
        done = tuple((-1, i, "done") for i in range(self.phrase_index))
        return (*done, (-1, self.phrase_index, "current"))

    def _chips(self) -> tuple[str, ...]:
        """Summarise this sitting: answers, accuracy, streak, and coverage of the set."""
        chips: list[str] = []
        if self.answered:
            chips.append(f"{self.answered} answered")
            chips.append(f"{round(100 * self.clean_count / self.answered)}% clean first time")
            chips.append(f"streak {self.streak}")
        if len(self.items) > 1:
            chips.append(f"{len(self._cleared)} of {len(self.items)} cleared")
        return tuple(chips)

    def view(self, now: float) -> DrillView:
        """Describe the current prompt, targets, and tallies."""
        settings = self.host.settings
        return DrillView(
            layout=self._layout if self.show_layout() else None,
            expected=self._expected_keys(),
            marks=self._marks(),
            prompt_index=self.phrase_index,
            title=self._prompt.title,
            instruction=self.instruction,
            prompt_text=self.prompt_text(),
            chips=self._chips(),
            reveal=self.running and (self._revealed or (self.assistable and settings.key_hints)),
            assisted=self.assistable and settings.assisted,
        )


class SightDrill(SequenceDrill):
    """Read notes, intervals, triads and short contours from the grand staff."""

    scene = "sight"
    instruction = "Play what you see. The next one appears as soon as you are right."


class KeysDrill(SequenceDrill):
    """Find keys and chords by name, with no staff involved."""

    scene = "keys"
    instruction = "Find it on your piano. Any octave counts unless the prompt names one."

    def _build_layout(self) -> StaffLayout | None:
        """Name-based prompts are not drawn on a staff."""
        return None

    def prompt_text(self) -> str:
        """Return the spoken-style prompt, such as ``Play any C``."""
        return self._prompt.text

    def summary(self, clean: bool, response_ms: float) -> str:
        """Confirm the name that was found, spelling out a chord's notes."""
        name = self._prompt.title.removeprefix("Find ")
        spelled = f" = {self._prompt.answer}" if self._prompt.answer else ""
        if clean:
            return f"Yes, first try • {name}{spelled} in {response_ms / 1000:.1f} s"
        return f"Found it • {name}{spelled}"


class TechniqueDrill(SequenceDrill):
    """Play a fixed pattern and measure how even its timing and touch are."""

    scene = "technique"
    instruction = "Play up and back as evenly as you can, in both time and touch."
    auto_advance = False
    shuffled = False
    repeat_on_play = True
    preview_first = True
    auto_hint = False
    assistable = False

    def __init__(self, host: Host, items: Sequence[CurriculumItem], title: str = "") -> None:
        """Create the drill with no measurement shown yet."""
        self.graph: tuple[float, ...] = ()
        self.velocity_graph: tuple[float, ...] = ()
        self._beat = 0.0
        self._count_end = 0.0
        self._pulse_until = 0.0
        self._label = ""
        self._timing_sd = 0.0
        self._touch_sd = 0.0
        self._lightest = 1
        super().__init__(host, items, title)

    def _build_layout(self) -> StaffLayout | None:
        """Write the whole pattern out in 4/4 so it can be read before playing."""
        atoms = self._prompt.atoms
        right: tuple[NotatedAtom, ...] = ()
        left: tuple[NotatedAtom, ...] = ()
        if self.item.hand == "both":
            right = tuple(
                NotatedAtom((a.pitches[0],), a.duration, (a.fingering[0],)) for a in atoms
            )
            left = tuple(NotatedAtom((a.pitches[1],), a.duration, (a.fingering[1],)) for a in atoms)
        elif self._prompt.clef == Clef.TREBLE:
            right = atoms
        else:
            left = atoms
        upper, lower = group_measures(right), group_measures(left)
        measures = tuple(
            (upper[i] if i < len(upper) else (), lower[i] if i < len(lower) else ())
            for i in range(max(len(upper), len(lower)))
        )
        return layout_measures(measures, self._prompt.key, beat_width=6.0)

    def on_activate(self, now: float) -> None:
        """Count in at a fixed tempo, or wait for the player to set the pace."""
        settings = self.host.settings
        if settings.technique_self_paced:
            self._beat = 0.0
            self.status = "Play at your own steady pace • your first two notes set the click"
            return
        self._beat = 60 / settings.tempo_bpm
        for i in range(4):
            self.host.click(now + i * self._beat, i == 0)
        self._count_end = now + 4 * self._beat
        notes = len(self._prompt.atoms)
        for i in range(notes):
            self.host.click(self._count_end + i * self._beat, i % 4 == 0)
        self._pulse_until = self._count_end + notes * self._beat
        self.status = f"One bar count-in at {settings.tempo_bpm} BPM, then play with the click"

    def on_atom(self, now: float) -> None:
        """In self-paced mode, continue the click at the pace of the first two notes."""
        if self.host.settings.technique_self_paced and len(self._onsets) == 2:
            self._beat = max(0.15, self._onsets[1] - self._onsets[0])
            remaining = len(self._prompt.atoms) - 2
            for i in range(remaining):
                self.host.click(now + (i + 1) * self._beat, False)
            self._count_end = self._onsets[0]
            self._pulse_until = now + (remaining + 1) * self._beat

    def extra_details(self) -> dict[str, Any]:
        """Measure evenness and keep it for the graph and the attempt log."""
        metrics = measure_evenness(tuple(self._onsets), tuple(self._touch))
        self.graph = metrics.intervals_ms
        self.velocity_graph = tuple(float(v) for v in self._touch)
        by_finger = {
            finger: [v for f, v in zip(self._fingers, self._touch, strict=True) if f == finger]
            for finger in sorted(set(self._fingers))
        }
        self._lightest = min(by_finger, key=lambda f: sum(by_finger[f]) / len(by_finger[f]))
        self._label = metrics.label
        self._timing_sd, self._touch_sd = metrics.ioi_sd_ms, metrics.velocity_sd
        return {
            "ioi_sd_ms": metrics.ioi_sd_ms,
            "velocity_sd": metrics.velocity_sd,
            "hit_accuracy": float(self._clean),
            "tempo_bpm": self.host.settings.tempo_bpm,
            "velocities_by_finger": by_finger,
        }

    def summary(self, clean: bool, response_ms: float) -> str:
        """Report the evenness measurements in plain language."""
        text = (
            f"{self._label} • timing spread {self._timing_sd:.0f} ms"
            f" • touch spread {self._touch_sd:.0f} • lightest touch: finger {self._lightest}"
        )
        if not clean:
            return "A wrong key slipped in • " + text
        if self._timing_sd <= 35 and len(self.items) > 1:
            text += " • fluent: Next moves on"
        return text

    def view(self, now: float) -> DrillView:
        """Add the evenness graph, full fingering, and the click's visual pulse."""
        base = super().view(now)
        pulse = None
        if self.running and self._beat and now < self._pulse_until:
            if now < self._count_end:
                pulse = Pulse(4, max(0.0, 4 - (self._count_end - now) / self._beat), True)
            else:
                pulse = Pulse(4, ((now - self._count_end) / self._beat) % 4)
        return DrillView(
            layout=base.layout,
            expected=base.expected,
            marks=base.marks,
            prompt_index=base.prompt_index,
            title=base.title,
            instruction=base.instruction,
            chips=base.chips,
            reveal=base.reveal,
            pulse=pulse,
            graph=self.graph,
            velocity_graph=self.velocity_graph,
            fingering="all",
        )


class EarDrill(SequenceDrill):
    """Hear a note, interval or chord on the piano and find it by ear."""

    scene = "ear"
    instruction = "Listen on the piano, then play what you heard. Probing is fine."
    auto_advance = False
    auto_hint = False
    assistable = False
    reference = 60  # middle C, sounded first so single notes are heard as scale degrees

    def __init__(self, host: Host, items: Sequence[CurriculumItem], title: str = "") -> None:
        """Create the drill with nothing sounding."""
        self._sounding: list[tuple[int, float, float]] = []
        self._audio_end = 0.0
        self._now = 0.0
        super().__init__(host, items, title)

    @property
    def engaged(self) -> bool:
        """Report whether the piano is still playing the prompt."""
        return self.running and self._now < self._audio_end

    def _sound(self, now: float) -> None:
        """Play the prompt on the piano: a reference C for single notes, then the target."""
        self.host.silence()
        channel = self.host.settings.piano_channel
        start = now
        self._sounding = []
        if self.item.kind == "ear_note":
            self.host.play(OutputNote(start, self.reference, 0.75, 70, channel))
            self._sounding.append((self.reference, start, start + 0.75))
            start += 1.0
        for i, atom in enumerate(self._prompt.atoms):
            for pitch in atom.pitches:
                self.host.play(OutputNote(start + i * 0.65, pitch.midi, 0.55, channel=channel))
        self._audio_end = start + len(self._prompt.atoms) * 0.65

    def on_activate(self, now: float) -> None:
        """Sound the prompt as soon as it starts."""
        self._sound(now)
        if self.item.kind == "ear_note":
            self.status = "You hear C first, then the mystery note • R or the soft pedal replays"
        else:
            self.status = "Listen, then play what you hear • R or the soft pedal replays"

    def replay(self, now: float) -> None:
        """Hear the prompt again; probes so far are kept and nothing is penalised."""
        if (self.running and self._evaluator is not None) or self._finished:
            self._sound(now)
        else:
            super().replay(now)

    def tick(self, now: float) -> None:
        """Remember the time so the view can show what is sounding."""
        self._now = now

    def show_layout(self) -> bool:
        """Reveal the notation only once the prompt has been answered."""
        return self._finished

    def prompt_text(self) -> str:
        """Invite listening, then name the answer."""
        if self._finished:
            return f"It was {self._prompt.answer}" if self._prompt.answer else "Found it"
        return "Listen…" if self.running else "Press Play to hear it"

    def summary(self, clean: bool, response_ms: float) -> str:
        """Name what was heard and how directly it was found."""
        answer = self._prompt.answer or self._prompt.title
        if clean:
            return f"Yes, first try • {answer}"
        return f"Found after {len(self._played)} keys • {answer}"

    def view(self, now: float) -> DrillView:
        """Light the reference key while it sounds; never show the target itself."""
        base = super().view(now)
        lit = frozenset(p for p, start, end in self._sounding if start <= now < end)
        return DrillView(
            layout=base.layout,
            expected=base.expected,
            marks=base.marks,
            prompt_index=base.prompt_index,
            title=base.title,
            instruction=base.instruction,
            prompt_text=base.prompt_text,
            chips=base.chips,
            reveal=base.reveal,
            lit=lit,
        )
