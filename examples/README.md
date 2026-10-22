# Examples — a usage tour

Runnable programs that tour `sequence_extensions`, one per aspect. Each is a
standalone script with a `main()` function; `tests/usage_examples/` executes
them as part of `pytest`, so the examples cannot drift from the library.

Run them from the repository root:

```bash
python examples/sequences.py
python examples/graph_futures.py
python examples/campaign.py --out /tmp/campaign
python examples/policies.py --out /tmp/policies
python examples/run_log.py --out /tmp/run-log
python examples/process_pool.py --out /tmp/process-pool

cd examples/flow_runner
flow-runner campaign.toml
```

The file-writing scripts accept `--out` (default `examples/_out/<name>`).
That output is scratch: it is gitignored, and a fresh `--out` directory gives
a clean rerun. Nothing here needs a network, a simulator install, or a
service.

| Example | What it shows |
| --- | --- |
| [`sequences.py`](sequences.py) | `list_ext`, `dict_ext`, `KeyValueTuple`, `gen_ext` |
| [`graph_futures.py`](graph_futures.py) | `GraphFuture` / `GraphPool`: a DAG diamond, chaining, errors, timeouts |
| [`campaign.py`](campaign.py) | `@node`, `.submit()`, dependency edges, `gather`, retries, `RunOptions`, run log |
| [`policies.py`](policies.py) | retries/backoff, `node_defaults`, node and run timeouts, skipped dependencies |
| [`run_log.py`](run_log.py) | `RunLog.records` / `filter` / `summarize` / `diff`, reference mode, `summary`, `log=None` |
| [`process_pool.py`](process_pool.py) | `ProcessGraphPool` for CPU-bound fan-out |
| [`flow_runner/`](flow_runner) | the TOML-driven `flow-runner` command |

## `sequences.py` — sequence helpers

A small run-report cleanup: filter the finished runs, map to scores, use a
sliding window, reduce, convert columns to a dict, and read one pair through
`KeyValueTuple`.

```bash
python examples/sequences.py
```

```text
metadata: solver : mock, cases : 4
finished: c1, c2, c3
scores:   0.82, 0.91, 0.74
mean:     0.823
best:     c2
moving:   0.865, 0.825
sum:      2.47
passing:  c1 : 0.82, c2 : 0.91
first:    c2 -> 0.91
report:   {'c1': 0.8, 'c2': 0.9, 'c3': 0.7}
inverse:  0.82 : c1, 0.91 : c2, 0.74 : c3
missing:  missing
stages:   [2, 4, 8, 16, 32]
```

Worth noticing:

- `map`, `filter`, and `window` return `list_ext`, so calls chain.
- `to_dict_key(cases)` turns the score column plus the case-name column into
  a `dict_ext`; `filter(func)` there receives `(key, value)`.
- `first(...)` returns a `KeyValueTuple`, so `.key` / `.value` read better
  than tuple indexing.
- `gen_ext.recursive_gen` is a bounded walk, not an infinite generator: the
  `stop_f` predicate is what stops it.

## `graph_futures.py` — the execution substrate

Build a diamond (`base` → `left` / `right` → `total`), chain a node that
returns another future, and handle the two failure modes of a future pool.

```bash
python examples/graph_futures.py
```

```text
diamond:  50
chained:  20
plain:    20
node error: ZeroDivisionError
timeout:    TimeoutError
```

Worth noticing:

- `GraphFuture(fn, dependency, ...)` replaces dependency arguments with their
  results before `fn` runs. `base` runs once, `left` and `right` in parallel.
- A node function may return another `GraphFuture`; its result is forwarded
  without holding a worker.
- Any `concurrent.futures.Future` is a dependency too, so a graph can join a
  future produced outside the graph layer.
- A node's exception propagates from `pool.result()`; `timeout=` bounds the
  wait, not the node body.
- `with GraphPool(...)` is the cleanup form: pending nodes are cancelled on
  exit and the executor is shut down.

## `campaign.py` — the core flow shape

The main flow example: discover cases, fan out simulations, chain an
evaluation onto each, and fan in one verdict. Each case fails its first
attempt, so the log shows the retry policy in action.

```bash
python examples/campaign.py --out /tmp/campaign
```

```text
status:  ok
result:  {'cases': 4, 'passed': 2, 'mean_score': 0.78}
attempt: 1, duration_ms: 25
retried: 4 simulate attempts (one per case)
log:     /tmp/campaign/runs/campaign-20261022T072726-69304af3.jsonl
nodes:   [['campaign', 'count_cases'], ['campaign', 'simulate'], ['campaign', 'evaluate'], ['campaign', 'summarize'], ['campaign']]
```

Worth noticing:

- A plain call (`count_cases(cases_dir)`) runs inline in the caller's thread;
  `.submit()` schedules on the run's bounded pool. The root uses `.submit()`
  for every case.
- Passing `simulate.submit(...)` to `evaluate.submit(...)` creates a
  dependency edge — no manual waiting.
- `gather({"evaluations": evaluations, "cases": case_count})` keeps the dict
  shape around the list of results. Return one future, not a container of
  futures.
- `simulate` returns a `Path`, so the log records the artifact path and its
  sha256 rather than the payload.
- `simulate` has explicit `retries=1` / `timeout=5.0`; the other nodes inherit
  `RunOptions.node_defaults`. An explicit decorator keyword wins.
- `RunLog.summarize(run.log)` gives the per-path account; `RunLog.filter`
  selects records (here, the errored attempts).

## `policies.py` — retries, timeouts, and failure

Six small runs, each isolating one policy.

```bash
python examples/policies.py --out /tmp/policies
```

```text
retries:     ['error', 'error', 'ok'] -> 3
defaults:    ['error', 'ok'] -> 2
node timeout:{'error': 'NodeTimeoutError', 'node': 'too_slow', 'timeout': 0.05, 'statuses': ['timeout']}
failure:     {'error': 'deliberate failure', 'run_status': 'error', 'skip_reason': 'dependency failed'}
run timeout: {'error': 'NodeTimeoutError', 'run_status': 'timeout', 'run_end_status': 'timeout'}
run retries: 2 (2 logs)
```

Worth noticing:

- `retries=2` means up to three attempts; each attempt is one log record.
- A node with no decorator policy resolves `retries` / `timeout` from
  `RunOptions.node_defaults`.
- A node `timeout` abandons one attempt and raises `NodeTimeoutError`; the
  attempt record says `status: "timeout"`.
- A failed dependency does not run: its dependent is recorded `skipped` with
  `reason: "dependency failed"`.
- `execute_flow` raises the node's exception with `.run` attached. The run
  account still names the log and the status.
- `RunOptions(timeout=...)` bounds the whole run; `run_end` records `timeout`
  instead of `error`.
- `RunOptions(retries=...)` retries the whole run. Each attempt gets its own
  log file and run id, so a failed attempt is still auditable.

## `run_log.py` — reading the executed truth

Run the same flow twice in reference mode, then read the log back.

```bash
python examples/run_log.py --out /tmp/run-log
```

```text
fixed logs byte-identical: True
diff equal:               True
records:                  9
ok node records:          7
square records:           6
summary:                  log_demo-fixed ok
summary-mode args:        {'type': 'list', 'len': 20}
quiet log:                None
```

Worth noticing:

- `fixed_clock=True` pins the run id (`<name>-fixed`), timing, and worker
  fields, and writes records in canonical order. Identical runs are
  byte-identical files — suitable as golden references in git.
- `RunLog.diff(a, b)` compares what ran (path, parent attempt, attempt,
  inputs) and ignores order, identity, wall-clock, and worker names. The
  result is a jsonable report; `equal` is the verdict.
- `RunLog.records`, `RunLog.filter`, and `RunLog.summarize` are the reading
  toolkit: whole file, selected records, and a compact per-path account.
- `summary=True` replaces long containers with counts (`{"type": "list",
  "len": 20}`) while the returned `Run.result` stays complete.
- `log=None` disables the log file for tests and short-lived embedding.

## `process_pool.py` — CPU-bound fan-out

The same node graph, but workers are processes instead of threads.

```bash
python examples/process_pool.py --out /tmp/process-pool
```

```text
status:  ok
results: [21333253333400000, 21333253333400000, 21333253333400000, 21333253333400000]
workers: ['proc-ForkProcess-1', 'proc-ForkProcess-2']
log:     /tmp/process-pool/runs/cpu_campaign-20261022T072728-e88fd2ef.jsonl
```

Worth noticing:

- `RunOptions(pool=pool)` lets the run use a caller-owned pool; the run never
  shuts it down.
- Nodes and arguments must be picklable: module-level functions and plain
  data, no lambdas or closures.
- The root body runs on the driver process; that is where process-mode
  fan-out is built. A body already in a process worker cannot submit or
  return a live future.
- The log is still complete on return: worker records are buffered and
  replayed by the parent.

## `flow_runner/` — run from a TOML file

One module of nodes plus a config file; no driver script.

```bash
cd examples/flow_runner
flow-runner campaign.toml --list
flow-runner campaign.toml
```

```text
flows in flows:
  campaign  — Run every case through simulate and evaluate; return one verdict.
  evaluate  — Compare one simulated value to the tolerance.
  simulate  — Double the case value; fail once per case to exercise retries.
  summarize — Fan in the evaluations into one verdict.
flow campaign: ok (20 ms)
log: _out/runs/campaign-20261022T072729-b295323b.jsonl
result: {"cases": 4, "passed": 2, "mean": 1.565}
```

Worth noticing:

- `[run]` selects the module and root node and sets run options. `[inputs]`
  are keyword arguments for that node; `[node]` supplies policy defaults.
- Inputs come from the file, so one TOML per variant; check a node's
  signature before running — a mismatch is a config error (exit code 2)
  before anything starts.
- `--list` discovers `@node` functions by the marker the decorator stamps;
  `--flow NAME` overrides the selection.
- Exit codes are cron/CI/SLURM friendly: `0` ok, `1` the run raised, `2`
  usage or config error.
- `fixed_clock = true` in `[run]` makes an identical run produce a
  byte-identical log, so a committed log stays clean in git.
