import random

import pytest

from consonance.core.prompt_queue import PromptQueue


def test_ordered_queue_cycles_and_returns_a_miss_after_three_others() -> None:
    """Verify ordered queue cycles and returns a miss after three others."""
    queue = PromptQueue(4)
    assert queue.current == 0
    served = [queue.advance(missed=True), queue.advance(), queue.advance(), queue.advance()]
    assert served == [1, 2, 3, 0]
    assert [queue.advance() for _ in range(4)].count(0) == 1


def test_shuffled_queue_covers_every_item_without_immediate_repeats() -> None:
    """Verify shuffled queue covers every item without immediate repeats."""
    queue = PromptQueue(7, random.Random(11))
    served = [queue.current] + [queue.advance() for _ in range(69)]
    assert all(a != b for a, b in zip(served, served[1:], strict=False))
    for start in range(0, 70, 7):
        assert sorted(served[start : start + 7]) == list(range(7))
    assert served[:7] != served[7:14] or served[7:14] != served[14:21]


def test_small_sets_shorten_the_retry_gap() -> None:
    """Verify small sets shorten the retry gap."""
    pair = PromptQueue(2)
    assert [pair.current, pair.advance(missed=True), pair.advance()] == [0, 1, 0]
    single = PromptQueue(1)
    assert [single.advance(missed=True) for _ in range(3)] == [0, 0, 0]
    with pytest.raises(ValueError, match="at least one"):
        PromptQueue(0)


def test_a_missed_item_is_not_shown_again_before_its_retry() -> None:
    """Verify a missed item is not shown again before its retry."""
    queue = PromptQueue(5, random.Random(3))
    missed = queue.current
    between = [queue.advance(missed=True), queue.advance(), queue.advance()]
    assert missed not in between
    assert queue.advance() == missed
