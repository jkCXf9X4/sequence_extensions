"""
dict_ext: an extended dict class with functional-style helpers
(map, filter, reduce, ...) mirroring list_ext semantics.
"""

from functools import reduce
from typing import Any, Callable, NamedTuple, Optional

from sequence_extensions.list_ext import list_ext


class KeyValueTuple(NamedTuple):
    """A (key, value) pair as a named tuple with .key and .value attributes."""

    key: Any
    value: Any


class dict_ext(dict):
    """
    Extend the normal dict class
    """

    def map(self, func: Callable[[Any, Any], Any], cast: Any = "dict_ext") -> Any:
        """
        Apply func to each (key, value) pair and cast the results.

        Parameters
        ----------
        func : Callable[[Any, Any], Any]
            func(key, value) -> result
        cast : Any, default "dict_ext"
            How to cast the iterable of func results:
            - dict: return a plain dict (builtin); accepts any
              dict-constructible iterable of (key, value) pairs
              (no 2-tuple validation)
            - dict_ext: return a dict_ext; each func result must be a
              (key, value) 2-tuple, otherwise a TypeError is raised
            - list_ext: return a list_ext of func results (no 2-tuple
              validation)
            - other: cast(iterable_of_func_results)

        Returns
        -------
        The func results cast with `cast`.
        """
        results = [func(*i) for i in self.items()]

        if cast is dict or cast == "dict":
            return dict(results)

        if cast is dict_ext or cast == "dict_ext":
            for r in results:
                if not isinstance(r, (tuple, list)) or len(r) != 2:
                    raise TypeError("map func must return a (key, value) 2-tuple")
            return dict_ext(results)

        if cast is list_ext or cast == "list_ext":
            return list_ext(results)

        return cast(results)

    def filter(self, func: Optional[Callable[[Any, Any], bool]] = None) -> "dict_ext":
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

        Returns None.
        """
        for key, value in self.items():
            func(key, value)

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
        return self.map(
            lambda a, b: (str(a) if key else a, str(b) if value else b),
            cast=dict_ext,
        )

    def to_string(self, separator: str = "\n") -> str:
        """
        return string of dict

        separator: str, default "\\n"
            separator between entries

        Return:
        key1 : value1
        key2 : value2
        ...
        """
        results = self.map(lambda a, b: f"{a} : {b}", list_ext)
        s = results.to_string(separator=separator)
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

    def to_tuple(self) -> tuple[tuple[Any, Any], ...]:
        """
        ((key, value),..)
        """
        return tuple((key, value) for key, value in self.items())

    def to_named_tuple(self) -> tuple[KeyValueTuple, ...]:
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

    def reduce(self, func: Callable[[KeyValueTuple, KeyValueTuple], tuple[Any, Any]]) -> "dict_ext":
        """
        Reduce the dict's (key, value) pairs
        func(a : KeyValueTuple, b : KeyValueTuple) -> (key_c, value_c)
        [a|b].key
        [a|b].value

        If the dict is empty, return an empty dict_ext.
        """
        if not self:
            return type(self)()

        t = self.to_named_tuple()

        # ensure that the returned type is the same as the iterable
        def f(*args):
            result = func(*args)
            if not isinstance(result, (tuple, list)) or len(result) != 2:
                raise TypeError("reduce func must return a (key, value) 2-tuple")
            return KeyValueTuple(*result)

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

        If multiple keys share the same value, the last one wins.
        """
        return type(self)({value: key for key, value in self.items()})

    def first(self, func: Optional[Callable[[Any, Any], bool]] = None) -> KeyValueTuple:
        """
        Filter the dict on func(key, value), return the first (key, value) pair
        as a KeyValueTuple.
        Will raise IndexError if no item is found.

        if func is None the first item will be returned
        """
        results = self.filter(func) if func is not None else self

        return KeyValueTuple(*results.to_list()[0])

    def last(self, func: Optional[Callable[[Any, Any], bool]] = None) -> KeyValueTuple:
        """
        Filter the dict on func(key, value), return the last (key, value) pair
        as a KeyValueTuple.
        Will raise IndexError if no item is found.

        if func is None the last item will be returned
        """
        results = self.filter(func) if func is not None else self

        return KeyValueTuple(*results.to_list()[-1])

    def all(self, func: Optional[Callable[[Any, Any], bool]] = None) -> bool:
        """
        Check if all items fulfill the condition

        if func is None, operate on the dict's VALUES only:
            all(self.values())

        if func is provided equivalent to  'all(self.map(func, cast=list_ext))'
        """
        if func is None:
            return all(self.values())
        results = self.map(func, cast=list_ext)
        return all(results)

    def any(self, func: Optional[Callable[[Any, Any], bool]] = None) -> bool:
        """
        Check if at least one item fulfill the condition

        if func is None, operate on the dict's VALUES only:
            any(self.values())

        if func is provided equivalent to  'any(self.map(func, cast=list_ext))'
        """
        if func is None:
            return any(self.values())
        results = self.map(func, cast=list_ext)
        return any(results)
