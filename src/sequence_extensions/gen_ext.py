"""Generator utilities for sequence_extensions."""

from collections.abc import Iterable, Iterator
from typing import Callable, Optional, TypeVar

from sequence_extensions.list_ext import list_ext

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
            stop_f: Predicate on the *next* item: return True to keep
                yielding, False to stop. Default None means never stop
                (callers must supply a stop predicate or an iter_f that
                terminates, e.g. by raising StopIteration).

        Returns:
            An iterator over the yielded items.
        """
        while True:
            item = iter_f(item)
            if stop_f is not None and not stop_f(item):
                return
            yield item