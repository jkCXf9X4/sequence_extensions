---
id: CP-013
type: capability
title: UC-13 Record and replay a run
summary: RunHistory records every action; replay re-executes the records to the same final result
date: 2026-10-13
status: current
---

# UC-13 Record and replay a run

## Scenario

- An auditor re-runs last night's campaign to confirm the result.
- The run recorded an execution history; replay re-executes the recorded calls.

## Workflow

```python
from sequence_extensions import run_workflow
from sequence_extensions.workflow.history import RunHistory, replay

history = RunHistory()
result = run_workflow(xml, history=history)   # opt-in recording
same = replay(history)                        # re-execution, not echo
```

What a record holds (one `ExecutionRecord` per executed action):

- Registry name, resolved parameters (injected handles stripped — plain data), return value or exception.
- Start and end timestamps, monotonic `duration`, deterministic completion-order index, tree path.
- `dynamic=True` on spliced actions, recorded immediately after the splicing action.
- Run identity: `run_id` and the workflow digest (`source`) stamped at run start, carried on every record.

Modes:

- `params_mode="summary"` records bulk parameter payloads as item counts.
- `replay` warns on registry drift (a changed function signature between run and replay).

## Acceptance

Requirement:

- `replay(history)` returns the same final result as the original run, by re-executing every recorded call with its recorded parameters — not by echoing stored results.
- A run whose action raised re-raises at the same point.
- Without `history=`, recording is fully off — zero behavior change.

## Evidence

- `tests/workflow/test_history.py` — recording, thread safety, spliced actions, replay determinism, opt-in default.

## Owns
- The UC-13 concretization: history and replay.

## Excludes
- The by-reference artifact replay: `CP-014`.
- The history design: `IMP-010`, `IMP-011`.
