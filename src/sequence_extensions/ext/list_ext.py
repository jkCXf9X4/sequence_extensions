# this code is free to use, copy, change and do anything that you want with it
"""
Extensions to the built-in `list` class with convenience methods
for mapping, filtering, windows, dict conversions, and more.
"""

from collections import ChainMap, deque
from collections.abc import Iterable
from functools import reduce
from statistics import mean
from typing import TYPE_CHECKING, Any, Callable, Optional, TypeVar, Union

if TYPE_CHECKING:
    from . import dict_ext

T = TypeVar("T")
U = TypeVar("U")


class list_ext(list):
    """
    Extend the normal list class

    Transformations such as map, filter, zip, window, to_type and to_strings
    preserve the subclass type (they return list_ext or the subclass).
    Conversions such as to_set, to_tuple and to_dict_* return plain
    set/tuple/dict_ext objects.

    Exception types: first and last raise IndexError when no item is found,
    while single raises ValueError when the (filtered) length is not 1.
    """

    def map(self, func: Callable[[T], U]) -> "list_ext":
        """
        Map function over the list
        func(x) -> y

        list_ext(map(func, list))
        """
        return type(self)(map(func, self))

    def filter(self, func: Callable[[T], bool]) -> "list_ext":
        """
        Filter the list using func
        func(x) -> bool

        list_ext(filter(func, list))
        """
        return type(self)(filter(func, self))

    def reduce(self, func: Callable[[T, T], T]) -> T:
        """
        Reduce the list
        func(a, b) -> c

        reduce(func, list)
        """
        return reduce(func, self)

    def zip(self, *iterables: Any) -> "list_ext":
        """
        Zip list together with iterables

        list_ext(zip(self, *iterables))

        If no extra iterables are given, an empty list_ext is returned.
        """
        if not iterables:
            return type(self)()
        return type(self)(zip(self, *iterables))

    def for_each(self, func: Callable[[T], Any]) -> None:
        """
        Execute function on each item in list
        [func(i) for i in list]

        Returns None; func is called for its side effects only.
        """
        for x in self:
            func(x)

    def window(self, n: int = 2) -> "list_ext":
        """
        Return a list of sliding/rolling windows of size n over the list.

        For n=2 over [a1, a2, a3, a4]:
        [[a1, a2], [a2, a3], [a3, a4]]

        If n > len(self), an empty list is returned.
        Raises ValueError if n < 1.
        """
        if n <= 0:
            raise ValueError("window size must be >= 1")
        windows = []
        d = deque(maxlen=n)
        for x in self:
            d.append(x)
            if len(d) == n:
                windows.append(type(self)(d))
        return type(self)(windows)

    def window_select(self, func: Callable, n: int = 2) -> "list_ext":
        """
        Apply func to a sliding/rolling window of size n
        [a1, a2, a3, a4, ...]

        for n=2
        [func(a1, a2), func(a2, a3),...]
        n=3
        [func(a1, a2, a3), func(a2, a3, a4),...]

        func is required and is called with the items of each window.

        Returns:
            list_ext of the results of func applied to each window.

        Raises:
            ValueError: if n < 1.
        """
        return type(self)(self.window(n=n).map(lambda x: func(*x)))

    @staticmethod
    def execute_or_default(
        func: Callable,
        default: Any = None,
        exception: Union[type, tuple[type, ...]] = (IndexError, KeyError),
    ) -> Any:
        """
        Try to execute function, return default if one of the expected
        lookup errors (IndexError, KeyError) is raised

        exception: the exception type(s) to catch, defaults to (IndexError, KeyError)
        """
        try:
            return func()
        except exception:
            return default

    def get_item_or_default(self, index: int, default: Any = None) -> Any:
        """
        Get self[index] or default if the access fails
        """
        return self.execute_or_default(
            lambda: self[index], default=default, exception=(IndexError, TypeError)
        )

    def first(self, func: Optional[Callable[[T], bool]] = None) -> T:
        """
        filter list on func, return first item in the filtered list
        will raise IndexError if no item is found

        if func is None the first item will be returned
        """
        if func is None:
            return self[0]
        for x in self:
            if func(x):
                return x
        raise IndexError("no item found")

    def first_or_default(
        self, func: Optional[Callable[[T], bool]] = None, default: Any = None
    ) -> Any:
        """
        filter list on func, return first item in the filtered list,
        will return default if no item is found
        """
        filtered = self.filter(func) if func is not None else self

        return filtered.get_item_or_default(index=0, default=default)

    def last(self, func: Optional[Callable[[T], bool]] = None) -> T:
        """
        filter list on func, return last item in the filtered list
        will raise IndexError if no item is found
        """
        if func is None:
            return self[-1]
        for x in reversed(self):
            if func(x):
                return x
        raise IndexError("no item found")

    def last_or_default(
        self, func: Optional[Callable[[T], bool]] = None, default: Any = None
    ) -> Any:
        """
        filter list on func, return last item in the filtered list,
        will return default if no item is found
        """
        filtered = self.filter(func) if func is not None else self

        return filtered.get_item_or_default(index=-1, default=default)

    def to_type(self, t: type) -> "list_ext":
        """
        list_ext([t(x) for x in list])
        """
        return type(self)([t(i) for i in self])

    def to_strings(self) -> "list_ext":
        """
        Convert all items to their string equivalent
        """
        return self.to_type(str)

    def to_string(
        self,
        separator: str = ", ",
        pre: bool = False,
        post: bool = False,
        prefix: str = "",
        suffix: str = "",
    ) -> str:
        """
        Convert the list to a string

        pre/post: if True, prepend/append the separator
        prefix/suffix: string to prepend/append when pre/post are False
        """
        _pre = separator if pre else prefix
        _post = separator if post else suffix
        return f"{_pre}{separator.join(str(x) for x in self)}{_post}"

    def of_type(self, t: type) -> "list_ext":
        """
        Filter the list depending on type

        Uses isinstance(x, t), so subclasses of t are included.
        """
        return self.filter(lambda x: isinstance(x, t))

    def to_set(self) -> set:
        """
        Convert to set
        """
        return set(self)

    def to_tuple(self) -> tuple:
        """
        Convert to tuple
        """
        return tuple(self)

    def to_dict_key(self, keys: Iterable) -> "dict_ext":
        """
        Convert to dict, using keys as the dict keys and the list items as values.

        Raises ValueError if len(keys) != len(self).
        """
        from .dict_ext import dict_ext

        keys = list(keys)
        if len(keys) != len(self):
            raise ValueError(f"keys length ({len(keys)}) does not match list length ({len(self)})")
        return dict_ext((j, i) for i, j in self.zip(keys))

    def to_dict_value(self, values: Iterable) -> "dict_ext":
        """
        Convert to dict, using the list items as keys and values as the dict values.

        Raises ValueError if len(values) != len(self).
        """
        from .dict_ext import dict_ext

        values = list(values)
        if len(values) != len(self):
            raise ValueError(
                f"values length ({len(values)}) does not match list length ({len(self)})"
            )
        return dict_ext((i, j) for i, j in self.zip(values))

    def to_dict_fn(
        self,
        key_func: Optional[Callable[[T], Any]] = None,
        value_func: Optional[Callable[[T], Any]] = None,
    ) -> "dict_ext":
        """
        Convert to a dict using key_func and value_func:
        {key_func(i): value_func(i) for i in self}

        If key_func is None the identity is used as the key; if value_func is
        None the identity is used as the value.
        """
        from .dict_ext import dict_ext

        def f(i):
            k = key_func(i) if key_func else i
            v = value_func(i) if value_func else i
            return (k, v)

        return dict_ext(f(i) for i in self)

    def all(self, func: Optional[Callable[[T], bool]] = None) -> bool:
        """
        Check if all items fulfill the condition

        if func is provided equivalent to 'all(func(x) for x in self)'
        """
        if func is None:
            return all(self)
        return all(func(x) for x in self)

    def any(self, func: Optional[Callable[[T], bool]] = None) -> bool:
        """
        Check if at least one item fulfill the condition

        if func is provided equivalent to 'any(func(x) for x in self)'
        """
        if func is None:
            return any(self)
        return any(func(x) for x in self)

    def contains(self, item: T) -> bool:
        """
        Check if item is an item in the list
        """
        return item in self

    def is_empty(self) -> bool:
        """
        Check if the list is empty
        """
        return len(self) == 0

    def is_single(self) -> bool:
        """
        Check if the list is 1 item long
        """
        return len(self) == 1

    def single(self, func: Optional[Callable[[T], bool]] = None) -> T:
        """
        Returns the unique item fulfilling the condition, if more than one is
        found a ValueError will be raised

        If func is None, an error is raised if the list is not one item long,
        but no filtering will occur

        Raises ValueError when the (filtered) length is not 1.
        """
        if func is None:
            if len(self) != 1:
                raise ValueError(f"Expected exactly one item, got {len(self)}")
            return self[0]
        count = 0
        item = None
        for x in self:
            if func(x):
                count += 1
                item = x
        if count != 1:
            raise ValueError(f"Expected exactly one item, got {count}")
        return item

    def intersect(self, other: Iterable) -> "list_ext":
        """
        Return common elements shared between two lists
        """
        return type(self)(set(self) & set(other))

    def union(self, other: Iterable) -> "list_ext":
        """
        Return a list of the set containing all the items
        """
        return type(self)(set(self) | set(other))

    def chainmap(self: "list[dict[Any, Any]]") -> "dict_ext":
        """
        Chain multiple dicts together.

        Later dicts' overlapping keys are ignored (first dict wins).
        Returns a dict_ext of the chained dicts.
        """
        from .dict_ext import dict_ext

        return dict_ext(ChainMap(*self))

    def average(self) -> float:
        """
        Return the arithmetic mean of the list items

        Raises StatisticsError if the list is empty.
        """
        return mean(self)

    def max(self) -> T:
        """
        Return the largest item in the list
        """
        return max(self)

    def min(self) -> T:
        """
        Return the smallest item in the list
        """
        return min(self)
