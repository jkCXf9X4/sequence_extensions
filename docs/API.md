# sequence_extensions API Reference

Hand-written API reference for the `sequence_extensions` package — higher-order function extensions for sequences (lists, dicts, generators) plus a small dependency-graph future and a parallel, deterministic, audited flow engine.

> **Version:** this document describes **version 3.0.0** (Python >= 3.11).

## Package layout

```
sequence_extensions/
├── ext/        # list_ext / dict_ext / gen_ext (functional sequence helpers)
├── graph/      # the execution substrate
│   └── graph_future.py # GraphFuture / GraphPool
└── flow/       # the mini flow engine
    ├── node.py       # @node (retries, backoff, timeout), NodeTimeoutError
    ├── run.py        # execute_flow, Run, RunOptions wiring
    ├── _options.py   # NodePolicy, RunOptions, UNSET, validation
    ├── runlog.py     # RunLog JSON-lines writer, reading toolkit, jsonable
    ├── process_pool.py # ProcessGraphPool, ProcessDispatchError
    └── _context.py   # RunContext + path/attempt/worker ContextVars
```

`ext` and `graph` names are re-exported from the package root; `flow` is imported as its own package (`from sequence_extensions.flow import node, execute_flow`).

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
    node,
    execute_flow,
    gather,
    Run,
    RunOptions,
    NodePolicy,
    NodeFunction,
    FlowFuture,
    FlowOutcome,
    NodeTimeoutError,
    RunLog,
    DIFF_EXCLUDE,
    SCHEMA_VERSION,
    RunContext,
    ProcessGraphPool,
    ProcessDispatchError,
    DEFAULT_LOG_DIR,
    DEFAULT_MAX_WORKERS,
    UNSET,
    jsonable,
    validate_node_policy,
    current_run,
)

__version__ = "3.0.0"
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
| `node` | Decorator: retry, backoff, and timeout policy around a function; `.submit()` |
| `gather` | One future resolving to the results of several futures, in order |
| `execute_flow` | Open a top-level run around a root node and return a `Run` |
| `Run` | One run's account: result, identity, status, log, duration, error |
| `RunOptions` | Per-run options (pool, log, summary, fixed clock, retries, node defaults) |
| `NodePolicy` | Default retry/backoff/timeout for nodes that left a value unset |
| `NodeFunction` | The object `@node` returns: callable inline, plus `.submit()` |
| `FlowFuture` | A submitted node's future (`.result()` is rejected on an incomplete future in a worker) |
| `FlowOutcome` | A deferred direct-call outcome; a worker-side call returns one when it cannot wait |
| `UNSET` | Sentinel for an unspecified `RunOptions` / `NodePolicy` field |
| `DEFAULT_MAX_WORKERS` / `DEFAULT_LOG_DIR` | Built-in run defaults (`16`, `"runs"`) |
| `validate_node_policy` | Validate explicit retry/backoff/timeout values |
| `RunLog` | JSON-lines run-log writer and reader (`records`, `filter`, `summarize`, `diff`) |
| `DIFF_EXCLUDE` | Fields `RunLog.diff` drops by default: order, run identity, wall-clock, worker |
| `NodeTimeoutError` | `TimeoutError` carrying `node`, `timeout`, `attempt` |
| `ProcessGraphPool` | `GraphPool` subclass with worker processes (CPU-bound tasks) |
| `ProcessDispatchError` | A payload could not be dispatched to a worker process |
| `__version__` | `"3.0.0"` |

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

`class GraphFuture` — a small dependency-graph future. Build a graph by passing other `GraphFuture` objects (or plain `concurrent.futures.Future` values) as arguments; dependency arguments are replaced with their results by the time the function executes. Scheduling is event-driven (callback based) with a bounded `ThreadPoolExecutor` — no polling or scheduler loop.

### `__init__`

```python
def __init__(self, *args, **kwargs)
```

- **Parameters:** the function is normally the first positional argument. The keyword form `GraphFuture(function=fn, args=(...))` is also accepted. `*args` / `**kwargs` are arguments for `function`; any `GraphFuture` or `concurrent.futures.Future` values among them become **dependencies** (their results are substituted in before execution). When a positional function is present, a keyword named `function` or `args` is an ordinary node argument, not a constructor keyword.
- **Returns:** nothing (constructor).
- **Raises:** `TypeError` when no function is supplied.
- **Description:** Create a node; `GraphFuture` values among the arguments become dependencies.

### `result`

```python
def result(self, timeout=None)
```

- **Parameters:** `timeout` (optional) — seconds to wait before giving up.
- **Returns:** the node's result (or the forwarded result of a chained inner graph).
- **Raises:** `TimeoutError` on `timeout` expiry; an **unbound node (no pool)** blocks forever unless a `timeout` is given; the node function's exception propagates.
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

A node's `function` may return another `GraphFuture` or a plain `concurrent.futures.Future`; that inner future is chained onto the node and its result is **forwarded** as the node's result, without holding the worker.

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
- **Description:** Bind the graph reachable from `gf` without touching any result: submit every ready leaf, wire the rest for event-driven scheduling. A **pure bind** — unlike `result(gf, timeout=0)`, it never raises a settled node's own exception. This is the call `node.submit()` uses.

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

`class ProcessGraphPool(GraphPool)` — evaluate a `GraphFuture` graph with a bounded **process** pool: same `bind` / `result` / context-manager surface as `GraphPool`, workers are processes. The fix for CPU-bound node bodies, which the GIL serializes under a thread pool.

```python
from sequence_extensions.flow import ProcessGraphPool, RunOptions, execute_flow, gather, node

items = range(8)


@node
def cpu_heavy(i):
    return sum(n * n for n in range(i))


@node
def campaign(items):
    futures = [cpu_heavy.submit(i) for i in items]  # dispatched to worker processes
    return gather(futures)                          # no .result() wait


with ProcessGraphPool(max_workers=4) as pool:
    run = execute_flow(campaign, items, options=RunOptions(pool=pool, log="runs"))
```

The root node body runs on the driver (the parent process); that is where
process-mode fan-out is built. A body already running inside a process
worker cannot submit or return a live future.

- **`__init__(max_workers=None)`** — worker process count; `None` keeps the executor's own default (the CPU count).
- **Picklable payloads:** nodes and arguments must survive `pickle` — module-level functions and plain data. `@node`-decorated module-level functions pickle (the raw function is aliased under a private module name at decoration). A lambda, a closure, or an unpicklable argument fails at dispatch: the node settles with `ProcessDispatchError` and the run log records `skipped` / `dispatch failed`.
- **Run-log records replay in the parent:** a worker cannot write the run's open log file, so the worker buffers its attempt records and the run writes them before `run_end` — the log is still complete the moment the run returns.
- **Dependencies resolve in the parent:** a failed dependency skips the dependent without a process round-trip (same `skipped` record as thread mode).
- **Node defaults follow direct calls:** a node called directly inside a process worker still resolves unset policy from `RunOptions.node_defaults`; only `.submit()` and returning a live future are process-worker restrictions.
- **Limits:** a node body running in a *process worker* cannot submit or return a live future (the worker has no pool); the root body runs on the driver, so a future it returns is bound in the parent and process-mode fan-out is built there. `execute_flow` inside a process worker is rejected in 3.0; a timed-out attempt is abandoned as a daemon thread *in the worker process*; errors must be picklable to cross the boundary.
- Under the default *fork* start method (Linux), function closures defined at call time also pickle; under *spawn* (Windows, macOS default), module-level nodes only.

---

## `flow`

The engine has one composable primitive and one explicit run boundary.

```python
from pathlib import Path

from sequence_extensions.flow import NodePolicy, RunOptions, execute_flow, gather, node

@node(retries=2, retry_delay_seconds=0.1, timeout=60.0)
def simulate(case): ...

@node
def evaluate(sim, tolerance): ...

@node
def merge(evaluations):
    return {"count": len(evaluations)}

@node
def campaign(cases_dir):
    cases = sorted(cases_dir.glob("*.csv"))
    sims = [simulate.submit(c) for c in cases]
    return merge.submit(gather([evaluate.submit(s, 0.5) for s in sims]))

run = execute_flow(campaign, Path("cases"), options=RunOptions(max_workers=8, log="runs"))
run.result, run.run_id, run.status, run.log, run.duration_ms
```

### `@node` — policy around a function

```python
@node(retries=2, retry_delay_seconds=0.5, timeout=30.0, name="simulate")
def simulate(case): ...
```

| Keyword | Default | Meaning |
| --- | --- | --- |
| `retries` | `0` | additional attempts after a failed one (`2` means up to 3). |
| `retry_delay_seconds` | `0.0` | backoff delay between attempts (a timer; no worker is held). |
| `timeout` | `None` | wall budget for ONE attempt; the body runs in its own thread and a returned future gets the remaining budget as a timer; raises `NodeTimeoutError`. |
| `name` | function name | node name used in the run id, records, and discovery. |

- `@node` returns a `NodeFunction`: still callable, and additionally `.submit(...)` schedules on the current run's pool and returns a `FlowFuture`.
- A direct call runs inline in the caller's thread. On the driver it returns the body's value (waiting for a returned future if needed); inside a pool worker an unsettled call returns a `FlowOutcome` that the caller must return rather than block on.
- Futures passed as arguments become dependency edges; plain `concurrent.futures.Future` values are dependencies too. Cycles raise at submit time.
- `.submit()` is legal in the driver and in a pool worker. A worker does not block: it returns a future and frees the worker.
- A node may return a value or a future. A returned future (`submit()` or `gather(...)`) is awaited by that node's attempt; the worker is freed. `.result()` on an incomplete future inside a pool worker raises `RuntimeError` with guidance instead of deadlocking.
- `gather(futures)` returns one future resolving to the results in order. It accepts an iterable, a single future, or empty input (`[]`). Return it from a node or pass it as a dependency (`merge.submit(gather(evals))`). A node should not return a list/dict containing futures; wrap it with `gather`.
- A node body that calls/submits other nodes is a composite; there is no separate decorator and no separate run. Nested nodes share the run's pool and log; `path` and `parent_attempt` record the tree, and the composite's `retries`/`timeout` apply to the returned future as a whole — a retry re-runs the body (hence its subtree) with a new `parent_attempt`.
- A `BaseException` (`SystemExit`, `KeyboardInterrupt`) from a node body is recorded and re-raised wrapped in `RuntimeError`.
- Unset keywords resolve from the active run's `RunOptions.node_defaults`, then the built-in default; an explicit keyword always wins.

### `execute_flow` — the run boundary

```python
run = execute_flow(node, *args, options=RunOptions(...), **kwargs)
```

| `RunOptions` field | Default | Meaning |
| --- | --- | --- |
| `name` | root node name | run name; prefixes the run id and `run_start.node`. |
| `max_workers` | `16` | thread pool size for the run's `submit()` calls. |
| `log` | `"runs"` | directory for `<run_id>.jsonl`; `None` disables the file. |
| `summary` | `False` | log item counts for long containers instead of items. |
| `fixed_clock` | `False` | reference mode: byte-identical logs for identical runs. |
| `pool` | `None` | a caller-owned pool (`GraphPool` / `ProcessGraphPool`); never settled by the run. |
| `retries` | `0` | run-level retries; one run file per attempt, each with its own id. |
| `retry_delay_seconds` | `0.0` | backoff between run attempts. |
| `timeout` | `None` | wall budget for the whole attempt; on expiry the pool is cancelled and `run_end` records `timeout`. |
| `node_defaults` | `None` | `NodePolicy` for nodes whose decorator left a value unset. |

- Returns a `Run`: `result`, `run_id`, `node`, `status` (`ok` / `error` / `timeout`), `log`, `duration_ms`, `attempt`, `started`, `ended`, `error`.
- On failure `execute_flow` raises the node's exception with `.run` attached (the last attempt's account).
- `options` is a reserved keyword; pass a node parameter with that name positionally.
- `execute_flow` is a top-level entry point. Calling it inside an active run raises `RuntimeError`; a node composes nodes directly or by returning their futures. Its first argument must be a `@node` (`NodeFunction`).
- `execute_flow` inside a process worker is rejected in 3.0.
- `node.submit()` outside an active run raises `RuntimeError`.

### Lifecycle

- **Drain-on-return** — the run returns only after every submitted node has settled, so the log is complete on return.
- **Failure** — a failed run cancels its own pool's pending nodes (each recorded `skipped`), waits for the running ones, records `run_end` with `status: "error"` (or `"timeout"`), and re-raises.
- A caller-owned pool is never settled: success and failure both drain; the owner owns the lifecycle.
- `run_id` format: `<name>-<UTC timestamp>-<short uuid>`; reference mode `<name>-fixed`.
- Concurrent runs are safe in one process: pool exit cancels only that pool's own nodes.
- A timed-out attempt thread cannot be preempted; its late records are dropped (`RunLog.abandon`), so the log never changes after `run_end`.

### Configuration

There is no global configuration. Run-level knobs travel with `execute_flow` (`RunOptions`); node-level defaults come from `RunOptions.node_defaults` (`NodePolicy`) or the decorator. Precedence: **explicit decorator keyword > `node_defaults` > built-in default**. `RunOptions` fields left unset take the built-in default; nothing is inherited from an enclosing run (there is none).

```python
RunOptions(
    max_workers=8,
    log="output/runs",
    summary=True,
    fixed_clock=False,
    node_defaults=NodePolicy(retries=2, retry_delay_seconds=0.5, timeout=30.0),
)
```

### `flow-runner` — run a node from the command line

```text
flow-runner config.toml                # run the configured node
flow-runner config.toml --flow report  # override the selection
flow-runner config.toml --list         # nodes in the module, with docstrings
python -m sequence_extensions.flow_runner config.toml   # same thing
```

```toml
[run]
module = "mypackage.flows"
flow = "campaign"
max_workers = 8
log = "runs"
summary = false
fixed_clock = false
retries = 0
timeout = 60.0

[node]                 # -> RunOptions.node_defaults
retries = 2
retry_delay_seconds = 0.5
timeout = 30.0

[inputs]               # keyword arguments for the root node
cases_dir = "cases"
tolerance = 0.25
```

The runner loads and validates the whole file first (unknown keys and sections fail with the file, section, and key named; `[flow]`/`[task]` are rejected with a 3.0 migration message), imports `[run] module`, scans it for the `__node__` marker, validates `[inputs]` against the node's signature, calls `execute_flow`, and reports status, duration, log path, and result. Exit codes: `0` ok, `1` the run raised, `2` usage/config error. Process pools are constructed in code; the runner drives thread-mode runs.

### The run log — the executed truth

One JSON-lines file per run (schema 2). Record kinds:

- `run_start` — `run_id`, `node`, `attempt`, `started`, `version`, args/kwargs.
- `node` — one record per attempt: `node`, `path` (the node-name chain), `attempt`, `parent_attempt`, `status` (`ok` / `error` / `timeout` / `skipped`), inputs, timing, `worker`, result/error. A `skipped` record also carries `reason` (`cancelled (run failed)`, `dispatch failed`, or `dependency failed`).
- `run_end` — `status` (`ok` / `error` / `timeout`), result/error.

```json
{"seq": 2, "schema": 2, "record": "node", "run_id": "campaign-…", "node": "simulate", "path": ["campaign", "simulate"], "attempt": 1, "parent_attempt": 1, "status": "error", "error": {"type": "RuntimeError", "message": "flaky"}, "worker": "graph-worker_1"}
{"seq": 3, "schema": 2, "record": "node", "run_id": "campaign-…", "node": "simulate", "path": ["campaign", "simulate"], "attempt": 2, "parent_attempt": 1, "status": "ok", "result": {"score": 0.3}, "worker": "graph-worker_1"}
```

Reading:

- `RunLog.records(path)` — the whole log, in file order.
- `RunLog.filter(records, record=..., node=..., status=..., attempt=..., path=...)` — selection.
- `RunLog.summarize(path)` — per-path account (`attempts`, `statuses`, `status`, `duration_ms`) plus the run verdict.
- `RunLog.diff(a, b, exclude=DIFF_EXCLUDE)` — semantic comparison; identity is `(path, parent_attempt, attempt, inputs)` for nodes and the kind for run records. `DIFF_EXCLUDE` drops order, run identity, wall-clock, and worker; pass a replacement set to compare more or less.

Reference mode (`fixed_clock=True`) buffers records and writes them at close, in canonical order, with timing pinned to `1970-01-01T00:00:00+00:00`, `duration_ms` to `0`, and `worker` to `fixed`. Identical runs produce byte-identical files — for storing logs as reference artifacts. A fixed run rejects run-level retries.

### Example campaign

```python
from pathlib import Path

from sequence_extensions.flow import RunOptions, execute_flow, gather, node


@node(retries=2, retry_delay_seconds=0.05)
def simulate(case: Path) -> dict:
    ...


@node
def evaluate(sim: dict, tolerance: float) -> dict:
    ...


@node
def campaign(cases_dir: Path, tolerance: float = 0.5) -> list:
    cases = sorted(cases_dir.glob("*.csv"))
    sims = [simulate.submit(c) for c in cases]
    evals = [evaluate.submit(s, tolerance) for s in sims]
    return gather(evals)


run = execute_flow(
    campaign,
    Path("cases"),
    options=RunOptions(max_workers=8, log="runs"),
)
print(run.result, run.status, run.log)
```

## Wrapping an external simulator (recipe)

The engine is deliberately stdlib-only: no subprocess helpers, no FMI bindings, no HPC client. A real `simulate` (an FMI co-simulation, a Modelica tool, a command-line solver) is yours to write. This is the canonical pattern — a **recipe, not a dependency**.

1. **Run the tool with `subprocess.run` and a `timeout`.** The tool is a black box; its contract is the command line, the exit code, and the files it writes. `subprocess.run(..., timeout=...)` kills a hung tool at the process level — the layer a node `timeout=` cannot reach.
2. **Map a non-zero exit to an exception.** Raise `RuntimeError`; the node fails, the run log records it, and `retries=` / the run's failure handling take over.
3. **Return a `Path`, not the payload.** The run log serializes it as path plus sha256; downstream nodes receive the path by value.
4. **Stay deterministic.** Same inputs, same command line, same output bytes — the log then proves it.

```python
import subprocess
from pathlib import Path

from sequence_extensions.flow import RunOptions, execute_flow, gather, node


@node(retries=2, retry_delay_seconds=5.0, timeout=330.0)
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


@node
def campaign(model: str, stop_times: list, workdir: Path) -> list:
    futures = [
        simulate.submit(model, stop_time, workdir / f"case_{i}")
        for i, stop_time in enumerate(stop_times)
    ]
    return gather(futures)


run = execute_flow(campaign, model, stop_times, workdir, options=RunOptions(log="runs"))
```

Use both timeouts: the subprocess timeout kills the tool; the node `timeout=` is the campaign-level backstop (it abandons the attempt and retries — see the mechanics above).

### HPC (SLURM) variant

The batch scheduler is the orchestrator; the engine's job is to speak it. The same recipe with `sbatch` in place of a direct run:

```python
@node(retries=2, timeout=7200.0)
def submit_job(script: Path) -> str:
    proc = subprocess.run(
        ["sbatch", "--parsable", str(script)], capture_output=True, text=True, timeout=60
    )
    if proc.returncode != 0:
        raise RuntimeError(f"sbatch failed: {proc.stderr.strip()}")
    return proc.stdout.strip()  # job id


@node(retries=1000, retry_delay_seconds=60.0)
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

A polling node with `retries` large and `retry_delay_seconds` matching the poll interval is one line of policy — no scheduler adapter in the engine.
