---
id: IMP-008
type: imp
title: Generic node layer in graph
summary: Node structure and the DAG manipulation patterns move to a domain-free graph layer; workflow schema, DAGHandle and ReplayHandle become specializations
date: 2026-10-12
status: current
---

# Generic node layer in graph

## Problem

The workflow package owned its own structural substrate, as private
domain helpers:

- Tree operations were reimplemented per module:
  `adaptation._contains`, `engine._find_in_tree` / `_position_of`, and
  `schema.clone_node` (itself a dedupe of two earlier copies) — three
  private implementations of containment, search and deep clone.
- The `DAGHandle` combinators (`fan_out` / `select` / `skip` /
  `skip_following` / `repeat`, IMP-006) are intent-level *tree*
  manipulations, but lived as domain code: nothing but the workflow
  could reuse the map / branch / skip / iterate patterns.
- `ReplayHandle` mirrored the handle **by hand** — every new method
  needed a second implementation, and the two had already drifted
  (`select`'s error message and default-miss behavior differed).
- The `graph` branch held only the future substrate; the structural
  layer it should own did not exist.

## Decision

Extract a generic, domain-free node layer into `graph`:

- `graph.node` — `Node` (ordered `children` + optional `name`;
  identity-based `contains`, depth-first `locate`, deep `clone` with a
  per-class `_copy` hook that receives the opaque overrides) and
  `Group` (the container specialization; "is a branch" is a structural
  check).
- `graph.handle` — `TreeHandle`, the scoped manipulation surface:
  reads (`following` / `preceding` / `following_group`), clone ops
  (`copy` / `adjusted` / `copy_self`), write primitives (`replace` /
  `append`) and the five intent-level patterns, verbatim flows.  The
  handle never mutates: a domain supplies policy through hooks —
  `_emit` (op recording), `_check_writable`, `_check_target`,
  `_check_nodes`, `_empty_group`.

The workflow layer becomes a specialization:

- `Action(Node)` (leaf) and a group base on `Group` that adds
  `.globals`; `clone_node` is superseded by `Node.clone`.
- `DAGHandle(TreeHandle)` keeps only the policy: workflow validation
  rules and messages, `AdaptationOp` recording plus the dynamic-node
  bound, the empty-`Sequential` skip sentinel, `adjust`, and `ops`.
- `ReplayHandle(TreeHandle)`: value-returning flows (`select`, clone
  ops, reads) are inherited and served from the fake tree; write-only
  patterns (`fan_out` / `skip` / `skip_following` / `repeat`) are
  explicit no-ops, so replay raises nothing it did not raise before.
- Engine: `_find_in_tree` (3 call sites) → `Node.locate`.

Behavior notes (documented, deliberate):

- Op shapes are identical by construction — the flows moved, they did
  not change; the commit protocol (`_commit` / `_apply` /
  `_revalidate`) is untouched.
- Pattern-raised errors lose the `dynamic adaptation: ` prefix (they
  now come from the generic layer; every pinned `match=` substring is
  retained).  `DAGHandle`'s own hook messages (read-only parallel
  scope, executed target, scope, node types, bound) keep their texts.
- Replay `select` unifies with the live handle's error path (the two
  had drifted); successful replay is unaffected.

Declined: moving `DAGHandle` itself into `graph` (the commit protocol,
`AdaptationOp` and the validation rules are workflow domain — the
generic layer must stay independent); generic surgery methods for
one-line list edits; a generic message catalog.

## Owns

- The generic node layer (`graph.node`): `Node`, `Group`, the tree
  operations, the clone hook contract.
- The generic scoped manipulation layer (`graph.handle`): `TreeHandle`
  and the hooks that domain handles implement.

## Excludes

- Engine commit protocol, op kinds, `AdaptationOp` shape — `INFO-004`.
- Schema constructs (XML, templates) — `IMP-001`.
- ReplayHandle's fake-tree materialization (history format).
- Artifact store — `IMP-007`.
- Return-nodes splice protocol (unchanged).

## Verification

- `tests/graph/test_node.py`, `tests/graph/test_handle.py` — generic
  node operations, hook contracts, pattern op shapes, workflow
  specialization facts.
- The 447 pre-existing workflow tests pass unchanged.
- `pb check --strict`, `pytest --cov` (96.4%), `ruff check .` — pass.
