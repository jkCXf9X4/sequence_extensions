# sequence_extensions

**Version:** 3.0.0 · **Python:** >=3.11

Higher-order function extensions for Python lists, dicts, and generators, plus a mini flow engine on dependency-graph futures: deterministic parallel campaigns, local or at HPC — retries, timeouts, and a JSON-lines run log that is the executed truth of every run.

The package is organized into three subpackages plus the CLI:

```
sequence_extensions/
├── ext/           # functional helpers for built-in sequences
├── graph/         # the execution substrate (GraphFuture / GraphPool)
├── flow/          # the mini flow engine (node / execute_flow / run log)
└── flow_runner/   # the flow-runner CLI
```

- `ext.list_ext` — an extended `list` class with functional helpers (`map`, `filter`, `reduce`, `window`, ...)
- `ext.dict_ext` — an extended `dict` class with functional helpers (`map`, `filter`, `reduce`, ...)
- `ext.gen_ext` — static helpers for generators (`to_list`, `recursive_gen`)
- `graph.graph_future` — dependency-graph futures (`GraphFuture`, `GraphPool`)
- `flow` — the flow engine: `@node` (retry, backoff, timeout policy, `.submit()`) and `execute_flow` (run identity, pool, audit log)
- `flow_runner` — the `flow-runner` command: run a node selected by a TOML file

`ext` and `graph` names are re-exported from the package root; `flow` is imported as its own package (`from sequence_extensions.flow import node, execute_flow`). See [docs/API.md](docs/API.md) for the full API reference.

## Installation

Requires **Python >= 3.11**.

```
pip install sequence-extensions-flow
```

From source:

```
pip install .
```

The PyPI name `sequence-extensions` is held by an unrelated, older project
(0.1.4) that does not contain the flow engine. This project publishes as
`sequence-extensions-flow`; the import package is still
`sequence_extensions`.

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


# Chaining: a function returning another GraphFuture forwards its result.
# Plain concurrent.futures.Future values are dependencies too, and are
# forwarded when returned.
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

The mini flow engine — parallel, deterministic, audited. A **node** is a function with retry/backoff/timeout policy; `execute_flow` opens a **run**: run identity, a bounded pool, and one JSON-lines audit log. A node body is ordinary Python — direct calls are sequential, `.submit()` is concurrent, and futures passed as arguments are dependency edges.

```python
from pathlib import Path

from sequence_extensions.flow import RunOptions, execute_flow, gather, node


@node(retries=2, retry_delay_seconds=0.1, timeout=60.0)
def simulate(case: Path) -> dict: ...  # one case; flakes are retried, hangs are bounded


@node
def evaluate(sim: dict, tolerance: float) -> dict: ...


@node
def merge(evaluations: list) -> dict:
    return {
        "count": len(evaluations),
        "mean_score": sum(e["score"] for e in evaluations) / len(evaluations),
        "passed": sum(1 for e in evaluations if e["passed"]),
        "all_passed": all(e["passed"] for e in evaluations),
    }


@node
def campaign(cases_dir: Path, tolerance: float = 0.5) -> dict:
    cases = sorted(cases_dir.glob("*.csv"))  # plain call: sequential
    sims = [simulate.submit(c) for c in cases]  # concurrent map
    evals = [evaluate.submit(s, tolerance) for s in sims]  # futures = edges
    return merge.submit(gather(evals))  # no .result() wait


run = execute_flow(campaign, Path("cases"), options=RunOptions(max_workers=16, log="runs"))
run.result, run.run_id, run.status, run.log, run.duration_ms
```

Semantics, in one list:

- **`execute_flow(node, ...)` is the top-level run boundary.** It returns a `Run` (`result`, `run_id`, `node`, `status`, `log`, `duration_ms`, `attempt`, `started`, `ended`, `error`). A failure raises the node's exception with `.run` attached. Calling it inside an active run raises: a node composes nodes, it does not open a second run.
- **Plain call = sequential** (inline in the caller's thread: a value outside a body, a `FlowOutcome` to return inside one when the call cannot settle); **`.submit()` = concurrent** (the run's bounded pool, default 16 workers; `RunOptions(max_workers=...)`).
- **Retries and timeouts are node attributes**: `retries=2` means up to three attempts; `timeout=30` bounds one attempt and raises `NodeTimeoutError`. Every attempt is one record in the log.
- **Futures as arguments are dependency edges** — any DAG shape, diamonds included; cycles raise at submit time.
- **Return futures, don't block a body.** A node may return a value or a future. A returned future (`submit()` or `gather(...)`) is awaited by the node attempt; the worker is freed immediately. `.result()` on an incomplete future inside a node body — root body or pool worker — raises with guidance instead of deadlocking.
- **`gather(...)` resolves futures in place** without a `.result()` wait and keeps the container shape: `gather({"evals": evals})` resolves to `{"evals": [...]}`, and dicts, nested lists, tuples, sets and namedtuples survive. A bare future becomes a one-element list, any other iterable a list, and `[]` is accepted. Pass the resulting future to a dependent node (`merge.submit(gather(evals))`) or return it. Return one future, never a list/dict of futures (that is rejected).
- **Drain-on-return**: the run returns only after every submitted node settles. A failed run cancels its pending nodes (recorded `skipped`), waits for the running ones, and re-raises.
- **Nested nodes are one run and one log.** A composite is just a node that calls/submits other nodes. Node records carry `path` (the node-name chain) and `parent_attempt`; composite `retries`/`timeout` apply to the returned future as a whole. There are no child runs and no second log.
- **The run log** (default `runs/<run_id>.jsonl`) records `run_start`, every node attempt (`ok` / `error` / `timeout` / `skipped`), and `run_end`. Paths log as path plus sha256 — bulky payloads return a `Path` by convention and never bloat the log.
- **Read it back**: `RunLog.records(path)`, `RunLog.filter(...)`, `RunLog.summarize(path)`, and `RunLog.diff(a, b)` — record order, wall-clock, and worker identity never count as differences.
- **Concurrent runs are safe in one process** — pool exit cancels only that pool's own nodes. CPU-bound campaigns swap threads for processes:

```python
from sequence_extensions.flow import ProcessGraphPool, RunOptions, execute_flow

with ProcessGraphPool() as pool:  # worker processes instead of threads
    run = execute_flow(campaign, cases_dir, options=RunOptions(pool=pool))
```

Nodes and arguments must be picklable (module-level functions, plain data); attempt records are buffered by the worker and replayed by the run, so the log is still complete on return. An unpicklable payload surfaces as `ProcessDispatchError` with a `skipped` / `dispatch failed` record. The root node body runs on the driver; that is where process-mode fan-out is built. A body already running inside a process worker cannot submit or return a live future, and `execute_flow` inside a process worker is rejected in 3.0.

Two examples of the log's shape (from the acceptance test's campaign — six cases, one flaky):

```json
{"seq": 3, "schema": 2, "record": "node", "run_id": "campaign-20261013T101500-1a2b3c4d", "node": "simulate", "path": ["campaign", "simulate"], "attempt": 1, "parent_attempt": 1, "status": "error", "args": [{"path": "cases/case_3.csv", "sha256": "…"}], "error": {"type": "RuntimeError", "message": "transient simulator crash on case_3"}, "worker": "graph-worker_2"}
{"seq": 4, "schema": 2, "record": "node", "run_id": "campaign-20261013T101500-1a2b3c4d", "node": "simulate", "path": ["campaign", "simulate"], "attempt": 2, "parent_attempt": 1, "status": "ok", "args": [{"path": "cases/case_3.csv", "sha256": "…"}], "result": {"case": "case_3", "score": 0.3}, "worker": "graph-worker_2"}
```

For wrapping real simulators (subprocess timeouts, `sbatch`-and-poll for HPC), see the recipes in [docs/API.md](docs/API.md).

## Run options

There is no global configuration: everything a run needs travels with the `execute_flow` call. `RunOptions` fields left unset fall back to the built-in default.

```python
from sequence_extensions.flow import NodePolicy, RunOptions, execute_flow

run = execute_flow(
    campaign,
    Path("cases"),
    options=RunOptions(
        max_workers=8,                       # default 16
        log="output/runs",                   # default "runs"; None disables
        summary=False,                       # log item counts for long containers
        fixed_clock=False,                   # reference mode (see below)
        retries=0,                           # run-level retries (one log per attempt)
        timeout=None,                        # run-level wall budget
        node_defaults=NodePolicy(            # defaults for nodes that left a value unset
            retries=2,
            retry_delay_seconds=0.5,
            timeout=30.0,
        ),
    ),
)
```

Resolution is **explicit `@node` keyword > `RunOptions.node_defaults` > built-in default**.

`fixed_clock = true` opts a run into **reference mode**: the run executes as if on a frozen clock, so an identical run produces a byte-identical log. The run id pins to `<node>-fixed` (the log file overwrites itself instead of accumulating), every engine-written timestamp becomes `1970-01-01T00:00:00+00:00`, `duration_ms` becomes `0`, the `worker` field becomes constant, and records are written in canonical order — `run_start`, nodes by path/parent attempt/attempt/inputs, `run_end`. Root-level run retries are rejected with `fixed_clock` (one reference execution per file). Built for storing run logs as reference files (golden files in git) without timestamp churn; the trade is that the file holds nothing until the run returns.

## flow-runner

The `flow-runner` command starts a run from a TOML file — one file selects the module and root node, passes inputs, and tunes the engine:

```toml
# campaign.toml
[run]
module = "mypackage.flows"  # module scanned for @node functions
flow = "campaign"            # which node to run
log = "runs"
max_workers = 8

[node]                       # defaults for nodes that left a value unset
retries = 2
timeout = 60.0

[inputs]                     # keyword arguments for the root node
cases_dir = "cases"
tolerance = 0.25
```

```
$ flow-runner campaign.toml
flow campaign: ok (1843 ms)
log: runs/campaign-20261016T110258-b0e4a12e.jsonl
result: {"count": 6, "mean_score": 0.71, "passed": 6, "all_passed": true}

$ flow-runner campaign.toml --list   # nodes in the module, with docstrings
$ flow-runner campaign.toml --flow report   # override the selection
```

Same entry point as a module: `python -m sequence_extensions.flow_runner campaign.toml`. Exit codes: `0` the run succeeded, `1` the run raised, `2` usage or config error — cron/CI/SLURM friendly. The TOML is strict (unknown keys fail early with the file, section, and key named); `[flow]`/`[task]` are rejected with a 3.0 migration message, and process pools are constructed in code. A config file names a module to import, so treat it as trusted code.

## Larger workflows

Two ways to drive the engine from outside its own code — a shell or pipeline on the CLI, or an embedding application on the library.

### From a shell or pipeline

`flow-runner` fits make, CI, cron, and batch scripts: one command, no driver script per run, and the outcome lands in the exit code.

```make
# Makefile — one target per config
campaign:
	flow-runner configs/nightly.toml

report:
	flow-runner configs/report.toml
```

```yaml
# .github/workflows/campaign.yml — run, gate on the exit code, keep the log
- run: pip install .
- run: flow-runner configs/ci.toml
- uses: actions/upload-artifact@v4
  if: always()                    # archive the log even when the run fails
  with:
    name: run-log
    path: artifacts/runs/         # = [run] log in ci.toml
```

The pipeline picks the config file, so one file per environment keeps runs apart:

```
configs/
├── ci.toml        # small pools, log into artifacts/
├── nightly.toml   # more retries, longer timeouts
└── report.toml    # another root node, other inputs
```

- **Branch on the exit code**: `0` success, `1` the run raised, `2` usage or config error — cron, CI, and SLURM see the same codes.
- **Fail before the first node**: a bad config fails at load with the file, section, and key named; nothing has run yet.
- **The log is the artifact**: `[run] log` puts the JSON-lines file where the pipeline collects it; the account line (status, duration, log path) names it.
- **Look before you run**: `--list` shows the nodes in the module with their docstrings; `--flow NAME` overrides the selection.
- **Varying inputs per invocation** means one TOML per variant — inputs come from the file, there is no `--set` flag.
- **Store logs as golden files**: `fixed_clock = true` in `[run]` makes an identical run produce a byte-identical log (pinned run id, pinned timing, canonical record order) — commit it, and re-running the pipeline leaves git clean.

### Embedded in an application

The engine is a library: no service to run, no threads started at import, no dependencies beyond Python. Call `execute_flow` where the run belongs; the returned `Run` carries the verdict.

```python
# app.py
from sequence_extensions.flow import RunOptions, execute_flow

from mypackage.flows import campaign

run = execute_flow(campaign, cases_dir="cases", options=RunOptions(log="runs"))
if run.status != "ok":
    raise RuntimeError(f"campaign failed, see {run.log}")
archive(run.log)  # keep the JSONL beside app data
```

- **No global state, no import-order constraint**: options travel with the call; two runs can use different pools/logs/summaries in the same process.
- **Scoped by construction**: per-tenant or per-request settings are just different `RunOptions` values — there is no `configure()` to leak into the next caller.
- **Quiet when unwanted**: `log=None` disables run logging — tests and short-lived jobs keep the disk clean.
- **Determinism holds**: option values never enter run-log records, so identical code and inputs still diff identical.
- **Failures carry the account**: `execute_flow` raises with `.run` attached, so a host can log the status, duration, and log path while still propagating the exception.
- Nodes needing open connections or custom objects are called directly like this; the runner is the convenience for TOML-shaped inputs.

## Runnable examples

[`examples/`](examples/) is a hands-on tour of the library: one small,
self-contained program per aspect, plus a TOML-driven `flow-runner` setup.
They are part of the test suite (`tests/usage_examples/`), so they cannot
drift from the code.

| Example | What it shows |
| --- | --- |
| [`examples/sequences.py`](examples/sequences.py) | `list_ext`, `dict_ext`, `KeyValueTuple`, `gen_ext` |
| [`examples/graph_futures.py`](examples/graph_futures.py) | `GraphFuture` / `GraphPool`: DAGs, chaining, errors, timeouts |
| [`examples/campaign.py`](examples/campaign.py) | `@node`, `.submit()`, dependency edges, `gather`, retries, run log |
| [`examples/policies.py`](examples/policies.py) | retries/backoff, `node_defaults`, node/run timeouts, skipped dependencies |
| [`examples/run_log.py`](examples/run_log.py) | `RunLog.records` / `filter` / `summarize` / `diff`, reference mode |
| [`examples/process_pool.py`](examples/process_pool.py) | `ProcessGraphPool` for CPU-bound fan-out |
| [`examples/flow_runner/`](examples/flow_runner) | the TOML-driven `flow-runner` command |

```bash
python examples/campaign.py --out /tmp/campaign
python examples/policies.py --out /tmp/policies
cd examples/flow_runner && flow-runner campaign.toml
```

The file-writing scripts take `--out` (default `examples/_out/<name>`,
gitignored) and print the result they check. See
[examples/README.md](examples/README.md) for the walkthrough and the expected
output of each example.

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