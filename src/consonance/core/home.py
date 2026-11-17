"""Small, explainable recommendations for the practice desk; independent of Qt."""

import json
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from statistics import median

from consonance.core.curriculum import ITEMS, countable
from consonance.core.db import Attempt
from consonance.core.notation import Hand
from consonance.core.plan import Plan, PlanStep
from consonance.core.song import SongTimeline
from consonance.core.song_session import SongConfig


def available_steps(plan: Plan, piano: bool, sound: bool) -> tuple[PlanStep, ...]:
    """Prefer quiet reading when unplugged, leaving every mode open in Free Practice."""
    modes = {"keys", "sight"} if not piano else {"keys", "sight", "technique", "song"}
    return tuple(s for s in plan.steps if (sound and piano) or s.mode in modes)


@dataclass(frozen=True)
class Insight:
    """One observation backed by comparable, unassisted reading attempts."""

    title: str
    detail: str


def reading_insight(attempts: list[Attempt]) -> Insight | None:
    """Compare five recent responses with five earlier responses on the same reading item.

    Keep accuracy steady or better and require at least 10% faster median responses.
    These are response observations, not claims about physical piano technique.
    """
    groups: dict[str, list[Attempt]] = defaultdict(list)
    for attempt in attempts:
        if (
            attempt.mode in ("keys", "sight")
            and attempt.item_id in ITEMS
            and attempt.response_ms is not None
            and countable(attempt)
            and not json.loads(attempt.prompt_json).get("incomplete")
        ):
            groups[attempt.item_id].append(attempt)
    for item_id in reversed(groups):
        recent = groups[item_id][-10:]
        if len(recent) < 10:
            continue
        before, after = recent[:5], recent[5:]
        old = median(a.response_ms for a in before if a.response_ms is not None)
        new = median(a.response_ms for a in after if a.response_ms is not None)
        clean = sum(a.is_first_try_correct for a in after)
        if (
            old > 0
            and 0 < new <= old * 0.9
            and clean >= max(4, sum(a.is_first_try_correct for a in before))
        ):
            return Insight(
                "A little more familiar",
                f"{ITEMS[item_id].title}: median response "
                f"{old / 1000:.1f}s → {new / 1000:.1f}s. Your latest five answers were "
                f"{clean}/5 clean on the first try. Compared with the preceding five "
                "unassisted answers to this same exercise.",
            )
    return None


def song_bookmark(config: SongConfig) -> dict[str, object]:
    """Remember the selected section and playing choices, without serializing the score."""
    return {
        "song_id": config.timeline.song_id,
        "title": config.timeline.title,
        "mode": config.mode,
        "hand": config.hand_name,
        "tempo_scale": config.tempo_scale,
        "start_measure": config.start_measure,
        "end_measure": config.end_measure,
        "loop": config.loop,
        "auto_ramp": config.auto_ramp,
    }


def restore_song(data: object, timelines: Sequence[SongTimeline]) -> SongConfig | None:
    """Validate a saved section against the available built-in and imported timelines."""
    if not isinstance(data, dict):
        return None
    timeline = next((t for t in timelines if t.song_id == data.get("song_id")), None)
    if timeline is None:
        return None
    try:
        hand = data["hand"]
        hands = frozenset(Hand) if hand == "both" else frozenset({Hand(hand)})
        return SongConfig(
            timeline,
            str(data["mode"]),
            hands,
            float(data["tempo_scale"]),
            int(data["start_measure"]),
            int(data["end_measure"]),
            bool(data.get("loop", False)),
            bool(data.get("auto_ramp", False)),
        )
    except (ValueError, TypeError, KeyError):
        return None
