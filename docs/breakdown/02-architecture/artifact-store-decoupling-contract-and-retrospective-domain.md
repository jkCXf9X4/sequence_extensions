---
id: INFO-009
type: info
title: Artifact store — decoupling contract and retrospective domain
summary: The walker drives the store with settled facts; the store sees only the present and the causal past, so frozen snapshots answer every query and replay needs no engine.
date: 2026-10-11
status: current
---

# Artifact store — decoupling contract and retrospective domain

Why the store's boundary sits where it does, and what invariant holds it
there. The store's parts and addressing are `INFO-008`; the decision is
`DR-004`; the investigation is `IMP-005`.

## Two arrows, opposite directions

- Dependency: the engine imports the store; the store imports schema only,
  never the reverse.
- Information: the walker pushes settled facts into the store; the store
  never pulls.
- Module decoupling is not information decoupling: the store is a passive
  service driven by the engine.
- The schema import is vocabulary only — `group_label` reads a node's
  name or kind; no tree knowledge crosses the boundary.

## The walker is the courier, the store the record

- Only the walker observes the live, transformed DAG; it re-reads
  children every step (`INFO-004`).
- The walker compresses every observation into settled facts: an address,
  the readable past, the completed groups.
- The store receives results, never mechanics: a sweep splices three
  clones; the store receives three addresses in walk order.
- Mint at submission, never recompute: the address is computed after the
  dust settles — the store receives identity, not history.
- An observing store would need the adaptation protocol (splices, replace
  ops, the commit transaction); that would be the real pollution.

## The domain is retrospective-only

- Write scope: the present — the node's own directory, written once, by
  its one node (single assignment).
- Read scope: the past — the own directory, the causal past, the completed
  groups' branches.
- Nothing ahead of the walker is reachable; the forward-read API does not
  exist.
- A settled domain has one decisive property: a frozen snapshot answers
  every possible query.
- The handle is plain data, built on the walker thread, used on a pool
  worker: no live tree references, no callbacks, no locks at read time.

## Causal past, not temporal past

- A sibling branch may finish before another runs (temporally past) yet
  never fan into its kwargs (causally forward): unreadable. The parallel
  barrier is this rule, not a second one.
- The scope is exactly the actions whose results the engine delivers to
  the call.
- Artifact visibility mirrors result visibility by construction, not by a
  second rule the two planes could drift on.

## One widening, still retrospective

- `branches(name)` reads inside completed groups' branch directories:
  wider than the kwargs fan-in, but the whole subtree must be settled
  first. It widens what of the past is visible, never when.

## The inherited invariant

- Behind the walker: frozen. Ahead: unwalked. The walker's sequential
  invariant (`INFO-004`).
- The same invariant that makes `dag` writes safe makes artifact reads
  settled: no new proof obligation.
- Replay proves the boundary: `ReplayArtifacts` reconstructs every view
  from the manifest alone, no engine, no live tree.

## Owns

- The decoupling contract: dependency direction, information direction.
- The retrospective-only domain rule and its snapshot consequence.
- The causal-past definition of the read scope.

## Excludes

- The store's parts, addressing, manifest, handle surface: `INFO-008`.
- The walk and injection mechanics: `INFO-004`.
- The decision, alternatives, consequences: `DR-004`, `IMP-005`.
