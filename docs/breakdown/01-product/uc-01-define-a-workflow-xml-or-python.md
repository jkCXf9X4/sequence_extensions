---
id: CP-001
type: capability
title: UC-01 Define a workflow, XML or Python
summary: One campaign authored in both schema forms; identical constructs and results
date: 2026-10-13
status: current
---

# UC-01 Define a workflow, XML or Python

## Scenario

- An engineer authors one sweep campaign twice: once as XML, once as Python nodes.
- Campaign: find test cases, simulate two cases concurrently, compare.
- Both forms run against the same registry and produce the identical final result.

## Workflow

XML:

```xml
<VerificationWorkflow>
  <argument key="model" value="./model_1"/>
  <scope type="sequential">
    <action function="find_test_cases">
      <argument key="path" value="./test"/>
    </action>
    <scope type="parallel">
      <action function="simulate">
        <argument key="case" value="case_1.csv"/>
      </action>
      <action function="simulate">
        <argument key="case" value="case_2.csv"/>
      </action>
    </scope>
    <action function="compare_results"/>
  </scope>
</VerificationWorkflow>
```

Python, the same campaign:

```python
from sequence_extensions import Action, Parallel, Sequential, Test_Framework

workflow = Sequential(
    Action("find_test_cases", path="./test"),
    Parallel(
        Action("simulate", case="case_1.csv"),
        Action("simulate", case="case_2.csv"),
    ),
    Action("compare_results"),
)
result = Test_Framework(workflow, parameters={"model": "./model_1"})
```

Schema rules both forms share:

- Root: `<VerificationWorkflow>` (globals plus one grouping), or a bare `<scope>` root.
- `<action function="name">` holds parameters as `<argument key value>` children.
- `<scope type="sequential|parallel">` is the grouping, optional `name` label; `<sequential>` / `<parallel>` are accepted aliases (the fixtures use the scope form).
- A scope holding exactly one child may omit `type`: one child carries no ordering; the parser builds a sequential group (`IMP-014`).
- Optional `description` attribute labels a node for the history; it never executes.

## Acceptance

- `parse_workflow` returns plain `Action` / `Sequential` / `Parallel` nodes — the same tree the Python API builds.
- Both forms produce the identical final result under the same registry.
- Every XML rejection rule raises `ValueError`: unknown element, missing `function`, `type` omitted on a scope with zero or several children, duplicate key.

## Evidence

- `tests/workflow/test_schema.py` — parsing and every rejection rule.
- `tests/workflow/test_engine.py` — XML and Python paths execute with the same semantics.
- Fixtures: `eval_task_01.xml`, `sequential_example.xml`, `parallel_example.xml`.

## Owns
- The UC-01 concretization: dual authoring forms and schema parity.

## Excludes
- Template mechanics: `CP-002`.
- The engine walk: `INFO-004`.
