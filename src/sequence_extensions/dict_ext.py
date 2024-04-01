

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

    def map_dict(self, func):
        """
        func(key, item) -> (key_t, item_t)
        returns {key_t1 : item_t1, key_t2 : item_t2, ...}
        """
        l = [func(key, value) for key, value in self.items()]
        return type(self)(l)
    
    def map_list(self, func):
        """
        func(key, item) -> a
        returns [a1, a2, a3 ...]
        """
        l = [func(key, value) for key, value in self.items()]
        return list_ext(l)

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

    def to_strings(self):
        """
        {key:value} -> {"key":"value"}
        """

        return self.map_dict(lambda a, b: (str(a), str(b)))
    
    def to_string(self, separator = "\n"):
        """ 
        return string of dict
        
        "key1 : value1
        key2 : value2
        ..."
        
        """
        l = list_ext(self.map_list(lambda a, b: f"{a} : {b}"))
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
        Itterate over dict to find the key corresponding to the value
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

    def first(self, func=None):
        """
        filter list on func, return first item in the filtered list
        will raise IndexError if no item is found

        if func == None the first item will be returned
        """
        l = self.filter(func) if func != None else self

        return KeyValueTuple(*l.to_list()[0])