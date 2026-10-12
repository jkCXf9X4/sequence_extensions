---
id: CP-003
type: capability
title: UC-03 Run a campaign unattended
summary: One composite workflow runs to completion without operator input; deterministic final result
date: 2026-10-13
status: current
---

# UC-03 Run a campaign unattended

## Scenario

- An overnight campaign composes every feature at once: templates, library functions, parallel fan-out, history.
- No operator input mid-run; the run ends with a deterministic final result.

## Workflow

Fixture `tests/resources/workflows/scope_integration.xml` — a `find_files` driver, a reusable `file_check` template used at one site, and a final `compare_results`, all in one `VerificationWorkflow`:

```xml
<VerificationWorkflow>
  <argument key="model" value="./model_1"/>
  <template name="file_check">
    <scope type="sequential">
      <action function="simulate">
        <argument key="file" value="{file}"/>
      </action>
      <action function="evaluate_results">
        <argument key="file" value="{file}"/>
      </action>
    </scope>
  </template>
  <scope type="sequential">
    <action function="find_files">
      <argument key="path" value="file_storage/"/>
    </action>
    <use-template name="file_check">
      <argument key="file" value="case_0.csv"/>
    </use-template>
    <action function="compare_results"/>
  </scope>
</VerificationWorkflow>
```

Driver (the integration test's shape):

```python
from sequence_extensions import run_workflow
from sequence_extensions.workflow.history import RunHistory
from sequence_extensions.workflow.library import register_library

register_library()                       # opt-in: fills DEFAULT_REGISTRY
history = RunHistory()
result = run_workflow(xml, history=history)
```

## Acceptance

- Runs to completion with no operator input: drivers adapt, templates expand, the engine walks.
- The final result is deterministic: same XML, same registry, same inputs, same result.
- History records every executed action, template-bound parameters included.

## Evidence

- `tests/workflow/test_integration_alignment.py` — one workflow composing all features end to end.
- Fixture: `scope_integration.xml`.

## Owns
- The UC-03 concretization: unattended composite execution.

## Excludes
- Replay of the recorded run: `CP-013`.
- Per-feature mechanics: the other `CP-` leaves.
