---
id: IMP-020
type: imp
title: Split ext from flow at a future release
summary: One distribution ships two unrelated products; kept together for 1.0.0, revisit when either half grows a dependency
date: 2026-10-14
status: current
---

# Split ext from flow at a future release

Candidate, not selected. The 2026-10-14 review kept `ext` in-package for
1.0.0 ("keep ext for now"); this leaf records the revisit.

## Pain

- `sequence-extensions` ships two unrelated value propositions: sequence
  helpers (`ext`) and the flow engine (`flow`/`graph`).
- An importer of one carries the other; their version histories and
  audiences are coupled.

## Proposal

- Two distributions (or a namespace package) at a future major version:
  the flow engine without list helpers, the helpers standalone.

## Cost

- Packaging churn and migration for current users; CI, README, and
  `docs/API.md` split.
- A shared distribution costs nothing today: zero runtime dependencies,
  one version line.

## Evidence

- `DR-005` open-decision 1 recommended a split at 1.0.0; the author
  overrode for now (2026-10-14).
- Revisit trigger: either half grows a dependency the other must not
  carry.
