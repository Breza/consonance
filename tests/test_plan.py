from datetime import UTC, datetime, timedelta

from consonance.core.curriculum import ITEMS, UNITS, ItemSchedule
from consonance.core.plan import MAX_STEPS, NEW_PER_DAY, build_plan

NOW = datetime(2026, 3, 1, 18, tzinfo=UTC)
PAST = (NOW - timedelta(hours=1)).isoformat()
LATER = (NOW + timedelta(days=2)).isoformat()


def state(item_id: str, due: str = LATER, mastered: bool = False) -> ItemSchedule:
    """Build a review state for one item."""
    return ItemSchedule(item_id, 2, due, 1.0, 900, mastered)


def test_a_new_learner_meets_a_little_of_each_kind_of_work() -> None:
    """Verify a new learner meets a little of each kind of work."""
    plan = build_plan({}, NOW)
    assert (plan.unit, plan.due_count, plan.new_left) == (1, 0, NEW_PER_DAY)
    assert [step.kind for step in plan.steps] == ["new", "new", "new"]
    assert [step.mode for step in plan.steps] == ["keys", "sight", "rhythm"]
    introduced = [item_id for step in plan.steps for item_id in step.item_ids]
    assert len(introduced) <= NEW_PER_DAY and len(set(introduced)) == len(introduced)
    assert all(ITEMS[i].unit == 1 for i in introduced)
    for step in plan.steps:
        assert len({ITEMS[i].mode for i in step.item_ids}) == 1 and step.title and step.detail


def test_due_reviews_come_first_grouped_by_mode_oldest_first() -> None:
    """Verify due reviews come first grouped by mode oldest first."""
    older = (NOW - timedelta(days=3)).isoformat()
    states = {
        "note:treble:G4": state("note:treble:G4", PAST),
        "note:bass:F3": state("note:bass:F3", older),
        "key:C": state("key:C", PAST),
        "rhythm:4/4:quarters": state("rhythm:4/4:quarters", PAST),
        "song:hot_cross_buns:all:rh": state("song:hot_cross_buns:all:rh", PAST),
        "key:D": state("key:D"),
        "not:in:curriculum": state("not:in:curriculum", PAST),
    }
    plan = build_plan(states, NOW, first_seen_today={"key:D"}, practiced_today={"key:D"})
    assert plan.due_count == 5 and plan.new_left == NEW_PER_DAY - 1
    reviews = [step for step in plan.steps if step.kind == "review"]
    assert [step.mode for step in reviews] == ["keys", "sight", "rhythm", "song"]
    assert reviews[1].item_ids == ("note:bass:F3", "note:treble:G4")
    assert reviews[3].item_ids == ("song:hot_cross_buns:all:rh",)
    fresh = [item_id for step in plan.steps if step.kind == "new" for item_id in step.item_ids]
    assert fresh and not set(fresh) & set(states) and len(plan.steps) <= MAX_STEPS


def test_new_material_is_capped_per_day_then_practice_is_offered() -> None:
    """Verify new material is capped per day then practice is offered."""
    seen = {item.item_id: state(item.item_id) for item in UNITS[0].items}
    met_today = set(list(seen)[:NEW_PER_DAY])
    plan = build_plan(seen, NOW, first_seen_today=met_today)
    assert plan.new_left == 0 and plan.steps
    assert all(step.kind == "practice" for step in plan.steps)
    partly = build_plan({}, NOW, first_seen_today=set(list(seen)[: NEW_PER_DAY - 2]))
    assert sum(len(step.item_ids) for step in partly.steps if step.kind == "new") == 2


def test_practising_with_aids_does_not_reoffer_the_same_new_items_today() -> None:
    """Verify practising with aids does not reoffer the same new items today."""
    first = build_plan({}, NOW).steps[0].item_ids
    again = build_plan({}, NOW, practiced_today=set(first))
    assert not set(first) & {i for step in again.steps for i in step.item_ids}


def test_the_plan_moves_to_the_next_unit_once_one_is_mastered() -> None:
    """Verify the plan moves to the next unit once one is mastered."""
    done = {item.item_id: state(item.item_id, mastered=True) for item in UNITS[0].items}
    plan = build_plan(done, NOW)
    assert plan.unit == 2
    assert {ITEMS[i].unit for step in plan.steps for i in step.item_ids} == {2}
    assert "song" in {step.mode for step in plan.steps}
