"""The order in which a drill presents its items."""

import random


class PromptQueue:
    """Serve item indices in bags, bringing a missed item back after a short gap.

    With a random source every pass through the items is freshly shuffled and never opens
    with the item just shown, so order cannot be memorised. Without one the items cycle in
    their given order, which keeps behaviour fully predictable for tests and replays. A
    missed item returns after ``retry_gap`` other prompts (fewer in a very small set).
    """

    def __init__(self, size: int, rng: random.Random | None = None, retry_gap: int = 3) -> None:
        """Create a queue over ``size`` items and select the first one."""
        if size < 1:
            raise ValueError("A prompt queue needs at least one item")
        self.size = size
        self.rng = rng
        self.gap = min(retry_gap, size - 1)
        self.served = 0
        self._bag: list[int] = []
        self._retries: list[tuple[int, int]] = []
        self.current = self._draw(None)

    def _refill(self) -> None:
        """Start a new pass through every item."""
        self._bag = list(range(self.size))
        if self.rng is not None:
            self.rng.shuffle(self._bag)

    def _draw(self, avoid: int | None) -> int:
        """Take the next item from the bag, skipping ones already scheduled to return."""
        pending = {index for _, index in self._retries}
        for _ in range(2):
            self._bag = [index for index in self._bag if index not in pending]
            for position, index in enumerate(self._bag):
                if index != avoid:
                    return self._bag.pop(position)
            self._refill()
        return avoid if avoid is not None else 0

    def advance(self, *, missed: bool = False) -> int:
        """Finish the current item and return the next; a missed item is queued to return."""
        self.served += 1
        if missed and self.gap:
            self._retries.append((self.served + self.gap, self.current))
        if self._retries and self._retries[0][0] <= self.served:
            _, self.current = self._retries.pop(0)
        else:
            self.current = self._draw(self.current)
        return self.current
