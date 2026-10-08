"""Generator utilities for sequence_extensions."""

from collections.abc import Iterable, Iterator
from typing import Callable, Optional, TypeVar

T = TypeVar("T")


class gen_ext:
    """Static helper functions for working with generators and iterables."""

    @staticmethod
    def to_list(generator: Iterable[T]) -> list[T]:
        """Convert an iterable into a plain list.

        Args:
            generator: Any iterable (generator, list, tuple, ...).

        Returns:
            A plain ``list`` containing all items from the iterable.
        """
        return list(generator)

    @staticmethod
    def recursive_gen(
        item: T,
        iter_f: Callable[[T], T],
        stop_f: Optional[Callable[[T], bool]] = None,
    ) -> Iterator[T]:
        """Iteratively walk a chain of items, yielding each next item.

        Starting from ``item``, repeatedly applies ``iter_f`` to obtain the
        next item and yields it. The walk continues until ``stop_f`` returns
        False for a next item, or forever if ``stop_f`` is None.

        Args:
            item: The starting item (not yielded itself).
            iter_f: Function mapping the current item to the next item.
            stop_f: Keep-going predicate on the *next* item: return True to
                continue, False to stop. Default None means never stop —
                callers must always pass a stop_f, or bound the walk with
                itertools.islice/takewhile.

        Returns:
            An iterator over the yielded items.
        """
        while True:
            try:
                item = iter_f(item)
            except StopIteration:
                return
            if stop_f is not None and not stop_f(item):
                return
            yield item
