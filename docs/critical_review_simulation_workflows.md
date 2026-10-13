# Critical Review — Workflow Implementation vs. the Paper and Custom Simulation Workflow Requirements

**Date:** 2026-10-12
**Scope:** `src/sequence_extensions/workflow/` and `src/sequence_extensions/graph/`, reviewed against `docs/references/paper_44_yBqbPyj1.pdf` ("Automation Nation: Taming Complex V&V Workflows", Rosenlund, Hällqvist, Braun, Krus, Modelica & FMI Conference 2025) and `docs/breakdown/00-intent/vision.md`.
**Purpose:** record the findings so they can be turned into patches later. (At review time the new findings had no IMP number; they were filed as IMP-016 on 2026-10-13 — see the RESOLUTION blocks.)
**Baseline at review time:** 515 tests passed (`python3 -m pytest -q`), working tree at commit `a453e6f`.
**Resolution (2026-10-13):** all findings below are patched and verified; the new findings are filed as IMP-016. Each section carries a RESOLUTION block; the suite now stands at 666 passed, 0 failed.

## Method

Read the paper via the repo's extracted summaries (`.dynamic-harness/261010_090045_b8c9/artifacts/*/paper44_summary.md`, `analysis_paper_scenarios.md`) plus `vision.md`; read the full `workflow/` and `graph/` source; read the five selected patch batches IMP-009…IMP-013 to separate known from new findings. Wrote four probe workflows to verify suspected behaviors (probe scripts reproduced below in "Verification probes").

Findings are marked **[verified]** (measured or reproduced by running code) or **[known]** (already recorded in a selected IMP — listed here only for completeness, not for re-filing).

## Verdict

The engine core is sound and arguably better engineered than the paper's full-DAG-passing design: scoped-handle adaptation, transactional commit, at-most-once, bounded adaptation, opt-in history and artifact store with structural addressing. One **untracked critical gap** breaks the paper's central value proposition, and a cluster of papercuts matters specifically when a user runs *real* simulations through this library.

**Resolution (2026-10-13):** every finding below has been patched and verified against the working tree — the critical fan-out gap is closed (4× measured speed-up), the IMP-009 residual gaps are fixed, and the new findings are filed as **IMP-016** (the user-requested IMP-015 was already taken by `scope-only-xml-vocabulary.md`). Suite: 666 passed, 0 failed (baseline at review time: 515).

| # | Finding | Severity | Status |
|---|---|---|---|
| 1 | Dynamic fan-out executes clones sequentially — no speed-up for runtime-sized campaigns | Critical | **Resolved** — `fan_out_parallel` + `parallel=True` (IMP-016) |
| 2 | By-name kwargs data plane crashes / miscounts on prefix-colliding names | High | **Resolved** — IMP-009 fix verified, 3 residual gaps patched (IMP-016) |
| 3 | XML parameters arrive as untyped strings; no per-function parameter schema | High | **Resolved** — `param_types` + `coerce_params` (IMP-016) |
| 4 | No error capture around real bodies; `try_action` cannot see upstream data | Medium-High | **Resolved** — per-scope `on_error="capture"` (IMP-016) |
| 5 | No per-action timeout, no fail-fast cancellation of in-flight siblings | Medium-High | **Resolved** — `action_timeout` + `fail_fast` (IMP-016) |
| 6 | GIL-bound threads, non-configurable pool/bound, unbounded branch threads | Medium | **Resolved** — branch-thread bound (IMP-016); GIL/pool items remain IMP-012 |
| 7 | Run identity, history persistence, manifest timestamps, seed metadata | Medium | **Resolved** — manifest header, `RunHistory` JSON, `randomize_scenarios` (IMP-016); run identity remains IMP-010/011 |
| 8 | Docs imply swept campaigns run as "parallel groups" — they run sequentially | Medium | **Resolved** — wording fixed with finding 1 (IMP-016) |

## 1. Dynamic fan-out cannot parallelize [verified, new — critical]

Measured with a 0.3 s action (probe `fanout_test.py`):

```text
parameter_sweep with 4 clones:      1.21 s   ← sequential (4 × 0.3 s)
static <parallel> with same 4:      0.31 s   ← concurrent
replace inside following parallel:  0.30 s   ← concurrent (hand-rolled)
spliced Parallel(*clones) wrapper:  0.31 s   ← concurrent (hand-rolled)
```

**Cause.** `TreeHandle.fan_out` (`src/sequence_extensions/graph/handle.py:284-308`) replaces the declared downstream group with N clones as siblings in the actor's parent. The actor's parent must be `Sequential` (writes are rejected in `Parallel` scopes, `src/sequence_extensions/workflow/adaptation.py:197-204`), and `_walk_spliced` (`src/sequence_extensions/workflow/engine.py:482-527`) walks those siblings one at a time, blocking on each. Every shipped fan-out driver (`find_files`, `parameter_sweep`, `src/sequence_extensions/workflow/library.py:139-170, 207-242`) therefore produces strictly serial execution.

**Why it matters.** The paper's UC1 step 3 is "Simulate the different variants **in parallel**" (§3.1.1); UC2's generated scenarios "can all be executed in parallel" (§3.1.2); UC3 is batch-parallel iteration (§3.1.3); resource utilization is a named requirement (§3.2). Dynamic adaptation exists precisely for counts unknown at authoring time — exactly the case that now gets zero speed-up. The paper's two headline principles (dynamic adaptation + parallel grouping) never compose in this implementation. UC3's batch-sequential pattern (parallel batch → barrier → goal check → next batch) is not expressible at all.

**The engine already supports the fix — both shapes verified:**

- A spliced `Parallel(*clones)` wrapper runs its children concurrently (`_walk_spliced` → `_walk_group` → `_walk_parallel`).
- An action in a sequential scope may adapt *inside a following parallel group's subtree* (replace its placeholder child with N clones) — allowed by `_revalidate` (`src/sequence_extensions/workflow/engine.py:788-813`).

**Recommended change (in order of preference):**

1. Add `fan_out(overrides, *, mode="sequential"|"parallel")` (or a separate `fan_out_parallel`) to `TreeHandle`/`DAGHandle`, emitting one `Parallel` wrapper containing the clones. Engine needs no changes.
2. Give `parameter_sweep` and `find_files` a `parallel=True` option, or document the idiom: declare a following `<scope type="parallel">` containing the body once.
3. With that, UC3 becomes expressible: `while_condition` + parallel fan-out per iteration.
4. Until fixed, state the sequential semantics in the `fan_out`, `find_files`, `parameter_sweep` docs.

Note: `ADAPTATION_BOUND` (10 000) counts fan-out clones, so a 20 000-point sweep dies at the bound even sequentially — tracked by IMP-012, but it compounds this gap.

**RESOLUTION (2026-10-13).** Resolved, filed in IMP-016. `TreeHandle.fan_out_parallel(overrides)` splices the clones as direct children of the declared parallel scope, and `parameter_sweep`/`find_files` gained a `parallel=True` option (default `False` — sequential semantics preserved and documented, per rec 4). Measured 4× speed-up: 0.303 s vs 1.209 s for 4 × 0.3 s sims (probe 1 now passes in parallel mode). 15 tests in `tests/workflow/test_parallel_fanout.py`. **Deviations from the preferred fix above:** no `Parallel` wrapper node — a wrapper loses all clone results downstream (data-plane evidence); the implemented shape is rec 2's idiom, which the engine already ran concurrently. A separate method rather than a `mode` kwarg, to keep `ReplayHandle` replay-compatible.

## 2. Data plane: by-name kwargs [known, IMP-009 — confirmed]

Independently reproduced before reading IMP-009:

- `_upstream_field({"evaluate": …, "evaluate_results": …}, "evaluate", …)` raises `ValueError: invalid literal for int() with base 10: 'results'` (`src/sequence_extensions/workflow/library.py:869-897`). Any kwarg sharing the `<upstream>_` prefix without a numeric tail crashes every driver (`evaluate_goal`, `guard`, `while_condition`, `retry`, `fallback`).
- `_upstream_count({"simulate": …, "simulate_2": …, "simulate_seed": 42}, "simulate")` returns 3 (`src/sequence_extensions/workflow/library.py:900-911`) — iteration drivers silently miscount and can loop once too often or stop early.

Additional design point beyond IMP-009's regex fix: three namespaces are flattened into one — globals, own params, and upstream results keyed by **function name** (not action identity) with ad-hoc suffixes. Even after the fix, two actions calling the same function are distinguishable only by position-derived suffixes, and an action parameter named like an upstream function silently shadows it (precedence: own > upstream > globals). Consider a structured results view handed to functions (keyed by action identity), or engine-computed suffix bookkeeping exposed to drivers. That would also make `aggregate`/`regression_gate`'s all-suffixed scans (`library.py:914-952`) principled rather than heuristic.

**RESOLUTION (2026-10-13).** Verified, and the residual gaps patched (IMP-016). Probe 2 now passes. The initial IMP-009 patch was incomplete — three residual gaps were found and fixed via a single contiguous-walk primitive (`_upstream_keys`): (a) the `isdigit`/unicode-digit crash class, (b) engine-impossible suffixes like `sim_1` could silently override branch decisions, (c) scan/walk inconsistency between `_upstream_count`/`_upstream_field` and `_upstream_all`/`_upstream_keys`. 15 regression tests. **Known limitation (unchanged, IMP-009 §2):** a contiguous same-suffixed own param is indistinguishable from a genuine result without engine bookkeeping — the structured-results-view design point above remains open.

## 3. Custom-simulation papercuts [new]

What a user hits on day one wrapping a real simulator:

- **XML values are strings; only `values` is normalized** (`src/sequence_extensions/workflow/params.py:61-71`). A custom `simulate(duration=10)` driven from XML receives `"10"`. The library coerces its own operands ad hoc (`_coerce_operand`, `library.py:1142-1160`); user functions must hand-roll coercion for every numeric parameter. Recommendation: optional per-function parameter schema at registration (names/types/defaults) with generic coercion at injection. Also makes history/manifest params unambiguous plain data (helps IMP-010).
- **No execution helper for external simulators.** Real `simulate` is a subprocess (FMI co-sim, Modelica tool, HPC job). The stdlib-only deterministic library is defensible, but nothing shows the canonical pattern (subprocess + timeout + exit-code-to-result + write payload to `artifacts.out_dir()` + return pointer). Recommendation: a documented example or optional recipe module. This is the paper's "easy implementation of verification activities" requirement (§3).
- **`try_action` cannot wrap a real body.** It invokes a named function with exactly static `params` (`library.py:348-392`) — no upstream results, no globals, no adaptation, single function (not a group). Error-reactive simulation scenarios (retry a data-dependent simulation) need bespoke drivers. Root cause flagged in `docs/dynamic_scenarios_analysis.md` §2.3 ("no per-node exception capture ... root blocker"). Recommendation: an engine-level opt-in error policy (per-scope `on_error="capture"` turning exceptions into data) composes with `retry`/`fallback` and matches paper P3 (branch on failures) more directly than the `try_action` workaround.
- **No per-action timeout.** A hung simulator blocks a pool worker forever. `GraphPool.result` supports timeouts (`src/sequence_extensions/graph/graph_future.py`) but the engine never applies one. Needed for unattended automation (paper requirement). Should land with IMP-012's executor work: per-action or per-scope wall-clock budget.
- **No fail-fast cancellation.** `_walk_parallel` waits for ALL children to settle before re-raising the first error (`engine.py:429-455`). One early failure still pays for every sibling. At minimum make the policy configurable ("fail fast, cancel unwalked work" vs "drain then report").
- **Zero observability, no CLI.** No `logging` anywhere in `src/`; no `console_scripts` in `pyproject.toml`. Unattended runs are silent until they end. Small, high-leverage adds for the automation requirement.

**RESOLUTION (2026-10-13).** All six papercuts resolved, filed in IMP-016:

- **Typed params (F3a):** `param_types` at registration + `params.coerce_params` + `ParameterCoercionError`; 9 tests. **Deviation:** history/manifest record the raw pre-coercion params — typed values are delivered at the function-call boundary.
- **External-simulator recipe (F3b):** "Wrapping an external simulator" recipe in `docs/API.md` (subprocess + timeout, exit-code mapping, artifacts to `out_dir`, pointer return; worked generic + FMI examples; recipe, not a dependency).
- **Error capture (F3c):** per-scope `on_error="capture"` (engine policy, XML surface) producing a `CapturedError` object (`is_error`/`ok`/`function`/`error_type`/`error`/`timeout`); retry/fallback run first, capture last; composes with `fail_fast` and `action_timeout`; `KeyboardInterrupt`/`SystemExit` never captured. `try_action` deprecated with a migration note. 24 tests.
- **Per-action timeout (F3d):** `run_workflow(action_timeout=…)` raising `ActionTimeoutError(TimeoutError)` naming the action, the timeout, and the option; 17 tests. **Notes:** hung workers are abandoned (threads are unkillable) and the engine-owned pool is torn down without waiting; abandoned workers can block interpreter exit (documented); `GraphPool` lacks a public non-blocking shutdown (the engine reaches into privates — cleanup candidate).
- **Fail-fast (F3e):** `run_workflow(fail_fast=False)` default drains then reports; `True` skips/cancels unwalked siblings and raises the first error promptly; the `_SKIPPED` sentinel is handled in the data plane. 13 tests.
- **CLI + logging (F3f):** `src/sequence_extensions/cli.py` with a `console_scripts` entry and `python -m` support, campaign-level logging, `--history-out` (RunHistory JSON), `--artifacts-dir` (manifest shares the run's `run_id`). 7 tests.

## 4. Traceability & reproducibility (paper C1 / P24)

Known and tracked: live `dag` handle in `record.params` and replay not verifying function identity (IMP-010); no run identity, O(n²) params memory (IMP-011 — confirmed structural: every downstream record embeds all upstream results; the artifact store only helps when functions opt in).

Not yet tracked:

- **Manifest entries carry no timestamps** (`src/sequence_extensions/workflow/artifacts.py:432-443`: `seq`, `address`, `function`, `params`, `dynamic`). Wall-clock evidence exists only in `ExecutionRecord`, and history/artifacts are separate opt-ins. Add timestamps (and a run header) to the manifest.
- **`RunHistory` has no persistence** — no `to_json`/`from_json`. Traceability that lives only in process memory is not traceability for regression campaigns. A plain-data serializer needs the IMP-010 handle-stripping fix and a defined policy for non-JSON params.
- **No seed/randomization convention** (paper P16/UC2, §3.1.2). The library is deliberately deterministic, but the paper allows Monte Carlo *if* the full scenario or recreation metadata (method, seed) is stored. No `randomize_scenarios(method, seed)` driver exists (recommended in `docs/dynamic_scenarios_analysis.md` §5 but not built), and no seed field in records/manifest. UC2 is half-supported.

**RESOLUTION (2026-10-13).** All three untracked items resolved, filed in IMP-016:

- **Manifest timestamps (F4c):** run header (`run_id`, `started_at`, derived `ended_at`) + per-entry timestamps; 4 tests.
- **History persistence (F4d):** `RunHistory.to_json()`/`from_json()` with a typed-placeholder policy for non-JSON params; byte-stable double round-trip; 6 tests.
- **Seed/randomization (F4e):** `randomize_scenarios(method, seed, count, options)` driver (dedicated `random.Random(seed)`, cross-interpreter determinism verified) + `RunHistory.seed` round-tripped; 10 tests. **Residual gaps:** the manifest does not carry the seed, and there is no engine auto-stamp of `history.seed` — the caller sets it.

## 5. Execution substrate

Known (IMP-012): hardcoded `ThreadPoolExecutor` (GIL-bound simulation code gets no speed-up; the barrier-based scaling test is structurally blind to this since sleeps release the GIL), non-configurable `max_workers=16`/`ADAPTATION_BOUND`, `except Exception` swallowing `BaseException` in the parallel walk.

New:

- **Nested parallel groups spawn unbounded raw threads.** Group children of a `Parallel` run on plain `threading.Thread`s, one per branch (`engine.py:416-426`). Deeply nested, wide campaigns create threads multiplicatively. The daemon-thread choice avoids pool starvation, not thread explosion. Bound it or reuse a walk executor.
- **HPC/distributed (paper P19)** is out of scope per `INFO-001` — fine — but once IMP-012 makes the executor pluggable, document the registry-function-as-remote-job pattern. Today there is no story for a user who needs to leave one machine.

**RESOLUTION (2026-10-13).** The new thread-growth item is resolved (IMP-016): `BRANCH_THREAD_BOUND=32` engine-wide semaphore with non-blocking acquire + inline fallback — flat parallelism is fully concurrent, and the bound composes with `fail_fast`/`action_timeout`. 6 tests. The known IMP-012 items (GIL-bound `ThreadPoolExecutor`, non-configurable `max_workers`/bound, `BaseException` swallowing) remain tracked there; the `BaseException` half was probed and found **correct as-is** — `BaseException` from parallel children is re-raised as the original type (5 cases: `KeyboardInterrupt`, `SystemExit`, nested, sequential control, KI+timeout) — so no fix was needed. The HPC/distributed item is unchanged — still out of scope per `INFO-001`.

## 6. Paper-fidelity nuances [new]

- The **read-only parallel handle** is narrower than the docs suggest, in a good way: an action whose *direct* parent is an inner `Sequential` nested in a parallel group CAN adapt (verified — probe `verify2.py` xml2). The error message "runs inside a parallel scope, whose handle is read-only" (`adaptation.py:197-204`) and `docs/API.md:1118` read as a blanket prohibition. Document the wrap-your-branch-in-a-scope idiom — it is the only way to get per-branch adaptation today.
- `docs/API.md:1191` describes clone directories as "clone 1 of a swept parallel group" — the clones run one after another (see finding 1). Fix the doc alongside the fix.
- The deviation ledger itself is good (scoped handle vs. full DAG, copy-to-end vs. loops, read-only parallel vs. negotiated merges are reasoned and documented; IMP-013 plans to surface the divergence table). Include the two biggest *behavioral* deviations from the paper's examples there: sequential fan-out (finding 1) and the parallel-branch restriction.

**RESOLUTION (2026-10-13).** All three nuances resolved, filed in IMP-016:

- **F6a:** the error message and `docs/API.md` now state the direct-parent rule precisely, and the inner-scope idiom is documented with a verified example (probe 4). 1 regression test.
- **F6b:** resolved with finding 1 — the "clone 1 of a swept parallel group" wording in `docs/API.md` is fixed to match the now-parallel semantics.
- **F6c:** IMP-013's "Deviations from the paper" table now carries the two behavioral deviations (sequential-by-default fan-out; inner-scope requirement for per-branch adaptation).

## 7. Prioritized recommendations

(2026-10-13: items 1, 3, 4, 5-new, and 6 are implemented — see the RESOLUTION blocks above; item 2's timeout/fail-fast half landed with IMP-016, the executor-pluggable half remains IMP-012. The list is kept as the original prioritization.)

1. **P0 — Parallel fan-out** (finding 1): `fan_out(mode="parallel")` + `parameter_sweep`/`find_files` support + doc honesty. Restores the paper's core composition. Engine changes: none.
2. **P0 — Land IMP-012** (executor pluggable, configurable `max_workers`/bound, `BaseException`), folding in per-action **timeout** + fail-fast policy (finding 3).
3. **P1 — IMP-009** (upstream matching, template/`parameters=` precedence, reserved-name warnings) — confirmed by independent reproduction.
4. **P1 — Parameter typing/schema at registration** (finding 3) with generic XML coercion — the biggest day-one papercut for custom functions.
5. **P1 — IMP-010/011** (record plainness, function-identity check on replay, run identity, by-reference params) **plus** manifest timestamps and a `RunHistory` serializer (finding 4).
6. **P2 — Engine-level error capture policy** (per-scope `on_error`); seed metadata convention for UC2; logging + CLI entry point; bound nested-parallel threads; document the inner-sequential adaptation idiom.

## Verification probes

Reproduce the key claims before patching (all against the working tree at review time):

```python
# 1) fan_out is sequential; static parallel and hand-rolled shapes are not.
#    See docs/critical_review_simulation_workflows.md section 1 timings.
import time
from sequence_extensions.workflow.registry import FunctionRegistry, workflow_function
from sequence_extensions import run_workflow
from sequence_extensions.workflow.library import register_library

reg = FunctionRegistry(); register_library(reg)

@workflow_function(registry=reg)
def sim(**kwargs):
    time.sleep(0.3)
    return {"sim": True}

xml = """<VerificationWorkflow><scope type="sequential">
  <action function="parameter_sweep">
    <argument key="parameter_name" value="p"/><argument key="values" value="1, 2, 3, 4"/>
  </action>
  <scope type="parallel"><action function="sim"/></scope>
</scope></VerificationWorkflow>"""
t0 = time.time(); run_workflow(xml, registry=reg)
assert time.time() - t0 > 1.0   # sequential: 4 x 0.3 s measured 1.21 s

# 2) Upstream-name crash and miscount (independently reproduced; tracked by IMP-009).
from sequence_extensions.workflow.library import _upstream_field, _upstream_count
try:
    _upstream_field({"evaluate": {"g": 1}, "evaluate_results": {"n": 1}}, "evaluate", "g")
except ValueError as e:
    assert "invalid literal for int()" in str(e)
assert _upstream_count({"simulate": 1, "simulate_2": 1, "simulate_seed": 42}, "simulate") == 3  # wrong: should be 2

# 3) Parallel shapes the engine already runs concurrently (fix targets for finding 1):
#    - dag.replace(body, [Parallel(*clones)])          -> measured 0.31 s for 4 x 0.3 s
#    - dag.replace(child_inside_following_parallel, clones) -> measured 0.30 s
# 4) Adaptation inside a parallel branch via inner sequential scope: works (no error).
```

**Current results (2026-10-13, post-patch):** probe 1 — the same `parameter_sweep` XML with `parallel=True` now runs in **0.303 s** (was 1.209 s sequential); probe 2 — **passes** (no crash, correct count); probe 3 — unchanged (the engine shapes were always concurrent); probe 4 — the inner-scope idiom is now documented in `docs/API.md` with a verified example.

## Relation to existing tracking

- IMP-009 (kwargs precedence/upstream matching/reserved names), IMP-010 (history record evidence), IMP-011 (run identity, quadratic params), IMP-012 (engine resources/exception contract), IMP-013 (docs parity) — all confirmed valid by this review; several items independently reproduced. No duplication intended: those findings are theirs.
- **IMP-016** (`docs/breakdown/06-evolution/implemented/simulation-campaign-findings-parallel-fan-out-typed-params-timeouts-fail-fast-traceability-docs.md`) — filed 2026-10-13, carries everything marked **New** above (findings 1, 3, 5, 6-new, 7-new, 8 plus the IMP-009 residual gaps). Fully implemented; moved to `implemented/` 2026-10-13. Note: the user requested IMP-015, but that number was already taken by `scope-only-xml-vocabulary.md`, so the findings were filed as IMP-016 per pb conventions.
- This file was the holding record until the new findings were filed; it now stands as the review record with per-finding RESOLUTION blocks.
