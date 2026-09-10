# sequence_extensions

Higher-order function extensions for Python lists, dicts, generators, and dependency-graph futures.

The package provides four modules:

- `list_ext` — an extended `list` class with functional helpers (`map`, `filter`, `reduce`, `window`, ...)
- `dict_ext` — an extended `dict` class with functional helpers (`map`, `filter`, `reduce`, ...)
- `gen_ext` — static helpers for generators (`to_list`, `recursive_gen`)
- `graph_future` — dependency-graph futures (`GraphFuture`, `GraphPool`)

## list_ext

```python
from sequence_extensions import list_ext

l = list_ext([1, 2, 3, 4])

l.map(lambda x: x*2)
[2, 4, 6, 8]

l.filter(lambda x: x%2==0)
[2, 4]

l.for_each(lambda x: print(x))
1
2
3
4

l.first(lambda x: x%2==0)
2

l.last(lambda x: x%2==0)
4

l.to_strings()
['1', '2', '3', '4']

l.to_string()
'1, 2, 3, 4'
```

## dict_ext

`dict_ext` extends `dict` with functional helpers that operate on `(key, value)` pairs:

```python
from sequence_extensions import dict_ext

d = dict_ext({"a": 1, "b": 2, "c": 3, "d": 4})

d.map(lambda k, v: (k * 2, v * 2))          # {'aa': 2, 'bb': 4, 'cc': 6, 'dd': 8}
d.filter(lambda k, v: v % 2 == 0)           # {'b': 2, 'd': 4}
d.for_each(lambda k, v: print(k, v))        # prints each pair
d.to_list()                                 # [['a', 1], ['b', 2], ['c', 3], ['d', 4]]
d.to_strings()                              # {'a': '1', 'b': '2', 'c': '3', 'd': '4'}
d.to_string()                               # 'a : 1\nb : 2\nc : 3\nd : 4'
d.get_keys()                                # ['a', 'b', 'c', 'd']
d.get_values()                              # [1, 2, 3, 4]
d.to_tuple()                                # (('a', 1), ('b', 2), ('c', 3), ('d', 4))
d.to_named_tuple()                          # (KeyValueTuple(key='a', value=1), ...)
d.get_key_from_value(3)                     # ['c']
d.reduce(lambda a, b: (a.key + b.key, a.value + b.value))  # {'abcd': 10}
d.extend({"e": 5})                          # merged dict (other wins on conflicts)
d.union({"e": 5})                           # dict union (other wins on conflicts)
d.inverse()                                 # {1: 'a', 2: 'b', 3: 'c', 4: 'd'}
d.first()                                   # KeyValueTuple(key='a', value=1)
d.last()                                    # KeyValueTuple(key='d', value=4)
d.all(lambda k, v: type(v) == int)          # True
d.any(lambda k, v: v == 1)                  # True
```

`KeyValueTuple` is a `NamedTuple` with `.key` and `.value` attributes, returned by `first`, `last`, `reduce`, and `to_named_tuple`.

## gen_ext

Static helpers for generators and iterables:

```python
from sequence_extensions import gen_ext

gen_ext.to_list(iter([1, 2, 3]))            # [1, 2, 3]
list(gen_ext.recursive_gen(5, lambda x: x - 1, stop_f=lambda x: x > 0))  # [4, 3, 2, 1]
```

`recursive_gen` yields each next item produced by `iter_f`; `stop_f` is called on the *next* item — when it returns `False` the walk stops before yielding that item.

## graph_future

Dependency-graph futures evaluated with a bounded thread pool:

```python
from sequence_extensions import GraphFuture, GraphPool

def add(x, y):
    return x + y

with GraphPool(max_workers=4) as pool:
    a = GraphFuture(lambda: 1)
    b = GraphFuture(lambda: 2)
    c = GraphFuture(add, a, b)      # waits for a and b
    result = pool.result(c)         # 3
```

`GraphFuture` nodes may depend on other nodes; results are resolved automatically. `GraphPool` can also be used without the context manager (the executor is created lazily on first use).

## Development

For development install:

```
pip install -e ".[dev]"
```

To run tests (bare `pytest` works — `pythonpath` is configured in `pyproject.toml`):

```
pytest
```

To generate coverage:

```
pytest --cov --cov-report html
```

## License

MIT