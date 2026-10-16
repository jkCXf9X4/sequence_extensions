# sequence_extensions API Reference

Hand-written API reference for the `sequence_extensions` package — higher-order function extensions for sequences (lists, dicts, generators) plus a small dependency-graph future and a V&V workflow layer.

> **Version:** this document describes **version 0.2.0** (Python >= 3.9).

## Package layout

```
sequence_extensions/
├── ext/        # list_ext / dict_ext / gen_ext (functional sequence helpers)
├── graph/      # the execution substrate
│   └── graph_future.py # GraphFuture / GraphPool
└── flow/       # the mini flow engine
    ├── task.py       # @task (retries, backoff, timeout), TaskTimeoutError
    ├── flow.py       # @flow (run identity, pool, run log wiring)
    ├── runlog.py     # RunLog JSON-lines writer, reading toolkit, jsonable
    └── _context.py   # RunContext + current-run ContextVar plumbing
```

`ext` and `graph` names are re-exported from the package root; `flow` is imported as its own package (`from sequence_extensions.flow import task, flow`).

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
)

from sequence_extensions.flow import (
    task,
    flow,
    RunLog,
    DIFF_EXCLUDE,
    RunContext,
    TaskFunction,
    TaskTimeoutError,
    ProcessGraphPool,
    ProcessDispatchError,
    jsonable,
    current_run,
)

__version__ = "1.2.0"
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
| `task` | Decorator: retry, backoff, and timeout policy around a function |
| `flow` | Decorator: run identity, pool, and audit log around a function |
| `RunLog` | JSON-lines run-log writer and reader (`records`, `filter`, `summarize`, `diff`) |
| `DIFF_EXCLUDE` | Fields `RunLog.diff` drops by default: order, run identity, wall-clock, worker |
| `TaskTimeoutError` | `TimeoutError` carrying `task`, `timeout`, `attempt` |
| `ProcessGraphPool` | `GraphPool` subclass with worker processes (CPU-bound tasks) |
| `ProcessDispatchError` | A payload could not be dispatched to a worker process |
| `__version__` | `"1.2.0"` |

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

### `bind`

```python
def bind(self, gf: GraphFuture) -> None
```

- **Parameters:** `gf` (`GraphFuture`) — the graph node to bind.
- **Returns:** nothing.
- **Raises:** `ValueError("dependency cycle detected")` on cyclic graphs.
- **Description:** Bind the graph reachable from `gf` without touching any result: submit every ready leaf, wire the rest for event-driven scheduling. A **pure bind** — unlike `result(gf, timeout=0)`, it never raises a settled node's own exception. This is the call `task.submit()` uses.

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
- **Description:** Cancel **this pool's** pending nodes, then shut the executor down. Cancellation is pool-scoped: nodes bound to other pools (e.g. a concurrent flow's pool in the same process) are untouched.

### Lifecycle notes

- The `with`-block form is **required for cleanup**; lazy use without `with` is safe (atexit shutdown).
- Exit cancels the pool's **own** pending nodes (`result()` on those raises `CancelledError`); nodes bound to other pools survive. A node never bound to any pool is left pending — bind nodes through `pool.result()` / `pool.bind()`.
- Re-entry (`__enter__` twice) raises `RuntimeError`.
- Cycle detection: `pool.result()` and `pool.bind()` raise `ValueError("dependency cycle detected")` instead of deadlocking.
- Exceptions in a node function propagate from `pool.result()`.

---

## `ProcessGraphPool`

`class ProcessGraphPool(GraphPool)` — evaluate a `GraphFuture` graph with a bounded **process** pool: same `bind` / `result` / context-manager surface as `GraphPool`, workers are processes. The fix for CPU-bound task bodies, which the GIL serializes under a thread pool.

```python
from sequence_extensions.flow import ProcessGraphPool, flow


@flow(pool=ProcessGraphPool(max_workers=4), log="runs")
def campaign(items):
    futures = [cpu_heavy.submit(i) for i in items]  # runs in worker processes
    return [f.result() for f in futures]
```

- **`__init__(max_workers=UNSET)`** — worker process count; `UNSET` (the default) resolves to the active configuration's `[pool] process_max_workers` — `None` without a config, the executor's own default (the CPU count). Construct after `configure()` or pass `max_workers` explicitly (resolution is at construction time).
- **Picklable payloads:** tasks and arguments must survive `pickle` — module-level functions and plain data. `@task`-decorated module-level functions pickle (the raw function is aliased under a private module name at decoration). A lambda, a closure, or an unpicklable argument fails at dispatch: the node settles with `ProcessDispatchError` and the run log records `skipped` / `dispatch failed`.
- **Run-log records replay in the parent:** a worker cannot write the flow's open log file, so the worker buffers its attempt records and the flow writes them before `run_end` — the log is still complete the moment the flow returns.
- **Dependencies resolve in the parent:** a failed dependency skips the dependent without a process round-trip (same `skipped` record as thread mode).
- **Limits:** a task returning a `GraphFuture` (graph chaining) works in thread mode only; `task.submit()` inside a process worker is unsupported (the worker has no pool); a timed-out attempt is abandoned as a daemon thread *in the worker process*; errors must be picklable to cross the boundary.
- Under the default *fork* start method (Linux), function closures defined at call time also pickle; under *spawn* (Windows, macOS default), module-level tasks only.

---

## `flow`

The mini flow engine — parallel, deterministic, audited — built on the `graph` substrate. A task is a function; a flow is a function; a future passed as an argument is a dependency edge. Every run writes one JSON-lines audit log — the executed truth of the run.

### `@task` — policy around a function

```python
from sequence_extensions.flow import task


@task(retries=2, retry_delay_seconds=0.1, timeout=30.0, name="simulate")
def simulate(case): ...
```

| Keyword | Default | Meaning |
| --- | --- | --- |
| `retries` | `0` | extra attempts after a failed one (`retries=2` means up to 3 attempts) |
| `retry_delay_seconds` | `0.0` | backoff sleep between attempts; the task holds its pool worker through it |
| `timeout` | `None` | wall budget for ONE attempt, in seconds |
| `name` | function name | task name in the run log |

- **Defaults are configurable**: an omitted keyword resolves per call — explicit keyword > active config (`[task]` in a `Config`, see [Configuration](#configuration)) > built-in default. Resolution happens at call time, so `configure()` in `main()` reaches module-level tasks.

- **Plain call** — runs inline in the caller's thread (sequential): `simulate(case)`.
- **`.submit(...)`** — schedules on the current run's pool, returns a `GraphFuture`; requires an active `@flow` (raises `RuntimeError` otherwise).
- Futures may be passed as submit arguments (positional or keyword); they resolve to their results before the body runs. Any DAG shape, diamonds included; a cycle raises `ValueError("dependency cycle detected")` at submit time.
- Exhausted retries raise the last attempt's exception. A timeout raises `TaskTimeoutError` (a `TimeoutError` subclass) carrying `.task`, `.timeout`, `.attempt`.
- Timeout mechanics: the attempt runs in its own thread joined with the budget. Python threads cannot be preempted — a timed-out attempt thread is abandoned as a daemon and its eventual result discarded. Prefer a task-level `timeout` plus your own subprocess timeout (see the recipe below).
- A `BaseException` from a task body (e.g. `SystemExit`) is wrapped to `RuntimeError` — the node must settle.
- Every attempt — success, failure, or timeout — is one record in the run log.

### `@flow` — run identity, pool, audit log

```python
from sequence_extensions.flow import flow


@flow(name="campaign", max_workers=16, log="runs", summary=False, pool=None)
def campaign(cases_dir): ...
```

| Keyword | Default | Meaning |
| --- | --- | --- |
| `name` | function name | flow name; prefixes the `run_id` |
| `max_workers` | `16` | thread pool size for the run's `submit()` calls |
| `log` | `"runs"` | directory for `<run_id>.jsonl`; `None` disables the file |
| `summary` | `False` | log item counts for long containers instead of items |
| `pool` | `None` | a caller-owned pool — a `GraphPool` (threads) or a `ProcessGraphPool` (processes); never settled by the flow |

- **Defaults are configurable**: `max_workers`, `log`, and `summary` left unset resolve per call — explicit keyword > active config (`[flow]`, see [Configuration](#configuration)) > built-in default.
- The wrapper carries `__flow__` (the flow name — how `flow-runner` discovers it) and `last_run` (a dict with `run_id`, `status`, `log`, `duration_ms` of the most recent call; concurrent calls race, last writer wins).


- The body is ordinary Python: plain calls are sequential, `.submit()` calls are concurrent.
- **Drain-on-return** — the flow returns only after every submitted task has settled, so the log is complete on return.
- **Failure** — a failed flow cancels its own pool's pending tasks (each recorded `skipped`), waits for running ones, records `run_end` with `status: "error"`, and re-raises.
- A caller-owned pool is never settled: success and failure both drain; the owner owns the lifecycle.
- `run_id` format: `<flow>-<UTC timestamp>-<short uuid>`.
- **Concurrent flows are safe in one process**: pool exit cancels only that pool's own nodes, so two flows — each on its own pool — can run side by side.
- Nested flows work: an inner `@flow` gets its own run, pool, and log.
- On a `ProcessGraphPool`, settle-time records (replayed worker records, skip records) are written by the flow before `run_end`; an unpicklable payload settles its node with `ProcessDispatchError` and records `skipped` / `dispatch failed`.

### Configuration

Every engine parameter can live outside the code, in a TOML file loaded into a `Config` and installed with `configure`. Resolution is per call and keyword-first: **explicit decorator keyword > active config > built-in default**.

```python
from sequence_extensions.flow import Config, configure, flow, task

configure(Config.from_toml("config.toml"))


@task  # retries / retry_delay_seconds / timeout from [task]
@flow  # max_workers / log / summary from [flow]
def campaign(cases_dir): ...
```

```toml
# config.toml — every section and key is optional
[flow]
max_workers = 8            # default 16
log = "output/runs"        # default "runs"; "" disables run logging
summary = true             # default false

[task]
retries = 2                # default 0
retry_delay_seconds = 0.5  # default 0.0
timeout = 30.0             # default: omit (no timeout)

[pool]
process_max_workers = 4    # ProcessGraphPool() default; omit → CPU count

[run]                      # flow-runner selection (unused by configure)
module = "mypackage.flows"
flow = "campaign"

[inputs]                   # keyword arguments for the flow
items = [1, 2, 3]
```

**`Config.from_toml(path)`** — parse and validate a TOML file. **`Config.from_dict(data, where=...)`** — build from a mapping (code, tests); `where` prefixes error messages. Both are strict: unknown sections and keys are errors (typo-proof), values are type-checked, ranges follow the same rules as the decorators. Every `Config` constructor validates — build one directly and bad values fail at construction. `log = ""` is the TOML spelling of "disabled" (TOML has no `null`) and normalizes to `None`; an omitted key keeps the built-in default.

**`configure(config)`** — install `config` as the active configuration for the calling context; returns a reset token. **`reset_config(token)`** — restore. **`active_config()`** — read. **`use_config(config)`** — context manager: run a block under a configuration.

Resolution mechanics worth knowing:

- **Call time, not import time**: `configure()` in `main()` reaches module-level decorators regardless of import order.
- **Threads**: the flow layer restores the active configuration in pool workers and timeout attempt threads around task bodies, so nested direct calls and `active_config()` reads see the submitting context.
- **Processes**: `submit()` resolves the task policy in the submitting thread and ships concrete values across the boundary — worker processes never need the config.
- **Pools constructed directly**: a bare `ProcessGraphPool()` resolves at construction time — construct it after `configure()`, or pass `max_workers` explicitly. The thread substrate stays config-free: `GraphPool` keeps its fixed default (16) and `@flow` sizes its own pool from `[flow] max_workers`.
- **Determinism**: config values never enter run-log records; a run without `configure()` behaves exactly as before.

### `flow-runner` — run a flow from the command line

```text
flow-runner config.toml                # run the configured flow
flow-runner config.toml --flow report  # override the selection
flow-runner config.toml --list         # flows in the module, with docstrings
python -m sequence_extensions.flow_runner config.toml   # same thing
```

The runner loads and validates the whole config first, installs it as the active configuration, imports `[run] module`, scans it for the `__flow__` marker (no registry, no registration call), validates `[inputs]` against the flow's signature, and calls the flow with them as keyword arguments. It then prints the status, duration, log path, and result:

```text
$ flow-runner campaign.toml
flow campaign: ok (1843 ms)
log: runs/campaign-20261016T110258-b0e4a12e.jsonl
result: {"count": 6, "mean_score": 0.71, "passed": 6, "all_passed": true}
```

- **Exit codes**: `0` run succeeded, `1` the flow raised, `2` usage or config error (missing file, invalid TOML, unknown key, no flow selected, inputs that do not match the signature).
- **Inputs** are TOML values passed as keyword arguments — recorded in `run_start` by the existing serialization policy. Flows needing non-TOML inputs (open connections, custom objects) belong in a small `main.py` that calls them directly.
- A config file names a module to import: treat it as trusted code.

### The run log — the executed truth

One JSON-lines file per run (default `runs/<run_id>.jsonl`), written while things happen. Every record gets `seq` (per-run monotonic) and `schema`.

Record kinds:

| Record | Fields |
| --- | --- |
| `run_start` | `run_id`, `flow`, `started`, `version`, `args`, `kwargs` |
| `task` | `run_id`, `task`, `attempt`, `status`, `args`, `kwargs`, `start`, `end`, `duration_ms`, `worker`, plus `result` (ok) or `error` |
| `run_end` | `run_id`, `status`, `ended`, `duration_ms`, plus `result` (ok) or `error` |

- Task `status`: `ok` (attempt succeeded), `error`, `timeout`, or `skipped` (`attempt: 0` — the node never executed: a dependency failed, the payload could not be dispatched to a process (`reason: "dispatch failed"`), or the flow failed and cancelled it).
- Serialization policy (`jsonable`): paths log as `{"path": ..., "sha256": ...}` (hashed when the file exists); `bytes` as length plus sha256; datetimes as ISO 8601; sets as sorted lists; unknown values as `str(value)`. Bulky payloads return a `Path` by convention — never inlined.
- `summary=True` replaces containers longer than 8 items with `{"type": ..., "len": ...}`.

Reading a log back:

```python
from sequence_extensions.flow import RunLog

for record in RunLog.records("runs/campaign-20261013T101500-1a2b3c4d.jsonl"):
    print(record["seq"], record.get("task"), record["status"])
```

#### Reading toolkit — filter, summarize, diff

All three accept a log path or a record list; `records` itself is unchanged.

```python
from sequence_extensions.flow import RunLog

path = "runs/campaign-20261013T101500-1a2b3c4d.jsonl"

RunLog.filter(path, task="simulate", status="error")  # selection
RunLog.summarize(path)  # compact account
RunLog.diff(path, "runs/campaign-20261013T111500-2b3c4d5e.jsonl")  # determinism
```

**`filter(records, *, record=None, task=None, status=None, attempt=None)`** — records matching every given field (`None` = no constraint). `record` selects the kind (`"run_start"` / `"task"` / `"run_end"`); a record without a constrained field never matches. Input order preserved.

**`summarize(records)`** — the compact account, one jsonable dict: run level `flow`, `run_id`, and `status` (the verdict; absent when the log has no `run_end` — an interrupted run), plus one entry per task in first-appearance order — `attempts` (executions; a skip is not an attempt), `statuses` in record order, the last recorded `status`, and `duration_ms` summed over executions.

**`diff(left, right, *, exclude=DIFF_EXCLUDE)`** — the semantic comparison of two runs, the determinism check. Records are identified by *what ran* — task, inputs, attempt number (run records by kind) — never by record position, so a fan-out compares case by case. Fields dropped before comparing, by default (`DIFF_EXCLUDE`):

| Dropped | Why |
| --- | --- |
| `seq` | completion order is wall-clock, not execution |
| `run_id` | the run's own identity |
| `start`, `end`, `started`, `ended`, `duration_ms` | wall time is not a determinism claim |
| `worker` | which thread or process happened to run it |

A future argument's `done` snapshot (`{"node": ..., "done": ...}`) is ignored for the same reason. Duplicate identities: the last record wins. The report is jsonable and stably ordered:

```python
{"equal": False,
 "only_left":  [{"record": "task", "task": "simulate", "attempt": 2,
                 "args": ["cases/a.csv"], "kwargs": {}}],
 "only_right": [],
 "changed":   [{"record": "task", "task": "simulate", "attempt": 1,
                 "args": ["cases/a.csv"], "kwargs": {},
                 "fields": {"status": {"left": "error", "right": "ok"}, ...}}]}
```

Pass `exclude=` a replacement set to compare more or less — e.g. `DIFF_EXCLUDE - {"duration_ms"}` to make durations count.

### Example campaign

```python
from pathlib import Path

from sequence_extensions.flow import flow, task


@task(retries=2, retry_delay_seconds=0.1, timeout=60.0)
def simulate(case: Path) -> dict: ...


@task
def evaluate(sim: dict, tolerance: float) -> dict: ...


def aggregate(evaluations: list) -> dict:
    return {
        "count": len(evaluations),
        "mean_score": sum(e["score"] for e in evaluations) / len(evaluations),
        "passed": sum(1 for e in evaluations if e["passed"]),
        "all_passed": all(e["passed"] for e in evaluations),
    }


@flow
def campaign(cases_dir: Path, tolerance: float = 0.5) -> dict:
    cases = sorted(cases_dir.glob("*.csv"))  # plain call: sequential
    sims = [simulate.submit(c) for c in cases]  # concurrent map
    evals = [evaluate.submit(s, tolerance) for s in sims]  # futures = edges
    return aggregate([e.result() for e in evals])  # gather
```

---

## Wrapping an external simulator (recipe)

The engine is deliberately stdlib-only: no subprocess helpers, no FMI bindings, no HPC client. A real `simulate` (an FMI co-simulation, a Modelica tool, a command-line solver) is yours to write. This is the canonical pattern — a **recipe, not a dependency**.

1. **Run the tool with `subprocess.run` and a `timeout`.** The tool is a black box; its contract is the command line, the exit code, and the files it writes. `subprocess.run(..., timeout=...)` kills a hung tool at the process level — the layer a task `timeout=` cannot reach.
2. **Map a non-zero exit to an exception.** Raise `RuntimeError`; the task fails, the run log records it, and `retries=` / the flow's failure handling take over.
3. **Return a `Path`, not the payload.** The run log serializes it as path plus sha256; downstream tasks receive the path by value.
4. **Stay deterministic.** Same inputs, same command line, same output bytes — the log then proves it.

```python
import subprocess
from pathlib import Path

from sequence_extensions.flow import flow, task


@task(retries=2, retry_delay_seconds=5.0, timeout=330.0)
def simulate(model: str, stop_time: float, out_dir: Path) -> Path:
    """Run the external solver; returns the result file path."""
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = ["solver", "--model", model, "--stop-time", repr(stop_time), "--out", str(out_dir)]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300.0)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"solver timed out after {exc.timeout}s") from exc
    if proc.returncode != 0:
        raise RuntimeError(f"solver exited {proc.returncode}: {proc.stderr.strip()}")
    return out_dir / "result.csv"


@flow(log="runs")
def campaign(model: str, stop_times: list, workdir: Path) -> list:
    futures = [
        simulate.submit(model, stop_time, workdir / f"case_{i}")
        for i, stop_time in enumerate(stop_times)
    ]
    return [f.result() for f in futures]
```

Use both timeouts: the subprocess timeout kills the tool; the task `timeout=` is the campaign-level backstop (it abandons the attempt and retries — see the mechanics above).

### HPC (SLURM) variant

The batch scheduler is the orchestrator; the engine's job is to speak it. The same recipe with `sbatch` in place of a direct run:

```python
@task(retries=2, timeout=7200.0)
def submit_job(script: Path) -> str:
    proc = subprocess.run(
        ["sbatch", "--parsable", str(script)], capture_output=True, text=True, timeout=60
    )
    if proc.returncode != 0:
        raise RuntimeError(f"sbatch failed: {proc.stderr.strip()}")
    return proc.stdout.strip()  # job id


@task(retries=1000, retry_delay_seconds=60.0)
def wait_for_job(job_id: str) -> str:
    proc = subprocess.run(
        ["sacct", "-j", job_id, "--format=State", "--noheader"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    state = proc.stdout.split()[-1] if proc.stdout.strip() else "PENDING"
    if state in ("COMPLETED",):
        return state
    if state in ("FAILED", "CANCELLED", "TIMEOUT", "OUT_OF_MEMORY"):
        raise RuntimeError(f"slurm job {job_id} ended {state}")
    raise RuntimeError(f"job {job_id} still {state}")  # retried until done
```

A polling task with `retries` large and `retry_delay_seconds` matching the poll interval is one line of policy — no scheduler adapter in the engine.
