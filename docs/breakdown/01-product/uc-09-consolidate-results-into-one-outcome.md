---
id: CP-009
type: capability
title: UC-09 Consolidate results into one outcome
summary: aggregate reduces every upstream result into the final workflow result; deterministic fold
date: 2026-10-13
status: current
---

# UC-09 Consolidate results into one outcome

## Scenario

- A parallel sweep produced N `simulate` results; the campaign needs one verdict.
- `aggregate` reads every result named `simulate` (all collision-suffixed occurrences) and reduces one field into one value.

## Workflow

```xml
<scope type="sequential">
  <scope type="parallel">
    <action function="simulate">
      <argument key="case" value="case_1.csv"/>
    </action>
    <action function="simulate">
      <argument key="case" value="case_2.csv"/>
    </action>
  </scope>
  <action function="aggregate">
    <argument key="upstream" value="simulate"/>
    <argument key="field" value="score"/>
    <argument key="op" value="mean"/>
  </action>
</scope>
```

Reduction vocabulary:

- Numeric: `sum`, `max`, `min`, `mean`.
- `count` — the number of results.
- Boolean: `all`, `any`.
- Optional `key` groups results by a key field first (for example a per-test-case verdict).

## Acceptance

- The final action's return value is the workflow result.
- The fold is deterministic: group outputs sort by key, never across types.
- Zero results aggregate to `count: 0`, `value: None` (except `all` = True, `any` = False) — a summary never fails the run.

## Evidence

- `tests/workflow/test_library.py` — `aggregate` over ops, keys, and the empty case.

## Owns
- The UC-09 concretization: consolidation.

## Excludes
- The final-result rule of the engine: `INFO-004`.
- Gating on deviations: `CP-011`.
