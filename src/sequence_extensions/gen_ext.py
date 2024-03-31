from  sequence_extensions import list_ext

from collections.abc import Generator
import copy

class gen_ext:


    @staticmethod
    def to_list(generator):
        return list_ext(generator)

    @staticmethod
    def recursive_gen(item, iter_f, stop_f = lambda x: x != None):
        next = iter_f(item)
        if stop_f(next):
            yield next
            yield from gen_ext.recursive_gen(next, iter_f=iter_f, stop_f=stop_f)


