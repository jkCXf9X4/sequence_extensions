---
id: CP-002
type: capability
title: UC-02 Reuse a scenario subtree
summary: One template body expands at two use sites with different parameters, at parse time
date: 2026-10-13
status: current
---

# UC-02 Reuse a scenario subtree

## Scenario

- The per-file `simulate` + `evaluate_results` chain repeats for every test file.
- An engineer factors it into one template and uses it at two sites with different `file` bindings.
- `model` stays a workflow global, bound once.

## Workflow

XML (fixture `tests/resources/workflows/template_reuse.xml`):

```xml
<VerificationWorkflow>
  <argument key="model" value="./model_1"/>
  <template name="file_check">
    <scope type="sequential">
      <action function="simulate">
        <argument key="file" value="{file}"/>
        <argument key="model" value="{model}"/>
      </action>
      <action function="evaluate_results">
        <argument key="file" value="{file}"/>
      </action>
    </scope>
  </template>
  <scope type="sequential">
    <use-template name="file_check">
      <argument key="file" value="case_1.csv"/>
    </use-template>
    <use-template name="file_check">
      <argument key="file" value="case_2.csv"/>
    </use-template>
  </scope>
</VerificationWorkflow>
```

Python:

```python
from sequence_extensions import Action, Sequential, Template

file_check = Template(
    "file_check",
    Sequential(
        Action("simulate", file="{file}", model="{model}"),
        Action("evaluate_results", file="{file}"),
    ),
)
tree = file_check.instantiate(file="case_1.csv", model="./model_1")
```

Binding precedence, strict resolution:

- Use-site binding wins over template default.
- Template default wins over a same-named workflow global.
- Every `{placeholder}` must resolve to a binding, a default, or a global, or parsing raises.

## Acceptance

- Expansion happens at parse time: `parse_workflow` returns plain `Action` / `Sequential` / `Parallel` nodes, so engine, history, and adaptation are unchanged.
- Two use sites yield distinct, independent trees — no shared state between instantiations.
- Template definition and use rules reject with `ValueError`: missing name, unknown template, undeclared binding, unbound required parameter, duplicate template names.

## Evidence

- `tests/workflow/test_templates.py` — `Template`, XML surface, all rejection rules.
- Fixtures: `template_reuse.xml`, `template_parallel.xml`, 13 invalid fixtures under `tests/resources/workflows/invalid/`.

## Owns
- The UC-02 concretization: template reuse and binding precedence.

## Excludes
- The paper's reuse principle: `INFO-001`.
- Driver-driven cloning at runtime: `CP-007`.
