---
id: IMP-006
type: imp
title: Simplify DAG manipulation surface for adaptation drivers
summary: Intent-level handle combinators replace the primitive-op rituals the eight drivers repeat; copy_self fixes the one capability gap
date: 2026-10-11
status: current
---

# Simplify DAG manipulation surface for adaptation drivers

## Problem

Eight adaptation drivers orchestrate four primitive write ops
(`replace` / `adjust` / `copy` / `append`). Five manipulation patterns
recur across them:

- **map** — `find_files`, `parameter_sweep`: clone the declared
  downstream scope once per item, replace it with the clones.
- **branch** — `evaluate_goal`: pick a named child of the following
  group, replace the group with it.
- **skip** — `guard`: replace the following group with an empty group.
- **skip-rest** — `fallback`: replace every following sibling with an
  empty group.
- **iterate** — `check_convergence`, `while_condition`, `retry`: append
  copies of the preceding body plus a fresh copy of the check itself.

Friction, by inspection of `workflow/library.py`:

- The copy-to-end idiom is six lines, repeated verbatim in three
  drivers.
- `copy` cannot target the acting action: `_check_target` accepts
  following siblings (and preceding as copy source), never self. Each
  iteration driver compensates by rebuilding its own node
  (`dag.scope.children[dag.index]` plus
  `Action(check.function, **check.params)`) — breaking the design rule
  "functions never build nodes" (`IMP-001`, `docs/API.md`).
- `guard` and `fallback` build `Sequential()` skip sentinels themselves;
  `fallback` records one replace op per following sibling.
- `evaluate_goal` walks the alternatives group's children by hand to
  find a named child.

## Decision

- Add `DAGHandle.copy_self(**overrides)` — clone the acting action with
  parameter overrides. Closes the one capability gap.
- Add five combinators, sugar over the existing op kinds; the engine
  commit path (`_commit` / `_apply` / `_revalidate`) is unchanged:
  - `fan_out(overrides)` — map: clone the declared downstream scope
    once per override set, replace it.
  - `select(name, default=None)` — branch: pick the named child of the
    following group, replace the group with it, return the child.
  - `skip()` — replace the following group with an empty group.
  - `skip_following()` — replace every following sibling with an empty
    group.
  - `repeat(**overrides)` — iterate: append copies of the preceding
    body plus `copy_self()`.
- Combinators record the same op shapes the drivers recorded by hand.
  Behavior is identical; tests that pin op shapes still pass.
- Rewrite the eight drivers onto the combinators. Library functions
  build no nodes.
- Scope snapshots record a group's `name`; replay materializes it.
  Branching drivers replay (`ReplayHandle.select` serves named fake
  children).
- `ReplayHandle` mirrors: write combinators are no-ops; `copy_self` and
  `select` are functional.
- Declined: new op kinds (engine churn, history-format change, pinned
  group-result semantics would move); declarative plans (a third
  mechanism — `IMP-001` kept two).

## Owns

- The handle's driver-facing combinator layer: which manipulation
  intents get one call.

## Excludes

- Engine commit protocol, op kinds, `AdaptationOp` shape — `INFO-004`.
- Schema constructs (no change) — `IMP-001`.
- Return-nodes splice protocol (unchanged).
- New drivers (Tier 3) — `docs/dynamic_scenarios_analysis.md` §5.

## Verification

- `tests/workflow/test_adaptation.py` — combinator unit tests: op
  shapes, validation errors, read-only rejection, bound accounting.
- `tests/workflow/test_library.py` — driver tests unchanged except two
  error-message matches (`evaluate_goal` prefix moved into the handle).
- `pb check --strict`, `pytest --cov` — pass.
