---
id: IMP-021
type: imp
title: Public bind API on GraphPool
summary: The only public bind-without-wait is result(gf, timeout=0), which raises the node's own exception when settled; the flow layer uses private _bind_graph instead
date: 2026-10-14
status: current
---

# Public bind API on GraphPool

Candidate, not selected. Deferred: `DR-005` keeps the substrate
(`graph.graph_future`) untouched.

## Pain

- Binding a graph without waiting on results has one public path:
  `pool.result(gf, timeout=0)` — and it **raises the node's own
  exception** when the node settles before the zero-timeout check. An
  instantly-failing dependency triggers exactly that.
- The API is bind-plus-raise-if-settled, not a pure bind; a caller
  copying the bind-without-wait pattern gets a surprise exception from
  a call documented as a wait.
- The flow layer works around it with its one deliberate private-API
  use: `pool._bind_graph(gf)` in `task.submit()` (rationale commented in
  place), held under a flow-layer bind lock because
  `GraphPool._visiting` is pool-level DFS state, not thread-safe.

## Proposal

- A public `GraphPool.bind(gf)`: bind the reachable graph — submit every
  ready leaf, raise `ValueError` on a dependency cycle — without touching
  any result.
- `task.submit()` switches from `pool._bind_graph(gf)` to
  `pool.bind(gf)`; the private call disappears from the flow layer.

## Cost

- Touches the substrate `DR-005` deliberately leaves unchanged — one
  additive method, no behavior change to existing paths.
- Own test matrix: bind idempotency, cycle raise at bind time, proof
  that no result is touched.
- Pairs with `IMP-019` (the other substrate follow-up) if the substrate
  is ever reopened; one reopen can carry both.

## Evidence

- Surfaced during flow-layer implementation by
  `tests/flow/test_flow.py::test_flow_failed_dependency_gets_skipped_record`
  (the instantly-failing dependency case).
- Rationale comment at the call site: `src/sequence_extensions/flow/task.py`,
  `TaskFunction.submit`.
