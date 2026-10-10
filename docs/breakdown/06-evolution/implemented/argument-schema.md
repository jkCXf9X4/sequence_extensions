---
id: IMP-002
type: imp
title: Replace named parameter elements with generic <argument key value> in the workflow schema
summary: Action parameters use one generic <argument key=... value=...> element instead of per-parameter element names
date: 2026-10-09
status: current
---

# Replace named parameter elements with generic <argument key value> in the workflow schema

## What changed

`<action>` parameters no longer use per-parameter element names
(`<parameter_name value="..."/>`, `<values value="..."/>`). One generic
element carries every parameter: `<argument key="name" value="..."/>`,
where `key` is the parameter name and `value` its value. `<argument>` is
the only child element allowed inside `<action>` (and for global
parameters on `<VerificationWorkflow>`).

## Why

`INFO-001` requires the schema stay small, declarative, and human-readable
("complexity in the library, not the schema"). Named elements forced the
schema to know every function's parameter names and clashed with
structural element names; a generic key/value pair keeps the schema
closed and lets any parameter name — even a Python keyword — pass
through.

## The shape a user writes

```xml
<action function="parameter_sweep">
    <argument key="parameter_name" value="parameter_1"/>
    <argument key="values" value="5, 10, 15"/>
</action>
```

## Verification

- `src/sequence_extensions/workflow/schema.py:37-40` — docstring:
  `<argument key="name" value="..."/>` is the parameter form;
  `schema.py:122` — `_ARGUMENT_TAG = "argument"`;
  `schema.py:471-490` — `_parse_action` accepts only `<argument>`
  children, rejects duplicates; `schema.py:572-585` — `_argument`
  validates `key`/`value` attributes.
- `tests/workflow/test_engine.py:62-63` — the exact example above parses
  and runs; `tests/workflow/test_schema.py` and
  `tests/workflow/test_integration_alignment.py` cover argument parsing,
  globals, and templates.
