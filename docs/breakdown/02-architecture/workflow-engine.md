---
id: INFO-004
type: info
title: Workflow engine — lazy tree-walking interpreter
summary: The workflow engine walks the node tree lazily, one GraphFuture per action; runtime adaptation mutates the live tree through a scoped DAGHandle with transactional commit.
date: 2026-10-09
status: current
---

# Workflow engine — lazy tree-walking interpreter

The workflow engine is a lazy tree-walking interpreter. It walks the node tree child by child, one `GraphFuture` per action, instead of compiling the whole tree up front. The node tree is the mutable DAG; the walker re-reads it after every step, so runtime changes are observed immediately. The design is motivated by `IMP-001` and locked in by `DR-002`.

## The walker

- `_walk_sequential` re-reads `group.children` every step; a runtime splice is seen on the next iteration.
- `_walk_parallel` snapshots children once; action children submit as `GraphFuture`s, group children run on plain threads (never pool workers, to avoid starvation).
- Each action runs as a `GraphFuture` on the pool; upstream results are positional dependencies (strict ordering).
- The final result is the last action's result, resolved post-run by `_final_action`.

## The DAGHandle

- A `DAGHandle` is a scoped read/write handle on the live tree, injected as the reserved kwarg `dag` when a function's signature declares it.
- Reads (`following()`, `preceding()`, `copy()`) are served from the live tree.
- Writes (`replace()`, `adjust()`, `append()`) are validated eagerly and recorded as `AdaptationOp` data, never applied directly.
- At function return, the engine commits the op log under one lock: re-validate, apply, bound-check, mark dynamic. If the function raised, the log is discarded (atomic).

## The invariants

- **Sequential:** while an action runs, its following positions are unwalked, so handle writes land only on nodes with no future yet.
- **Parallel parents are read-only:** inside a `Parallel` scope, all write ops raise `ValueError` (the F4 race is resolved structurally).
- **At-most-once:** each walked node runs exactly once; removed nodes are never walked (no cancellation machinery).
- **Bounded adaptation:** the engine counts dynamic nodes added; exceeding 10 000 raises a deterministic `ValueError`.

## Owns
- The workflow engine's execution model: the lazy tree-walking interpreter, the DAGHandle, and the invariants.
