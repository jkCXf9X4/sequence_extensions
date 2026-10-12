---
id: CP-007
type: capability
title: UC-07 Adapt per item found
summary: find_files fans out the declared downstream scope once per file, optionally in parallel
date: 2026-10-13
status: current
---

# UC-07 Adapt per item found

## Scenario

- `file_storage/` holds three CSVs; the count is unknown at authoring time.
- `find_files` finds them and clones the declared downstream body once per file — each file gets its own copy.
- With `parallel="true"` the clones run concurrently.

## Workflow

XML, sequential mode — the single-child declared body omits the type (`IMP-014`):

```xml
<scope type="sequential">
  <action function="find_files">
    <argument key="path" value="file_storage/"/>
  </action>
  <scope>
    <action function="simulate"/>
  </scope>
</scope>
```

Parallel mode — the declared body's `parallel` type is the concurrency contract (the clones become its direct children):

```xml
<scope type="sequential">
  <action function="find_files">
    <argument key="path" value="file_storage/"/>
    <argument key="parallel" value="true"/>
  </action>
  <scope>
    <action function="simulate"/>
  </scope>
</scope>
```

Mechanics:

- The declared downstream scope is the template the driver clones; the driver never builds nodes itself.
- A one-item declared scope carries no scheduling meaning of its own: the action before the scope chooses the resulting DAG.
- `parallel` unset (default): `dag.fan_out` splices one copy of the scope per file, in place — the copies run one after another, in sorted file order; deterministic.
- `parallel="true"`: `dag.fan_out_parallel` replaces each declared child with one clone per file — the clones run as direct children of the declared group, so results flow downstream past the group's information barrier.
- The concurrent map requires a parallel-typed declared scope: the type is the concurrency contract — the clones land in that group and the engine's parallel walk runs them. A sequential-typed scope with `parallel="true"` raises `ValueError`.
- Ops record as `AdaptationOp`, commit atomically; spliced nodes carry `dynamic=True`.
- No file matches: nothing is adapted, the declared scope runs once as declared.

## Acceptance

- Each found file gets its own copy of the declared body.
- Adaptation stays inside the driver's own grouping scope; parallel parents are read-only.
- Dynamic-node growth is bounded (`adaptation_bound`, default 10 000) — exceeding it raises a deterministic `ValueError`.

## Evidence

- `tests/workflow/test_adaptation.py` — `DAGHandle` reads, writes, commit protocol.
- `tests/workflow/test_parallel_fanout.py` — concurrent clones, placement, op shape, bound counting.
- Fixtures: `dynamic_adaptation.xml`, `adaptation_scope.xml`.

## Owns
- The UC-07 concretization: per-item adaptation.

## Excludes
- The `DAGHandle` design: `INFO-004`.
- Iteration until a condition: `CP-008`.
