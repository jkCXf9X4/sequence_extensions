---
id: IMP-014
type: imp
title: Optional scope type for single-child scopes
summary: A scope holding exactly one child may omit the type attribute; the parser builds a sequential group
date: 2026-10-13
status: current
---

# Optional scope type for single-child scopes

Schema evolution, same family as `IMP-002` (the `<argument>` element).

## Pain

- A `<scope>` with one child forced a meaningless `type` label: one child
  carries no ordering, so sequential and parallel walk identically.
- Driver declared bodies (single-action templates for `fan_out`) carried
  the ambiguous label; the use-case review flagged it (`CP-001`, `CP-007`).

## Change

- `schema.py` `_parse_group`: a `<scope>` without `type` holding exactly
  one child parses to a `Sequential` (the default); zero or several
  children without `type` raise `ValueError` (the type is what orders or
  parallelizes several children).
- The rule: `type` is required exactly when it means something — several
  children, or the scope serves as a concurrent-map host
  (`fan_out_parallel` still requires an explicitly parallel group, so a
  type-less scope never silently becomes one).
- Docstrings, `docs/API.md`, and `docs/schema.xsd` updated; the XSD marks
  `type` optional with a comment (XSD 1.0 cannot express the count rule;
  the parser is authoritative).

## Verification

- `tests/workflow/test_schema.py`: type-less single-child scope parses to
  `Sequential` (root and nested); type-less scope with zero or several
  children rejected; suite green.
- `pb check --strict` green.

## Excludes

- Dropping the `<sequential>` / `<parallel>` aliases: `IMP-015` (candidate,
  deferred for paper-listing parity).
