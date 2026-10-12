---
id: CP-014
type: capability
title: UC-14 Trace data by reference
summary: ArtifactStore mints one directory per action; reads limited to the causal past; append-only manifest
date: 2026-10-13
status: current
---

# UC-14 Trace data by reference

## Scenario

- A simulation writes a 2 GB output; the result flowing through kwargs is a pointer, not the payload.
- Each executed action owns one minted directory; the manifest is the executed truth.

## Workflow

```python
from pathlib import Path
from sequence_extensions import ArtifactStore, run_workflow

store = ArtifactStore(root=Path("artifacts"))
result = run_workflow(xml, artifacts=store)
```

A function declares the reserved `artifacts` kwarg:

```python
@workflow_function
def write_report(artifacts=None, **params):
    out = artifacts.out_dir()               # own minted directory, the only write scope
    (out / "report.txt").write_text("...")
    data = artifacts.read("upstream/simulate/output.bin")   # causal past only
    branches = artifacts.branches("sweep")   # completed parallel groups, in causal order
```

Mechanics:

- An address is the action's tree position (labels plus rank suffix on repeat), minted at call entry, never recomputed — scheduling-independent.
- Sweep clones and iteration bodies mint fresh directories (`sequential`, `sequential_2`, ...): single assignment, per-clone outputs preserved.
- `manifest.jsonl` is append-only, one entry per executed action in call order: `seq`, `address`, `function`, own `params`, `dynamic`.
- Write scope: the own directory, nothing else. Read scope: the causal past — parallel siblings are barriers, exactly as for results.

## Acceptance

- Every artifact addresses back to the action and the inputs that produced it.
- Addresses are deterministic: same tree, same addresses, regardless of scheduling.
- `replay(history, registry, artifacts=store)` re-invokes artifacts-declaring functions with a `ReplayArtifacts` handle reading the recorded manifest — a deterministic function re-derives identical content.

## Evidence

- `tests/workflow/test_artifacts.py` — addresses, manifest, handles, scopes, replay (42 tests).

## Owns
- The UC-14 concretization: the by-reference data plane.

## Excludes
- The data-plane design: `INFO-008`; the decoupling contract: `INFO-009`.
