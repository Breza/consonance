"""Starter fingerings built from five-finger hand positions.

A beginner's hand rests over five neighbouring white-key letter names. This module chooses
a sequence of such positions for a part that needs as few hand shifts as possible, and puts
each unavoidable shift where it is least awkward: after a long note or a rest, and never by
reusing one finger for two different neighbouring notes. The result is always playable,
though a teacher may prefer something more elegant for a particular passage.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass, replace
from fractions import Fraction

from consonance.core.notation import Hand, NotatedAtom, NotatedPitch

SPAN = 4  # diatonic steps covered by five fingers
SHIFT = 1.0
AWKWARD = 1.5
BREATH = 0.25


@dataclass(frozen=True)
class _Event:
    """One sounding atom reduced to what position planning needs."""

    index: int
    low: int
    high: int
    after_pause: bool
    fixed: int | None


def chord_fingers(pitches: Sequence[NotatedPitch], hand: Hand) -> tuple[int, ...]:
    """Finger simultaneous notes, giving the outer notes to the thumb and little finger.

    Fingers are returned in the same order as the pitches were supplied.
    """
    if not pitches:
        return ()
    order = sorted(range(len(pitches)), key=lambda i: pitches[i].diatonic)
    low = pitches[order[0]].diatonic
    span = pitches[order[-1]].diatonic - low
    # Wide chords spread proportionally, leaning toward the thumb as a hand naturally does.
    lean = math.floor if hand == Hand.RIGHT else math.ceil
    ranks: list[int] = []
    for i in order:
        offset = pitches[i].diatonic - low
        rank = offset if span <= SPAN else lean(SPAN * offset / span)
        if ranks and rank <= ranks[-1]:
            rank = ranks[-1] + 1
        ranks.append(rank)
    overflow = max(0, ranks[-1] - SPAN)
    ranks = [max(0, rank - overflow) for rank in ranks]
    fingers = [0] * len(pitches)
    for rank, i in zip(ranks, order, strict=True):
        fingers[i] = rank + 1 if hand == Hand.RIGHT else 5 - rank
    return tuple(fingers)


def position_anchor(pitch: NotatedPitch, finger: int, hand: Hand) -> int:
    """Return the staff position under the hand's lowest finger for a fingered note.

    Two consecutive notes with the same anchor are played without moving the hand, so a
    change of anchor marks the place where a printed finger number is genuinely helpful.
    """
    return pitch.diatonic - (finger - 1 if hand == Hand.RIGHT else 5 - finger)


def _events(atoms: Sequence[NotatedAtom], hand: Hand) -> list[_Event]:
    """Summarise the sounding atoms, remembering where the hand has time to move."""
    events: list[_Event] = []
    pause = False
    for index, atom in enumerate(atoms):
        if not atom.pitches:
            pause = True
            continue
        lowest = min(atom.pitches, key=lambda p: p.diatonic)
        fixed = None
        if atom.fingering:
            finger = atom.fingering[atom.pitches.index(lowest)]
            fixed = position_anchor(lowest, finger, hand)
        high = max(p.diatonic for p in atom.pitches)
        events.append(_Event(index, lowest.diatonic, high, pause, fixed))
        pause = atom.duration >= Fraction(2)
    return events


def _candidates(event: _Event) -> range:
    """List the hand positions from which every note of an event can be reached."""
    if event.fixed is not None:
        return range(event.fixed, event.fixed + 1)
    if event.high - event.low > SPAN:
        return range(event.low, event.low + 1)
    return range(event.high - SPAN, event.low + 1)


def _shift_cost(before: _Event, old: int, after: _Event, new: int) -> float:
    """Price moving the hand between two consecutive events."""
    if old == new:
        return 0.0
    cost = SHIFT + 0.05 * abs(new - old)
    old_rank, new_rank = before.low - old, after.low - new
    rising, falling = after.low > before.low, after.low < before.low
    if after.after_pause:
        return cost - BREATH  # a long note or a rest gives the hand time to travel
    if (rising and new_rank <= old_rank) or (falling and new_rank >= old_rank):
        cost += AWKWARD
    elif not rising and not falling:
        cost += 0.5
    return cost


def _plan(events: Sequence[_Event]) -> list[int]:
    """Choose one hand position per event with the cheapest total shifting."""
    if not events:
        return []
    # A faint pull toward resting the lowest finger on the lowest note breaks ties.
    costs = [{base: 0.001 * (events[0].low - base) for base in _candidates(events[0])}]
    back: list[dict[int, int]] = [{}]
    for before, after in zip(events, events[1:], strict=False):
        row: dict[int, float] = {}
        pointer: dict[int, int] = {}
        for new in _candidates(after):
            old = min(costs[-1], key=lambda o: costs[-1][o] + _shift_cost(before, o, after, new))
            row[new] = (
                costs[-1][old] + _shift_cost(before, old, after, new) + 0.001 * (after.low - new)
            )
            pointer[new] = old
        costs.append(row)
        back.append(pointer)
    base = min(costs[-1], key=lambda b: costs[-1][b])
    plan = [base]
    for pointer in reversed(back[1:]):
        base = pointer[base]
        plan.append(base)
    return plan[::-1]


def finger_part(atoms: Sequence[NotatedAtom], hand: Hand) -> tuple[NotatedAtom, ...]:
    """Return a hand's atoms with a starter fingering on every sounding note.

    Atoms that already carry a fingering are kept exactly as written and pin the hand
    position at that point, so explicit fingerings (for scale crossings, say) always win.
    """
    events = _events(atoms, hand)
    result = list(atoms)
    for event, base in zip(events, _plan(events), strict=True):
        atom = atoms[event.index]
        if atom.fingering:
            continue
        if event.high - event.low > SPAN:
            fingers = chord_fingers(atom.pitches, hand)
        else:
            fingers = tuple(
                (p.diatonic - base + 1) if hand == Hand.RIGHT else 5 - (p.diatonic - base)
                for p in atom.pitches
            )
        result[event.index] = replace(atom, fingering=fingers)
    return tuple(result)
