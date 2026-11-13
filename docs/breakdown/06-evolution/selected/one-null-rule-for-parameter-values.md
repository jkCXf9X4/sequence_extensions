---
id: IMP-028
type: imp
title: One null rule for parameter values
summary: null is the value None for an optional parameter, missing for a required one, and absence is the only unset signal
date: 2026-11-13
status: selected
---

# One null rule for parameter values

- **Question:** Does `null` in a plan mean the value `None`, or "unset, use the default"?
- **Evidence:** `plan_document` materialises every value, defaults included (`_planning/document.py:76-96`); `execute_plan` rejects `null` on a required parameter as missing (`_planning/document.py:458-464`) but passes it through for an optional one (`_planning/document.py:383-388`); the GUI filters `None` before re-planning (`seq_ext_gui/src/seq_ext_gui/engine.py:268-270`). One plan, two behaviours, and no GUI way to set an optional parameter to `None`.
- **Change:** adopt and document one rule: in a full document every value is present and `null` is the value `None` for an optional parameter; `null` on a required parameter is missing and rejected; in an override, absence means no change. Remove the GUI filter so omission is expressed by omission.
- **Risk:** a caller relying on `null` to reset an optional parameter to its default changes meaning. The plan document is a contract, so this needs a deliberate note in `flow-reference.md` and `CP-026`; the GUI alignment is a separate record in the GUI breakdown.
- **Acceptance:** an optional parameter with `value: null` reaches the body as `None` through `execute_plan` and through a GUI re-plan; a required parameter with `value: null` keeps the existing rejection; omitting a node parameter in an override leaves the document value untouched.
