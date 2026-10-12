---
id: IMP-009
type: imp
title: Kwargs precedence fixes: templates, upstream matching, reserved names
summary: Fix template placeholders ignoring run-time parameters, strict upstream-suffix matching, and warn on reserved kwarg collisions
date: 2026-10-12
status: current
---

# Kwargs precedence fixes: templates, upstream matching, reserved names

First of five patch batches from the 2026-10-12 implementation review. Build order:
IMP-009, then IMP-010, IMP-011, IMP-012, IMP-013.

## Pain

- Template placeholders expand at parse time against XML globals only
  (`schema.py` `_parse_use_template`); the `parameters=` argument of
  `run_workflow` merges into `engine._globals` after parsing
  (`engine.py` `_Engine.__init__`).
- Verified: same XML, `parameters={"file": "model_B.csv"}` still returns
  `model_A.csv` inside the template instance.
- Contract broken: `schema.py` binding precedence says use-site binding >
  template default > same-named workflow global; the `run_workflow` docstring
  says `parameters` win on a name clash. Both false for template-referenced
  globals.
- Upstream-name matching is loose: `_upstream_field`, `_upstream_latest` and
  `_upstream_count` in `workflow/library.py` accept any kwarg equal to
  `upstream` or starting with `upstream + "_"`, then `int(key.rsplit("_", 1)[1])`.
- Verified crash: user global `simulate_note` raises
  `ValueError: invalid literal for int() with base 10: 'note'`.
- `_upstream_count` counts such keys, so `check_convergence` and
  `while_condition` (added by IMP-003) and `retry` (IMP-004) report wrong
  iteration counts when a user parameter shares the `<name>_` prefix.
- Reserved kwargs `dag`, `walk_context`, `artifacts` silently hijack user data
  parameters. Verified: `def adapter(dag, **kw)` with a global
  `<argument key="dag">` receives the `DAGHandle`, not the value; no warning.

## Change

- Template precedence: `run_workflow` parses once to collect globals, merges
  `parameters` over them, then re-parses with the merged globals available to
  template expansion. Two cheap parses; expansion sees run-time overrides.
  Document-only fallback (state the parse-time limitation in the docstring)
  only if the two-parse approach breaks a test contract.
- Upstream matching: strict anchored regex `^{escaped name}(_[0-9]+)?$` for
  result keys; any other same-prefix kwarg ignored; suffix never parsed with a
  bare `int` on a non-numeric tail.
- Reserved names: `FunctionRegistry.register` emits a `UserWarning` when the
  registered function declares a parameter named `dag`, `walk_context` or
  `artifacts` (the engine injects the handle, silently clobbering the
  parameter today).

## Verification

- `tests/workflow/test_templates.py`: run-time `parameters` override reaches
  template placeholders.
- `tests/workflow/test_library.py`: global named `<upstream>_note` — no crash
  in `_upstream_field`, not counted by `_upstream_count`.
- `tests/workflow/test_registry.py`: reserved-name collision emits a warning.
- Full suite green; `pb check --strict` green.
