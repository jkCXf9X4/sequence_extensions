

from functools import reduce
from typing import Any, Callable, NamedTuple
from sequence_extensions import list_ext


class KeyValueTuple(NamedTuple):
    key: Any
    value: Any


class dict_ext(dict):
    """
    Extend the normal dict class
    """

    def map(self, func, cast=dict):
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
        return cast(l)


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
        return list_ext([[key, value] for key, value in self.items()])

    def to_strings(self, key=True, value=True):
        """
        {key:value} -> {"key":"value"}
        """
        return self.map(lambda a, b: (str(a) if key else a, str(b) if value else b))
    
    def to_string(self, separator = "\n"):
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

    def get_keys(self):
        """
        [key1, key2,..]
        """
        return list_ext(self.keys())
    
    def get_values(self):
        """
        [value1, value2,..]
        """
        return list_ext(self.values())

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

    def get_key_from_value(self, value):
        """
        Iterate over dict to find all keys corresponding to the value
        A list of all keys will be returned
        """
        return list_ext([key for key, val in self.items() if val == value])

    def reduce(self, func : Callable[[KeyValueTuple, KeyValueTuple], tuple[Any, Any]]):
        """
        Reduce the list
        func(a : KeyValueTuple, b : KeyValueTuple) -> (key_c, item_c)
        [a|b].key
        [a|b].value
        """
        t = self.to_named_tuple()

        # ensure that the returned type is the same as the iterable
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

    def first(self, func=None):
        """
        filter list on func, return first item in the filtered list
        will raise IndexError if no item is found

        if func == None the first item will be returned
        """
        l = self.filter(func) if func != None else self

        return KeyValueTuple(*l.to_list()[0])
    
    def last(self, func=None):
        """
        filter list on func, return last item in the filtered list
        will raise IndexError if no item is found

        if func == None the last item will be returned
        """
        l = self.filter(func) if func != None else self

        return KeyValueTuple(*l.to_list()[-1])
    
    def all(self, func=None) -> bool:
        """
        Check if all items fulfill the condition
        
        if func is provided equivalent to  'all(self.map(func, cast=list))'
        """
        l = self.map(func, cast=list_ext) if func != None else self
        return all(l)

    def any(self, func=None) -> bool:
        """
        Check if at least one item fulfill the condition
        
        if func is provided equivalent to  'any(self.map(func, cast=list))'
        """
        l = self.map(func, cast=list_ext) if func != None else self
        return any(l)