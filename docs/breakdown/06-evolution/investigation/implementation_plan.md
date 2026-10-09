# Dynamic adaptation via a lazy tree-walking engine

**Date:** 2026-10-09
**Status:** architecture chosen — ready to implement
**Decides:** the open architecture question from
`docs/breakdown/06-evolution/investigation/dynamic_adaptation.md` (§4.2/§5.1), which this plan amends.

## 1. Decision

- **Engine shape: LAZY TREE-WALKING INTERPRETER.** `workflow/engine.py` is rewritten from
  "eagerly build all futures, then let the pool drive" to "walk the node tree child by child,
  submitting one `GraphFuture` per action as it goes." The rejected alternative (keep the eager
  engine + reconcile hooks) is recorded in the conversation and the investigation doc.
- **`graph/graph_future.py`: ZERO changes.** The substrate stays frozen; the walker is a
  different *consumption pattern* of it (incremental instead of compile-whole-tree).
- **The node tree is the mutable DAG** (the "blackboard"). Alterations are never *passed* to the
  engine: functions mutate the tree through a scoped handle (transactional commit at function
  return), and the walker observes by re-reading the live tree after every step.

## 2. Architecture

```
library functions  (find_files, evaluate_goal, check_convergence, ...)   ← Turing-complete part
        │  dag= handle (injected only when the signature declares it)
        ▼
DAGHandle / workflow/adaptation.py  — scoped reads, op log, write rules, bound
        │  transactional commit at function return (one lock acquisition)
        ▼
node tree (schema Action/Sequential/Parallel) — the mutable DAG; surgery under engine lock
        │  walker step loop re-reads group.children after every step
        ▼
engine walker (workflow/engine.py, rewritten) — lazy; actions run as GraphFutures on GraphPool
```

## 3. Key invariants (the correctness core)

1. **Sequential invariant:** while action A's function runs, every following position in A's own
   scope is unwalked → handle writes can only land on nodes that have no future yet. Structural,
   not conventional.
2. **Parallel parents → read-only handles:** inside a `Parallel` scope the invariant fails
   (siblings can be running), so all write ops (and splices) raise `ValueError`. This resolves
   finding F4 structurally.
3. **At-most-once:** each walked node runs exactly once; removed nodes are never walked (no
   cancellation machinery needed at all).
4. **Bounded adaptation:** engine counts dynamic nodes added; exceeding the bound (default
   10 000) raises a deterministic `ValueError`.

## 4. The commit protocol

1. **Injection** — the walker passes `dag=` only when the function's signature declares it;
   the registry caches the `wants_dag` flag at registration time. `dag` is a reserved kwarg
   name for adapting functions (injected handle wins).
2. **During the call** — reads (`following()`, `preceding()`, node traversal via `.children`)
   are served from the live tree; write ops (`replace`, `adjust`, `append`, `copy`) are
   validated eagerly (scope rules, read-only, bound) and recorded as data (`AdaptationOp`).
   Functions never build nodes — `dag.copy(target, **param_overrides)` clones subtrees.
3. **At return — the commit** (same thread, inside `_run_action`, one lock acquisition):
   re-validate → tree surgery (children-list edits, in-place `params.update` for adjust,
   appends at scope end) → bound check → record `adaptations` on the `ExecutionRecord` →
   `_mark_dynamic` on inserted nodes. If the function raised, the log is discarded —
   nothing applied (atomic; matches the paper's "merged when returned").
4. **The walker observes** — `while i < len(group.children)` re-reads the live tree each
   step. Replace-next-sibling-group (Listing 5), replace-next-sibling-action (Listing 7
   inner / F1), and append-at-scope-end (§5 iteration) are all plain tree edits.

## 5. Engine rewrite specifics

- `_walk_sequential(group, pairs)`: live re-read loop; accumulate `(action, result)` pairs —
  an action contributes its own pair, a group contributes its *direct action children's*
  pairs (one-level flattening, matching today's fan-in chain).
- `_walk_parallel(group, pairs)`: snapshot children; **action** children submit as
  `GraphFuture`s; **group** children run on plain `threading.Thread`s (never on pool workers —
  avoids the walk-task starvation deadlock). **Wire-then-wait (parallelism parity):** all
  action futures are wired at once via a join future (`GraphFuture(fn, *child_futures)` + one
  `pool.result`, exactly today's `_group_future` pattern) — never awaited one at a time
  (`pool.result` in a loop would serialize the group). Join threads, assemble results in
  child order, then raise the first *in-order* exception (parity: today's `_collect` waits for
  all children to settle before failing).
- kwargs resolution (globals + accumulated pairs + collision suffixes + own params) reused
  verbatim from `_run_action`.
- Pre-validation pass at `run()` start: every action's function name resolvable — preserves
  today's eager `ValueError` for unknown functions before any execution.
- Final result: `_final_action(root)` post-run tree resolution (mirrors `_find_final_future`);
  each action's runtime result stored as `action._engine_result`; `_mark_final` via
  `action._engine_record` as today.
- **Removed machinery:** `_cancelled` / `_skip` / `_SENTINEL`, `_build` / `_wire` /
  `_collect` / `_locate` / `_find_final_future` / `_group_future`.
- **Return-nodes protocol (back-compat):** fn returns nodes → `check_splice_scope` → tree
  surgery → mark spliced `_engine_dynamic` + `_engine_executed` → nested sequential walk with
  the actor's *upstream* pairs → actor's runtime result = spliced results list → outer walker
  skips the executed nodes without adding their pairs (parity: downstream sees the actor-keyed
  spliced list, exactly today's semantics).
- `check_splice_scope` changes: allow an **action** next sibling (F1); reject splices whose
  parent is `Parallel` (F4).
- **Substrate usage note:** the walker deliberately consumes a narrow slice of
  `sequence_extensions.graph` — the pool as bounded executor (every action still runs on a
  pool worker), `GraphFuture` as a task with a Future facade, one-level joins
  (`GraphFuture(fn, *child_futures)`, whose positional resolution gives the first-in-order
  exception semantics), `pool.result` for wire-then-wait, and exit-time cancellation. NOT
  consumed: multi-level dependency scheduling (the walker owns ordering — the tree is the
  schedule), chaining (already unused by the workflow layer today — the splice uses the
  blocking form), and cycle detection (defensive only). The substrate stays anyway: it is a
  public, pinned module (top-level export, own test suite) whose DAG scheduling is its
  standalone feature, not engine incidental complexity; unused paths cost nothing at
  runtime; the narrow surface avoids the substrate's hardest modes (deep chains +
  callbacks + cancellation — where the F4-class bugs lived); and keeping it frozen contains
  the rewrite risk. If the substrate is ever deemed internal-only, slimming it is a separate
  later pass, never bundled with this rewrite.

## 6. Parity checklist (the 295 existing tests are the gate)

- fan-in kwargs (chain accumulation, one-level group flattening, collision suffixes)
- group result = ordered list of child results; root result = last action's result
- **parallelism ceiling:** a `Parallel` group's children (and their whole subtrees) start
  concurrently in both engines — the ceiling is tree-determined, not build-time-determined;
  pinned by a barrier-based test (two parallel actions must overlap; a serializing walker
  deadlocks/timeouts)
- return-nodes: "the spliced group's result becomes the action's result"; replaced subtree
  does not run; spliced actions recorded `dynamic=True` after the actor's record
- at-most-once; `ValueError` behavior/messages for unknown function and out-of-scope splice
- history: completion order, `final_order` marking, `replay` determinism
- failure paths: parallel siblings run to completion before the exception propagates

Deliberate, documented behavior changes (previously racy/underspecified or new):
- splice/handle writes from inside a `Parallel` parent → `ValueError` (F4 fix)
- handle-driven replacements run in place; their results fan in keyed by their own action
  names (return-nodes keeps actor-keyed legacy semantics)
- a function that declares `dag` AND returns nodes → `ValueError` (one mechanism per action)
- `find_files`/`parameter_sweep` re-expressed via the handle: their own return value becomes
  their result (the file/value list) instead of the spliced segment's results — verify
  affected tests, update minimally where pinned

## 7. Schema (`workflow/schema.py`)

- `<scope type="sequential|parallel">` with required, validated `type`; optional `name`.
- `<sequential>`/`<parallel>` keep parsing as aliases (D1 recommendation, no deprecation
  warnings); `<scope>` allowed everywhere a group is allowed (root, wrapper, nested, template
  bodies).
- Maps onto the existing `Sequential`/`Parallel` classes (`name` becomes a keyword on
  `_Group.__init__`); history path labels unchanged (derived from type: `sequential[i]` etc.).
- Invalid structure → existing-style `ValueError`s (missing/invalid `type`, bad children).

## 8. Library (`workflow/library.py`)

- `find_files` / `parameter_sweep`: clone the declared following scope per file/value via the
  handle (`dag.copy(body, file=f)` + `dag.replace(body, clones)`), replacing hardcoded node
  construction.
- NEW `evaluate_goal` (objective 2, branching): reads an upstream result field, selects a
  named child of the following alternatives scope; others never run; unknown alternative →
  `ValueError`; optional default alternative.
- NEW `check_convergence` (objective 2, iteration): while not converged, appends a copy of
  the iteration body at the scope end (copy-to-end, §5); returns a summary; unknown
  iteration count; engine bound terminates runaways.
- `register_library()` grows; still opt-in.

## 9. History & replay (`workflow/history.py`)

- `ExecutionRecord.adaptations: list[dict]` — committed op descriptors (plain data).
- `ExecutionRecord.scope: dict | None` — snapshot of the acting action's sibling list +
  index, recorded at injection; replay materializes a fake tree from it.
- `replay`: strip the recorded `dag` kwarg, re-inject a replay handle (reads served from the
  materialized snapshot; writes are no-ops). Strict op-equality assertion = optional follow-up.

## 10. Phases (implementation order)

1. **Read & pin:** `library.py`, `registry.py`, `params.py`, all `tests/workflow/*`, test
   resources, `docs/API.md`/`README.md`/`CHANGELOG.md` — confirm every pinned behavior above.
2. **Engine rewrite** to the lazy walker, pure behavior-parity refactor, gated by the existing
   suite (no new features yet).
3. **`workflow/adaptation.py`** (DAGHandle, AdaptationOp, commit) + engine injection +
   `check_splice_scope` updates (F1, F4).
4. **Schema `<scope>`** + alias-equivalence.
5. **Library** re-expression + `evaluate_goal` + `check_convergence`.
6. **History** `adaptations`/`scope` + replay handle.
7. **Tests:** rewrite the two Listing-7 tests (inner case now in scope); add: scope parsing +
   alias equivalence, handle ops + write rules + parallel read-only, branch-by-selection
   (chosen runs / others never / unknown → ValueError), iterate-until-converged with unknown
   count, at-most-once across copied iterations, history/replay with handle, the
   barrier-based parallelism-parity test (§6), one integration XML
   (`<scope>` + template + handle drivers + history); update the fixture README table.
8. **Docs:** `docs/API.md` workflow section (schema, engine, registry, library, history,
   adaptation contract table, non-Turing-completeness statement), `README.md` example with
   `<scope>`, `CHANGELOG.md` entry, amend the investigation doc (§5.1 → walker architecture +
   this layering analysis), touch up the alignment report's P2 row.

## 11. Settled decisions

- D4 injection: signature inspection, flag cached at registration.
- D5 bound: 10 000 dynamic nodes (engine-level, deterministic `ValueError`).
- Write rules: full investigation §4.2 (later siblings + following subtrees + appends) —
  the walker makes far-sibling writes trivial, so no narrowing is needed.
- D1–D3 per the investigation's recommendations: alias strategy, `sequential`/`parallel` type
  values, required `type`.

## 12. Risks / watch-list

- Tests asserting exact splice error-message texts (update with the F1/F4 wording changes).
- `find_files` result-semantics change (§6) — verify and update minimally.
- Thread usage: one plain thread per parallel-group *group* child (bounded by workflow
  structure; actions still run on the pool).
- Failure-path parity: join-all-then-raise in `_walk_parallel`.
