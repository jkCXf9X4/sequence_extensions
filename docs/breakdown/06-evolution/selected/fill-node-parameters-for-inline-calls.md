---
id: IMP-027
type: imp
title: Fill node parameters for inline calls
summary: A name-wide parameter entry reaches nodes called directly, not only nodes submitted to the pool
date: 2026-11-13
status: selected
---

# Fill node parameters for inline calls

- **Question:** Does a name-wide parameter entry reach a node the body calls directly, or only one it submits?
- **Evidence:** `CP-033` makes the name-wide form reach every node sharing that name. Today `submit` fills parameters (`_execution/node.py:196-206`) but the inline path goes straight to `_execute_deferred` (`_execution/node.py:149-166`), so policy reaches inline calls (`_execution/node.py:295`) while values do not. The same flow is tunable with `score.submit(...)` and silently immune with `score(...)`.
- **Change:** call `fill_parameters` at the top of `_execute_deferred`, using the `identity` it already accepts (`_execution/node.py:284-306`). Submitted nodes pass their claimed identity; inline calls pass none, so they receive name-only entries. The fill is idempotent for submitted nodes, so `submit` keeps its pre-fill for process mode.
- **Risk:** existing runs change: a name-wide entry now reaches direct call sites, including direct calls executed during the plan pass. Inline occurrences have no document identity, so exact-identity entries still cannot target them; that limit must be documented rather than implied.
- **Acceptance:** a flow with inline `score()` and `parameters={"score": {"tolerance": 0.7}}` receives 0.7; an explicit `score(0.7)` still wins; exact-identity entries still target submitted occurrences only; policy precedence is unchanged.
