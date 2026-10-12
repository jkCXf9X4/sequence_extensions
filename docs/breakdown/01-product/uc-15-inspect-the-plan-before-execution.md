---
id: CP-015
type: capability
title: UC-15 Inspect the plan before execution
summary: dry_run returns the expanded workflow tree, executes nothing, history still records
date: 2026-10-13
status: current
---

# UC-15 Inspect the plan before execution

## Scenario

- An expensive campaign gets a dry pass first: the engineer inspects what will run before committing compute.
- The run parses, expands templates, and returns the plan.

## Workflow

```python
from sequence_extensions import run_workflow

plan = run_workflow(xml, dry_run=True)   # the expanded tree, not a result
```

## Acceptance

- No registered function executes — the registry is wrapped with plan stubs.
- Templates expand and parameters resolve exactly as in a real run, so the returned tree is the effective plan.
- `history` still records the plan walk when passed alongside.
- The same option exists on `Test_Framework` for the Python API.

## Evidence

- `tests/workflow/test_engine.py` — `test_dry_run_returns_the_plan_and_executes_nothing`.

## Owns
- The UC-15 concretization: plan inspection.

## Excludes
- History recording: `CP-013`.
- Template expansion rules: `CP-002`.
