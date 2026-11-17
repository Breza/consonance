"""Today's practice plan: due reviews first, then a small helping of new material."""

from dataclasses import dataclass
from datetime import datetime

from consonance.core.curriculum import (
    ITEMS,
    MODE_TITLES,
    UNITS,
    CurriculumItem,
    ItemSchedule,
    recommended_unit,
)

MODE_ORDER = ("keys", "sight", "rhythm", "technique", "ear", "song")
NEW_PER_DAY = 8
REVIEW_BATCH = 12
MAX_STEPS = 6
# How many unseen items of each mode one step introduces.
NEW_PER_STEP = {"keys": 3, "sight": 3, "ear": 3, "rhythm": 1, "technique": 1, "song": 1}


@dataclass(frozen=True)
class PlanStep:
    """One suggested activity: a set of same-mode items and why it is suggested."""

    kind: str
    mode: str
    title: str
    detail: str
    item_ids: tuple[str, ...]


@dataclass(frozen=True)
class Plan:
    """The suggested steps for today and the numbers behind them."""

    steps: tuple[PlanStep, ...]
    due_count: int
    new_left: int
    unit: int


def _names(items: list[CurriculumItem], limit: int = 3) -> str:
    """List a few item titles, summarising the rest."""
    titles = [item.title for item in items[:limit]]
    extra = len(items) - len(titles)
    return ", ".join(titles) + (f" and {extra} more" if extra > 0 else "")


def build_plan(
    states: dict[str, ItemSchedule],
    now: datetime,
    first_seen_today: set[str] | frozenset[str] = frozenset(),
    practiced_today: set[str] | frozenset[str] = frozenset(),
) -> Plan:
    """Suggest what to practise now.

    Reviews that have come due are offered first, oldest first, one step per practice
    mode. New material then comes from the first unit that is not yet 80% mastered, with at
    most :data:`NEW_PER_DAY` first meetings in a day so that new things have room to settle.
    When nothing is due and the day's new material has been met, unfinished items of that
    unit are offered for extra practice.
    """
    unit = UNITS[recommended_unit(states) - 1]
    steps: list[PlanStep] = []
    due = sorted(
        (
            state
            for item_id, state in states.items()
            if item_id in ITEMS and datetime.fromisoformat(state.due_at_utc) <= now
        ),
        key=lambda state: state.due_at_utc,
    )
    for mode in MODE_ORDER:
        items = [ITEMS[s.item_id] for s in due if ITEMS[s.item_id].mode == mode]
        if not items:
            continue
        if mode == "song":
            for item in items[:2]:
                steps.append(
                    PlanStep("review", mode, f"Play again: {item.title}", "Due", (item.item_id,))
                )
            continue
        batch = items[:REVIEW_BATCH]
        plural = "review" if len(batch) == 1 else "reviews"
        steps.append(
            PlanStep(
                "review",
                mode,
                f"{len(batch)} {plural} in {MODE_TITLES[mode]}",
                _names(batch),
                tuple(i.item_id for i in batch),
            )
        )
    new_left = max(0, NEW_PER_DAY - len(set(first_seen_today) & ITEMS.keys()))
    budget = new_left
    for mode in MODE_ORDER:
        if budget <= 0:
            break
        unseen = [
            item
            for item in unit.items
            if item.mode == mode
            and item.item_id not in states
            and item.item_id not in practiced_today
        ]
        fresh = unseen[: min(budget, NEW_PER_STEP[mode])]
        if not fresh:
            continue
        budget -= len(fresh)
        steps.append(
            PlanStep(
                "new",
                mode,
                f"New in {MODE_TITLES[mode]}: {_names(fresh, 2)}",
                f"Unit {unit.number} • {unit.title}",
                tuple(i.item_id for i in fresh),
            )
        )
    if not steps:
        for mode in MODE_ORDER:
            unfinished = [
                item
                for item in unit.items
                if item.mode == mode
                and not (item.item_id in states and states[item.item_id].mastered)
            ]
            if unfinished and mode != "song":
                steps.append(
                    PlanStep(
                        "practice",
                        mode,
                        f"Keep building {MODE_TITLES[mode]}",
                        _names(unfinished),
                        tuple(i.item_id for i in unfinished[:REVIEW_BATCH]),
                    )
                )
            elif unfinished:
                item = unfinished[0]
                steps.append(
                    PlanStep("practice", mode, f"Work on {item.title}", "Song", (item.item_id,))
                )
    return Plan(tuple(steps[:MAX_STEPS]), len(due), new_left, unit.number)
