---
id: CP-030
type: capability
title: UC-30 Compose nodes — a node inside a node
summary: a reusable node tree runs as a step in a larger node tree — one run, one log, future-first fan-out, and composite policy for the subtree
date: 2026-10-21
status: current
---

# UC-30 Compose nodes — a node inside a node

## Scenario

- A team has a reusable sub-workflow — a calibration campaign, a report phase, a model build — and wants it as one step in a larger campaign.
- The sub-workflow must stay runnable on its own and keep one complete record when nested.
- The team wants retry and wall-budget policy for the whole sub-workflow, not repeated on each inner node.
- Several sub-workflows may run concurrently, and a sub-workflow may itself contain one.

## Acceptance

- A composite is an ordinary `@node` that calls or submits other nodes.  The whole tree is one run, one pool, and one log; no second run or log is opened.
- Node records carry `path` (the node-name chain) and `parent_attempt`; the nesting is visible without separate run files.
- A node may return a value or a future.  A returned `submit()`/`gather(...)` future is awaited by that node's attempt; the worker is freed and can run other work.  `.result()` on an incomplete future inside a node body (root or worker) raises with guidance instead of deadlocking.
- `gather(value)` resolves every future inside a value without `.result()`, preserving container shape (dicts and nesting included); the result can be returned or passed to a dependent node.
- A composite's `retries` and `timeout` apply to the returned future as a whole.  A failure is recorded once for the composite attempt and once for the failing child; a retry re-executes the subtree with a new `parent_attempt`.
- A composite timeout drops late records from its abandoned subtree; only the composite attempt is recorded.
- `execute_flow` is top-level only: calling it inside an active run raises.  A host runs a sub-workflow on its own by calling `execute_flow` at the top level.
- Concurrent fan-out from a submitted composite works at `max_workers=1` without a second pool.
- Reference-mode logs stay byte-identical for identical nested fan-out; node records are ordered by `path`, `parent_attempt`, attempt, and inputs.
- Process workers cannot submit or return live futures; process-mode fan-out is built in the parent process.

## Evidence

- `tests/flow/test_nested.py` — three-level nesting, submitted composite fan-out at `max_workers=1`, inline fan-out on a worker, gather forms + dependent node, composite retry/timeout/failure, pending-subtree drain, container-of-futures rejection, fixed-clock nested fan-out.
- `tests/flow/test_node.py` — submit inside a worker fans out; blocking on a future in a worker raises; incomplete plain-future return and plain-future dependency; exported future types; node policy and defaults.
- `tests/flow/test_run.py` — one log for nested nodes, nested `path`/`parent_attempt`, node defaults across a nested tree, fixed-clock nested stability.
- `tests/flow/test_process_pool.py::test_execute_flow_inside_process_worker_is_rejected`

## Owns

- The nested-workflow need: composition of nodes, nested audit paths, future-first fan-out, and composite policy over a returned future.

## Excludes

- How the need is met: `INFO-002` (shipped surface), `INFO-011` (engine design).
- Implementation rationale: `DR-018` (with `DR-017`).
- Concurrent runs at the top level: `CP-023`.
- The run record's shape: `CP-020`.
- Determinism of the comparison: `CP-025`.
