# sequence_extensions API Reference

Hand-written API reference for the `sequence_extensions` package — higher-order function extensions for sequences (lists, dicts, generators) plus a small dependency-graph future and a V&V workflow layer.

> **Version:** this document describes **version 0.2.0** (Python >= 3.9).

## Package layout

```
sequence_extensions/
├── ext/        # list_ext / dict_ext / gen_ext (functional sequence helpers)
├── graph/      # graph_future (GraphFuture / GraphPool execution substrate)
└── workflow/   # V&V workflow layer
    ├── schema.py      # Action / Sequential / Parallel / Template + parse_workflow
    ├── registry.py    # FunctionRegistry + DEFAULT_REGISTRY
    ├── params.py      # parameter normalization (XML form -> Python form)
    ├── engine.py      # run_workflow / Test_Framework execution engine
    ├── adaptation.py  # DAGHandle / AdaptationOp (dynamic adaptation)
    ├── library.py     # the paper's library functions + register_library
    └── history.py     # ExecutionRecord / RunHistory / replay
```

All names below are re-exported from the package root.

## Package exports

```python
from sequence_extensions import (
    list_ext,
    dict_ext,
    gen_ext,
    graph_future,
    GraphFuture,
    GraphPool,
    KeyValueTuple,
    Action,
    Sequential,
    Parallel,
    Template,
    parse_workflow,
    run_workflow,
    Test_Framework,
    FunctionRegistry,
    DEFAULT_REGISTRY,
)

__version__ = "0.2.0"
```

| Export | Description |
| --- | --- |
| `list_ext` | Extended `list` class with functional helpers |
| `dict_ext` | Extended `dict` class with functional helpers |
| `gen_ext` | Static helper functions for generators/iterables |
| `graph_future` | Module containing `GraphFuture` and `GraphPool` |
| `GraphFuture` | Dependency-graph future node |
| `GraphPool` | Thread pool that evaluates a `GraphFuture` graph |
| `KeyValueTuple` | `NamedTuple` with `.key` and `.value` attributes |
| `Action` | Workflow node: one function call |
| `Sequential` | Workflow group: children execute in strict order |
| `Parallel` | Workflow group: independent, concurrent children |
| `Template` | Named, parameterized subtree; `instantiate(**params)` returns a fresh bound copy |
| `parse_workflow` | Parse a workflow XML document into a root group |
| `run_workflow` | Parse and execute a workflow XML document |
| `Test_Framework` | Execute a workflow built via the Python API |
| `FunctionRegistry` | Name -> function registry for workflow actions |
| `DEFAULT_REGISTRY` | Default (empty) function registry |
| `__version__` | `"0.2.0"` |

---

## `list_ext`

`class list_ext(list)` — extends the built-in `list` with convenience methods for mapping, filtering, windows, dict conversions, and more.

### `map`

```python
def map(self, func: Callable[[T], U]) -> "list_ext"
```

- **Parameters:** `func` (`Callable[[T], U]`) — function applied to each item, `func(x) -> y`.
- **Returns:** `list_ext` — `list_ext(map(func, self))`.
- **Raises:** nothing.
- **Description:** Map `func` over the list.

### `filter`

```python
def filter(self, func: Callable[[T], bool]) -> "list_ext"
```

- **Parameters:** `func` (`Callable[[T], bool]`) — predicate, `func(x) -> bool`.
- **Returns:** `list_ext` — `list_ext(filter(func, self))`.
- **Raises:** nothing.
- **Description:** Filter the list using `func`.

### `reduce`

```python
def reduce(self, func: Callable[[T, T], T]) -> T
```

- **Parameters:** `func` (`Callable[[T, T], T]`) — binary reduction function, `func(a, b) -> c`.
- **Returns:** `T` — the reduced value.
- **Raises:** `TypeError` on an empty list (no initial value).
- **Description:** Reduce the list with `functools.reduce` semantics.

### `zip`

```python
def zip(self, *iterables: Any) -> "list_ext"
```

- **Parameters:** `*iterables` (`Any`) — iterables to zip with this list.
- **Returns:** `list_ext` — `list_ext(zip(self, *iterables))`; **`[]` when called with no arguments**.
- **Raises:** nothing.
- **Description:** Zip the list together with the given iterables.

### `for_each`

```python
def for_each(self, func: Callable[[T], Any]) -> None
```

- **Parameters:** `func` (`Callable[[T], Any]`) — function executed on each item.
- **Returns:** `None` (side-effect only).
- **Raises:** whatever `func` raises.
- **Description:** Execute `func` on each item in the list.

### `window`

```python
def window(self, n: int = 2) -> "list_ext"
```

- **Parameters:** `n` (`int`, default `2`) — window size.
- **Returns:** `list_ext` of sliding/rolling windows; **inner windows are `list_ext`**. For `n=2` over `[a1, a2, a3, a4]`: `[[a1, a2], [a2, a3], [a3, a4]]`. Returns an **empty list if `n > len(self)`**.
- **Raises:** `ValueError` if `n < 1`.
- **Description:** Return a list of sliding/rolling windows of size `n` over the list.

### `window_select`

```python
def window_select(self, func: Callable, n: int = 2) -> "list_ext"
```

- **Parameters:** `func` (`Callable`) — called with the items of each window **as positional args** (e.g. `func(a1, a2)` for `n=2`); `n` (`int`, default `2`) — window size.
- **Returns:** `list_ext` — `[func(a1, a2), func(a2, a3), ...]`.
- **Raises:** `ValueError` if `n < 1` (via `window`).
- **Description:** Apply `func` to each sliding window of size `n`.

### `execute_or_default` *(staticmethod)*

```python
@staticmethod
def execute_or_default(func: Callable, default: Any = None, exception: Any = (IndexError, KeyError)) -> Any
```

- **Parameters:** `func` (`Callable`) — zero-arg callable to try; `default` (`Any`, default `None`) — returned when an expected error is raised; `exception` (`Any`, default `(IndexError, KeyError)`) — exception type(s) to catch (customizable, e.g. `exception=ZeroDivisionError`).
- **Returns:** `Any` — `func()` result, or `default` if one of the expected errors is raised.
- **Raises:** any exception not in `exception`.
- **Description:** Try to execute `func`, return `default` if one of the expected lookup errors is raised.

### `get_item_or_default`

```python
def get_item_or_default(self, index: int, default: Any = None) -> Any
```

- **Parameters:** `index` (`int`) — item index; `default` (`Any`, default `None`) — returned if access fails.
- **Returns:** `Any` — `self[index]` or `default`.
- **Raises:** nothing (out-of-range access is caught).
- **Description:** Get `self[index]` or `default` if the access fails.

### `first`

```python
def first(self, func: Optional[Callable[[T], bool]] = None) -> T
```

- **Parameters:** `func` (`Optional[Callable[[T], bool]]`, default `None`) — optional filter predicate; if `None`, the first item of the list is returned.
- **Returns:** `T` — first item of the (filtered) list.
- **Raises:** `IndexError` if no item is found.
- **Description:** Filter the list on `func` and return the first item.

### `first_or_default`

```python
def first_or_default(self, func: Optional[Callable[[T], bool]] = None, default: Any = None) -> Any
```

- **Parameters:** `func` (`Optional[Callable[[T], bool]]`, default `None`) — optional filter predicate; `default` (`Any`, default `None`) — returned if no item is found.
- **Returns:** `Any` — first item of the (filtered) list, or `default`.
- **Raises:** nothing.
- **Description:** Return the first matching item, or `default` if none is found.

### `last`

```python
def last(self, func: Optional[Callable[[T], bool]] = None) -> T
```

- **Parameters:** `func` (`Optional[Callable[[T], bool]]`, default `None`) — optional filter predicate; if `None`, the last item of the list is returned.
- **Returns:** `T` — last item of the (filtered) list.
- **Raises:** `IndexError` if no item is found.
- **Description:** Filter the list on `func` and return the last item.

### `last_or_default`

```python
def last_or_default(self, func: Optional[Callable[[T], bool]] = None, default: Any = None) -> Any
```

- **Parameters:** `func` (`Optional[Callable[[T], bool]]`, default `None`) — optional filter predicate; `default` (`Any`, default `None`) — returned if no item is found.
- **Returns:** `Any` — last item of the (filtered) list, or `default`.
- **Raises:** nothing.
- **Description:** Return the last matching item, or `default` if none is found.

### `to_type`

```python
def to_type(self, t: type) -> "list_ext"
```

- **Parameters:** `t` (`type`) — target type.
- **Returns:** `list_ext` — `list_ext([t(x) for x in self])`.
- **Raises:** whatever `t(x)` raises.
- **Description:** Convert every item to type `t`.

### `to_strings`

```python
def to_strings(self) -> "list_ext"
```

- **Parameters:** none.
- **Returns:** `list_ext` — all items converted to their string equivalent.
- **Raises:** whatever `str(x)` raises.
- **Description:** Convert all items to strings.

### `to_string`

```python
def to_string(self, separator: str = ", ", pre: bool = False, post: bool = False, prefix: str = "", suffix: str = "") -> str
```

- **Parameters:** `separator` (`str`, default `", "`) — separator between items; `pre` (`bool`, default `False`) — if `True`, prepend the separator (e.g. `list_ext([1, 2, 3, 4]).to_string(pre=True)` → `', 1, 2, 3, 4'`); `post` (`bool`, default `False`) — if `True`, append the separator (e.g. `list_ext([1, 2, 3, 4]).to_string(post=True)` → `'1, 2, 3, 4, '`); `prefix` (`str`, default `""`) — prepended to the result when `pre` is `False`; `suffix` (`str`, default `""`) — appended to the result when `post` is `False`.
- **Returns:** `str` — `(separator if pre else prefix) + separator.join(str items) + (separator if post else suffix)`.
- **Raises:** nothing.
- **Description:** Convert the list to a string (default separator is `", "`).

### `of_type`

```python
def of_type(self, t: type) -> "list_ext"
```

- **Parameters:** `t` (`type`) — type to match.
- **Returns:** `list_ext` — items for which `isinstance(x, t)` is true (e.g. `list_ext([True, 1]).of_type(int)` → `[True, 1]`).
- **Raises:** nothing.
- **Description:** Filter the list by type using `isinstance`.

### `to_set`

```python
def to_set(self) -> set
```

- **Parameters:** none.
- **Returns:** `set` — `set(self)`.
- **Raises:** nothing.
- **Description:** Convert the list to a set.

### `to_tuple`

```python
def to_tuple(self) -> tuple
```

- **Parameters:** none.
- **Returns:** `tuple` — `tuple(self)`.
- **Raises:** nothing.
- **Description:** Convert the list to a tuple.

### `to_dict_key`

```python
def to_dict_key(self, keys: Iterable) -> "dict_ext"
```

- **Parameters:** `keys` (`Iterable`) — iterable of dict keys; the list items become the values.
- **Returns:** `dict_ext` — `{keys[i]: self[i], ...}`.
- **Raises:** `ValueError` on length mismatch between the list and `keys`.
- **Description:** Convert to a dict using `keys` as keys and the list items as values.

### `to_dict_value`

```python
def to_dict_value(self, values: Iterable) -> "dict_ext"
```

- **Parameters:** `values` (`Iterable`) — iterable of dict values; the list items become the keys.
- **Returns:** `dict_ext` — `{self[i]: values[i], ...}`.
- **Raises:** `ValueError` on length mismatch between the list and `values`.
- **Description:** Convert to a dict using the list items as keys and `values` as values.

### `to_dict_fn`

```python
def to_dict_fn(self, key_func: Optional[Callable[[T], Any]] = None, value_func: Optional[Callable[[T], Any]] = None) -> "dict_ext"
```

- **Parameters:** `key_func` (`Optional[Callable[[T], Any]]`, default `None`) — key function; **identity is used when `None`**; `value_func` (`Optional[Callable[[T], Any]]`, default `None`) — value function; **identity is used when `None`**.
- **Returns:** `dict_ext` — `{key_func(i): value_func(i) for i in self}`.
- **Raises:** whatever `key_func`/`value_func` raise.
- **Description:** Convert to a dict using `key_func` and `value_func`.

### `all`

```python
def all(self, func: Optional[Callable[[T], bool]] = None) -> bool
```

- **Parameters:** `func` (`Optional[Callable[[T], bool]]`, default `None`) — optional predicate; if `None`, the **truthiness of the items** is used.
- **Returns:** `bool` — `True` if all items fulfill the condition.
- **Raises:** nothing.
- **Description:** Check if all items fulfill the condition.

### `any`

```python
def any(self, func: Optional[Callable[[T], bool]] = None) -> bool
```

- **Parameters:** `func` (`Optional[Callable[[T], bool]]`, default `None`) — optional predicate; if `None`, the **truthiness of the items** is used.
- **Returns:** `bool` — `True` if at least one item fulfills the condition.
- **Raises:** nothing.
- **Description:** Check if at least one item fulfills the condition.

### `contains`

```python
def contains(self, item: T) -> bool
```

- **Parameters:** `item` (`T`) — item to look for.
- **Returns:** `bool` — `item in self`.
- **Raises:** nothing.
- **Description:** Check if `item` is in the list.

### `is_empty`

```python
def is_empty(self) -> bool
```

- **Parameters:** none.
- **Returns:** `bool` — `True` if the list is empty.
- **Raises:** nothing.
- **Description:** Check if the list is empty.

### `is_single`

```python
def is_single(self) -> bool
```

- **Parameters:** none.
- **Returns:** `bool` — `True` if the list is exactly 1 item long.
- **Raises:** nothing.
- **Description:** Check if the list is 1 item long.

### `single`

```python
def single(self, func: Optional[Callable[[T], bool]] = None) -> T
```

- **Parameters:** `func` (`Optional[Callable[[T], bool]]`, default `None`) — optional filter predicate; if `None`, no filtering occurs.
- **Returns:** `T` — the unique item of the (filtered) list.
- **Raises:** `ValueError` if the (filtered) length is not exactly 1 (e.g. `"Expected exactly one item, got 2"`).
- **Description:** Return the unique item fulfilling the condition.

### `intersect`

```python
def intersect(self, l: Iterable) -> "list_ext"
```

- **Parameters:** `l` (`Iterable`) — iterable to intersect with.
- **Returns:** `list_ext` — set-based intersection `set(self) & set(l)`.
- **Raises:** nothing.
- **Description:** Return the common elements shared between the two collections (set-based).

### `union`

```python
def union(self, l: Iterable) -> "list_ext"
```

- **Parameters:** `l` (`Iterable`) — iterable to union with.
- **Returns:** `list_ext` — set-based union `set(self) | set(l)`.
- **Raises:** nothing.
- **Description:** Return a list of the set containing all items of both collections (set-based).

### `chainmap`

```python
def chainmap(self: list[dict[Any, Any]]) -> "dict_ext"
```

- **Parameters:** none (the list must contain dicts).
- **Returns:** `dict_ext` — merged dict; on overlapping keys the **first dict wins**.
- **Raises:** `TypeError` if items are not dicts.
- **Description:** Chain multiple dicts together (first dict wins on conflicts).

### `average`

```python
def average(self) -> float
```

- **Parameters:** none.
- **Returns:** `float` — the arithmetic mean of the list items.
- **Raises:** `statistics.StatisticsError` on an empty list.
- **Description:** Return the arithmetic mean of the list items.

### `max`

```python
def max(self) -> T
```

- **Parameters:** none.
- **Returns:** `T` — the largest item in the list.
- **Raises:** `ValueError` on an empty list.
- **Description:** Return the largest item in the list.

### `min`

```python
def min(self) -> T
```

- **Parameters:** none.
- **Returns:** `T` — the smallest item in the list.
- **Raises:** `ValueError` on an empty list.
- **Description:** Return the smallest item in the list.

---

## `dict_ext`

`class dict_ext(dict)` — extends the built-in `dict` with functional-style helpers mirroring `list_ext` semantics.

### `map`

```python
def map(self, func: Callable[[Any, Any], Any], cast: Any = "dict_ext") -> Any
```

- **Parameters:** `func` (`Callable[[Any, Any], Any]`) — called as `func(key, value)`; `cast` (`Any`, default `"dict_ext"`) — result container: `"dict_ext"` or the `dict_ext` class (default) → `dict_ext`; `cast=dict` → **plain `dict`**; `cast=list` → plain `list`. Both the string `"dict_ext"` and the `dict_ext` class are accepted.
- **Returns:** `dict_ext` (default), plain `dict` (`cast=dict`), or `list` (`cast=list`).
- **Raises:** `TypeError` if `func` does not return a `(key, value)` 2-tuple when casting to a dict.
- **Description:** Map `func` over the dict's `(key, value)` pairs and cast the results.

### `filter`

```python
def filter(self, func: Optional[Callable[[Any, Any], bool]] = None) -> "dict_ext"
```

- **Parameters:** `func` (`Optional[Callable[[Any, Any], bool]]`, default `None`) — predicate called as `func(key, value)`; if `None`, **all entries are kept**.
- **Returns:** `dict_ext` — filtered entries.
- **Raises:** whatever `func` raises.
- **Description:** Filter the dict on `func(key, value)`.

### `for_each`

```python
def for_each(self, func: Callable[[Any, Any], Any]) -> None
```

- **Parameters:** `func` (`Callable[[Any, Any], Any]`) — called as `func(key, value)`.
- **Returns:** `None` (side-effect only).
- **Raises:** whatever `func` raises.
- **Description:** Execute `func(key, value)` on each entry.

### `to_list`

```python
def to_list(self) -> list[list[Any]]
```

- **Parameters:** none.
- **Returns:** `list_ext` of `[key, value]` pairs.
- **Raises:** nothing.
- **Description:** Convert the dict to a `list_ext` of `[key, value]` pairs.

### `to_strings`

```python
def to_strings(self, key: bool = True, value: bool = True) -> "dict_ext"
```

- **Parameters:** `key` (`bool`, default `True`) — if `True`, convert keys to `str`; if `False`, keep keys as-is; `value` (`bool`, default `True`) — if `True`, convert values to `str`; if `False`, keep values as-is.
- **Returns:** `dict_ext` — new dict with the converted keys/values.
- **Raises:** nothing.
- **Description:** Convert keys/values to strings, controlled by the `key`/`value` flags.

### `to_string`

```python
def to_string(self, separator: str = "\n") -> str
```

- **Parameters:** `separator` (`str`, default `"\n"`) — separator between `key : value` entries.
- **Returns:** `str` — e.g. `"a : 1;b : 2"` for `separator=';'` (default separator is `"\n"`).
- **Raises:** nothing.
- **Description:** Return a string of the dict, one `key : value` per entry.

### `get_keys`

```python
def get_keys(self) -> list[Any]
```

- **Parameters:** none.
- **Returns:** `list_ext` of the dict keys.
- **Raises:** nothing.
- **Description:** Return the keys as a `list_ext`.

### `get_values`

```python
def get_values(self) -> list[Any]
```

- **Parameters:** none.
- **Returns:** `list_ext` of the dict values.
- **Raises:** nothing.
- **Description:** Return the values as a `list_ext`.

### `to_tuple`

```python
def to_tuple(self) -> Tuple[Tuple[Any, Any], ...]
```

- **Parameters:** none.
- **Returns:** `tuple` of `(key, value)` pairs.
- **Raises:** nothing.
- **Description:** Convert the dict to a tuple of `(key, value)` pairs.

### `to_named_tuple`

```python
def to_named_tuple(self) -> Tuple[KeyValueTuple, ...]
```

- **Parameters:** none.
- **Returns:** `tuple` of `KeyValueTuple` (each with `.key` and `.value`).
- **Raises:** nothing.
- **Description:** Convert the dict to a tuple of `KeyValueTuple`.

### `get_key_from_value`

```python
def get_key_from_value(self, value: Any) -> list[Any]
```

- **Parameters:** `value` (`Any`) — value to search for.
- **Returns:** `list_ext` of all keys whose value equals `value`.
- **Raises:** nothing.
- **Description:** Find all keys corresponding to the given value.

### `reduce`

```python
def reduce(self, func: Callable[[KeyValueTuple, KeyValueTuple], Tuple[Any, Any]]) -> "dict_ext"
```

- **Parameters:** `func` (`Callable[[KeyValueTuple, KeyValueTuple], Tuple[Any, Any]]`) — binary function over `KeyValueTuple` pairs returning a `(key, value)` 2-tuple.
- **Returns:** `dict_ext` — reduced dict; an **empty dict returns an empty `dict_ext`**.
- **Raises:** whatever `func` raises.
- **Description:** Reduce the dict's `(key, value)` pairs.

### `extend`

```python
def extend(self, other: dict) -> "dict_ext"
```

- **Parameters:** `other` (`dict`) — dict to merge in.
- **Returns:** `dict_ext` — new merged dict; on key conflicts **`other`'s value wins**.
- **Raises:** nothing.
- **Description:** Return a new `dict_ext` merging `other` into this one (other wins on conflicts).

### `union`

```python
def union(self, other: dict) -> "dict_ext"
```

- **Parameters:** `other` (`dict`) — dict to union with.
- **Returns:** `dict_ext` — dict union `self | other`; on key conflicts **`other`'s value wins**.
- **Raises:** nothing.
- **Description:** Return a new `dict_ext` with the entries of both dicts (other wins on conflicts).

### `inverse`

```python
def inverse(self) -> "dict_ext"
```

- **Parameters:** none.
- **Returns:** `dict_ext` — `{value: key}`.
- **Raises:** nothing.
- **Description:** Invert the dict (`{key: value}` → `{value: key}`).

### `first`

```python
def first(self, func: Optional[Callable[[Any, Any], bool]] = None) -> KeyValueTuple
```

- **Parameters:** `func` (`Optional[Callable[[Any, Any], bool]]`, default `None`) — optional predicate called as `func(key, value)`; if `None`, the first entry is returned.
- **Returns:** `KeyValueTuple` — first matching `(key, value)` pair.
- **Raises:** `IndexError` if no item is found.
- **Description:** Return the first (matching) `(key, value)` pair as a `KeyValueTuple`.

### `last`

```python
def last(self, func: Optional[Callable[[Any, Any], bool]] = None) -> KeyValueTuple
```

- **Parameters:** `func` (`Optional[Callable[[Any, Any], bool]]`, default `None`) — optional predicate called as `func(key, value)`; if `None`, the last entry is returned.
- **Returns:** `KeyValueTuple` — last matching `(key, value)` pair.
- **Raises:** `IndexError` if no item is found.
- **Description:** Return the last (matching) `(key, value)` pair as a `KeyValueTuple`.

### `all`

```python
def all(self, func: Optional[Callable[[Any, Any], bool]] = None) -> bool
```

- **Parameters:** `func` (`Optional[Callable[[Any, Any], bool]]`, default `None`) — optional predicate called as `func(key, value)`; if `None`, **values-only semantics** apply (`all(self.values())`).
- **Returns:** `bool` — `True` if all entries fulfill the condition.
- **Raises:** nothing.
- **Description:** Check if all entries fulfill the condition.

### `any`

```python
def any(self, func: Optional[Callable[[Any, Any], bool]] = None) -> bool
```

- **Parameters:** `func` (`Optional[Callable[[Any, Any], bool]]`, default `None`) — optional predicate called as `func(key, value)`; if `None`, **values-only semantics** apply (`any(self.values())`).
- **Returns:** `bool` — `True` if at least one entry fulfills the condition.
- **Raises:** nothing.
- **Description:** Check if at least one entry fulfills the condition.

---

## `KeyValueTuple`

`class KeyValueTuple(NamedTuple)` — a `(key, value)` pair as a named tuple.

- **Import path:** `from sequence_extensions import KeyValueTuple`.
- **Attributes:** `.key` (`Any`) — the key; `.value` (`Any`) — the value.
- **Returned by:** `dict_ext.first`, `dict_ext.last`, `dict_ext.reduce`, `dict_ext.to_named_tuple`.

---

## `gen_ext`

`class gen_ext` — static helper functions for working with generators and iterables.

### `to_list` *(staticmethod)*

```python
@staticmethod
def to_list(generator: Iterable[T]) -> list[T]
```

- **Parameters:** `generator` (`Iterable[T]`) — any iterable (generator, list, tuple, ...).
- **Returns:** `list[T]` — a plain `list` containing all items.
- **Raises:** nothing.
- **Description:** Convert an iterable into a plain list.

### `recursive_gen` *(staticmethod)*

```python
@staticmethod
def recursive_gen(item: T, iter_f: Callable[[T], T], stop_f: Optional[Callable[[T], bool]] = None) -> Iterator[T]
```

- **Parameters:** `item` (`T`) — the starting item (**never yielded**); `iter_f` (`Callable[[T], T]`) — maps the current item to the next item; `stop_f` (`Optional[Callable[[T], bool]]`, default `None`) — keep-going predicate on the *next* item: `True` continues, `False` stops.
- **Returns:** `Iterator[T]` — an iterator over the yielded items.
- **Raises:** nothing from the walk itself — a `StopIteration` raised by `iter_f` is **caught and stops the walk cleanly**.
- **Description:** Iteratively walk a chain of items, yielding each next item. **Warning: if `stop_f` is `None` the walk never terminates** — use `itertools.islice` or always pass a `stop_f`.

---

## `GraphFuture`

`class GraphFuture` — a small dependency-graph future. Build a graph by passing other `GraphFuture` objects as arguments; dependency arguments are replaced with their results by the time the function executes. Scheduling is event-driven (callback based) with a bounded `ThreadPoolExecutor` — no polling or scheduler loop.

### `__init__`

```python
def __init__(self, function, *args, **kwargs)
```

- **Parameters:** `function` (`Callable`) — the node's function; the keyword form `GraphFuture(function=fn, ...)` also works. `*args` / `**kwargs` — arguments for `function`; any `GraphFuture` values among them become **dependencies** (their results are substituted in before execution).
- **Returns:** nothing (constructor).
- **Raises:** nothing.
- **Description:** Create a node; `GraphFuture` values among `args`/`kwargs` become dependencies.

### `result`

```python
def result(self, timeout=None)
```

- **Parameters:** `timeout` (optional) — seconds to wait before giving up.
- **Returns:** the node's result (or the forwarded result of a chained inner graph).
- **Raises:** `TimeoutError` on timeout; on an **unbound node (no pool)** raises `TimeoutError`; the node function's exception propagates.
- **Description:** Block until the node's result is available and return it.

### `has_result`

```python
def has_result(self) -> bool
```

- **Parameters:** none.
- **Returns:** `bool` — `True` only when the node completed successfully (done, not cancelled, no exception).
- **Raises:** nothing.
- **Description:** Check whether the node has a successful result.

### `done`

```python
def done(self) -> bool
```

- **Parameters:** none.
- **Returns:** `bool` — passthrough to `self.future.done()`.
- **Raises:** nothing.
- **Description:** Check whether the node is done.

### `cancelled`

```python
def cancelled(self) -> bool
```

- **Parameters:** none.
- **Returns:** `bool` — passthrough to `self.future.cancelled()`.
- **Raises:** nothing.
- **Description:** Check whether the node was cancelled.

### `exception`

```python
def exception(self, timeout=None)
```

- **Parameters:** `timeout` (optional) — seconds to wait.
- **Returns:** the exception raised by the node's function, or `None` if it completed successfully.
- **Raises:** `TimeoutError` on timeout.
- **Description:** Return the node's exception, if any.

### `add_done_callback`

```python
def add_done_callback(self, fn) -> None
```

- **Parameters:** `fn` (`Callable`) — callback invoked with the future when it completes.
- **Returns:** `None`.
- **Raises:** nothing.
- **Description:** Attach a done callback (passthrough to `self.future.add_done_callback`).

### `set_name`

```python
def set_name(self, name) -> "GraphFuture"
```

- **Parameters:** `name` (`str`) — human-readable name for the node.
- **Returns:** `GraphFuture` — `self`, for chaining.
- **Raises:** nothing.
- **Description:** Set a human-readable name for this node.

### `__str__`

```python
def __str__(self) -> str
```

- **Parameters:** none.
- **Returns:** `str` — human-readable one-liner: `[GraphFuture] <id> <name> done=<bool> queued=<bool>`.
- **Raises:** nothing.
- **Description:** Human-readable one-liner description of the node.

### `__repr__`

```python
def __repr__(self) -> str
```

- **Parameters:** none.
- **Returns:** `str` — detailed one-liner including the node's arguments.
- **Raises:** nothing.
- **Description:** Detailed one-liner description including the node's arguments.

### Chaining

A node's `function` may return another `GraphFuture`; that inner future is chained onto the node and its result is **forwarded** as the node's result.

---

## `GraphPool`

`class GraphPool` — evaluate a `GraphFuture` graph with a bounded thread pool. Reactor-style callbacks (not polling) drive scheduling: a leaf is submitted as soon as it is reached; dependents are submitted when their dependencies complete.

### `__init__`

```python
def __init__(self, max_workers: int = 16)
```

- **Parameters:** `max_workers` (`int`, default `16`) — max worker threads; the executor is created lazily on first use.
- **Returns:** nothing (constructor).
- **Raises:** nothing.
- **Description:** Create a pool; the executor is created lazily on first use.

### `result`

```python
def result(self, gf: GraphFuture, timeout=None)
```

- **Parameters:** `gf` (`GraphFuture`) — the graph node to evaluate; `timeout` (optional) — seconds to wait.
- **Returns:** the result of `gf` (the whole reachable graph is evaluated).
- **Raises:** `ValueError("dependency cycle detected")` on cyclic graphs; `TimeoutError` on timeout; exceptions raised by node functions propagate.
- **Description:** Evaluate the graph reachable from `gf` and return its result.

### `__enter__`

```python
def __enter__(self) -> "GraphPool"
```

- **Parameters:** none.
- **Returns:** `GraphPool` — the pool itself.
- **Raises:** `RuntimeError` on re-entry (`"GraphPool.__enter__ called more than once"`).
- **Description:** Create the executor and return the pool (rejects re-entry).

### `__exit__`

```python
def __exit__(self, exc_type, exc_val, exc_tb) -> None
```

- **Parameters:** the standard context-manager exception triple.
- **Returns:** `None` (any exception from the `with` body propagates).
- **Raises:** nothing directly.
- **Description:** Cancel pending work and shut the executor down. **Unbound nodes are cancelled with `CancelledError`** — calling `result()` on them after exit raises `CancelledError`.

### Lifecycle notes

- The `with`-block form is **required for cleanup**; lazy use without `with` is safe (atexit shutdown).
- Unbound nodes (not yet evaluated) are cancelled at `__exit__`; `result()` on those raises `CancelledError` after exit.
- Re-entry (`__enter__` twice) raises `RuntimeError`.
- Cycle detection: `pool.result()` raises `ValueError("dependency cycle detected")` instead of deadlocking.
- Exceptions in a node function propagate from `pool.result()`.

---

## `workflow`

The V&V workflow layer: a small XML/Python schema of `Action` / `Sequential` / `Parallel` nodes, a named function registry, and a lazy tree-walking execution engine built on the `graph` substrate. The semantics follow the paper "Automation Nation: Taming Complex V&V Workflows" (16th International Modelica & FMI Conference, September 2025, Lucerne, Switzerland; DOI 10.3384/ecp12076741).

The layer is split into modules:

| Module | Contents |
| --- | --- |
| `workflow.schema` | `Action` / `Sequential` / `Parallel` node classes, `Template`, `parse_workflow` |
| `workflow.registry` | `FunctionRegistry`, `DEFAULT_REGISTRY`, `workflow_function`, `wants_dag` |
| `workflow.params` | parameter normalization (XML string form → Python form) |
| `workflow.engine` | `run_workflow` / `Test_Framework`, `check_splice_scope` |
| `workflow.adaptation` | `DAGHandle`, `AdaptationOp`, `ADAPTATION_BOUND` |
| `workflow.library` | the paper's library functions + `register_library` |
| `workflow.history` | `ExecutionRecord`, `RunHistory`, `replay`, `ReplayHandle` |

All names are re-exported from `sequence_extensions.workflow` (and the core node / registry / engine names from the package root).

### The engine: a lazy tree-walking interpreter

The engine does **not** pre-build a future graph. It walks the live node tree as it executes, re-reading each group's `children` list every step, so nodes spliced in at runtime by dynamic adaptation are seen immediately. Every action still runs on a pool worker thread via a `GraphFuture` leaf; a `Parallel` group wires all of its action futures at once through a single join node and waits on it with one `pool.result` call (wire-then-wait), so a group's children start concurrently — the parallelism ceiling is tree-determined, not build-time-determined.

Key behaviors:

- **Sequential** — children run in strict order; child `i + 1` depends on child `i`.
- **Parallel** — children are independent and run concurrently; the group's result is the ordered list of its children's results, and each child's result is also passed to the next sibling as its own keyword argument (fan-in).
- **Global parameters** — the root group's `.globals` are passed as default kwargs to every function; an action's own `.params` win over globals, and upstream results win over both.
- **At most once** — every action executes at most once; the engine never re-runs a function (no feedback loops).
- **Pre-validation** — before any execution, every action's function name must resolve; an unknown function raises `ValueError` naming the function.
- **Final result** — the return value of the last action in the root group's execution order (resolved recursively into groups after the run, since the tree may have been spliced).

### `run_workflow`

```python
def run_workflow(xml_source, registry=None, parameters=None, history=None)
```

- **Parameters:** `xml_source` (`str` | `bytes`) — the workflow XML (see `parse_workflow`); `registry` (`FunctionRegistry`, default `DEFAULT_REGISTRY`); `parameters` (`dict`, optional) — extra global parameters merged over the XML's globals (winning on a name clash); `history` (`RunHistory`, optional) — opt-in execution recording.
- **Returns:** the final result (the last action's return value).
- **Raises:** `ValueError` for invalid XML, an unknown function name, or an out-of-scope dynamic-adaptation splice.
- **Description:** Parse and execute a workflow XML document.

### `Test_Framework`

```python
def Test_Framework(seq, parameters=None, registry=None, history=None)
```

- **Parameters:** `seq` (`Sequential` | `Parallel`) — the root group built via the Python API; `parameters` / `registry` / `history` as in `run_workflow`.
- **Returns:** the final result.
- **Raises:** as `run_workflow`.
- **Description:** Execute a workflow built via the Python API (the paper's Listing 10).

### `check_splice_scope`

```python
def check_splice_scope(parent, index, returned)
```

- **Parameters:** `parent` (the group containing the returning action, or `None`); `index` (the action's position in `parent.children`); `returned` (the function's return value).
- **Returns:** `None`.
- **Raises:** `ValueError` when `returned` is a workflow node (or list of nodes) but the action has no next sibling, or the parent is a `Parallel` group (read-only parallel scopes). A plain (non-node) return value is always allowed.
- **Description:** Validate that a function's returned node(s) may be spliced into the workflow. A splice replaces the action's **next sibling** — a group (the paper's Listing 5) or an action (the paper's Listing 7 inner case). The splice stays within the returning action's own grouping scope.

### Return-nodes protocol (backward compatibility)

A registered function may return an `Action` / `Sequential` / `Parallel` node (or a list of them); the node(s) are spliced into the workflow in place of the action's next sibling. The replaced subtree is marked executed (its actions do not run), the spliced nodes are walked with the actor's upstream pairs, and the actor's runtime result becomes the ordered list of the spliced nodes' results. This is the legacy adaptation mechanism; it coexists with the scoped `DAGHandle` (see the adaptation contract below), but a function may use **only one** per action.

### Schema nodes

A workflow is a tree of three node types:

- `Action(function, **params)` — the smallest unit: one call to a registered function with custom keyword parameters.
- `Sequential(*children, name=None)` — children execute in strict order.
- `Parallel(*children, name=None)` — children are independent and may run concurrently.

Groups nest arbitrarily. `name` is an optional label (set from a `<scope name="...">` attribute); it does not appear in history path labels, which are derived from the group type.

### XML schema

`parse_workflow` turns the paper's XML into these nodes:

- `<VerificationWorkflow>` wraps any number of global parameter `<argument>` elements (e.g. `<argument key="model" value="./model_1"/>`), optional `<template>` definitions, and exactly **one** top-level grouping. The globals are exposed on the returned root group as the `.globals` dict.
- A bare `<sequential>` / `<parallel>` / `<scope>` root (no wrapper) is also accepted; its `.globals` is an empty dict.
- **`<scope type="sequential|parallel">`** is the explicit form of a grouping: `type` is **required** and must be `sequential` or `parallel`; an optional `name` attribute labels the group. `<sequential>` / `<parallel>` are **aliases** for `<scope type="...">` and parse exactly as before (no deprecation warnings). `<scope>` is allowed everywhere a group is allowed: as the root, as the `<VerificationWorkflow>` top-level grouping, nested inside other groups, and as a template body.
- `<action function="name">` takes custom parameters as `<argument key="name" value="..."/>` child elements (the `key` attribute carries the parameter name, so a parameter can be any name without clashing with the structural element names).
- `<template name="...">` / `<use-template name="...">` — named, parameterized subtrees (see `Template`); expansion happens at **parse time**, so the returned tree contains only `Action` / `Sequential` / `Parallel` nodes.

Invalid structure raises `ValueError` with a message naming the problem: a root element that is not `<VerificationWorkflow>` / `<sequential>` / `<parallel>` / `<scope>`, a `<scope>` missing its `type` attribute or carrying a `type` other than `sequential` / `parallel`, zero or multiple top-level groupings inside `<VerificationWorkflow>`, an unknown element name anywhere, an `<action>` without a `function` attribute, an `<argument>` without a `key` or `value` attribute, a duplicate parameter key on one action, or an `<argument>` containing child elements. Template misuse is reported the same way (see `Template`). Malformed (non-well-formed) XML is also reported as `ValueError`.

### `parse_workflow`

```python
def parse_workflow(xml_source)
```

- **Parameters:** `xml_source` (`str` | `bytes`) — the workflow XML.
- **Returns:** the root group (`Sequential` | `Parallel`).
- **Raises:** `ValueError` for any invalid structure (see above).
- **Description:** Parse a workflow XML document and return its root group.

### `Template`

`class Template` — a named, parameterized subtree: the unit of reuse between workflows.

- **`Template(name, body, **defaults)`** — `body` is the subtree to reuse (a `Sequential` / `Parallel` group, or a single `Action`, which is wrapped in a `Sequential`); `defaults` are the parameter values used when a use site does not bind them. A parameter is *declared* when it has a default or when the body references it as a `{placeholder}` inside an action parameter value.
- **`instantiate(**params)`** — returns a **new** node tree: the body with every placeholder bound. A placeholder that fills a whole value is replaced by the bound value itself (type preserved); one embedded in a longer string is replaced by its string form. Resolution is strict: every placeholder must resolve to a binding, a default or a same-named global parameter.
- **`parameters`** — the template's declared parameter names, sorted.
- **Binding precedence:** use-site binding > template default > same-named workflow global.
- **Raises:** `ValueError` for a binding that names an undeclared parameter, or a placeholder that resolves to nothing.

### `FunctionRegistry`

`class FunctionRegistry` — a name → function registry for workflow actions. Functions are called with keyword arguments only (the engine passes globals, upstream results, and the action's own parameters as kwargs).

- **`register(name, fn)`** — register `fn` under `name` (replacing any earlier registration). The function's `wants_dag` flag (whether its signature declares a `dag` parameter) is **cached here, at registration time**, so the engine never inspects a signature on the hot path. Raises `ValueError` if `name` is empty or `fn` is not callable. Emits a `UserWarning` if `name` already holds a different function (which is then replaced); re-registering the same function object is a silent no-op.
- **`get(name)`** — return the function registered under `name`. Raises `ValueError` naming the function if it is not registered.
- **`adapts(name)`** — `True` when the function registered under `name` wants a `dag` handle (i.e. its signature declares a `dag` parameter). Raises `ValueError` for an unknown name (parity with `get`).
- **`names()`** — the registered function names in registration order.
- **`function(fn=None, *, name=None)`** — a decorator that registers a function in this registry (bare form `@registry.function` or with arguments).
- **`__contains__(name)`** — `True` if `name` is a registered function name.

`DEFAULT_REGISTRY` is the default (empty) registry used by `run_workflow` / `Test_Framework` when no `registry` is given. `workflow_function(fn=None, *, name=None, registry=None)` is the module-level decorator form targeting `DEFAULT_REGISTRY` by default.

`wants_dag(fn)` — `True` when `fn`'s signature declares an explicit `dag` parameter. A bare `**kwargs` does **not** count (it would silently swallow the handle); adaptation is opt-in by naming the parameter.

### Dynamic adaptation: the scoped `DAGHandle`

A registered function may declare a `dag` parameter; the engine then injects a scoped `DAGHandle` into its call (the paper's "the full DAG is passed to each action for modification and merged back when returned", made deterministic and scoped). The handle exposes the action's **own grouping scope** and applies changes transactionally at function return.

- **Injection** — the engine passes `dag=` only when the function's signature declares it (the registry's cached `wants_dag` flag). `dag` is a **reserved kwarg name** for adapting functions: the injected handle wins over any same-named parameter (globals, upstream results, own params).
- **Reads** — served from the live tree: `following()` (the siblings after the action, and their whole subtrees — so an outer action can alter inner actions, the paper's Listing 7), `preceding()` (the siblings before the action — so an end-of-body check can copy them to the end), `following_group()` (the first following sibling, which must be a group — the declared downstream scope a driver adapts), plus `scope` (the parent group), `index` (the action's position), `read_only`, and node traversal via `.children`.
- **Writes** — `replace`, `adjust`, `copy`, `append` (and the `adjusted` shorthand) are validated **eagerly** (scope rules, read-only parallel scopes, the dynamic-node bound) and recorded as plain data (`AdaptationOp`); the engine applies them at commit time. Functions never build nodes: `dag.copy(target, **param_overrides)` clones a declared subtree with parameter overrides.
- **Commit** — at function return, on the same thread, under **one** engine-lock acquisition: the recorded ops are re-validated, applied as tree surgery, bounded, recorded on the action's `ExecutionRecord`, and the inserted nodes are marked dynamic. If the function raised, the op log is discarded — nothing is applied (atomic).

#### `DAGHandle`

```python
class DAGHandle
```

Reads:

- **`scope`** — the action's own grouping scope (its parent group).
- **`index`** — the action's position in its parent's children list.
- **`read_only`** — `True` when the handle rejects writes (a parallel-scope child).
- **`following()`** — the siblings after this action, in order (outermost first).
- **`preceding()`** — the siblings before this action, in order.
- **`following_group()`** — the first following sibling, which must be a group. Raises `ValueError` when there is no following sibling, or the first following sibling is an action.

Write ops (all raise `ValueError` on a read-only handle):

- **`replace(target, nodes)`** — replace `target` with `nodes` in the live tree at commit time. `target` must be a following sibling (or a node inside a following sibling's subtree) that has not started. The replaced subtree never runs; the replacement nodes run in its place, and their results fan in downstream keyed by their **own** action names.
- **`adjust(target, **params)`** — retune `target`'s parameters in place at commit time (existing keys overwritten, missing keys added). For a group target, the overrides apply to every action in its subtree.
- **`copy(target, **param_overrides)`** — clone `target`'s subtree with parameter overrides (applied to every `Action` in the clone). Returns the cloned node(s) — the caller then `append`s or `replace`s with them. A preceding sibling is acceptable as a **copy source** (it is only read, never replaced).
- **`adjusted(**param_overrides)`** — shorthand for `copy(following()[0], **param_overrides)`: clone the first following sibling with parameter overrides.
- **`append(nodes)`** — append `nodes` at the **end** of this action's scope at commit time (the paper's section 5 iteration workaround: each appended copy is a fresh node, so at-most-once holds and the workflow stays strictly downstream).

#### `AdaptationOp`

`class AdaptationOp` — a validated dynamic-adaptation write, recorded as plain data. Fields: `kind` (`"replace"` / `"adjust"` / `"copy"` / `"append"`), `target` (the node the op acts on; `None` for `append`), `nodes` (the replacement/inserted nodes), `params` (the parameter overrides), `scope` (the group, for `append`). `describe()` returns a plain, comparable descriptor (for history records).

#### The adaptation contract

| Aspect | Rule |
| --- | --- |
| **Injection** | `dag=` is passed only when the function's signature declares it (registry-cached `wants_dag`). `dag` is a reserved kwarg name — the injected handle wins over any same-named parameter. |
| **Read scope** | The action's own grouping scope: following siblings + their subtrees, and preceding siblings. |
| **Write targets** | Only nodes that provably have not started: later siblings when the parent scope is sequential, the subtree of a following scope, and fresh appends at the scope end. A target that already executed is rejected. |
| **Parallel scopes** | Children of a `Parallel` scope get a **read-only** handle — every write op raises `ValueError` (inside a parallel scope the sequential invariant does not hold: siblings may already be running). |
| **Commit** | Transactional at function return (one lock acquisition); if the function raised, the op log is discarded and nothing is applied. |
| **Bound** | The engine counts dynamic nodes added; exceeding `ADAPTATION_BOUND` (default **10 000**) raises a deterministic `ValueError` (a runaway adaptation terminates instead of hanging). |
| **One mechanism** | A function that declares `dag` **and** returns workflow node(s) raises `ValueError` — use either the handle or the return-nodes protocol, not both. |
| **Reserved kwarg** | `dag` is reserved for the injected handle; a bare `**kwargs` does not opt a function into adaptation. |

#### Non-Turing-completeness

The workflow schema is **not** a Turing-complete language: a workflow is a finite tree (no loops, no recursion, no conditionals, no expressions), templates expand at parse time and self-reference is rejected, and the engine enforces at-most-once per node, strictly-downstream edges, and the bounded dynamic-node count — so runs terminate and replay. The only Turing-complete component is the Python library functions (the paper's split: *complexity in the library, not the schema*); the handle adds no schema constructs, and branching and iteration live in library functions.

### The workflow library

`workflow.library` ships the paper's library functions, ready to be addressed by name from XML or the Python API. Every function is deterministic and stdlib-only, and tolerates extra keyword arguments (the engine passes globals and upstream results alongside each action's own parameters). The four adaptation drivers (`find_files`, `parameter_sweep`, `evaluate_goal`, `check_convergence`) declare a `dag` parameter: the engine injects a scoped `DAGHandle` into them, and they adapt the workflow by cloning the **declared** downstream scope (they never build nodes themselves). Their own return value (a plain file/value list, an alternative name, or a convergence summary) is what flows downstream as their result.

- **`find_files(path, pattern="*.csv", *, dag, **kwargs)`** — file discovery and dynamic-adaptation driver (paper Listing 5, objective 1). The action must be followed by the scope it adapts; the function clones that declared scope once per found file (`dag.copy(body, file=f)`) and splices the clones in place of the declared scope (`dag.replace`), so each found file gets its own copy of the declared actions. Files are processed in sorted order. Returns the list of found file paths. When no file matches, nothing is adapted and the declared scope runs once, as declared.
- **`simulate(**params)`** — a placeholder simulation that echoes its parameters: returns `{"simulate": <params>}`.
- **`evaluate_results(**params)`** — a deterministic summary of one simulation's upstream results: the item count of each upstream result, keyed by the name the engine used for it.
- **`find_test_cases(path, **kwargs)`** — discovery of the test-case files (`*.csv`) directly under `path`, as strings in sorted order (empty if none match).
- **`parameter_sweep(parameter_name=None, values=None, *, dag, **kwargs)`** — dynamic-adaptation driver (paper Listing 9, objective 1). The action must be followed by the scope it adapts; the function clones that declared scope once per sweep value (`dag.copy(body, <name>=<value>)`) and splices the clones in place of the declared scope. `values` is accepted as a comma-separated string (`"5, 10, 15"`) or a list; string items are stripped, empty items dropped, and numeric strings converted to `int` (or `float`). Returns the list of sweep values. Raises `ValueError` if `parameter_name` is not given.
- **`compare_parameter_sweep(**params)`** — a deterministic summary of a sweep's results (item count of each upstream result, keyed by name).
- **`compare_results(**params)`** — a deterministic summary of the final results (item count of each upstream result, keyed by name).
- **`evaluate_goal(upstream, field, default=None, *, dag, **kwargs)`** — branching driver (paper objective 2: adaptation to intermediate results). The action must be followed by the **alternatives scope**: a group whose children are the named alternative branches (each a **named** group — the schema's optional `name` attribute; actions have no name). The function reads `field` from the latest upstream result (the result of the action named `upstream`, or the collision-suffixed variant the engine keys it under when the name repeats) and selects the alternative whose name matches that value. The chosen alternative is moved into place of the alternatives scope (`dag.replace`), so the unselected alternatives never run. When the selected name matches no alternative, the `default` alternative (a named child) is used instead; when there is no default (or the default name matches no alternative either), a `ValueError` is raised. Returns the name of the alternative that was selected.
- **`check_convergence(upstream, field, *, dag, **kwargs)`** — iteration driver (paper objective 2; the paper's section 5 copy-to-end workaround). The action is preceded by the iteration body in its scope (the copy-to-end pattern places it at the scope end). The function reads `field` from the latest upstream result (the result of the action named `upstream`, or the collision-suffixed variant when the name repeats across iterations). When the value is converged (truthy), it returns a plain-data summary and nothing is adapted. When it is not converged, it appends a copy of the iteration body — plus a fresh copy of this check action itself — at the scope end, so the next iteration runs strictly downstream. The iteration count is unknown a priori; a runaway workflow is terminated deterministically by the engine's dynamic-node bound (`ADAPTATION_BOUND`). `upstream` should be an action that is part of the iteration body (it runs once per iteration), so the number of its results equals the iteration count. Returns `{"converged": True, "iterations": <n>}` where `<n>` is the number of times the body has run (including the current iteration).

`register_library(registry=None)` — register the library functions into a registry (default `DEFAULT_REGISTRY`), each under its own name. The call is idempotent (re-registering the same function objects is a silent no-op). Returns the registry the functions were registered into. This is the explicit opt-in path: importing `workflow.library` does not touch `DEFAULT_REGISTRY` (a fresh interpreter still sees it empty).

### Execution history and replay

`workflow.history` supplies the evidence layer: per-action records and deterministic replay. Recording is opt-in — `run_workflow` / `Test_Framework` accept a `history=` argument (default `None`); when no history is requested the engine behaves exactly as before.

- **`ExecutionRecord`** — per-action evidence: `name` (the action's registry name), `function` (the resolved callable's name), `params` (the **resolved** keyword arguments the function was actually called with — globals, upstream results and own params merged in engine precedence order), `result` (the return value; a dynamic-adaptation return is stored as a plain descriptor), `exception`, `started_at` / `ended_at` (wall-clock timestamps), `order` (deterministic completion-order index), `group_path` (the action's path in the workflow tree at call completion, e.g. `root/parallel[1]/action[0]`), `dynamic` (`True` when the action was spliced in at runtime), **`adaptations`** (the committed dynamic-adaptation ops as plain descriptors — what the function did to the DAG; empty when it adapted nothing), and **`scope`** (a snapshot of the acting action's sibling list and index, recorded at handle injection; `None` for non-adapting actions).
- **`RunHistory`** — a thread-safe, ordered collector the engine appends to as each action's function call completes, so the history captures what *actually* executed — including actions spliced in at runtime by dynamic adaptation — in true completion order. `final_order` is set by the engine after a successful run to the `order` of the workflow's final action (the value `replay` returns).
- **`replay(history, registry=None)`** — replay a recorded run and return the same final result: it re-executes the recorded actions (see `replay_records`) and returns the replayed value of the run's final action. Returns `None` for an empty workflow. This proves reproducibility: the result is recomputed by re-running the recorded function calls, not echoed from the history.
- **`replay_records(history, registry=None)`** — re-execute every recorded action strictly sequentially, in recorded (completion) order, and return the replayed values (positionally aligned with `history.records`). A recorded failure re-raises at the same point in the sequence.
- **`ReplayHandle`** — a read-only, no-op stand-in for `DAGHandle` in replay. When a recorded run's function declared a `dag` parameter, replay re-invokes it with the recorded `dag` kwarg **stripped** and a `ReplayHandle` re-injected: reads (`following` / `preceding` / `following_group` and node traversal) are served from a **fake tree** materialized from the record's `scope` snapshot, write ops (`replace` / `adjust` / `append`) are **no-ops** (recorded nowhere, applied nowhere), and clone ops (`copy` / `adjusted`) are functional (they clone the materialized fake target). Replaying an adapting run is therefore deterministic and never mutates the live tree.
- **`recordable_result(value)`** — normalize a function return value for storage in a record: a dynamic-adaptation return (a workflow node, or a non-empty list/tuple of them) becomes a plain, comparable descriptor; any other value is returned unchanged.
- **`resolve_group_path(root, node)`** — return `node`'s path in the workflow tree rooted at `root` (e.g. `root/parallel[1]/action[0]`); `root` for the root itself, `""` when not in the tree.
