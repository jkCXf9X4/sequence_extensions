# Dynamic Scenarios — Analysis and Recommended Premade Generic Functions

**Scope:** `src/sequence_extensions/workflow/` · **Status:** decision basis · **Audience:** maintainers implementing new library functions

This document decides which **premade generic functions** (driver functions in
`workflow/library.py`) should be added to support **dynamic scenarios** — iteration,
conditionals, branching, composition, and V&V campaigns — in the workflow engine.

**Inputs** (all claims below trace to one of these, or to the repo itself):

1. The paper: Rosenlund, Hällqvist, Braun, Krus — *Automation Nation: Taming Complex V&V
   Workflows*, 16th International Modelica & FMI Conference, Lucerne, September 2025
   (`docs/references/paper_44_yBqbPyj1.pdf`). Section references are given as §.
   *Note: the repo's source headers cite DOI `10.3384/ecp12076741` while
   `docs/breakdown/00-intent/vision.md:11` cites `10.3384/ecp218741`; the two DOIs refer to
   the same paper and the discrepancy is unresolved in the repo.*
2. The engine: file:line-anchored capability inventory of `workflow/` (schema, registry,
   engine, adaptation, library, history) — anchors given as `file:line`.
3. The scenario taxonomy: 23 prioritized scenarios in 5 categories with feasibility notes
   grounded in engine semantics.

**Decision supported:** which functions to build, in what order, and which scenarios are
blocked on engine features rather than library functions.

---

## 1. Purpose & scope

The engine implements the paper's split — *complexity in the library, not the schema*
(`docs/API.md:1061-1063`, `docs/breakdown/06-evolution/implemented/dynamic-adaptation.md:102`):
the XML schema is a finite tree with no loops, conditionals, or expressions, and all dynamic
behavior lives in registered Python functions that adapt the DAG at runtime. The paper
explicitly leaves advanced dynamic patterns to the function library and warns that this
makes dynamic functions **opaque from the representation** — "it is not possible to determine
how the function find_files will alter the downstream actions by only looking at the
representation. This places requirements on the function library to provide clarity
regarding what functions do and how they affect the workflow" (§5).

This document therefore:

- condenses the engine's dynamics model and its hard constraints (§2),
- merges the paper's 24 dynamic-scenario patterns and the taxonomy's 23 scenarios into one
  deduplicated catalog (§3),
- maps the four existing drivers onto that catalog (§4),
- recommends a reconciled, prioritized shortlist of new premade generic functions (§5),
- records the design trade-offs behind the recommendations (§6),
- and gives the integration recipe any new function must follow (§7).

Out of scope: engine changes (flagged as gaps, not designed here), the `ext`/`graph`
subpackages, and the history/replay layer beyond what constrains new drivers.

---

## 2. Engine dynamics model (condensed)

### 2.1 The two adaptation mechanisms

A registered function adapts the workflow through **exactly one** of two mechanisms per
action (`engine.py:560-568`):

1. **Scoped `DAGHandle`** — the function's signature declares an explicit `dag` parameter;
   the engine injects a handle scoped to the action's own grouping scope, and write ops are
   committed transactionally at function return (`registry.py:31-49` `wants_dag`,
   `engine.py:575-594` `_make_handle`, `adaptation.py:117-371`).
2. **Return-nodes splice** — the function returns an `Action`/`Sequential`/`Parallel` node
   (or list), spliced in place of the action's **next sibling**; the replaced subtree is
   cancelled and never runs (`engine.py:23-27`, `engine.py:92-96`, `engine.py:484`,
   `docs/API.md:950-952`). This is the legacy mechanism.

Declaring `dag` **and** returning node(s) raises `ValueError` (`engine.py:560-568`). A bare
`**kwargs` does **not** opt a function into adaptation — the parameter must be named
(`registry.py:38-49`); `dag` is a reserved kwarg name, the injected handle winning over any
same-named parameter (`engine.py:522-524`, `engine.py:543-545`).

**`DAGHandle` API** (`adaptation.py:117-371`): reads `following()`, `preceding()`,
`following_group()` (the first following sibling, which must be a group — the *declared
downstream scope* a driver adapts); writes `replace(target, nodes)`, `adjust(target,
**params)`, `copy(target, **overrides)` (returns a clone; the caller then appends/replaces
with it), `adjusted(**overrides)`, `append(nodes)` (at the scope end — the paper's §5
copy-to-end iteration workaround). Ops are validated eagerly, recorded as `AdaptationOp`
data, and applied at commit (`adaptation.py:68-100`, `engine.py:614-653`).

### 2.2 Key constraints (every new driver must respect these)

| Constraint | Rule | Anchor |
|---|---|---|
| At-most-once | Every action executes at most once; the engine never re-runs a function. Iteration = appending **fresh copies** (each copy is a new node), so the workflow stays a DAG. | `engine.py:32-33`, `engine.py:171-172`, `adaptation.py:347-366` |
| No native control flow | The schema is only `Action`/`Sequential`/`Parallel` — no loop, branch, or try/catch node. Templates expand at parse time. The schema is deliberately non-Turing-complete. | `schema.py`, `docs/API.md:1061-1063` |
| Bounded adaptation | `ADAPTATION_BOUND = 10_000` dynamic nodes per run; exceeding it raises a deterministic `ValueError` (runaway adaptation terminates instead of hanging). The handle is constructed with the *remaining* budget. | `adaptation.py:59`, `engine.py:635-641`, `engine.py:593` |
| Parallel scopes read-only | Children of a `Parallel` scope get a read-only handle — every write op raises `ValueError` (inside a parallel scope the "every following position is unwalked" invariant does not hold). Reads still work. | `adaptation.py:215-222`, `engine.py:575-594`, `engine.py:113-119` |
| Sibling-scope adaptation only | A writable target is a **following** sibling or a node inside a following sibling's subtree; a preceding sibling is acceptable only as a **copy source** (read-only). Targets that already ran are rejected. An action can never alter siblings of its own group. | `adaptation.py:224-257`, `engine.py:92-96` |
| Transactional commit | Ops are re-validated and applied atomically at function return, on the same thread, under one engine-lock acquisition; if the function raised, nothing is applied. | `engine.py:614-653` |
| Deterministic + stdlib-only | Library functions must be deterministic, stdlib-only, and tolerate extra kwargs (the engine passes globals and upstream results alongside own params). | `library.py:1-96` |
| No import-time registration | A new library function must not self-register at import (a fresh interpreter sees an empty `DEFAULT_REGISTRY`); opt in via `register_library()`. | `library.py:1-96`, `library.py:338-364` |
| Replay compatibility | A driver that declares `dag` is re-invoked on replay with the recorded `dag` kwarg stripped and a `ReplayHandle` re-injected (reads from a fake tree, writes are no-ops). | `history.py:327-485` |

### 2.3 Facts that shape scenario feasibility

- **Lazy tree-walking**: the engine re-reads each sequential group's `children` every step,
  so runtime splices are seen immediately; a `Parallel` group's children are **snapshotted
  once** (no splicing inside a parallel group) (`engine.py:260-291`, `engine.py:293-373`).
- **Upstream results as kwargs**: each upstream action's result is passed downstream keyed
  by the producing action's **function name**, with collision suffixes `name`, `name_2`, …
  when the name repeats (e.g. across copied iterations). Precedence: **own params >
  upstream results > globals** (`engine.py:500-540`). Consequence: a stateless driver can
  read *all* past iterations' results from its kwargs (the highest suffix is the latest) —
  this is how a driver reconstructs "memory" across copy-to-end iterations
  (`library.py:416-428` `_upstream_count`).
- **No per-action timeout, no per-node exception capture**: an exception raised by a
  function propagates from `pool.result` and aborts the run; the engine does not catch a
  node's exception to let a sibling react (`engine.py:205-212`). This is the root blocker
  for retry-on-error / fallback-on-error / timeout / watchdog scenarios (§3, §5).
- **Parallelism is static schema**: concurrency comes from declared `Parallel` groups on a
  bounded `ThreadPoolExecutor` (default `max_workers=16`); a driver cannot add concurrency
  except by cloning nodes into a parallel group's subtree before it is snapshotted
  (`engine.py:293-373`, `graph_future.py:272-283`).
- **Paper grounding for the constraints**: strictly downstream execution and each action
  running once (§4.1); prohibition of feedback loops to protect artifacts from being
  overwritten at consecutive invocations (§5); adaptation scope limited to the action's own
  grouping scope (§4.2, Listing 7); upstream-only data access for determinism (§4.1, Fig. 4);
  full-DAG-in / merged-DAG-out contract (§4.2); group start/end nodes to make splicing a
  clean graph operation (§4.2); copy-to-end as the iteration workaround (§5).

---

## 3. Scenario catalog (merged)

Merged from the paper's 24 patterns and the taxonomy's 23 scenarios, deduplicated and
organized by category. **Coverage** refers to the four existing drivers
(`find_files`, `parameter_sweep`, `evaluate_goal`, `check_convergence` —
`library.py:98-104`, `:167-173`, `:229-235`, `:267-273`). **Priority** reconciles the
taxonomy's ratings with the paper's emphasis; disagreements are noted.

### 3.1 Iterative

| ID | Scenario | Description | V&V use case | Paper | Coverage | Feasibility | Priority |
|---|---|---|---|---|---|---|---|
| I1 | Fixed-count loop | Run the declared downstream body exactly `count` times, exposing a per-iteration index parameter. | Multi-start optimization (N independent starts); N repeated co-simulations for statistical confidence. | §4.1 (iterative tasks, unknown count) | **Covered** — `parameter_sweep` with `values = range(count)` clones the body per index. | Trivial (same replace-with-clones pattern). | **Low** — thin convenience over `parameter_sweep`. |
| I2 | While-condition loop (numeric tolerance) | Repeat the body while a comparison predicate on the latest upstream result holds (`field op threshold`), with a user-facing `max_iterations` cap. | Iterate a co-simulation until the coupling residual is below tolerance; run a campaign until all test cases pass. | §3.1.3 (repeat-until, "if not return to Item 2"); §4.1 (iteration count unknown a priori) | **Partial** — `check_convergence` handles a truthy field only, no comparison, no cap. | Feasible: copy-to-end pattern with a comparison predicate; cap via `_upstream_count`. | **High** — the single most important gap in the existing four; numeric tolerance is the actual V&V need. |
| I3 | Convergence loop (truthy field) | Iterate the body until an upstream field becomes truthy. | Co-simulation fixed-point convergence (boolean "converged" flag). | §3.1.3; §5 (copy-to-end workaround) | **Covered** — `check_convergence` (`library.py:267-320`). | Implemented. | n/a (existing). |
| I4 | Retry with backoff | Re-run a body that failed or produced an unacceptable result, up to `max_attempts`, with a delay between attempts. | Flaky FMI export (omc crashes on a bad model); a solver failing on first attempt; transient network fetch. | §3.5, §4.1 (failures as an adaptation trigger) | **Uncovered.** | **Split**: retry-on-result-field is feasible (copy-to-end); retry-on-**error** is infeasible today — the engine has no per-node exception capture, so a driver cannot observe a sibling's failure. Needs a `try_action` primitive (§5). | **High** — flaky toolchains are a real V&V pain; blocked on `try_action` for the error case. |
| I5 | Recursive refinement | Run a body, then re-run it with a parameter adjusted from the previous result (halve the step, tighten the tolerance) until a stop condition. | Adaptive time-step study (coarse → refine until stable); step/mesh refinement; tolerance tightening. | §3.1.3 (feedback of previous results into next iteration); §3 (Design of experiments) | **Uncovered.** | Feasible: copy-to-end where each appended copy carries the refined parameter computed from the latest upstream result; depth cap via `_upstream_count`. | **Medium** — I2 + `adjust` covers most of it; parameter feedback is the differentiator. |
| I6 | Optimization loop | Iterate a body with parameters set by an optimizer (grid, random, or sequential method) until a convergence criterion on the objective. | Parameter identification (fit model parameters to measured data); calibration; design-point search. | §3.1.3 (Bayesian design optimization, UC3); §3 (Design optimization) | **Uncovered.** | **Split**: grid/random = sweep-style clones (feasible; `n^k` grid nodes bite the 10 000 bound fast); sequential methods = copy-to-end with the driver reconstructing the optimizer trajectory from the full history of upstream results — feasible but the stateless-reconstruction constraint is real. | **Medium** — high V&V value but a larger build; grid/random is cheap. |
| I7 | Batch-sequential iteration | Group iterations into batches; a barrier between batches lets each batch use previous batches' outcomes while preserving determinism. | UC3's Bayesian optimization: "when a batch is completed the next one is allowed to start... while ensuring determinism" (§3.1.3). | §3.1.3 | **Uncovered.** | Feasible: a driver clones the body per batch member into a `Parallel` group, then appends the next batch's driver + check (copy-to-end across batches). | **Medium** — the paper's determinism-preserving pattern; a composition of I2 + parallel cloning. |

### 3.2 Conditional

| ID | Scenario | Description | V&V use case | Paper | Coverage | Feasibility | Priority |
|---|---|---|---|---|---|---|---|
| C1 | Guard / skip | Run the downstream body only if a predicate on an upstream result holds; otherwise skip it (the body never runs). | Skip post-processing if the simulation failed; run an expensive check only if a cheap pre-check passed; skip a test case with missing prerequisites. | §3.2, §4.1 (conditional rules on intermediate results, incl. missing artifacts) | **Uncovered.** | Trivial: `replace` the body with an empty `Sequential()` — a valid node that runs nothing; no `noop` primitive needed. `on_fail="fail"` raises. | **High** — the most common conditional in V&V and cheap to build. |
| C2 | Early-exit / short-circuit | Stop the rest of the workflow when a condition holds — a fail-fast gate. | A regression gate that aborts the campaign on the first failing test case; a smoke test that skips the full suite. | §3.2 (conditional rules); §4.1 (branch to alternative paths) | **Uncovered.** | **Limited**: the handle can `replace` the rest of its **own** scope with an empty group, but cannot reach outside its own scope (sibling-scope rule). Whole-workflow abort = raise (surfaces as an error, not a clean "stop"). | **Medium** — useful for fail-fast gates; the scope limitation is real; a `fail` mode covers the common case. |
| C3 | Timeout | Run a body with a wall-clock deadline; abort and report a timeout on expiry. | A co-simulation that can hang (FMI master/slave deadlock); a solver with a time budget. | §3.5 (error handling as a first-class concern) | **Uncovered.** | **Infeasible as a driver**: the driver runs *before* the body and cannot observe its execution time; the engine has no per-action timeout (`GraphPool.result` has one, but the engine does not expose it per action). | **High need, engine-blocked** — flag as an engine-level gap, not a library function. |
| C4 | First-success | Try a sequence of alternative bodies in order; stop at the first that succeeds (a result field indicates success); the rest never run. | Try solver A, then B, then C (fallback solvers); FMI 2.0 then FMI 1.0 export; local then remote model. | §3.5 (error handling); §4.1 (branch to alternative paths) | **Partial** — `evaluate_goal` covers the pick-one case by exact name match. | Feasible with a check-after-each-alternative pattern: a driver after each alternative `replace`s the remaining alternatives with an empty group on success. The driver must be duplicated after each alternative, or self-replicate (fiddly). | **Medium** — useful for solver fallbacks; the self-replicating setup is the complexity. |

### 3.3 Branching

| ID | Scenario | Description | V&V use case | Paper | Coverage | Feasibility | Priority |
|---|---|---|---|---|---|---|---|
| B1 | If/else (two-way) | Select one of two named alternatives based on an upstream result field. | Pass/fail routing (report branch or debug branch). | §4.1 (branch to alternative paths) | **Covered** — `evaluate_goal` (`library.py:229-265`). | Implemented. | n/a (existing). |
| B2 | Multi-way switch (exact match) | Select one of N named alternatives by exact name match on an upstream field value. | Route to a per-test-type handler; select a per-platform build step. | §4.1 | **Covered** — `evaluate_goal`. | Implemented. | n/a (existing). |
| B3 | Condition-based switch | Select an arm by a predicate/range rather than exact name match (e.g. "residual < 0.1 → A, < 1 → B, else C"). | Graded verdicts (pass / marginal / fail); severity routing. | §4.1 (branch on intermediate results) | **Partial** — `evaluate_goal` is exact-name-match only. | Feasible: same `replace` mechanism, selection logic = a list of `(condition, arm)` pairs. | **Medium** — a natural generalization of `evaluate_goal`; same mechanism. |
| B4 | Parallel-branch selection / negotiation | Run multiple candidate branches in parallel (solvers, FMI versions, configurations) and select the winner by a criterion; losers' results are discarded or kept. | Solver negotiation (run 3 solvers in parallel, pick the one that converged fastest/most accurately); FMI version negotiation. | §5 (parallel branches "must negotiate the new notion of truth before continuing when merging branches") | **Partial** — `evaluate_goal` covers pick-one-before-running. | The run-all-then-pick-best form needs **no adaptation at all**: the parallelism is static schema (a declared `Parallel` group) and the selection is a pure downstream function reading all the parallel results. The paper's negotiation problem is **designed out** in this engine: parallel-scope children get read-only handles, so two branches cannot both rewrite future common activities (`adaptation.py:215-222`). | **Medium** — the run-all-then-select form is cheap (no `dag`); the true pre-run pick-one is already `evaluate_goal`. |

### 3.4 Compositional

| ID | Scenario | Description | V&V use case | Paper | Coverage | Feasibility | Priority |
|---|---|---|---§|---|---|---|---|
| M1 | Nested loops | A loop over an outer collection where each outer iteration runs an inner loop (a sweep where each value runs a convergence loop). | A parameter sweep where each parameter value needs a co-simulation convergence loop; multi-model × multi-parameter study. | §4.1 (hierarchical nested grouping); App. Listing 9 (3 levels of nested `<sequential>`) | **By composition** — no dedicated function. | Feasible by composition: the outer driver clones the downstream scope once per outer value; the cloned scope contains the inner driver, which clones its own downstream scope. `dag.copy` deep-clones the subtree including the inner driver. Bound is the **product**: `outer × inner × body_size ≤ 10_000`. | **High** — core V&V pattern; already feasible, so a dedicated function is a thin convenience. |
| M2 | Loop-over-collection / map | Run the declared downstream scope once per item of a collection (files or values). | Simulate + evaluate each found result file; simulate each sweep value. | §4.1 (Listing 5, `find_files`); App. Listing 9 (`parameter_sweep`) | **Covered** — `find_files` (files) + `parameter_sweep` (values). | Implemented. A generic `map` over an arbitrary upstream list (list of dicts / (param, value) pairs) would generalize both — trivial, same pattern. | **Low** — already covered; a generic `map` is a thin generalization. |
| M3 | Aggregate / reduce | After a loop/map, combine all per-item results into a single summary (sum, max, min, count, mean, all/any). | A regression gate aggregating per-test-case pass/fail into an overall verdict; a sweep computing the worst-case error; a fault campaign counting detected faults. | §3 (Result aggregation); §3.1.1 step 4 (collect and compare QoIs); App. Listing 9 (`compare_parameter_sweep`, `compare_results`) | **Partial** — `compare_parameter_sweep` / `compare_results` return item counts only. | **No `dag` needed** — a pure function reading all upstream results (collision-suffixed kwargs give every iteration's result) and reducing them. Stateless and cheap. | **High** — every loop/map needs an aggregation downstream; the existing summaries are narrow. |
| M4 | Staged pipeline | A sequence of stages where each stage's go/no-go is decided by a gate; a failed gate stops the pipeline or routes to a failure branch. | A V&V pipeline build → smoke test → full test → report, each stage gating the next; export FMI → initialize → step → evaluate. | §3.1 (pre/post conditions: workflow establishment → final packaging activity) | **By composition** — no dedicated function. | A composition of C1 (guard) + C2 (early-exit): a `Sequential` of stages, each followed by a gate check. A single driver managing all stages would adapt multiple following siblings (feasible — the handle can adapt all following siblings in its scope). | **Medium** — common pattern, but a composition of cheaper primitives; a dedicated driver is a convenience. |
| M5 | Fallback / error-handling chain | Try a primary action; if it fails (error or bad result), try a fallback; a chain of fallbacks. | Primary solver fails → fallback solver; local FMI export fails → remote; primary model file missing → default model. | §3.5, §4.1 (failures as adaptation trigger) | **Uncovered.** | Same as C4 (first-success). Fallback-on-result-field is feasible now; fallback-on-**error** needs the `try_action` primitive (the engine propagates exceptions, so a driver cannot catch a sibling's failure). | **High** — error handling is essential for robust V&V; blocked on `try_action` for the error case. |
| M5b | Randomized fan-out with seed storage | Generate stochastic scenario permutations (e.g. Monte Carlo) and store the seed/method metadata so the run is repeatable. | UC2's randomized stimulus permutations; seeded Bayesian sampling (UC3). | §3.1.2 (randomization must store the full scenario or recreation metadata: software, method, seed); §3.1.3 step 1 | **Uncovered.** | Feasible: a sweep-style map over generated values, with the seed/method stored in the result and in the action's params (recorded by history). Determinism requires the seed to be a declared parameter, not hidden state. | **Medium** — required for UC2-style Monte Carlo; a composition of map + a seeded generator function. |

### 3.5 V&V campaigns

| ID | Scenario | Description | V&V use case | Paper | Coverage | Feasibility | Priority |
|---|---|---|---|---|---|---|---|
| V1 | Fault-injection campaign | Run a base scenario, then re-run it with each fault injected (parameter perturbation, signal disturbance, component failure), and compare each result to the base. | Robustness testing (does the controller handle a sensor fault?); fault detection & isolation (FDI) validation; sensitivity analysis. | §3.1.2 (stimulus combinations); §3 (Model exploration) | **By composition** — no dedicated function. | A sweep-style map over fault definitions (each fault = a clone with parameter overrides) + a downstream compare against the base result (available to each clone as an upstream kwarg). | **Medium** — a real V&V use case, but a composition of map + compare. |
| V2 | Regression gate | Run a set of test cases, compare each to a baseline, and produce a pass/fail verdict that gates the workflow. | A nightly regression suite; a CI gate for a model change; baseline comparison after a code change. | §3 (Automation: "enable effective regression testing"); §6 | **By composition** — no dedicated function. | A `find_files`-style map over test cases + per-case compare + `aggregate` (all/any) + a final gate that raises on regression. | **High** — bread and butter of V&V; the composition exists, a dedicated function is a high-value convenience. |
| V3 | Co-simulation iteration | Run a co-simulation (FMI master/slave) with an iteration loop on the coupling until the coupling converges. | A loosely-coupled co-simulation where interface variables must be iterated to a fixed point; a partitioned model with a convergence loop. | §3.1.3 (iterative optimization); §2 (FMI/SSP domain) | **Partial** — `check_convergence` is boolean-only. | A `check_convergence`-style loop specialized for the coupling residual — i.e. I2 (numeric tolerance) specialized. Optional under-relaxation is parameter feedback (I5). | **High** — the paper's core use case; the numeric-tolerance gap (I2) is the real blocker. |
| V4 | Resource / queue throttling | Limit the number of concurrent body executions (at most K simulations at a time). | A parameter sweep with a license-limited solver (at most 4 concurrent); a campaign respecting a compute quota. | §3.2 (distributed/HPC execution); §3 (Resource utilization) | **Uncovered.** | Feasible via **chunking**: `replace` a flat `Parallel` of N children with a `Sequential` of `Parallel` chunks of size K. The engine's parallelism is otherwise fixed by the `Parallel` group + the 16-worker pool. | **Medium** — a real need (license limits); the chunking trick makes it feasible. |
| V5 | Watchdog / heartbeat | Monitor a long-running body for liveness; if it stalls, abort. | A long co-simulation that must report progress; a solver writing a heartbeat file. | §3.5 (error handling) | **Uncovered.** | **Infeasible as a driver** — same root blocker as C3 (timeout): the driver runs before the body and cannot observe its runtime progress. | **Low** — real need but engine-blocked; overlaps with C3. |
| V6 | OD / DoV feedback | Store verification outcomes as Operational Domains (OD ⊆ DoV) via STMD, closing the model-credibility loop. | UC1 step 3 / UC2 final step: "generate a OD that corresponds to the fulfillment of that requirement." | §2, §3.1.1, §3.1.2 | **Uncovered.** | Feasible as a **plain function** (no `dag`): read the aggregated fulfillment results and emit an OD record. Not a dynamics problem — an output-formatting problem. | **Low** — domain-specific output formatting, not a dynamics gap; belongs to a domain library, not the generic driver set. |
| V7 | Distributed / HPC execution | Execute independent tasks concurrently in a distributed environment. | Scaling parallel simulation fan-out beyond a single machine. | §3.2 | **Uncovered.** | **Out of scope for library functions**: concurrency is fixed by the `Parallel` group + the local `ThreadPoolExecutor` (`graph_future.py:272-283`); distributed execution is an engine/substrate feature. | **Low** — engine-level, not a library function. |

**Deduplication notes.** The paper's P1 (parameter sweep) and P2 (file discovery) collapse
into M2; P4/P5 (iteration with unknown count / repeat-until) collapse into I2/I3; P6/P7
(batch-sequential / adaptive feedback) are kept distinct as I7/I5 because the taxonomy
treats them as different builds; P8/P9 (parallel fan-out / sequential chains) are engine
primitives, not scenarios, and appear only as feasibility facts (§2.3); P10 (nested
workflows) is M1; P11 (reusable templates) is the existing `Template` mechanism
(`schema.py:192-341`); P12 (fine-grained flags) and P13 (global parameters) are parameter
mechanisms, covered by the engine's kwargs precedence (`engine.py:500-540`); P14 (result
aggregation) is M3; P15 (OD/DoV) is V6; P16 (randomization with seed) is M5b; P17
(regression) is V2; P19 (HPC) is V7; P20 (error handling) is C1/C4/M5; P21 (upstream-only
data) and P22 (branch negotiation) are constraints/facts (§2); P23 (no central graph
handler) and P24 (version-control snapshots) are implementation/audit concerns outside the
driver-function decision.

---

## 4. Coverage map

Existing drivers vs. the catalog (✓ = covered, ◐ = partial, ✗ = uncovered):

| Scenario | `find_files` | `parameter_sweep` | `evaluate_goal` | `check_convergence` |
|---|---|---|---|---|
| I1 fixed-count loop | ◐ (via values=range) | ✓ | ✗ | ✗ |
| I2 while-condition (numeric) | ✗ | ✗ | ✗ | ◐ (truthy only) |
| I3 convergence loop (truthy) | ✗ | ✗ | ✗ | ✓ |
| I4 retry with backoff | ✗ | ✗ | ✗ | ✗ |
| I5 recursive refinement | ✗ | ✗ | ✗ | ✗ |
| I6 optimization loop | ✗ | ◐ (grid/random only) | ✗ | ✗ |
| I7 batch-sequential iteration | ✗ | ✗ | ✗ | ✗ |
| C1 guard / skip | ✗ | ✗ | ✗ | ✗ |
| C2 early-exit | ✗ | ✗ | ✗ | ✗ |
| C3 timeout | ✗ | ✗ | ✗ | ✗ |
| C4 first-success | ✗ | ✗ | ◐ (pick-one) | ✗ |
| B1 if/else | ✗ | ✗ | ✓ | ✗ |
| B2 multi-way switch | ✗ | ✗ | ✓ | ✗ |
| B3 condition-based switch | ✗ | ✗ | ◐ (exact match only) | ✗ |
| B4 parallel-branch selection | ✗ | ✗ | ◐ (pick-one) | ✗ |
| M1 nested loops | ◐ (outer level) | ◐ (either level) | ✗ | ◐ (inner level) |
| M2 map over collection | ✓ (files) | ✓ (values) | ✗ | ✗ |
| M3 aggregate / reduce | ✗ | ✗ | ✗ | ✗ |
| M4 staged pipeline | ✗ | ✗ | ✗ | ✗ |
| M5 fallback chain | ✗ | ✗ | ✗ | ✗ |
| M5b randomized fan-out (seeded) | ✗ | ◐ (map only) | ✗ | ✗ |
| V1 fault-injection campaign | ◐ (map) | ◐ (map) | ✗ | ✗ |
| V2 regression gate | ◐ (map) | ✗ | ✗ | ✗ |
| V3 co-simulation iteration | ✗ | ✗ | ✗ | ◐ (boolean only) |
| V4 throttling | ✗ | ✗ | ✗ | ✗ |
| V5 watchdog | ✗ | ✗ | ✗ | ✗ |
| V6 OD/DoV feedback | ✗ | ✗ | ✗ | ✗ |
| V7 distributed/HPC | ✗ | ✗ | ✗ | ✗ |

Reading: the existing four cover **map-style fan-out** (M2, I1) and **name-based branching**
(B1/B2) fully, and **truthy convergence** (I3) fully. The uncovered space clusters into:
(i) **numeric-tolerance iteration** (I2, V3), (ii) **predicate conditionals** (C1, B3),
(iii) **aggregation** (M3), (iv) **error-reactive behavior** (I4, M5, C4 — blocked on
`try_action`), and (v) **engine-blocked scenarios** (C3, V5, V7).

---

## 5. Recommended new premade generic functions

Reconciled shortlist. The taxonomy's build order and the code analysis's five candidates
agree on the top items; where they differ, the difference is noted. Signatures follow the
repo convention: parameters, then `*`, then `dag: DAGHandle` (drivers) or `**kwargs`
(plain), then `**kwargs` — see §7.2. Effort: **S** ≤ ~50 LOC + tests, **M** ~50–150 LOC +
tests, **L** > 150 LOC or non-trivial semantics.

### Tier 1 — build first (no prerequisites, high value)

| # | Function | Signature | Semantics sketch | Unlocks | Deps | Effort | Priority |
|---|---|---|---|---|---|---|---|
| 1 | `aggregate` | `aggregate(upstream: str, field: str, op: str, key: str \| None = None, **kwargs) -> dict` | Pure function, **no `dag`**: read all collision-suffixed upstream results named `upstream`, extract `field` from each, reduce with `op` (`sum\|max\|min\|count\|mean\|all\|any`), optionally group-by `key`. Return the summary dict. | M3; enables V2, V1, I6 (objective evaluation) | — | **S** | **High** — cheapest high-value build; every loop/map needs it. |
| 2 | `guard` | `guard(upstream: str, field: str, op: str, value: Any, on_fail: str = "skip", *, dag: DAGHandle, **kwargs) -> dict` | Driver: evaluate the predicate on the latest upstream result; if it fails, `dag.replace(body, [Sequential()])` (empty group — the body never runs); if `on_fail="fail"`, raise. Body = `dag.following_group()`. | C1; building block of M4, V2 | — | **S** | **High** — most common conditional; trivial build. |
| 3 | `while_condition` | `while_condition(upstream: str, field: str, op: str, threshold: float, max_iterations: int \| None = None, *, dag: DAGHandle, **kwargs) -> dict` | Driver, copy-to-end: while the latest upstream result's `field` fails `op threshold`, append a copy of the preceding body + a fresh copy of this check (the `check_convergence` pattern with a comparison predicate and a user-facing cap enforced via `_upstream_count`). Returns `{"converged": bool, "iterations": n}`. | I2; enables V3 (specialization), I5 (with `adjust`), I7 | — | **M** | **High** — the single most important gap; numeric tolerance is the actual V&V need. |

### Tier 2 — high value, one shared prerequisite

| # | Function | Signature | Semantics sketch | Unlocks | Deps | Effort | Priority |
|---|---|---|---|---|---|---|---|
| 4 | `try_action` | `try_action(function: str, **kwargs) -> dict` | **Primitive, not a driver** (no `dag`): invoke the registered function `function` with the given kwargs and return `{"ok": bool, "result": ..., "error": str \| None}` instead of propagating the exception. | I4, M5 (error case), C4 | — | **S** | **High** — the single highest-leverage new primitive; the engine's lack of per-node exception capture is the root blocker for all error-reactive scenarios. |
| 5 | `retry` | `retry(upstream: str, max_attempts: int, on: str = "error", field: str \| None = None, backoff: str = "fixed", delay: float = 0.0, *, dag: DAGHandle, **kwargs) -> dict` | Driver, copy-to-end: when the latest upstream result is not acceptable (error via `try_action`, or a result field), append a copy of the body + check, up to `max_attempts`; optional `time.sleep` backoff between attempts (blocks one pool worker — acceptable for sequential retry). | I4 | `try_action` (for `on="error"`) | **M** | **High** — flaky FMI toolchains are a real V&V pain. |
| 6 | `fallback` | `fallback(upstream: str, field: str, ok_value: Any, *, dag: DAGHandle, **kwargs) -> dict` | Driver: check-after-each-alternative — after each alternative in the chain, if the latest upstream result's `field == ok_value`, `dag.replace` the remaining alternatives with an empty group; otherwise do nothing (the next alternative runs). | M5, C4 | `try_action` (for error-triggered fallback) | **M** | **High** — robustness is essential for V&V. |
| 7 | `regression_gate` | `regression_gate(upstream: str, baseline: Any, field: str, tolerance: float = 0.0, on_regression: str = "fail", **kwargs) -> dict` | Plain function (no `dag`): compare each upstream result's `field` to `baseline` within `tolerance`; aggregate with `all`; raise on regression when `on_regression="fail"`, else return the verdict. | V2 | `aggregate` (or inline the reduce) | **S–M** | **High** — bread and butter of V&V; a high-value convenience composite. |

### Tier 3 — medium value, build on demand

| # | Function | Signature | Semantics sketch | Unlocks | Deps | Effort | Priority |
|---|---|---|---|---|---|---|---|
| 8 | `switch` | `switch(upstream: str, arms: list[tuple[str, Any]], default: str \| None = None, *, dag: DAGHandle, **kwargs) -> str` | Driver: like `evaluate_goal`, but select the arm by evaluating each arm's condition (a `(name, value-or-predicate)` pair) against the latest upstream result in order; first match wins; `replace` the alternatives scope with the chosen named child. | B3 | — | **S–M** | **Medium** — natural generalization of `evaluate_goal`. |
| 9 | `throttle` | `throttle(concurrency: int, *, dag: DAGHandle, **kwargs) -> None` | Driver: `replace` the following flat `Parallel` group with a `Sequential` of `Parallel` chunks of size `concurrency` (batched parallelism). | V4 | — | **S** | **Medium** — license limits; the chunking trick is clean. |
| 10 | `nested_sweep` | `nested_sweep(outer_param: str, outer_values: list, inner_param: str, inner_values: list, *, dag: DAGHandle, **kwargs) -> list` | Driver: clone the downstream scope once per outer value; the downstream scope contains the inner driver, which clones its own downstream scope per inner value. Document the pattern; the bound is the product. | M1 | — | **S** | **Medium** — already feasible by composition; a thin convenience. |
| 11 | `refine` | `refine(upstream: str, param: str, refine: str, stop_field: str, stop_op: str, stop_threshold: float, max_depth: int \| None = None, *, dag: DAGHandle, **kwargs) -> dict` | Driver, copy-to-end with parameter feedback: each appended copy of the body carries the refined parameter value computed from the latest upstream result (`"halve"`, `"scale:<f>"`, `"tighten"`). | I5, V3 (under-relaxation) | `while_condition` (shares the loop machinery) | **M** | **Medium** — adaptive studies; I2 + `adjust` covers most of it. |
| 12 | `select_best` | `select_best(candidates: list[str], criterion: str, field: str, **kwargs) -> Any` | Plain function (no `dag`): read all parallel branch results, pick the winner by `criterion` (`first_success\|min\|max`) on `field`. | B4 (run-all-then-select form) | — | **S** | **Medium** — cheap; no adaptation needed. |
| 13 | `randomize_scenarios` | `randomize_scenarios(method: str, seed: int, count: int, **kwargs) -> list` | Plain function (no `dag`): generate `count` scenario values with a seeded stdlib RNG (`method`); the seed and method are declared parameters, so they are recorded in history and the run is repeatable. | M5b | — | **S** | **Medium** — required for UC2-style Monte Carlo; compose with `parameter_sweep`-style map. |
| 14 | `co_simulate` | `co_simulate(upstream: str, field: str, tolerance: float, max_iterations: int, relaxation: float \| None = None, *, dag: DAGHandle, **kwargs) -> dict` | Driver: `while_condition` specialized for the coupling residual, with optional under-relaxation (parameter feedback). | V3 | `while_condition` | **M** | **Medium** — the paper's core use case, but a specialization of I2; build after I2 proves out. |
| 15 | `generate_od` | `generate_od(requirement: str, upstream: str, field: str, **kwargs) -> dict` | Plain function (no `dag`): read the aggregated fulfillment results and emit an OD record (`{"requirement": ..., "fulfilled": ..., "domain": ...}`). | V6 | `aggregate` | **S** | **Low** — domain output formatting, not a dynamics gap. |

### Explicitly deferred (engine-blocked or already covered)

| Scenario | Disposition |
|---|---|
| C3 `timeout`, V5 `watchdog` | **Engine-blocked**: need a per-action wall-clock deadline (the engine does not expose `GraphPool.result`'s timeout per action). Flag as an engine-level gap; revisit after an engine feature lands. |
| V7 distributed/HPC | **Engine-level**: concurrency is fixed by the `Parallel` group + local `ThreadPoolExecutor`; distributed execution is a substrate feature. |
| I1 `repeat`, M2 generic `map` | **Already covered** by `parameter_sweep` (index list) and `find_files`/`parameter_sweep`; add only as thin conveniences if user demand appears. |
| I6 `optimize` (sequential methods) | **Deferred**: feasible but the stateless-reconstruction constraint (the driver must rebuild the optimizer trajectory from collision-suffixed upstream kwargs) makes it an **L** build with subtle determinism requirements; revisit after I2/I5 prove the loop machinery. Grid/random forms are covered by `parameter_sweep` composition. |
| I7 `batch_iterate` | **Deferred**: a composition of I2 + parallel cloning; build on demand. |
| M4 `staged_pipeline` | **Deferred**: a composition of `guard` + `early_exit`; document the pattern rather than ship a driver. |
| C2 `early_exit` | **Deferred**: the scope limitation (own scope only) makes whole-workflow abort impossible without raising; a `fail` mode via `guard` covers the common case. |
| V1 `fault_inject` | **Deferred**: a composition of map + compare; build on demand. |

**Reconciliation notes.** The taxonomy's build order and the code analysis's five candidates
agree on `aggregate`/`guard`/`while_condition` as the top three (the code analysis's
"generic for/repeat", "grid sweep", "boolean branch", "repeat-while", "map" map onto the
taxonomy's I1, I6-grid, B3, I2/I5, M2 respectively — all present above as Tier 3 or
deferred). Two disagreements, resolved as follows: (a) the taxonomy ranks `retry`/`fallback`
high while the code analysis does not list them — resolved in favor of the taxonomy, since
the paper names failures as an explicit adaptation trigger (§3.5, §4.1) and the only blocker
(`try_action`) is a small primitive; (b) the code analysis's "generic `map`" is ranked low by
the taxonomy (already covered) — resolved in favor of the taxonomy, keeping `map` deferred.
The paper's pattern→function mapping (its Part 5) is fully represented: `find_files`,
`parameter_sweep`, `simulate`, `evaluate_results`, `compare_parameter_sweep`,
`compare_results`, and the grouping primitives already exist; repeat-until → `while_condition`;
batch-sequential → I7 (deferred); conditional branch → `guard`/`switch`; randomized scenarios
→ `randomize_scenarios`; OD generation → `generate_od`; branch-merge coordination → designed
out (§3.3 B4); design-of-experiments → I6 (deferred).

---

## 6. Design decisions & trade-offs

### 6.1 One generic per scenario vs. parameterized generics

**Recommendation: parameterized generics, with a small fixed set.** The shortlist keeps
~15 functions, each parameterized (e.g. `while_condition` takes `op`/`threshold`/
`max_iterations` rather than shipping `while_lt`, `while_le`, …). Rationale:

- The paper's own answer to complexity is *complexity in the library, not the schema*
  (§4.1, §5), and its readability caveat (§5, L6) is about **opacity of dynamic functions**,
  which argues for **fewer, well-documented** functions, not many narrow ones.
- The engine's kwargs precedence (`engine.py:500-540`) already gives every function the
  same parameter surface (own params > upstream > globals), so a parameterized generic
  costs nothing extra at the mechanism level.
- Counter-consideration: the paper warns that fine-grained flag control "might sometimes
  be too simplistic" (§5, L7) — a function with many flags can hide its behavior. Mitigate
  by keeping each function's parameter set small and its docstring explicit about what it
  does to the DAG (the existing library convention, `library.py:1-96`).

### 6.2 Function-based drivers vs. native node types

**Recommendation: functions now; native nodes as a future consideration.** The engine
deliberately has no loop/branch/try node types (`docs/API.md:1061-1063`), and the paper's
design keeps the representation declarative while the library carries the logic (§4.1, §5,
M6). Adding native control-flow nodes would (i) break the non-Turing-completeness
guarantee that makes runs terminate and replay, (ii) duplicate what drivers already do,
and (iii) require schema, parser, engine, and history changes — a large blast radius for
no new capability. Revisit only if a scenario class proves **impossible** as a driver
(today: C3/V5 timeout/watchdog, which need per-action deadlines — an engine feature, not a
node type).

### 6.3 Parallel-branch negotiation

**Include as advanced/limited, and mostly do not build it.** The paper reports parallel
branch-merge negotiation as an open problem — "each parallel branch has its own notion of
the DAG. Without a central authority, the branches must negotiate the new notion of truth
before continuing when merging branches" (§5) — and this engine **designed it out**:
parallel-scope children get read-only handles, so two branches cannot both rewrite future
common activities (`adaptation.py:215-222`, `engine.py:575-594`). The run-all-then-select
form (B4) needs no adaptation at all — a plain `select_best` function reading the parallel
results suffices. Building a true negotiation mechanism would reintroduce the paper's
hardest problem for a scenario the read-only rule already covers conservatively. Keep
`select_best` (Tier 3) and document the limitation.

### 6.4 Copy-to-end vs. declared-body iteration

`check_convergence` copies the **entire preceding scope** as the body, so the body runs
more than the threshold (pinned `state["n"] == 4` for `converge_after=3`,
`tests/workflow/test_adaptation.py:551-573`) — a known inefficiency of the pattern. New
iteration drivers (`while_condition`, `retry`, `refine`) should keep the same
preceding-scope convention for consistency, but the docstrings must state the body
definition explicitly (the paper's opacity caveat, §5 L6). A declared-body form (the
driver names its body group) is a possible future refinement; it is not required for
correctness.

---

### 6.5 Effort and sequencing summary

| Tier | Functions | Shared prerequisite | Cumulative effort |
|---|---|---|---|
| 1 | `aggregate`, `guard`, `while_condition` | — | ~S+S+M |
| 2 | `try_action`, `retry`, `fallback`, `regression_gate` | `try_action` (for error cases) | ~S+M+M+S/M |
| 3 | `switch`, `throttle`, `nested_sweep`, `refine`, `select_best`, `randomize_scenarios`, `co_simulate`, `generate_od` | mostly none; `refine`/`co_simulate` build on `while_condition` | ~S–M each |

---

## 7. Integration recipe (condensed)

### 7.1 Registration

- **Decorator:** `@workflow_function` registers under the function's `__name__` in
  `DEFAULT_REGISTRY`; `@workflow_function(name="...", registry=my_reg)` for a custom
  name/registry (`registry.py:179-221`).
- **Registry method:** `registry.register(name, fn)` — caches the `wants_dag` flag at
  registration time (`registry.py:68-97`).
- **Library opt-in:** add the function to `LIBRARY_FUNCTIONS` (`library.py:325-336`) so
  `register_library()` registers it (`library.py:338-364`). **No self-registration at
  import** — a fresh interpreter must see an empty `DEFAULT_REGISTRY`
  (`tests/workflow/test_registry.py:25-43`).
- **Driver opt-in:** declare an explicit `dag` parameter in the signature. A bare
  `**kwargs` does **not** opt in (`registry.py:31-49`).

### 7.2 Signature convention

```python
def fn(<positional/keyword params>, *, dag: DAGHandle, **kwargs: Any) -> <plain result>:  # driver
def fn(<params>, **kwargs: Any) -> <plain result>:                                       # plain
```

- The `*` makes `dag` keyword-only; `**kwargs` absorbs globals + upstream results
  (`library.py:98-104`, `library.py:133-143`).
- The function must be deterministic, stdlib-only, and tolerate extra kwargs
  (`library.py:1-96`).
- A driver must not both declare `dag` and return workflow node(s) (`engine.py:560-568`).
- A driver's own return value (plain data) is what flows downstream — not the adapted
  nodes (`library.py:1-96`).

### 7.3 XML and Python usage

- **XML:** `<action function="name">` with `<argument key="..." value="..."/>` children
  (`schema.py:470-494`, `docs/API.md:971`). Globals go in the `<VerificationWorkflow>`
  wrapper (`schema.py:375-420`). A driver's declared downstream scope is the **next
  sibling group** (`tests/resources/workflows/dynamic_adaptation.xml:1-9`). For
  `evaluate_goal`-style alternatives, the scope's children must be **named** groups
  (`tests/workflow/test_adaptation.py:400-421`). For copy-to-end drivers, the iteration
  body **precedes** the check action in the same scope
  (`tests/workflow/test_adaptation.py:516-532`).
- **Python API:** `Action("name", **params)`, `Sequential(*children)`,
  `Parallel(*children)`, run via `Test_Framework(seq=..., parameters=..., registry=...)`
  (`schema.py:132-183`, `engine.py:861-888`, `docs/API.md:928-937`).
- **Parameter normalization:** an XML `values="5, 10, 15"` string is auto-converted to a
  list before the function runs, so XML and Python API give the same shape
  (`params.py:61-68`, `engine.py:447`).
- **Templates:** a new function can be wrapped in a `Template` for reuse
  (`schema.py:192-341`, `docs/API.md:987-995`).

### 7.4 Test and style requirements

- **pytest, 90% coverage floor** — enforced by config (`[tool.coverage.report]
  fail_under = 90`, `pyproject.toml:45-48`); CI runs
  `pytest --cov=sequence_extensions --cov-report=term-missing`
  (`.github/workflows/ci.yml:24-25`).
- **Python 3.9–3.13 matrix** (`.github/workflows/ci.yml:13-15`); `ruff check .` and
  `ruff format --check .` (`.github/workflows/ci.yml:27-30`).
- **ruff:** `line-length = 100`, `target-version = "py39"`, lint select
  `["E","F","W","I","UP","B"]` (`pyproject.toml:50-58`).
- **Zero runtime dependencies** (`dependencies = []`, `pyproject.toml:26`).
- **Test layout:** one test module per source module (`tests/workflow/test_<module>.py`);
  registry isolation via a fresh `FunctionRegistry` + `register_library(registry)`
  (`tests/workflow/test_library.py:21-24`, `:79-83`); the `pristine_default_registry`
  fixture snapshots/restores `DEFAULT_REGISTRY` (`tests/workflow/conftest.py:8-15`).
- **Both paths tested:** the same workflow via XML (`run_workflow`) and the Python API
  (`Test_Framework`) (`tests/workflow/test_engine.py:26-44` vs `:84`, `:111`).
- **Driver tests:** direct-call tests (build a `DAGHandle` via a helper, assert on
  `dag.ops`) plus end-to-end tests (call sequence + final result)
  (`tests/workflow/test_library.py:170-208`, `:237-278`, `:449-499`, `:532-562`).
- **Edge cases to cover** (per the existing matrix): no-files-found, missing required
  param, unknown alternative (with/without default), non-converging (bound), immediate
  convergence, comma-string values (`tests/workflow/test_library.py:203-208`, `:273-278`,
  `:465-499`, `:553-562`, `:545-550`, `:264-270`).
- **Determinism:** the suite is fully deterministic — no network, no sleeps, no order
  dependence (`tests/workflow/__init__.py:27-29`). A `retry` driver with a `delay`
  parameter is the noted exception and must keep sleeps out of the default test path.
- **Docstrings:** every public function gets a full docstring (signature, semantics,
  scenario, return, limitations) — the library module docstring documents each function's
  adaptation behavior, addressing the paper's readability criticism (`library.py:1-96`).

---

## 8. Open questions & future work

1. **Per-action timeout (engine gap).** C3 `timeout` and V5 `watchdog` are infeasible as
   drivers because the engine exposes no per-action deadline. `GraphPool.result` accepts a
   `timeout` (`graph_future.py:320-328`), but the engine does not pass one per action.
   An engine feature (e.g. a `timeout` parameter honored by the walker) would unblock both.
2. **Per-node exception capture (engine gap).** `try_action` (Tier 2) works around this at
   the library level by wrapping a named function call. If error-reactive scenarios become
   common, an engine-level "catch and record, let a sibling react" mechanism would be
   cleaner than wrapper functions.
3. **Declared-body iteration.** The copy-to-end convention (body = everything preceding
   the check) re-copies a growing scope and runs the body more than the threshold
   (`tests/workflow/test_adaptation.py:551-573`). A declared-body form (the driver names
   its body group) would be cleaner; it requires no engine change, only a convention.
4. **Multi-parameter sweeps.** `parameter_sweep` sweeps exactly one parameter
   (`library.py:167-173`); a grid over `k` parameters is `n^k` nodes and bites the
   10 000 bound quickly. A `grid_sweep` accepting a dict of parameter→values is a possible
   Tier 3 addition if demand appears.
5. **Optimizer statelessness.** Sequential optimization (I6) requires the driver to
   reconstruct the optimizer trajectory from collision-suffixed upstream kwargs — feasible
   but subtle. If built, it needs explicit determinism tests (same inputs → same
   trajectory).
6. **Paper's open items not addressed here:** templates for common functions "promising
   and warrant further evaluation" (§4.4, L9); large-binary handling in Git (§4.3, L8);
   MTMD integration (§5, L11); layering on more sophisticated workflow management tools
   (§3.3, L12). These are outside the driver-function decision.
7. **DOI discrepancy.** The repo's source headers cite `10.3384/ecp12076741` while
   `docs/breakdown/00-intent/vision.md:11` cites `10.3384/ecp218741` for the same paper;
   one of them is a typo. Worth resolving in a separate commit (not this document).
