---
id: IMP-016
type: imp
title: Simulation-campaign findings: parallel fan-out, typed params, timeouts, fail-fast, traceability, docs
summary: The 2026-10-12 critical review's new findings (parallel fan-out, parameter typing, external-sim recipe, error capture, timeout, fail-fast, logging/CLI, manifest timestamps, history serializer, seed, nested parallelism, docs) filed with implementation status.
date: 2026-10-13
status: current
---

# Simulation-campaign findings: parallel fan-out, typed params, timeouts, fail-fast, traceability, docs

Files the 2026-10-12 critical review's **new** findings (no IMP at review time) as tracked evolution state, tied to the implementation. Source: `docs/critical_review_simulation_workflows.md`. Known findings (IMP-009 to IMP-013) are out of scope — the review's no-duplication rule.

## Scope

- **In** — the review's findings tagged New with no IMP: F1, F3a to F3f, F4c to F4e, F5b, F6a to F6c.
- **Out** — known findings already tracked by IMP-009 to IMP-013 (review finding 2, and the known parts of findings 4, 5, 6).
- **Out** — HPC / distributed execution (review finding 5, second item): out of scope per `INFO-001`.

## Findings and status

Status per finding. All findings resolved; suite result in Verification.

### F1 — Parallel fan-out (review finding 1) — DONE
- `TreeHandle.fan_out_parallel` + `parallel=True` on `parameter_sweep` / `find_files`.
- 15 tests: `tests/workflow/test_parallel_fanout.py`.
- 4x speed-up: 0.303 s vs 1.209 s for 4 x 0.3 s sims.
- **Deviations**
  - Clones spliced as direct children of the declared parallel scope (a `Parallel` wrapper loses clone results downstream — data-plane evidence).
  - Separate method, not a `mode` kwarg (ReplayHandle replay compat).

### F3a — Parameter schema + coercion (review finding 3) — DONE
- `param_types` at registration; `params.coerce_params`; `ParameterCoercionError`.
- 9 tests.
- **Deviation** — history/manifest record raw pre-coercion params (typed values at the function-call boundary).

### F3b — External-simulator execution recipe (review finding 3) — DONE
- `docs/API.md` "Wrapping an external simulator" recipe: subprocess + timeout, exit-code-to-result, artifacts to `out_dir`, pointer return; worked generic + FMI examples; recipe-not-dependency statement; cross-refs `action_timeout`.

### F3c — Engine error-capture policy / `try_action` real body (review finding 3) — DONE
- Per-scope `on_error="capture"` in `engine.py` + `schema.py`/`schema.xsd` + `docs/API.md`; `CapturedError` (`is_error`/`ok`/`function`/`error_type`/`error`/`timeout`).
- Retry/fallback first, capture last; composes with `fail_fast`/`action_timeout`; `KeyboardInterrupt`/`SystemExit` never captured; `try_action` deprecated with migration note. 24 tests.

### F3d — Per-action timeout (review finding 3) — DONE
- `run_workflow(action_timeout=...)`; `ActionTimeoutError`.
- 17 tests.
- **Notes**
  - Abandoned-worker semantics: threads unkillable, engine-owned pool torn down without wait; abandoned workers can block interpreter exit.
  - `GraphPool` lacks public non-blocking shutdown (engine reaches into privates — cleanup candidate).

### F3e — Fail-fast policy (review finding 3) — DONE
- `run_workflow(fail_fast=False)` default drain-then-report; `True` skips unwalked siblings, raises first error promptly; `_SKIPPED` handled in data plane. 13 tests.

### F3f — Logging + CLI (review finding 3) — DONE
- `src/sequence_extensions/cli.py` + `__main__.py` + `console_scripts` entry; campaign-level logging; `--history-out` / `--artifacts-dir`. 7 tests.

### F4c — Manifest timestamps + run header (review finding 4) — DONE
- Run header (`run_id`, `started_at`, derived `ended_at`) + per-entry timestamps.
- 4 tests.

### F4d — `RunHistory` serializer (review finding 4) — DONE
- `to_json` / `from_json` with typed-placeholder policy for non-JSON params.
- 6 tests.

### F4e — Seed convention (review finding 4) — DONE
- `randomize_scenarios(method, seed, count, options)` driver + `RunHistory.seed`.
- 10 tests; cross-interpreter determinism verified.
- **Gaps**
  - Manifest does not carry the seed.
  - No engine auto-stamp of `history.seed`.

### F5b — Bounded nested parallelism (review finding 5) — DONE
- `BRANCH_THREAD_BOUND=32` engine-wide semaphore; non-blocking acquire + inline fallback; flat parallelism fully concurrent. 6 tests.

### F6a — Read-only parallel docs (review finding 6) — DONE
- Error message + `docs/API.md` state the direct-parent rule and the inner-scope idiom.
- Verified probe; 1 regression test.

### F6b — "Swept parallel group" wording (review finding 6) — DONE
- Fixed with F1.

### F6c — Deviation ledger (review finding 6) — DONE
- The two biggest behavioral deviations added to IMP-013's deviation table.

## Related fixes
- `parallel_example.xml` fixture repaired: type-less 2-child scope vs IMP-014 rule (1-line fix).

## Verification

- `python3 -m pytest -q`: 666 passed, 0 failed (review baseline 515).
- `pb check --strict` green.

## Owns
- The review's new findings, filed with implementation status.

## Excludes
- Known findings: IMP-009 to IMP-013.
- HPC / distributed: `INFO-001`.
