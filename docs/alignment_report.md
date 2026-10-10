# Vision Alignment Report

Account of how the `sequence_extensions` workflow layer now aligns with the design
principles and success criteria in
[`docs/breakdown/00-intent/vision.md`](breakdown/00-intent/vision.md), what was
built to close the gaps, and the evidence for each claim.

## 1. The vision

The paper's research question: *how can automated model verification be conducted
in a manner that is both traceable, repeatable and comprehensible?* The package
realizes the workflow layer of that answer: an XML workflow schema, a named
function registry, a Python API mirroring the XML, and a DAG execution engine
with sequential/parallel grouping, global parameter propagation, and
scope-restricted dynamic adaptation.

**Design principles** (vision.md):

1. **Hierarchical grouping** — nested `<sequential>`/`<parallel>` structures
   express complex workflows while staying readable; parallel groups mark
   independent activities for concurrent execution.
2. **Dynamic adaptation** — actions may adjust downstream actions at runtime
   (e.g. per file found), restricted to their own grouping scope; execution is
   strictly downstream (DAG, no loops) to stay deterministic.
3. **Complexity in the library, not the schema** — the workflow representation
   stays small and declarative; advanced behavior lives in the registered
   function library.
4. **Reuse via templates** — actions with parameters form templates for common
   verification scenarios, limiting duplication between workflows.

**Success criteria** (vision.md):

- **C1** — Workflows are traceable and reproducible: the full history of
  verification activities is preserved and results can be replayed.
- **C2** — The representation is perceived as clearer and easier to navigate
  than previous solutions, with less code duplication between projects.
- **C3** — Parallelization of slow activities yields major speed-ups, with
  stable behavior under scaling, clear error handling, and effective dynamic
  adaptation.

## 2. Baseline gap analysis

At the start of this work the suite had **190 passing tests**. Measured against
the vision:

| Item | Baseline status |
| --- | --- |
| Principle 1 — hierarchical grouping | Met (nested `<sequential>`/`<parallel>`, engine + tests) |
| Principle 2 — dynamic adaptation | Met (scope-restricted splicing, DAG, deterministic) |
| Principle 3 — complexity in the library | Met in principle, but the paper's library functions existed only as **test-only stubs** (`tests/resources/workflow_stubs.py`), not as shipped, registered library code |
| Principle 4 — reuse via templates | Only implicit — no template construct in the schema or API |
| C1 — traceable / reproducible / replayable | **Unmet** — the engine returned only the final result; no execution history, no replay |
| C2 — clearer representation, less duplication | Partially met — no mechanism to eliminate duplication between workflows |
| C3 — stable speed-ups under scaling | **Unmet** — no scaling-stability evidence (no concurrency, exactly-once, or speed-up tests) |

## 3. What was implemented

### 3.1 Execution history + replay — `src/sequence_extensions/workflow/history.py`

- `ExecutionRecord` — per-action evidence: registry name, resolved function,
  the **resolved** parameters the function was actually called with (globals,
  upstream results, and own params merged in engine precedence order), return
  value or exception, start/end timestamps, a deterministic completion-order
  index, and the action's path in the workflow tree (e.g.
  `root/parallel[1]/action[0]`).
- `RunHistory` — thread-safe collector the engine appends to as each action's
  call completes, so the history captures what *actually* executed, in true
  completion order.
- `replay` / `replay_records` — deterministic re-execution: every recorded
  action is re-resolved through the function registry and called again with its
  recorded parameters, sequentially, in recorded order. `replay` returns the
  same final result as the original run — reproducibility by re-execution, not
  by echoing stored results. A run whose action raised re-raises at the same
  point.
- **Opt-in**: `run_workflow` and `Test_Framework` accept a `history=` argument
  (default `None`); with no history requested the engine behaves exactly as
  before.
- Dynamic-adaptation actions spliced in at runtime are recorded as their own
  records immediately after the splicing action, marked `dynamic=True`, with
  spliced group paths — so the history reflects the tree as it stood at
  execution time.
- Tests: `tests/workflow/test_history.py` (26 tests, incl. thread-safety under
  load, spliced-action recording, replay determinism, opt-in default-off).

### 3.2 Shipped function library — `src/sequence_extensions/workflow/library.py`

- The **7 paper functions** as real, importable library code: `find_files`,
  `simulate`, `evaluate_results`, `find_test_cases`, `parameter_sweep`,
  `compare_parameter_sweep`, `compare_results`.
- `register_library(registry=None)` — explicit opt-in registration; importing
  the module leaves `DEFAULT_REGISTRY` empty, preserving the existing
  empty-default-registry contract.
- Tests: `tests/workflow/test_library.py` (registry contract, idempotency,
  per-function behavior).

### 3.3 Templates — `src/sequence_extensions/workflow/schema.py`

- Python API: `Template(name, body, **defaults)` holds a reusable subtree;
  `Template.instantiate(**params)` returns a **new** node tree with every
  `{placeholder}` in an action parameter value bound, so the same template
  instantiated with different parameters yields distinct, independent trees.
  Resolution is strict: every placeholder must resolve to a binding, a default,
  or a same-named global parameter.
- XML: `<template name="...">` (one body group plus `<argument>` defaults)
  defined directly inside `<VerificationWorkflow>`; `<use-template name="...">`
  (with `<argument>` bindings) anywhere a group may appear, including inside
  other template bodies. Expansion happens at **parse time** —
  `parse_workflow` returns a tree of plain `Action`/`Sequential`/`Parallel`
  nodes, exactly what the equivalent inline workflow produces — so the engine,
  history recording, and dynamic adaptation are unchanged.
- Binding precedence: **use-site binding > template default > same-named
  workflow global**.
- 13 new invalid-XML rejection rules (`ValueError`, same style as existing
  schema errors): `<template>` without a name / without a body / with more than
  one body / with a duplicate default key / with an unknown child element;
  duplicate template names; `<template>` inside a grouping; `<use-template>`
  without a name / naming an unknown template / with an unknown or duplicate
  child element / binding an undeclared parameter / leaving a required
  parameter unbound.
- Tests: `tests/workflow/test_templates.py`, with fixtures
  `tests/resources/workflows/template_reuse.xml`, `template_parallel.xml`, and
  13 invalid fixtures under `tests/resources/workflows/invalid/`.

### 3.4 Scaling-stability tests — `tests/workflow/test_scaling.py`

- **True concurrency**: N=16 actions on a `threading.Barrier(16)` that only
  releases when a full wave of workers is in flight simultaneously — a
  sequential engine would time the barrier out and fail the test.
- **Stable under scaling**: full 16-worker barrier waves satisfied at
  N = 16, 64, 128, 192, with **exactly-once execution** and **deterministic,
  correct results** at every size; all waits bounded by a generous barrier
  timeout so a real deadlock is caught without flakiness on a loaded machine.
- **Speed-up vs sequential**: parallel wall-time must be < 0.5× the sequential
  baseline (≥2× speed-up margin; ideal is ~16× with the 16-worker pool).
- **Nested parallel** scaling covered as well.

## 4. Verification evidence

- **Test suite: 295 passed** (baseline 190 → 295), stable across repeated runs
  (7 consecutive runs in the verification report, zero warnings, no flakiness;
  re-confirmed: `python3 -m pytest -q` → `295 passed in 2.11s`).
- **Lint**: `ruff check .` and `ruff format --check .` clean (43 files
  formatted).
- **Zero runtime dependencies** (`pyproject.toml` `dependencies = []`; dev
  extras only) and **Python ≥ 3.9 compatible** (all new/alignment files parse
  under `feature_version=(3, 9)`).
- **Cross-feature integration**: `tests/workflow/test_integration_alignment.py`
  proves all four features compose in **one XML workflow** — a
  `<template>`/`<use-template>` pair expanded at two use sites, every action
  resolved from `workflow/library.py` via `register_library()`, run with
  `history=RunHistory()` (5 records in completion order, template-bound
  parameters carried), and `replay(history)` re-executing the recorded calls to
  a result identical to the original run's final result.
- **Change set**: 9 modified files (+549/−30, all additive integration points:
  exports, engine history hooks, schema template support, docs/changelog,
  test-package plumbing) and 22 new files (the two feature modules, five test
  modules, and 15 XML fixtures). No changes to `ext/`, `graph/`, or any
  pre-existing test file.

## 5. Status after this work

| Vision item | Status | Evidence |
| --- | --- | --- |
| P1 — hierarchical grouping | ✅ Met (unchanged, still covered) | `workflow/schema.py`, `workflow/engine.py`, existing suite |
| P2 — dynamic adaptation | ✅ Met (F1/F2 now addressed) | `workflow/engine.py` (lazy tree-walking walker) + `workflow/adaptation.py` (scoped `DAGHandle`: read / adjust / copy-to-end within the action's own scope); branching + iteration in `workflow/library.py` (`evaluate_goal`, `check_convergence`); spliced actions visible in history (`history.py`, `test_history.py`) |
| P3 — complexity in the library, not the schema | ✅ Met | `workflow/library.py` (7 paper functions, opt-in `register_library()`), `test_library.py` |
| P4 — reuse via templates | ✅ Met | `workflow/schema.py` (`Template`, `.instantiate()`, `<template>`/`<use-template>`), `test_templates.py`, 15 fixtures |
| C1 — traceable, reproducible, replayable | ✅ Met | `workflow/history.py` (`ExecutionRecord`, `RunHistory`, `replay`), `test_history.py`, `test_integration_alignment.py` |
| C2 — clearer representation, less duplication | ✅ Met | Templates eliminate duplicated scenario subtrees (parse-time expansion keeps the schema small and declarative); `template_reuse.xml` |
| C3 — stable speed-ups under scaling | ✅ Met | `test_scaling.py` (barrier-proven concurrency, N=16–192 exactly-once + deterministic, ≥2× speed-up margin, nested parallel) |
