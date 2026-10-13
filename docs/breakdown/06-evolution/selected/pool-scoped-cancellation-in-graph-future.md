---
id: IMP-019
type: imp
title: Pool-scoped cancellation in graph_future
summary: GraphPool.__exit__ cancels every live node process-wide, so concurrent flows in one process corrupt each other; iterate the pool's own nodes instead
date: 2026-10-14
status: current
---

# Pool-scoped cancellation in graph_future

Candidate, not selected. Deferred: `DR-005` keeps the substrate
(`graph.graph_future`) untouched.

## Pain

- `GraphPool.__exit__` iterates the module-wide `_LIVE_NODES` weakset,
  so exiting a pool cancels every pending `GraphFuture` in the process,
  not just its own.
- Consequence, documented as an accepted limit in `INFO-011`: flows run
  sequentially per process; a flow exiting while another has pending
  nodes cancels the other's work.

## Proposal

- Iterate the pool's own bound nodes (`self._nodes`) instead of the
  global weakset — a two-line change in `graph_future.py`.
- Keeps the global weakset for the atexit handler (process teardown),
  where global is correct.

## Cost

- Touches the substrate `DR-005` deliberately leaves unchanged.
- The current behavior may be load-bearing: unbound dependents of a
  pool's nodes (futures never registered with this pool) are cancelled
  by the global sweep; scoping needs its own test matrix.
- Review trigger: a real requirement for concurrent flows in one
  process (nested-parallel drivers, a server embedding the engine).

## Evidence

- `INFO-011` accepted limits (first bullet).
- `tests/graph/test_graph_future.py` pins the current exit semantics.
