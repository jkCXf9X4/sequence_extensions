---
id: CP-026
type: capability
title: UC-26 Set a run's parameters outside the code
date: 2026-10-16
status: current
summary: run options, per-node policy, and root inputs live in one flow-plan/2 JSON document; explicit parameter values keep winning, plan policy overrides decorator policy, and the document launches the run without a code change
---

# UC-26 Set a run's parameters outside the code

## Scenario

- An operator tunes retries, timeout, worker count, and summary mode for tonight's campaign. No Python edit allowed.
- The operator also sets the root node's inputs in the same document, or exports the document from the GUI.
- A developer keeps explicit keywords in code: parameter values the flow binds explicitly must win, while a plan's per-node policy is the supported override.

## Acceptance

- One `flow-plan/2` JSON document carries the run `options` (max workers, summary, fixed clock, run-level retries/backoff/timeout), the root parameters with values, and every node's effective `policy` and parameters; omitted option keys keep concrete defaults.
- The document does not select the flow: the GUI dropdown or `--flow NAME` chooses the root.
- A plan node policy beats an explicit `@node` keyword; `RunOptions.node_defaults` and the built-in default fill the rest.
- `execute_plan` builds `RunOptions`, the root kwargs, and the node registry from the document; there is no process-wide configuration and no import-order constraint.
- An unknown root parameter, node, node parameter, policy key, or option key fails before execution, naming the offending key.
- `flow-runner PLAN.json --module MODULE [--flow NAME] [--log DIR]` runs the document; exits 0 on success, 1 on run failure, 2 on usage or schema/config error.

## Evidence

- `tests/flow/test_plan_document.py`
- `tests/flow/test_options.py`
- `tests/runner/test_runner.py`

## Owns

- The file-driven-parameters need: run options, root inputs, and per-node policy in one plan document, code-first parameters, plan-first policy, CLI launch.

## Excludes

- How resolution works: `INFO-011`.
- Flow selection: external to the document, `CP-028`.
- The decision and its alternatives: `DR-017` (supersedes `DR-015`).
