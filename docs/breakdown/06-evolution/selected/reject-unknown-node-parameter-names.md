---
id: IMP-026
type: imp
title: Reject unknown node parameter names
summary: A parameter name the node signature does not accept fails at injection time instead of reaching the body or being swallowed by **kwargs
date: 2026-11-13
status: selected
---

# Reject unknown node parameter names

- **Question:** Does a plan that names a parameter the node signature does not accept fail, naming the key, instead of reaching the body?
- **Evidence:** `CP-026` requires an unknown node parameter to fail before execution, naming the offending key. Today `apply_override` rejects only names absent from the *document* (`_planning/document.py:333-339`), `execute_plan` checks only the schema marker (`_planning/document.py:445-452`), and `fill_parameters` injects every registry key (`_config/options.py:323-326`). A hand-edited plan or an older artifact therefore reaches the body, where a `**kwargs` signature swallows the typo silently.
- **Change:** validate each registry key against `inspect.signature(fn)` in `fill_parameters`; raise `ValueError` naming the node, identity, and key. Keep the `**kwargs` escape hatch: a signature that declares `**kwargs` accepts extra keys, documented as deliberate.
- **Risk:** a plan that only worked because a `**kwargs` body swallowed the key starts failing. Signature lookup is per node, so a hand-edited document fails when that node is first reached, not before the run; documents produced through `plan_document` and `apply_override` already fail before the run.
- **Acceptance:** a key absent from both the signature and `**kwargs` raises at injection with node, identity, and key named, and the node body does not run; a `**kwargs` node still accepts it; plans produced by `plan_document` and `apply_override` are unaffected.
