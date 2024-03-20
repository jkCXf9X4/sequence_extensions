

from functools import reduce
from typing import Any, Callable, NamedTuple


class KeyValueTuple(NamedTuple):
    key: Any
    value: Any


class dict_ext(dict):
    """
    Extend the normal dict class
    """

    def map(self, func):
        """
        func(key, item) -> (key, item)
        """
        l = [func(key, value) for key, value in self.items()]
        return type(self)(l)

    def filter(self, func):
        """
        func(key, item) -> bool
        """
        d = {key: value for key, value in self.items() if func(key, value)}
        return type(self)(d)

    def for_each(self, func):
        """
        func(key, item) -> None
        """
        [func(key, value) for key, value in self.items()]

    def to_list(self):
        """
        [[key, value],..]
        """
        return [[key, value] for key, value in self.items()]

    def to_tuple(self):
        """
        ((key, value),..)
        """
        return tuple((key, value) for key, value in self.items())

    def to_named_tuple(self):
        """
        (a : KeyValueTuple,..)
        a.key
        a.value
        """
        return tuple(KeyValueTuple(key, value) for key, value in self.items())

    def get_key(self, value):
        """
        Itterate over dict to find the key corresponding to the value
        A list of all keys will be returned
        """

        return [key for key, val in self.items() if val == value]

    def reduce(self, func : Callable[[KeyValueTuple, KeyValueTuple], tuple[Any, Any]]):
        """
        Reduce the list
        func(a : KeyValueTuple, b : KeyValueTuple) -> (key_c, item_c)
        [a|b].key
        [a|b].value
        """
        t = self.to_named_tuple()

        # ensure that the returned type is the same as the itterable
        def f(*args):
            return KeyValueTuple(*func(*args))

        # convert to dict
        t = (reduce(f, t),)
        return type(self)(t)

    def extend(self, dict):
        """
        Equivalent to return {**self, **dict}

        does not overwrite values like self.update(dict)
        """
        return type(self)(**self, **dict)

    def union(self, dict):
        """
        Equivalent to return {self | dict}

        """
        return type(self)(self | dict)

    def inverse(self):
        """
        {key:value} -> {value:key}
        """
        return type(self)({value:key for key, value in self.items()})
