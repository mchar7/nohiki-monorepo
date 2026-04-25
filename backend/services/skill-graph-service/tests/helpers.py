"""Shared test utilities for skill-graph-service tests.

Reusable test helpers that can be imported across
multiple test files to avoid code duplication.
"""

from __future__ import annotations


class MockAsyncIterator[T]:
    """Reusable mock async iterator for testing streaming functions.

    Simulates async iteration over a predefined list of items, useful for
    testing code that consumes async generators or streams.

    Example:
        >>> items = [obj1, obj2, obj3]
        >>> db.stream_scalars = AsyncMock(return_value=MockAsyncIterator(items))

    """

    def __init__(self, items: list[T]) -> None:
        """Initialize with list of items to iterate.

        Args:
            items: Items to yield during iteration.

        """
        self.items = items
        self.index = 0

    def __aiter__(self) -> MockAsyncIterator[T]:
        """Return self as the async iterator."""
        return self

    async def __anext__(self) -> T:
        """Return next item or raise StopAsyncIteration."""
        if self.index >= len(self.items):
            raise StopAsyncIteration
        item = self.items[self.index]
        self.index += 1
        return item
