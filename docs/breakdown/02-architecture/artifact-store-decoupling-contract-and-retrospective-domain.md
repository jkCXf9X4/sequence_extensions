---
id: INFO-009
type: info
title: Artifact store — decoupling contract and retrospective domain
summary: The store derives from raw position (walk context + registry wrapping); the store sees only the present and the causal past, so frozen snapshots answer every query and replay needs no engine.
date: 2026-10-11
status: current
---

# Artifact store — decoupling contract and retrospective domain

Why the store's boundary sits where it does, and what invariant holds it
there. The store's parts and addressing are `INFO-008`; the decision is
`DR-004`; the investigation is `IMP-005`.

## Two arrows, opposite directions

- Dependency: the store imports schema and registry, never the engine;
  the engine imports the store only for type checking — at runtime the
  wiring point (`IMP-007`) talks to it through its protocol and swaps in
  its wrapped registry view.
- Information: the walker pushes the action's RAW POSITION (the walk
  context — node plus ancestry chain); the store derives everything else.
- Module decoupling and information decoupling now agree: the store is a
  plugged-in consumer of position data, not a service the engine drives.
- The registry import is vocabulary only — signature flags and the
  registry surface; no tree knowledge crosses the boundary.

## The walker is the courier, the store the record

- Only the walker observes the live, transformed DAG; it re-reads
  children every step (`INFO-004`). The walk recursion holds every
  action's ancestry natively — position is where it walks.
- The walker hands out plain position data; the store's registry wrapper
  derives the settled facts from it: the address, the readable past, the
  completed groups.
- The store receives results, never mechanics: a sweep splices three
  clones; the store derives three ranks in child order.
- Mint at call entry, never recompute: the derivation reads the live
  tree at the one moment it is provably settled — the freeze theorem
  (`IMP-007`: an action's ancestry and left flank are frozen from
  submission until call completion; the same sequential invariant that
  makes `dag=` writes safe).
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
- The handle is plain data (address plus the causal-past and
  completed-group views derived at call entry), so it is safe to build
  and use on a pool worker: no live tree references, no callbacks, no
  locks at read time.

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
