---
id: IMP-015
type: imp
title: Scope-only XML vocabulary
summary: Candidate - drop the sequential/parallel alias tags, keep scope-with-type only; deferred for paper-listing parity
date: 2026-10-13
status: current
---

# Scope-only XML vocabulary

Candidate, not selected. Raised in the 2026-10-13 use-case review.

## Pain

- Two vocabularies express one concept: `<sequential>` / `<parallel>`
  aliases beside `<scope type="...">`. Every doc, fixture, and example
  now uses the scope form; the aliases survive for parity only.

## Proposal

- Drop `<sequential>` / `<parallel>` from the accepted schema; keep
  `<scope type="...">` (plus `IMP-014`'s optional type for one-child
  scopes) as the single grouping vocabulary.

## Cost

- Breaks paper-listing parity: the paper's design principle 1 and its
  listings use `<sequential>` / `<parallel>` (`INFO-001`); the fixtures
  mirror Listings 2, 3, 5, 7, 9; alias-equivalence tests and docstrings
  would be removed.
- No functional gain — the aliases are documented sugar with identical
  parse results.

## Disposition

- Deferred: revisit only for a major version where a paper-parity break
  is acceptable. Not scheduled.
