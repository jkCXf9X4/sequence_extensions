
# this code is free to use, copy, change and do anything that c

from functools import reduce

class ext_list(list):
    
    def map(self, func):
        return type(self)(map(func, self))
    
    def filter(self, func):
        return type(self)(filter(func, self))
        
    def reduce(self, func):
        return reduce(func, self)
    
    def zip(self, *iterables):
        return type(self)(zip(self, *iterables))
    
    def for_each(self, func):
        [func(i) for i in self]

    @staticmethod
    def try_default(func, default=None, exception=Exception):
        try:
            return func()
        except exception:
            return default
        
    def first(self):
        return super().__getitem__(0)

    def first_or_default(self, default=None):
        return ext_list.try_default(self.first, default=default, exception=IndexError)
            
    def last(self):
        return super().__getitem__(-1)

    def last_or_default(self, default=None):
        return ext_list.try_default(self.last, default=default, exception=IndexError)

    def to_type(self, t):
        return type(self)(t(i) for i in self)
        
    def to_strings(self):
        return self.to_type(str)
    
    def to_string(self, separator=", ", pre=False, post=False) -> str:
        _pre = separator if pre else ""
        _post = separator if post else ""
        return f"{_pre}{separator.join(self.to_strings())}{_post}"

    def of_type(self, t):
        return self.filter(lambda x: type(x)==t)
    
    def to_set(self):
        return set(self)
    
    def to_tuple(self):
        return tuple(self)
    
    def to_dict(self, keys):
        return {j:i for i, j in self.zip(keys)}
    
    def all(self, func) -> bool:
        l = self.map(func)
        return all(l)
    
    def any(self, func) -> bool:
        l = self.map(func)
        return any(l)   

    def contains(self, x) -> bool:
        return x in self
    
    def is_empty(self) -> bool:
        return len(self) == 0

    def is_single(self):
        return len(self) == 1

    def single(self, func):
        """
        Returns the 
        """
        l = self.filter(func)
        if l.is_single() == False:
            raise Exception("More than one item in a single list")
        return l.first()
    
    def intersect(self, l):
        """
        Return common elements shared between two lists
        """
        return type(self)(set(self) & set(l))

    def union(self, l):
        return type(self)(set(self) | set(l))
