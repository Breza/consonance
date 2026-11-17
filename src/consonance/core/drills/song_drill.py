"""Song Studio: a song session presented as a drill, with staff marks for built-in scores."""

import json

from consonance.core.builtin_scores import score_by_id
from consonance.core.curriculum import HAND_NAMES, song_item_id
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
from consonance.core.input_and_grading import MidiEvent, SoftPedalTap, UntimedEvaluator
from consonance.core.notation import Hand
from consonance.core.notation_layout import StaffLayout, layout_measures
from consonance.core.rhythm import mark_for
from consonance.core.song_session import SongConfig, SongSession


class SongDrill(Drill):
    """Practise a piece in Wait or Tempo mode."""

    scene = "song"

    def __init__(self, host: Host, config: SongConfig) -> None:
        """Create a stopped session for ``config`` and lay out its score if it has one."""
        super().__init__(host)
        self.config = config
        self.session = SongSession(config, host.settings, host.piano)
        self.item_id = config.item_id or song_item_id(
            config.timeline.song_id, config.hand_name, config.section
        )
        score = score_by_id(config.timeline.song_id)
        self.layout: StaffLayout | None = None
        self._heads: dict[tuple[int, float], int] = {}
        if score is not None:
            self.layout = layout_measures(
                tuple((m.right, m.left) for m in score.measures),
                score.key,
                score.time,
                numbers=True,
                final_bar=True,
            )
            self._heads = {(h.staff, round(h.beat, 6)): h.index for h in self.layout.heads}
        self.status = self.session.status

    @property
    def prompt(self) -> Prompt:
        """Return a prompt naming the piece; songs are not presented note by note."""
        return Prompt(self.item_id, (), title=self.config.timeline.title)

    @property
    def engaged(self) -> bool:
        """Report whether the song clock is moving."""
        return self.session.engaged

    @property
    def evaluator(self) -> UntimedEvaluator | None:
        """Return the Wait-mode evaluator listening for the next chord."""
        return self.session.evaluator

    def _collect(self) -> None:
        """Pass the session's output, results and feedback up to the host."""
        session = self.session
        if session.release_requested:
            self.host.silence()
            session.release_requested = False
        for note in session.output:
            self.host.play(note)
        session.output.clear()
        for result in session.results:
            details = {
                "hit_accuracy": result.accuracy,
                "tempo_scale": result.tempo_scale,
                "mode": self.config.mode,
                "steps": result.steps,
            }
            if not result.complete:
                details["incomplete"] = True
                details["blameless"] = True
            self.host.record(
                PracticeResult(
                    self.item_id,
                    result.expected,
                    result.played,
                    result.clean,
                    result.response_ms,
                    result.spread_ms,
                    result.velocities,
                    result.timing_error_ms,
                    json.dumps(details),
                )
            )
        session.results.clear()
        if session.feedback is not None:
            self.host.flash(*session.feedback)
            session.feedback = None
        self.running = session.active
        self.status = session.status

    def play(self, now: float) -> None:
        """Start a pass or continue a paused one."""
        self.session.play(now)
        self._collect()

    def pause(self, now: float) -> None:
        """Pause the pass so Play can resume it."""
        self.session.pause(now)
        self._collect()

    def replay(self, now: float) -> None:
        """Start the section again from its first measure."""
        self.session.ramp.streak = 0
        self.session.restart(now)
        self._collect()

    def seek(self, beat: float, now: float) -> None:
        """Restart from a chosen beat."""
        self.session.seek(beat, now)
        self._collect()

    def midi(self, event: MidiEvent, actions: Actions, now: float) -> None:
        """Hand input to the session; a soft-pedal tap restarts the section."""
        self.session.process_midi(event, any(isinstance(a, SoftPedalTap) for a in actions))
        self._collect()

    def tick(self, now: float) -> None:
        """Advance the song clock."""
        self.session.advance_to(now)
        self._collect()

    def abandon(self, now: float) -> None:
        """Stop for good, logging an unfinished pass without blame."""
        self.session.abandon(now)
        self._collect()

    def _mark(self, hand: Hand, beat: float, state: str, into: dict[tuple[int, int], str]) -> None:
        """Colour the notehead a song note is drawn as, keeping the worst state of a chord."""
        staff = 0 if hand == Hand.RIGHT else 1
        index = self._heads.get((staff, round(beat, 6)))
        if index is None:
            return
        rank = {"current": 0, "done": 1, "hit": 1, "near": 2, "miss": 3}
        key = (staff, index)
        if key not in into or rank[state] > rank[into[key]]:
            into[key] = state

    def _marks(self) -> Marks:
        """Show what has been played and what is wanted next on the staff."""
        if not self._heads:
            return ()
        session = self.session
        marks: dict[tuple[int, int], str] = {}
        if session.wait:
            if not session.active:
                return ()
            done = {step.beat for step in session.steps[: session.step_index]}
            focus = session.focus_beat
            for note in session.selected:
                beat = float(note.start_beat)
                if beat in done:
                    self._mark(note.hand, beat, "done", marks)
                elif focus is not None and abs(beat - focus) <= 0.125:
                    self._mark(note.hand, beat, "current", marks)
        else:
            for note, grade in session.graded():
                self._mark(note.hand, float(note.start_beat), mark_for(grade), marks)
        return tuple((staff, index, state) for (staff, index), state in marks.items())

    def view(self, now: float) -> DrillView:
        """Describe the song position, targets, pulse and progress."""
        session, config = self.session, self.config
        beat = session.transport.beat_at(now)
        scale = session.transport.tempo_scale
        bpm = config.timeline.tempo.bpm_at(beat) * scale
        chips = [f"{config.mode} mode", f"{scale:.0%} tempo • {bpm:.0f} BPM"]
        if session.wait and session.total_steps:
            chips.append(f"{session.clean_steps} of {session.total_steps} clean")
        if session.passes:
            chips.append(f"{session.passes} passes")
        if session.last_accuracy is not None:
            chips.append(f"last pass {session.last_accuracy:.0%}")
        if config.auto_ramp and session.ramp.streak:
            chips.append(f"clean passes {session.ramp.streak} of 3")
        beat_info = session.pulse(now)
        instruction = (
            "Play each highlighted chord when you are ready. The music follows you."
            if session.wait
            else "Play in time after the count-in. Every attack is graded against the beat."
        )
        return DrillView(
            layout=self.layout,
            expected=session.targets,
            allowed=session.allowed,
            marks=self._marks(),
            playhead=beat if self.layout is not None else None,
            scrolling=True,
            title=f"{config.timeline.title} • {HAND_NAMES[config.hand_name]}",
            instruction=instruction,
            chips=tuple(chips),
            pulse=Pulse(*beat_info) if beat_info else None,
            reveal=session.wait and session.active,
            tempo_scale=scale,
            beat=beat,
            beats_per_second=session.transport.beats_per_second(now),
            progress=session.progress(now),
        )
