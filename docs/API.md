# sequence_extensions API Reference

Hand-written API reference for the `sequence_extensions` package — higher-order function extensions for sequences (lists, dicts, generators) plus a small dependency-graph future.

> **Version:** this document describes **version 0.2.0** (Python >= 3.9).

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