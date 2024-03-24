from  sequence_extensions import list_ext


def recursive_gen(item, iter_f, stop_f = lambda x: x != None):
    
    next = iter_f(item)
    if stop_f(next):
        yield next
        yield from recursive_gen(next, iter_f=iter_f, stop_f=stop_f)

def recursive_list(item, iter_f, stop_f = lambda x: x != None):
    return list_ext(recursive_gen(item=item, iter_f=iter_f, stop_f=stop_f))