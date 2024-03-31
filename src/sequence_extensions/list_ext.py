# this code is free to use, copy, change and do anything that c

from collections import ChainMap
from functools import reduce
from statistics import mean


class list_ext(list):
    """
    Extend the normal list class
    """

    def map(self, func):
        """
        Map function over the list
        func(x) -> y

        list_ext(map(func, list))
        """
        return type(self)(map(func, self))

    def filter(self, func):
        """
        Filter the list using func
        func(x) -> bool

        list_ext(filter(func, list))
        """
        return type(self)(filter(func, self))

    def reduce(self, func):
        """
        Reduce the list
        func(a, b) -> c

        reduce(func, list)
        """
        return reduce(func, self)

    def zip(self, *iterables):
        """
        Zip list together with iterables

        list_ext(zip(self, *iterables))
        """
        return type(self)(zip(self, *iterables))

    def for_each(self, func) -> None:
        """
        Execute function on each item in list
        [func(i) for i in list]
        """
        self.map(func)

    def pairwice(self, func):
        """
        [a1, a2, a3, a4, ...]

        [func(a1, a2), func(a2, a3),...]
        """

        return self.window_select(func, n=2)

    def window_select(self, func=None, n=2):
        """
        Apply func to a sliding/rolling window of size n
        [a1, a2, a3, a4, ...]

        for n=2
        [func(a1, a2), func(a2, a3),...]
        n=3
        [func(a1, a2, a3), func(a2, a3, a4),...]

        """
        return type(self)([func(*self[i : i + n]) for i in range(len(self) - n + 1)])

    def window(self, n=2):
        """
        [[a1, a2], [a2, a3],...]
        """
        return type(self)([self[i : i + n] for i in range(len(self) - n + 1)])

    @staticmethod
    def execute_or_default(func, default=None, exception=Exception):
        """
        Try to execute function, return default if exception is raised
        """
        try:
            return func()
        except exception:
            return default

    def get_item_or_default(self, index, default=None):
        """
        Get self[index] or default if the access fails
        """
        return self.execute_or_default(
            lambda: self[index], default=default, exception=IndexError
        )

    def first(self, func=None):
        """
        filter list on func, return first item in the filtered list
        will raise IndexError if no item is found

        if func == None the first item will be returned
        """
        l = self.filter(func) if func != None else self

        return l[0]

    def first_or_default(self, func=None, default=None):
        """
        filter list on func, return first item in the filtered list,
        will return default if no item is found
        """

        l = self.filter(func) if func != None else self

        return l.get_item_or_default(index=0, default=default)

    def last(self, func=None):
        """
        filter list on func, return last item in the filtered list
        will raise IndexError if no item is found
        """
        l = self.filter(func) if func != None else self

        return l[-1]

    def last_or_default(self, func=None, default=None):
        """
        filter list on func, return last item in the filtered list,
        will return default if no item is found
        """
        l = self.filter(func) if func != None else self

        return l.get_item_or_default(index=-1, default=default)

    def to_type(self, t):
        """
        list_ext([t(x) for x in list])
        """
        return type(self)([t(i) for i in self])

    def to_strings(self):
        """
        Convert all items to their string equvalent
        """
        return self.to_type(str)

    def to_string(self, separator=", ", pre=False, post=False) -> str:
        """
        Convert the list to a string
        """
        _pre = separator if pre else ""
        _post = separator if post else ""
        return f"{_pre}{separator.join(self.to_strings())}{_post}"

    def of_type(self, t):
        """
        Filter the list depending on type

        """
        return self.filter(lambda x: type(x) == t)

    def to_set(self):
        """
        Convert to set
        """
        return set(self)

    def to_tuple(self):
        """
        Convert to tuple
        """
        return tuple(self)

    def to_dict_key(self, keys):
        """
        Convert to dict
        """
        from sequence_extensions import dict_ext

        return dict_ext((j, i) for i, j in self.zip(keys))

    def to_dict_value(self, values):
        """
        Convert to dict
        """
        from sequence_extensions import dict_ext

        return dict_ext((i, j) for i, j in self.zip(values))

    def to_dict_fn(self, key_func=None, value_func=None):
        """
        Convert to dict using a
        {func(i): i for i in self}
        """
        from sequence_extensions import dict_ext

        def f(i):
            k = key_func(i) if key_func else i
            v = value_func(i) if value_func else i
            return (k, v)

        return dict_ext(f(i) for i in self)

    def all(self, func=None) -> bool:
        """
        Check if all items fullfill the condition
        """
        l = self.map(func) if func != None else self
        return all(l)

    def any(self, func=None) -> bool:
        """
        Check if at least one item fullfill the condition

        """
        l = self.map(func) if func != None else self
        return any(l)

    def contains(self, x) -> bool:
        """
        Check if x is an item in the list
        """
        return x in self

    def is_empty(self) -> bool:
        """
        Check if the list is empty
        """
        return len(self) == 0

    def is_single(self):
        """
        Check if the list is 1 item long
        """
        return len(self) == 1

    def single(self, func=None):
        """
        Returns the quniqe item fullfilling the condition, if more than one is found an Exception will be raised

        If func == None, an error is raised if the list is not one item long, but no filtering will occur
        """
        l = self.filter(func) if func else self

        if l.is_single() == False:
            raise Exception("More than one item in a single list")
        return l.first()

    def intersect(self, l):
        """
        Return common elements shared between two lists
        """
        return type(self)(set(self) & set(l))

    def union(self, l):
        """
        Return a list of the set containing all the items
        """
        return type(self)(set(self) | set(l))

    def chainmap(self: list[dict]):
        """
        Chain multiple dicts together
        """
        from sequence_extensions import dict_ext

        return dict_ext(ChainMap(*self))

    def average(self):
        return mean(self)

    def max(self):
        return max(self)

    def min(self):
        return min(self)
