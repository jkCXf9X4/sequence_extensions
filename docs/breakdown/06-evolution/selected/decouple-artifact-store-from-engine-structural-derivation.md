---
id: IMP-007
type: imp
title: Decouple artifact store from engine — structural derivation
summary: Engine sheds all store knowledge: a plain walk context (own node plus ancestry) is the only injection, and the store derives address, causal past and branches structurally at call time via registry wrapping
date: 2026-10-11
status: current
---

# Decouple artifact store from engine — structural derivation

## Problem

- INFO-009's decoupling is one-sided: the store imports schema only; the
  engine imports the store and threads its addressing state.
- `_WalkState` (path, labels, mints, readable, groups) threaded through
  every walk, `_mint_address`, handle injection, `self._store`: 150 lines.
- A second consumer (tracer, profiler) extends the engine again — no
  extension surface exists.

## Key finding — the store's needs are structural

Everything the handle needs is a function of (own node, live tree) at
call time. No walk state.

- **Address** — rank among same-function siblings in the parent; per
  ancestor, rank among same-label siblings. Rank-based:
  scheduling-independent.
- Ranks reproduce `enter` / `mints` counting in every current mechanic
  (appended bodies, clones, splices, `select` / `skip_following`,
  parallel order).
- **Readable** — per ancestor, preceding action children plus direct
  action children of preceding group children (flattening is literal
  one-level).
- Spliced nodes included without a special case: preceding siblings in
  the live tree. Nodes replaced before start: absent, never entered,
  never minted.
- **Groups** — parallel groups in the deep left flank, sequential
  descent only, never a parallel barrier; matches `new_groups`
  propagation.

**Freeze theorem** — an action's ancestry and left flank are frozen from
submission to call completion. Mutations come only from preceding
siblings (done), the action itself, or later siblings (after). Concurrent
branches mutate their own subtrees; parallel parents are read-only
(`IMP-001` F4). Enforced for adaptation correctness; the derivation
borrows it. The store relies on it — pin with a test.

## Design

- **Walk context** — the engine's one generic addition: own node plus
  ancestry chain of (group, index) pairs. Plain data, injected as a
  reserved kwarg when declared; the walk holds the chain natively.
- Not the dag handle: `DAGHandle` carries (parent, index), adapting
  functions only, name bound to return-nodes rejection and commit.
- **Registry wrapping** — the store plugs in at the `run_workflow` /
  `Test_Framework` wiring point. The wrapper declares context, mints the
  manifest row, derives address / readable / groups, injects the handle
  for `artifacts`-declaring functions.
- The wrapped registry preserves inner `wants_dag` flags; the
  `artifacts` flag becomes wrapper-internal.
- Wrapping is safe because addresses are rank-based, not mint-order.
- **Engine deletions** — artifacts import, `_WalkState`, `_mint_address`,
  handle injection, `self._store`. Residue: context injection, the
  `_engine_address` getattr, `store._begin()` at wiring.
- **Determinism** — manifest `seq` becomes call order; parallel action
  children interleave too (cross-branch already accepted, `INFO-008`).
  Entry sets and addresses unchanged.
- **Cost** — only declaring actions pay the closure derivation.

## Work plan

- **W1** — thread (group, index) chains; inject context when declared.
- **W2** — move addressing into `artifacts.py`; registry wrapper; delete
  engine store code.
- **W3** — `ReplayArtifacts` wrap shape; replay strips the context kwarg
  as it strips `artifacts` today.
- Independent of IMP-005 P0 / P3. Lands on top of `IMP-006`.
- At implementation, revise `INFO-009`: walker couriers raw position.

## Owns

- Where artifact addressing derives from: walk state versus structure.
- The store's plug-in point: injection versus registry wrapping.

## Excludes

- Unchanged: handle API, manifest shape, addresses, layout, opt-in,
  paper parity — the `INFO-008` / `DR-004` contract.
- Schema, `graph/graph_future.py`, walk semantics; `DAGHandle`
  injection stays engine-side — `INFO-004`, `IMP-006`.
- P0 control-plane hygiene (`run_2` collision, D5 echo) — `IMP-005`.

## Verification

- Property test: derived addresses equal today's minted addresses across
  the driver corpus (sweep, iterate, branch, skip, return-nodes).
- Freeze theorem pinned by a dedicated test.
- Determinism: manifest entry sets and addresses stable across runs.
- The 34 tests in `tests/workflow/test_artifacts.py` pass; row-order
  assertions move from submission order to call order.
- `pb check --strict`, full suite.
