---
id: CP-033
type: capability
title: Override an input for one node occurrence
date: 2026-11-11
status: current
summary: One edited plan document targets one occurrence by identity, or every occurrence of a kind by name; explicit values written in code keep winning
---

# Override an input for one node occurrence

## Scenario

- An operator who knows exactly which call to change asks: "set tolerance to
  0.7 for the second evaluation in this run."
- The node entry carries the canonical identity — `name`, `path`, and
  `instance` — and the override reaches that one occurrence.
- Omitting `path` and `instance` keeps the name-wide behavior: "set tolerance
  to 0.7 for every evaluation in this run."
- Explicit values written in code keep winning in both forms.

## Acceptance

- A node override with both `path` and `instance` changes exactly that
  occurrence and leaves other occurrences of the name untouched.
- A node override with neither field changes every node sharing that name.
- Providing only one of `path` and `instance`, or an identity absent from the
  document, is rejected before the run starts.
- A parameter the code passes explicitly is never overridden by the document.

## Evidence

- `tests/flow/test_plan_document.py`

## Owns

- The per-occurrence tuning need: one change lands on one call; the legacy
  name-wide form remains available.

## Excludes

- How overrides merge into a run: `RunOptions.parameters` per `IMP-023`.
- The file-driven run options and node defaults: `CP-026`.
