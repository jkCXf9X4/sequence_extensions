# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.0.0] - 2026-10-16

The external-configuration release: every engine parameter can live
in a TOML file, and `flow-runner` starts a flow from the command line.
Decision `DR-015` in the product breakdown records the design
(precedence, call-time resolution, discovery by module scan).

### Breaking
- **Python >= 3.11 required** (was >= 3.9).  The config system reads
  TOML with the standard library's `tomllib` (3.11+); stdlib-only and
  zero-dependency stays true.

### Added
- **`sequence_extensions.config`** — the `Config` object: frozen,
  validated dataclasses for the `[flow]`, `[task]`, `[pool]`, `[run]`,
  and `[inputs]` sections.  `Config.from_toml(path)` /
  `Config.from_dict(data)` load and validate strictly: unknown sections
  and keys are errors (typo-proof), values are type-checked, and
  messages name the file, section, and key.  `log = ""` disables run
  logging (TOML has no `null`); an omitted key keeps its built-in
  default.
- **`configure(config)` / `active_config()` / `reset_config()` /
  `use_config()`** (`sequence_extensions.flow` and `.config`) — install
  a configuration for the thread; explicit decorator keywords keep
  winning.  Resolution is per call: unset `@task` keywords
  (`retries`, `retry_delay_seconds`, `timeout`), unset `@flow` keywords
  (`max_workers`, `log`, `summary`), and a bare `ProcessGraphPool()`
  resolve at call/construct time, so a config installed in `main()`
  reaches module-level decorators regardless of import order.  The
  thread substrate (`graph`) and the `ext` helpers stay config-free:
  `GraphPool` keeps its fixed default, and `@flow` sizes its own pool
  from `[flow] max_workers`.  Worker threads and timeout attempt
  threads restore the active configuration around task bodies; the
  process-pool path resolves the policy in the submitting thread and
  ships concrete values across the boundary.
- **`flow-runner`** — a console script and `python -m
  sequence_extensions.flow_runner` module.  One TOML file selects the
  module to import (`[run] module`), the flow to run (`[run] flow` or
  `--flow`), passes `[inputs]` as keyword arguments (validated against
  the flow's signature), and tunes the engine.  Flows are discovered by
  scanning the module for the `__flow__` marker `@flow` now stamps on
  its wrapper — no registry, no registration call.  `--list` prints the
  flows with their docstring summaries.  Exit codes: 0 ok, 1 flow
  failure, 2 usage/config error.  `[project.scripts]` gains the
  package's first console script.
- **`flow.last_run`** — the wrapper now records the most recent call:
  `run_id`, `status`, `log` path, `duration_ms` (concurrent calls race;
  last writer wins).  The runner reports from it.
- Task policy validation is shared: `validate_task_policy` (in
  `sequence_extensions.config`) is the one constraint check behind both
  `@task` and `Config`, with unchanged messages.
- CI matrix: Python 3.11–3.13 (3.9/3.10 dropped with the floor).

## [1.2.0] - 2026-10-14

The determinism release: the run log becomes checkable, not just
readable — see what a run did at a glance, and prove two runs executed
identically. Decision `DR-012` in the product breakdown records the
reading toolkit (`IMP-022`).

### Added
- **`RunLog.filter(records, ...)`** (`sequence_extensions.flow`) —
  select records by kind, task, status, or attempt; a record without a
  constrained field never matches; input order preserved.
- **`RunLog.summarize(records)`** — the compact account of a run: run
  level `flow`, `run_id`, and `status` (absent for an interrupted run),
  plus one entry per task — attempts, statuses in order, the last
  status, and compute time summed over executions.
- **`RunLog.diff(left, right)`** — the semantic comparison of two runs,
  the determinism check. Records are identified by what ran — task,
  inputs, attempt number (run records by kind) — never by record
  position, so fan-outs compare case by case and completion-order
  races never count. Fields in `DIFF_EXCLUDE` (record order, `run_id`,
  wall-clock, and `worker`) are dropped before comparing — wall time is
  not a determinism claim — and a future argument's `done` snapshot is
  ignored. The report is jsonable and stably ordered: `equal`,
  `only_left`, `only_right`, and `changed` (per-record differing
  fields with both values). Duplicate identities: last record wins.
- All three accept a log path or a record list; `records` itself is
  unchanged. `DIFF_EXCLUDE` is exported for composing a custom
  `exclude=` set.
- **e2e reference harness** (`tests/e2e/`) — two deterministic mock
  flows (a retrying fan-out pipeline with a verdict artifact, and a
  failing one with dependency skips) run against a committed reference
  (`tests/e2e/ref/`): logs compared with `RunLog.diff`, artifacts
  byte-for-byte.  The run id is pinned per flow and the scratch
  (`tests/e2e/out/`, one stable subtree per flow) is versioned, so
  repeated runs leave only timing-field differences — no file churn.
  A failure means behavior changed between versions;
  `UPDATE_REF=1 python -m pytest tests/e2e` regenerates the reference
  after an intended change.  The engine proves its own determinism
  claim.

## [1.1.0] - 2026-10-14

The parallelism release: local CPU-bound work parallelizes for real, and
concurrent flows in one process stop interfering. Decisions `DR-007` and
`DR-008` in the product breakdown record the substrate reopen and the
process pool.

### Added
- **`ProcessGraphPool`** (`sequence_extensions.flow`) — a `GraphPool`
  subclass driving a `ProcessPoolExecutor` behind the same
  `bind` / `result` / exit surface: `@flow(pool=ProcessGraphPool())`
  swaps local parallelism from threads to worker processes, so
  CPU-bound task bodies parallelize past the GIL. `max_workers`
  defaults to the executor's own default (the CPU count).
  - Worker-side run-log records are buffered and replayed by the flow
    at settle time, in the flow thread — the log is still complete the
    moment the flow returns.
  - Dispatch or transport failures (e.g. an unpicklable payload)
    surface as `ProcessDispatchError`; the run log records the node as
    `skipped` with reason `dispatch failed`.
  - `TaskTimeoutError` pickles across the process boundary (custom
    `__reduce__`); `@task`-decorated module-level functions pickle too
    (the raw function is aliased under a private module name at
    decoration, surviving the decorator-replaces-the-name problem).
- **`GraphPool.bind(gf)`** — a public, pure bind: submits every ready
  leaf, raises `ValueError` on a dependency cycle, never touches (or
  raises) a result — unlike the `result(gf, timeout=0)` probe.

### Changed
- **Pool exit is pool-scoped.** `GraphPool.__exit__` (and so a flow's
  pool) cancels only the nodes bound to that pool; the process-wide
  `_LIVE_NODES` sweep is removed. Concurrent flows in one process —
  each on its own pool — no longer cancel each other's work.
- Settle-time run-log records (replayed process records, `skipped`
  records for failed dependencies and cancelled nodes) are written by
  the flow thread before `run_end`, never from done-callbacks: a
  callback-side write could race `run_end` closing the log.
- Identity surfaces (README, API docs, package description, `flow`
  docstring) lead with the direction — parallel, deterministic,
  audited, local or at HPC — matching the re-authored vision.

### Deprecated
- Nothing.

### Removed
- Nothing.

### Fixed
- Nothing.

### Security
- Nothing.

## [1.0.0] - 2026-10-13

The identity release: the package is an **audit-first mini flow engine**. The
declarative workflow layer (XML schema, node tree, dynamic adaptation,
artifact store, replay, CLI) — everything accumulated under `[Unreleased]`
after 0.2.0 — is superseded before release and removed. `ext` and
`graph.graph_future` are unchanged. Rationale, benchmark evidence, and the
per-component reasoning are recorded in the product breakdown
(`docs/breakdown/`, decision `DR-005`).

### Added
- **`flow` package — the audit-first mini flow engine** built on the
  unchanged `graph.graph_future` substrate:
  - `@task(retries=, retry_delay_seconds=, timeout=, name=)` — retry,
    backoff, and timeout policy around a plain function. Plain calls run
    inline (sequential); `.submit()` schedules on the run's pool and
    returns a `GraphFuture`. Every attempt is one record in the run log.
  - `@flow(name=, max_workers=, log=, summary=, pool=)` — run identity,
    a bounded thread pool (or a caller-owned `GraphPool`, never settled
    by the flow), and a JSON-lines audit log. Drain-on-return: the log
    is complete the moment the flow returns; a failed flow cancels its
    pending tasks (recorded `skipped`) and re-raises.
  - Futures passed as submit arguments are dependency edges — general
    DAGs (diamonds included), cycles raise `ValueError` at submit time.
  - `TaskTimeoutError` — a `TimeoutError` carrying `task`, `timeout`,
    and `attempt`; raised when an attempt exceeds its budget.
  - `RunLog` — thread-safe JSON-lines writer plus a `records()` reader;
    `jsonable` serialization policy logs paths as path-plus-sha256 and
    supports a summary mode (counts, not items).
  - Run-log record kinds: `run_start`, per-attempt `task` records
    (`ok` / `error` / `timeout` / `skipped`), `run_end`; every record
    carries a monotonic `seq` and a `schema` version.
  - Acceptance test porting the four-engine benchmark campaign (six
    cases, one flaky, retried in parallel): identical verdict, 15 log
    records asserted.
- **Recipes** (documented, not shipped code): wrapping an external
  simulator with `subprocess.run(timeout=...)` returning a `Path`; an
  HPC (SLURM) `sbatch`-and-poll task using retries as the poll loop.

### Removed
- **The `workflow` subpackage** — XML schema and templates
  (`schema.py`), the function registry (`registry.py`), parameter
  normalization (`params.py`), the tree-walking engine (`engine.py`),
  dynamic adaptation (`adaptation.py`), the library functions
  (`library.py`), history and replay (`history.py`), and the artifact
  store (`artifacts.py`).
- **The generic node layer** — `graph/node.py` (`Node`, `Group`) and
  `graph/handle.py` (`TreeHandle`), which existed to declare and
  manipulate the workflow tree.
- **The CLI** — `sequence-extensions` console script, `cli.py`, and
  `__main__.py`.
- Root re-exports of the above (`Action`, `Sequential`, `Parallel`,
  `Template`, `parse_workflow`, `run_workflow`, `Test_Framework`,
  `FunctionRegistry`, `DEFAULT_REGISTRY`, `ArtifactStore`, `Node`,
  `Group`, `TreeHandle`, and related names).

### Changed
- Package description and keywords: audit-first flow engine (parallel,
  retry, audit) beside the sequence helpers.
- Test suite: 222 tests (from 666) — the 444 workflow-layer tests left
  with the layer; 69 flow tests joined; coverage 95.9%.
- Documentation: README and `docs/API.md` rewritten around `ext`,
  `graph.graph_future`, and `flow`; `docs/schema.xsd` removed; the
  product breakdown restructured (new use-case catalog CP-016..021,
  new architecture leaf INFO-011, superseded leaves tombstoned in the
  decision archive).

## [0.2.0] - 2026-09-10

### Changed
- **graph_future pool lifecycle**: fixed behavior around the `graph_future` pool lifecycle (pool teardown/cleanup semantics).
- **list/dict extension semantics**: corrected semantics of list and dict extension helpers (mapping, chaining, conversion behavior).
- **Docs**: expanded and corrected documentation.
- **CI**: added GitHub Actions CI matrix (Python 3.9–3.13) running tests, coverage, lint, format check, and build.
- **Lint**: added pre-commit hooks (ruff check + format, trailing whitespace, EOF fixer) and pinned dev dependencies.
- **Packaging**: migrated to PEP 639 license metadata, single-source the version from `sequence_extensions.__version__`, and added explicit src-layout package discovery.

## [0.1.4] - 2026-09-10

### Added
- Initial release: higher-order function extensions for Python lists, dicts, generators, and dependency-graph futures.