"""
dict_ext: an extended dict class with functional-style helpers
(map, filter, reduce, ...) mirroring list_ext semantics.
"""

from functools import reduce
from typing import Any, Callable, NamedTuple, Optional, Tuple
from sequence_extensions import list_ext


class KeyValueTuple(NamedTuple):
    """A (key, value) pair as a named tuple with .key and .value attributes."""

    key: Any
    value: Any


class dict_ext(dict):
    """
    Extend the normal dict class
    """

    def map(self, func: Callable[[Any, Any], Any], cast: Any = dict) -> Any:
        """
        cast([f(*item_1), f(*item_2), ...])

        cast usage:
            cast: dict
            func(key, value) -> (key_t, value_t)
            return: {key_t1 : value_t1, key_t2 : value_t2, ...}

            cast: list
            func(key, value) -> a_t
            return: [a_t1, a_t2, ...]
        """
        l = [func(*i) for i in self.items()]

        cast = dict_ext if cast == dict else cast

        # when casting to a dict, func must return a (key, value) 2-tuple
        if cast is dict_ext:
            for r in l:
                if not isinstance(r, (tuple, list)) or len(r) != 2:
                    raise TypeError("map func must return a (key, value) 2-tuple")

        return cast(l)

    def filter(
        self, func: Optional[Callable[[Any, Any], bool]] = None
    ) -> "dict_ext":
        """
        func(key, value) -> bool

        if func is None, keep all entries
        """
        if func is None:
            return type(self)(self)
        d = {key: value for key, value in self.items() if func(key, value)}
        return type(self)(d)

    def for_each(self, func: Callable[[Any, Any], Any]) -> None:
        """
        func(key, value) -> None
        """
        [func(key, value) for key, value in self.items()]

    def to_list(self) -> list[list[Any]]:
        """
        [[key, value],..]
        """
        return list_ext([[key, value] for key, value in self.items()])

    def to_strings(self, key: bool = True, value: bool = True) -> "dict_ext":
        """
        {key:value} -> {"key":"value"}

        key: if True, convert keys to str; if False, keep keys as-is
        value: if True, convert values to str; if False, keep values as-is

        Returns a new dict_ext with the converted keys/values.
        """
        return self.map(lambda a, b: (str(a) if key else a, str(b) if value else b))

    def to_string(self, separator: str = "\n") -> str:
        """
        return string of dict

        Return:
        key1 : value1
        key2 : value2
        ...
        """
        l = self.map(lambda a, b: f"{a} : {b}", list_ext)
        s = l.to_string(separator=separator)
        return s

    def get_keys(self) -> list[Any]:
        """
        [key1, key2,..]
        """
        return list_ext(self.keys())

    def get_values(self) -> list[Any]:
        """
        [value1, value2,..]
        """
        return list_ext(self.values())

    def to_tuple(self) -> Tuple[Tuple[Any, Any], ...]:
        """
        ((key, value),..)
        """
        return tuple((key, value) for key, value in self.items())

    def to_named_tuple(self) -> Tuple[KeyValueTuple, ...]:
        """
        (a : KeyValueTuple,..)
        a.key
        a.value
        """
        return tuple(KeyValueTuple(key, value) for key, value in self.items())

    def get_key_from_value(self, value: Any) -> list[Any]:
        """
        Iterate over dict to find all keys corresponding to the value
        A list of all keys will be returned
        """
        return list_ext([key for key, val in self.items() if val == value])

    def reduce(
        self, func: Callable[[KeyValueTuple, KeyValueTuple], Tuple[Any, Any]]
    ) -> "dict_ext":
        """
        Reduce the dict's (key, value) pairs
        func(a : KeyValueTuple, b : KeyValueTuple) -> (key_c, item_c)
        [a|b].key
        [a|b].value
        """
        if not self:
            return type(self)()

        t = self.to_named_tuple()

        # ensure that the returned type is the same as the iterable
        def f(*args):
            return KeyValueTuple(*func(*args))

        # convert to dict
        t = (reduce(f, t),)
        return type(self)(t)

    def extend(self, other: dict) -> "dict_ext":
        """
        Return a new dict_ext merging other into this one; on key conflicts,
        other's value wins (like dict union).
        """
        return type(self)({**self, **other})

    def union(self, other: dict) -> "dict_ext":
        """
        Return a new dict_ext with the entries of both dicts (dict union `self | other`).
        """
        return type(self)(self | other)

    def inverse(self) -> "dict_ext":
        """
        {key:value} -> {value:key}
        """
        return type(self)({value: key for key, value in self.items()})

    def first(
        self, func: Optional[Callable[[Any, Any], bool]] = None
    ) -> KeyValueTuple:
        """
        Filter the dict on func(key, value), return the first (key, value) pair
        as a KeyValueTuple.
        Will raise IndexError if no item is found.

        if func is None the first item will be returned
        """
        l = self.filter(func) if func is not None else self

        return KeyValueTuple(*l.to_list()[0])

    def last(
        self, func: Optional[Callable[[Any, Any], bool]] = None
    ) -> KeyValueTuple:
        """
        Filter the dict on func(key, value), return the last (key, value) pair
        as a KeyValueTuple.
        Will raise IndexError if no item is found.

        if func is None the last item will be returned
        """
        l = self.filter(func) if func is not None else self

        return KeyValueTuple(*l.to_list()[-1])

    def all(self, func: Optional[Callable[[Any, Any], bool]] = None) -> bool:
        """
        Check if all items fulfill the condition

        if func is provided equivalent to  'all(self.map(func, cast=list))'
        """
        if func is None:
            return all(self.values())
        l = self.map(func, cast=list_ext)
        return all(l)

    def any(self, func: Optional[Callable[[Any, Any], bool]] = None) -> bool:
        """
        Check if at least one item fulfill the condition

        if func is provided equivalent to  'any(self.map(func, cast=list))'
        """
        if func is None:
            return any(self.values())
        l = self.map(func, cast=list_ext)
        return any(l)