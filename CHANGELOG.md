# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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