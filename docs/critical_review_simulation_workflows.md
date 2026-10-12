# Critical Review — Workflow Implementation vs. the Paper and Custom Simulation Workflow Requirements

**Date:** 2026-10-12
**Scope:** `src/sequence_extensions/workflow/` and `src/sequence_extensions/graph/`, reviewed against `docs/references/paper_44_yBqbPyj1.pdf` ("Automation Nation: Taming Complex V&V Workflows", Rosenlund, Hällqvist, Braun, Krus, Modelica & FMI Conference 2025) and `docs/breakdown/00-intent/vision.md`.
**Purpose:** record the findings so they can be turned into patches later. Not yet an IMP; the new findings below have no IMP number assigned yet.
**Baseline at review time:** 515 tests passed (`python3 -m pytest -q`), working tree at commit `a453e6f`.

## Method

Read the paper via the repo's extracted summaries (`.dynamic-harness/261010_090045_b8c9/artifacts/*/paper44_summary.md`, `analysis_paper_scenarios.md`) plus `vision.md`; read the full `workflow/` and `graph/` source; read the five selected patch batches IMP-009…IMP-013 to separate known from new findings. Wrote four probe workflows to verify suspected behaviors (probe scripts reproduced below in "Verification probes").

Findings are marked **[verified]** (measured or reproduced by running code) or **[known]** (already recorded in a selected IMP — listed here only for completeness, not for re-filing).

## Verdict

The engine core is sound and arguably better engineered than the paper's full-DAG-passing design: scoped-handle adaptation, transactional commit, at-most-once, bounded adaptation, opt-in history and artifact store with structural addressing. One **untracked critical gap** breaks the paper's central value proposition, and a cluster of papercuts matters specifically when a user runs *real* simulations through this library.

| # | Finding | Severity | Status |
|---|---|---|---|
| 1 | Dynamic fan-out executes clones sequentially — no speed-up for runtime-sized campaigns | Critical | New [verified] |
| 2 | By-name kwargs data plane crashes / miscounts on prefix-colliding names | High | Known (IMP-009) — independently reproduced |
| 3 | XML parameters arrive as untyped strings; no per-function parameter schema | High | New |
| 4 | No error capture around real bodies; `try_action` cannot see upstream data | Medium-High | Partially known (`docs/dynamic_scenarios_analysis.md` flags the blocker) |
| 5 | No per-action timeout, no fail-fast cancellation of in-flight siblings | Medium-High | New |
| 6 | GIL-bound threads, non-configurable pool/bound, unbounded branch threads | Medium | Known (IMP-012) + new thread-growth item |
| 7 | Run identity, history persistence, manifest timestamps, seed metadata | Medium | Mostly known (IMP-010/011) + new additions |
| 8 | Docs imply swept campaigns run as "parallel groups" — they run sequentially | Medium | New |

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

## 2. Data plane: by-name kwargs [known, IMP-009 — confirmed]

Independently reproduced before reading IMP-009:

- `_upstream_field({"evaluate": …, "evaluate_results": …}, "evaluate", …)` raises `ValueError: invalid literal for int() with base 10: 'results'` (`src/sequence_extensions/workflow/library.py:869-897`). Any kwarg sharing the `<upstream>_` prefix without a numeric tail crashes every driver (`evaluate_goal`, `guard`, `while_condition`, `retry`, `fallback`).
- `_upstream_count({"simulate": …, "simulate_2": …, "simulate_seed": 42}, "simulate")` returns 3 (`src/sequence_extensions/workflow/library.py:900-911`) — iteration drivers silently miscount and can loop once too often or stop early.

Additional design point beyond IMP-009's regex fix: three namespaces are flattened into one — globals, own params, and upstream results keyed by **function name** (not action identity) with ad-hoc suffixes. Even after the fix, two actions calling the same function are distinguishable only by position-derived suffixes, and an action parameter named like an upstream function silently shadows it (precedence: own > upstream > globals). Consider a structured results view handed to functions (keyed by action identity), or engine-computed suffix bookkeeping exposed to drivers. That would also make `aggregate`/`regression_gate`'s all-suffixed scans (`library.py:914-952`) principled rather than heuristic.

## 3. Custom-simulation papercuts [new]

What a user hits on day one wrapping a real simulator:

- **XML values are strings; only `values` is normalized** (`src/sequence_extensions/workflow/params.py:61-71`). A custom `simulate(duration=10)` driven from XML receives `"10"`. The library coerces its own operands ad hoc (`_coerce_operand`, `library.py:1142-1160`); user functions must hand-roll coercion for every numeric parameter. Recommendation: optional per-function parameter schema at registration (names/types/defaults) with generic coercion at injection. Also makes history/manifest params unambiguous plain data (helps IMP-010).
- **No execution helper for external simulators.** Real `simulate` is a subprocess (FMI co-sim, Modelica tool, HPC job). The stdlib-only deterministic library is defensible, but nothing shows the canonical pattern (subprocess + timeout + exit-code-to-result + write payload to `artifacts.out_dir()` + return pointer). Recommendation: a documented example or optional recipe module. This is the paper's "easy implementation of verification activities" requirement (§3).
- **`try_action` cannot wrap a real body.** It invokes a named function with exactly static `params` (`library.py:348-392`) — no upstream results, no globals, no adaptation, single function (not a group). Error-reactive simulation scenarios (retry a data-dependent simulation) need bespoke drivers. Root cause flagged in `docs/dynamic_scenarios_analysis.md` §2.3 ("no per-node exception capture ... root blocker"). Recommendation: an engine-level opt-in error policy (per-scope `on_error="capture"` turning exceptions into data) composes with `retry`/`fallback` and matches paper P3 (branch on failures) more directly than the `try_action` workaround.
- **No per-action timeout.** A hung simulator blocks a pool worker forever. `GraphPool.result` supports timeouts (`src/sequence_extensions/graph/graph_future.py`) but the engine never applies one. Needed for unattended automation (paper requirement). Should land with IMP-012's executor work: per-action or per-scope wall-clock budget.
- **No fail-fast cancellation.** `_walk_parallel` waits for ALL children to settle before re-raising the first error (`engine.py:429-455`). One early failure still pays for every sibling. At minimum make the policy configurable ("fail fast, cancel unwalked work" vs "drain then report").
- **Zero observability, no CLI.** No `logging` anywhere in `src/`; no `console_scripts` in `pyproject.toml`. Unattended runs are silent until they end. Small, high-leverage adds for the automation requirement.

## 4. Traceability & reproducibility (paper C1 / P24)

Known and tracked: live `dag` handle in `record.params` and replay not verifying function identity (IMP-010); no run identity, O(n²) params memory (IMP-011 — confirmed structural: every downstream record embeds all upstream results; the artifact store only helps when functions opt in).

Not yet tracked:

- **Manifest entries carry no timestamps** (`src/sequence_extensions/workflow/artifacts.py:432-443`: `seq`, `address`, `function`, `params`, `dynamic`). Wall-clock evidence exists only in `ExecutionRecord`, and history/artifacts are separate opt-ins. Add timestamps (and a run header) to the manifest.
- **`RunHistory` has no persistence** — no `to_json`/`from_json`. Traceability that lives only in process memory is not traceability for regression campaigns. A plain-data serializer needs the IMP-010 handle-stripping fix and a defined policy for non-JSON params.
- **No seed/randomization convention** (paper P16/UC2, §3.1.2). The library is deliberately deterministic, but the paper allows Monte Carlo *if* the full scenario or recreation metadata (method, seed) is stored. No `randomize_scenarios(method, seed)` driver exists (recommended in `docs/dynamic_scenarios_analysis.md` §5 but not built), and no seed field in records/manifest. UC2 is half-supported.

## 5. Execution substrate

Known (IMP-012): hardcoded `ThreadPoolExecutor` (GIL-bound simulation code gets no speed-up; the barrier-based scaling test is structurally blind to this since sleeps release the GIL), non-configurable `max_workers=16`/`ADAPTATION_BOUND`, `except Exception` swallowing `BaseException` in the parallel walk.

New:

- **Nested parallel groups spawn unbounded raw threads.** Group children of a `Parallel` run on plain `threading.Thread`s, one per branch (`engine.py:416-426`). Deeply nested, wide campaigns create threads multiplicatively. The daemon-thread choice avoids pool starvation, not thread explosion. Bound it or reuse a walk executor.
- **HPC/distributed (paper P19)** is out of scope per `INFO-001` — fine — but once IMP-012 makes the executor pluggable, document the registry-function-as-remote-job pattern. Today there is no story for a user who needs to leave one machine.

## 6. Paper-fidelity nuances [new]

- The **read-only parallel handle** is narrower than the docs suggest, in a good way: an action whose *direct* parent is an inner `Sequential` nested in a parallel group CAN adapt (verified — probe `verify2.py` xml2). The error message "runs inside a parallel scope, whose handle is read-only" (`adaptation.py:197-204`) and `docs/API.md:1118` read as a blanket prohibition. Document the wrap-your-branch-in-a-scope idiom — it is the only way to get per-branch adaptation today.
- `docs/API.md:1191` describes clone directories as "clone 1 of a swept parallel group" — the clones run one after another (see finding 1). Fix the doc alongside the fix.
- The deviation ledger itself is good (scoped handle vs. full DAG, copy-to-end vs. loops, read-only parallel vs. negotiated merges are reasoned and documented; IMP-013 plans to surface the divergence table). Include the two biggest *behavioral* deviations from the paper's examples there: sequential fan-out (finding 1) and the parallel-branch restriction.

## 7. Prioritized recommendations

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

## Relation to existing tracking

- IMP-009 (kwargs precedence/upstream matching/reserved names), IMP-010 (history record evidence), IMP-011 (run identity, quadratic params), IMP-012 (engine resources/exception contract), IMP-013 (docs parity) — all confirmed valid by this review; several items independently reproduced. No duplication intended: those findings are theirs.
- Everything marked **New** above has no IMP yet. This file is the holding record until they are filed.
