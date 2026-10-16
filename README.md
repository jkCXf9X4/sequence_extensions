# sequence_extensions

**Version:** 2.0.0 · **Python:** >=3.11

Higher-order function extensions for Python lists, dicts, and generators, plus a mini flow engine on dependency-graph futures: deterministic parallel campaigns, local or at HPC — retries, timeouts, and a JSON-lines run log that is the executed truth of every run.

The package is organized into three subpackages:

```
sequence_extensions/
├── ext/           # functional helpers for built-in sequences
├── graph/         # the execution substrate (GraphFuture / GraphPool)
├── flow/          # the mini flow engine (@task / @flow / run log)
├── config.py      # external configuration (TOML → Config → configure)
└── flow_runner/   # the flow-runner CLI
```

- `ext.list_ext` — an extended `list` class with functional helpers (`map`, `filter`, `reduce`, `window`, ...)
- `ext.dict_ext` — an extended `dict` class with functional helpers (`map`, `filter`, `reduce`, ...)
- `ext.gen_ext` — static helpers for generators (`to_list`, `recursive_gen`)
- `graph.graph_future` — dependency-graph futures (`GraphFuture`, `GraphPool`)
- `flow` — the flow engine: `@task` (retry, backoff, timeout policy) and `@flow` (run identity, pool, audit log)
- `config` — the `Config` object and `configure()`: engine parameters from a TOML file
- `flow_runner` — the `flow-runner` command: run a flow selected by a config file

`ext` and `graph` names are re-exported from the package root; `flow` is imported as its own package (`from sequence_extensions.flow import task, flow`). See [docs/API.md](docs/API.md) for the full API reference.

## Installation

Requires **Python >= 3.11**.

```
pip install sequence-extensions
```

From source:

```
pip install .
```

Development install (includes dev/test dependencies):

```
pip install -e ".[dev]"
```

## list_ext

```python
from sequence_extensions import list_ext

l = list_ext([1, 2, 3, 4])

l.map(lambda x: x * 2)
[2, 4, 6, 8]

l.filter(lambda x: x % 2 == 0)
[2, 4]

l.for_each(lambda x: print(x))
1
2
3
4

l.first(lambda x: x % 2 == 0)
2

l.last(lambda x: x % 2 == 0)
4

l.to_strings()
["1", "2", "3", "4"]

l.to_string()
"1, 2, 3, 4"

l.to_string(prefix="[", suffix="]")
"[1, 2, 3, 4]"
```

`list_ext.to_string` defaults to `", "` (while `dict_ext.to_string` defaults to `"\n"`).

### More list_ext helpers

```python
l.window(2)  # [[1, 2], [2, 3], [3, 4]]  (inner windows are list_ext)
l.window(5)  # []
l.window_select(lambda a, b: a + b)  # [3, 5, 7]
list_ext.execute_or_default(
    lambda: [1, 2][5], default="D"
)  # 'D'  (catches IndexError, KeyError by default)
list_ext.execute_or_default(
    lambda: 1 / 0, default="D"
)  # raises ZeroDivisionError (not caught by default)
list_ext.execute_or_default(lambda: 1 / 0, default="D", exception=ZeroDivisionError)  # 'D'
l.get_item_or_default(10, "D")  # 'D'
l.first_or_default(lambda x: x > 10, "D")  # 'D'
l.last_or_default(lambda x: x > 10, "D")  # 'D'
l.to_type(str)  # ['1', '2', '3', '4']
l.to_set()  # {1, 2, 3, 4}
l.to_tuple()  # (1, 2, 3, 4)
list_ext([1, 2]).to_dict_key(["a", "b"])  # {'a': 1, 'b': 2}
list_ext([1, 2]).to_dict_value(["a", "b"])  # {1: 'a', 2: 'b'}
list_ext([1, 2, 3]).to_dict_key(["a", "b"])  # raises ValueError (length mismatch)
l.to_dict_fn(lambda x: "k" + str(x), lambda x: x * 10)  # {'k1': 10, 'k2': 20, 'k3': 30, 'k4': 40}
list_ext([1, "a", 2, "b"]).of_type(int)  # [1, 2]
list_ext([True, 1]).of_type(int)  # [True, 1]  (isinstance)
l.contains(3)  # True
l.is_empty()  # False
l.is_single()  # False
list_ext([5]).single()  # 5
list_ext([1, 2]).single()  # raises ValueError "Expected exactly one item, got 2"
l.intersect([3, 4, 5])  # [3, 4]
l.union([5, 6])  # [1, 2, 3, 4, 5, 6]
list_ext([{"a": 1}, {"a": 2, "b": 3}]).chainmap()  # {'a': 1, 'b': 3}  (first dict wins)
l.average()  # 2.5
list_ext([]).average()  # raises statistics.StatisticsError
l.max()  # 4
l.min()  # 1
l.reduce(lambda a, b: a + b)  # 10
l.zip()  # []  (no args)
l.zip(["a", "b", "c", "d"])  # [(1, 'a'), (2, 'b'), (3, 'c'), (4, 'd')]
```

## dict_ext

`dict_ext` extends `dict` with functional helpers that operate on `(key, value)` pairs:

```python
from sequence_extensions import dict_ext

d = dict_ext({"a": 1, "b": 2, "c": 3, "d": 4})

d.map(lambda k, v: (k * 2, v * 2))  # dict_ext({'aa': 2, 'bb': 4, 'cc': 6, 'dd': 8})
d.map(lambda k, v: (k * 2, v * 2), cast=dict)  # {'aa': 2, 'bb': 4, 'cc': 6, 'dd': 8}  (plain dict)
d.map(lambda k, v: v * 2, cast=list)  # [2, 4, 6, 8]  (plain list)
d.filter(lambda k, v: v % 2 == 0)  # {'b': 2, 'd': 4}
d.filter()  # same dict (no func keeps all entries)
d.for_each(lambda k, v: print(k, v))  # prints each pair
d.to_list()  # [['a', 1], ['b', 2], ['c', 3], ['d', 4]]
d.to_strings()  # {'a': '1', 'b': '2', 'c': '3', 'd': '4'}
d.to_strings(key=False)  # {'a': '1', 'b': '2', 'c': '3', 'd': '4'}  (keys kept as-is, values str)
d.to_strings(value=False)  # {'a': 1, 'b': 2, 'c': 3, 'd': 4}  (keys str, values kept as-is)
d.to_string()  # 'a : 1\nb : 2\nc : 3\nd : 4'  (default separator "\n")
d.to_string(separator=";")  # 'a : 1;b : 2;c : 3;d : 4'
d.get_keys()  # ['a', 'b', 'c', 'd']
d.get_values()  # [1, 2, 3, 4]
d.to_tuple()  # (('a', 1), ('b', 2), ('c', 3), ('d', 4))
d.to_named_tuple()  # (KeyValueTuple(key='a', value=1), ...)
d.get_key_from_value(3)  # ['c']
d.reduce(lambda a, b: (a.key + b.key, a.value + b.value))  # {'abcd': 10}
dict_ext().reduce(lambda a, b: (a.key + b.key, a.value + b.value))  # {}  (empty dict_ext)
d.extend({"e": 5})  # merged dict (other wins on conflicts)
d.union({"e": 5})  # dict union (other wins on conflicts)
dict_ext({"a": 1}).extend({"a": 9, "b": 2})  # {'a': 9, 'b': 2}  (other wins)
d.inverse()  # {1: 'a', 2: 'b', 3: 'c', 4: 'd'}
d.first()  # KeyValueTuple(key='a', value=1)
d.first(lambda k, v: v == 2)  # KeyValueTuple(key='b', value=2)
d.last()  # KeyValueTuple(key='d', value=4)
d.last(lambda k, v: v == 2)  # KeyValueTuple(key='b', value=2)
d.all(lambda k, v: type(v) == int)  # True
d.all()  # True  (values-only)
d.any(lambda k, v: v == 1)  # True
dict_ext({"a": 0, "b": 0}).any()  # False  (values-only)
```

`KeyValueTuple` is a `NamedTuple` with `.key` and `.value` attributes, returned by `first`, `last`, `reduce`, and `to_named_tuple`. Import it with `from sequence_extensions import KeyValueTuple` (exported from the package root).

## gen_ext

Static helpers for generators and iterables:

```python
from sequence_extensions import gen_ext

gen_ext.to_list(iter([1, 2, 3]))  # [1, 2, 3]
list(gen_ext.recursive_gen(5, lambda x: x - 1, stop_f=lambda x: x > 0))  # [4, 3, 2, 1]
```

`recursive_gen` yields each next item produced by `iter_f`; `stop_f` is called on the *next* item — when it returns `False` the walk stops before yielding that item. The starting item is never yielded. If `iter_f` raises `StopIteration`, the walk stops cleanly.

> **Warning:** if `stop_f` is `None` the walk never terminates — use `itertools.islice` or always pass a `stop_f`.

## graph_future

Dependency-graph futures evaluated with a bounded thread pool:

```python
from sequence_extensions import GraphFuture, GraphPool


def add(x, y):
    return x + y


with GraphPool(max_workers=4) as pool:
    a = GraphFuture(lambda: 1)
    b = GraphFuture(lambda: 2)
    c = GraphFuture(add, a, b)  # waits for a and b
    result = pool.result(c)  # 3
```

`GraphFuture` nodes may depend on other nodes; results are resolved automatically. `GraphPool` can also be used without the context manager (the executor is created lazily on first use).

### graph_future — advanced usage

```python
from sequence_extensions import GraphFuture, GraphPool


# Chaining: a function returning another GraphFuture forwards its result
def outer():
    return GraphFuture(lambda: 20)


with GraphPool(max_workers=4) as pool:
    chained = GraphFuture(outer)
    pool.result(chained)  # 20

    # Cycle detection: a cyclic dependency graph raises ValueError("dependency cycle detected")

    # Exceptions raised by a node's function propagate from pool.result()
    bad = GraphFuture(lambda: 1 / 0)
    pool.result(bad)  # raises ZeroDivisionError

    # Timeout: GraphPool.result(gf, timeout=...) raises TimeoutError if not ready in time
    fast = GraphFuture(lambda: 42)
    pool.result(fast, timeout=5)  # 42
```

Pool lifecycle:

- Use `with GraphPool(...)` for guaranteed cleanup: on exit, unbound (not-yet-completed) nodes are cancelled and their `result()` raises `CancelledError`.
- Re-entering the same pool (`with pool:` twice) raises `RuntimeError`.
- Lazy use without `with` is safe — the executor is created on first use and shut down at interpreter exit (atexit).

## flow

The mini flow engine — parallel, deterministic, audited. A task is a function; a flow is a function; a future passed as a submit argument is a dependency edge. Every run writes one JSON-lines audit log — the executed truth of what happened, complete the moment the flow returns.

```python
from pathlib import Path

from sequence_extensions.flow import flow, task


@task(retries=2, retry_delay_seconds=0.1, timeout=60.0)
def simulate(case: Path) -> dict: ...  # one case; flakes are retried, hangs are bounded


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


verdict = campaign(Path("cases/"))
```

Semantics, in one list:

- **Plain call = sequential** (runs inline); **`.submit()` = concurrent** (the run's bounded pool, default 16 workers; `@flow(max_workers=...)`, or `[flow] max_workers` in a config — see [Configuration](#configuration)).
- **Retries and timeouts are task attributes**: `retries=2` means up to three attempts; `timeout=30` bounds one attempt and raises `TaskTimeoutError` (a `TimeoutError` naming the task). Every attempt is one record in the log.
- **Futures as arguments are dependency edges** — any DAG shape, diamonds included; cycles raise at submit time.
- **Drain-on-return**: the flow returns only after every submitted task settles. A failed flow cancels its pending tasks (recorded `skipped`), waits for the running ones, and re-raises.
- **The run log** (default `runs/<run_id>.jsonl`, one JSON object per line) records `run_start`, every task attempt (`ok` / `error` / `timeout` / `skipped`), and `run_end`. Paths log as path plus sha256 — bulky payloads return a `Path` by convention and never bloat the log. Read it back with `RunLog.records(path)`, see it at a glance with `RunLog.summarize(path)`, select with `RunLog.filter(...)`, and prove two runs executed identically with `RunLog.diff(a, b)` — record order, wall-clock, and worker identity never count as differences.
- **Concurrent flows are safe in one process** — pool exit cancels only that pool's own nodes. CPU-bound campaigns swap threads for processes:

```python
from sequence_extensions.flow import ProcessGraphPool, flow

with ProcessGraphPool() as pool:  # worker processes instead of threads
    verdict = campaign(cases_dir, pool=pool)
```

Tasks and arguments must be picklable (module-level functions, plain data); attempt records are buffered by the worker and replayed by the flow, so the log is still complete on return. An unpicklable payload surfaces as `ProcessDispatchError` with a `skipped` / `dispatch failed` record.

Two examples of the log's shape (from the acceptance test's campaign — six cases, one flaky):

```json
{"seq": 3, "schema": 1, "record": "task", "run_id": "campaign-20261013T101500-1a2b3c4d", "task": "simulate", "attempt": 1, "status": "error", "args": [{"path": "cases/case_3.csv", "sha256": "…"}], "error": {"type": "RuntimeError", "message": "transient simulator crash on case_3"}, "worker": "graph-worker_2"}
{"seq": 4, "schema": 1, "record": "task", "run_id": "campaign-20261013T101500-1a2b3c4d", "task": "simulate", "attempt": 2, "status": "ok", "args": [{"path": "cases/case_3.csv", "sha256": "…"}], "result": {"case": "case_3", "score": 0.3}, "worker": "graph-worker_2"}
```

For wrapping real simulators (subprocess timeouts, `sbatch`-and-poll for HPC), see the recipes in [docs/API.md](docs/API.md).

## Configuration

Every engine parameter can live in a TOML file instead of the code. Load it with `Config.from_toml` and install it with `configure`; unset decorator keywords then resolve per call — **explicit keyword > config > built-in default**:

```python
from sequence_extensions.flow import Config, configure, flow, task

configure(Config.from_toml("config.toml"))


@task  # retries / timeout now come from the config
@flow  # max_workers / log / summary too
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
graph_max_workers = 16     # GraphPool() default
process_max_workers = 4    # ProcessGraphPool() default; omit → CPU count
```

Resolution happens at call time, so `configure()` in `main()` reaches module-level decorators regardless of import order. The whole file is validated on load — unknown keys and bad values fail immediately with the file, section, and key named. Pools constructed directly resolve at construction time: construct them after `configure()`, or pass `max_workers` explicitly. TOML has no `null`; an omitted key keeps the built-in default.

## flow-runner

The `flow-runner` command starts a flow from the config alone — one file selects the flow, passes its inputs, and tunes the engine:

```toml
# campaign.toml
[run]
module = "mypackage.flows"  # module scanned for @flow functions
flow = "campaign"            # which one to run

[inputs]                     # keyword arguments for the flow
cases_dir = "cases"
tolerance = 0.25

[task]
retries = 2
timeout = 60.0
```

```
$ flow-runner campaign.toml
flow campaign: ok (1843 ms)
log: runs/campaign-20261016T110258-b0e4a12e.jsonl
result: {"count": 6, "mean_score": 0.71, "passed": 6, "all_passed": true}

$ flow-runner campaign.toml --list   # flows in the module, with docstrings
$ flow-runner campaign.toml --flow report   # override the selection
```

Same entry point as a module: `python -m sequence_extensions.flow_runner campaign.toml`. Exit codes: `0` the run succeeded, `1` the flow raised, `2` usage or config error — cron/CI/SLURM friendly. Flows needing non-TOML inputs (open connections, custom objects) belong in a small `main.py` that calls them directly. A config file names a module to import, so treat it as trusted code.

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