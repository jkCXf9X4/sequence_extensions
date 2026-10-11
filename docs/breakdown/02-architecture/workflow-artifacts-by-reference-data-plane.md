---
id: INFO-008
type: info
title: Workflow artifacts — by-reference data plane
summary: The artifact store couples bulk data to the DAG, not the engine: minted addresses, an append-only manifest, a scoped handle with causal-past reads and fan-in branch enumeration
date: 2026-10-11
status: current
---

# Workflow artifacts — by-reference data plane

The workflow layer has two data planes. Control data (verdicts, counts,
paths, summaries) flows by value through kwargs, as the paper specifies.
Artifacts (simulation outputs, reports, datasets) flow by reference through
`workflow/artifacts.py`: written to a per-action directory, referenced by a
root-relative pointer that flows by value like any result. Motivated by
`IMP-005`; locked in by `DR-004`; the execution model is `INFO-004`.

## Split by weight

- Control data by value through kwargs: unchanged, paper parity.
- Artifacts by reference through the store: never enter kwargs.
- The store imports the schema only, never the engine (same isolation as
  history). The engine injects a handle; it never touches file payloads.

## Addressing

- An address is the action's call-time tree position: enclosing scope
  labels (a named scope by name, an unnamed one by kind) plus the function
  name, each with a collision suffix on repeat (`name`, `name_2`).
- Minted at submission, on the walking thread, in child order: walk order,
  never thread scheduling.
- Stored on the action, appended to the run's manifest, never recomputed.
  Positions shift under adaptation; minted addresses never move.
- Sweep clones and iteration bodies mint fresh directories
  (`sequential`, `sequential_2`, ...): single assignment, per-clone outputs
  preserved.

## The manifest

- `root/manifest.jsonl`, append-only, one entry per executed action in
  mint order: `seq`, `address`, `function`, the action's OWN `params`,
  `dynamic`.
- Own params, never merged kwargs: the manifest cannot echo upstream
  results.
- The manifest is executed truth; the XML is declared truth.
- Global sequence numbers may interleave across concurrent parallel
  branches; every address is deterministic.

## The handle

- Injected as the reserved `artifacts` kwarg when a function declares it
  and the run has a store (registry-cached flag, mirroring `dag`).
- Write scope: `out_dir()`, the node's own directory, nothing else.
- Read scope: the causal past — the own directory, the directories of the
  actions whose results fan into this call's kwargs, and the branch
  directories of completed parallel groups in the causal past.
- Fan-in: `branches(name)` enumerates every completed group named `name`
  in the causal past, in causal order (all-occurrences, like the library's
  upstream suffix scans).
- The read scope mirrors the by-value scope by construction: the walker
  threads the readable past alongside the kwargs chain, so parallel
  siblings are barriers for artifacts exactly as for results.

## Replay

- `replay(history, registry, artifacts=store)` re-invokes
  artifacts-declaring functions with a `ReplayArtifacts` handle: reads
  from the recorded manifest, `out_dir()` returning the original node
  directory, so a deterministic function re-derives identical content and
  returned pointers.
- With a store, every `ExecutionRecord.artifacts` carries the minted
  address: the join key from history into the manifest.

## Owns
- The by-reference data plane: the store, the addressing scheme, the
  manifest, the handle's scopes, and the replay stand-in.

## Excludes
- The walk and injection mechanics: `INFO-004`.
- The information-flow analysis and the option set: `IMP-005`.
