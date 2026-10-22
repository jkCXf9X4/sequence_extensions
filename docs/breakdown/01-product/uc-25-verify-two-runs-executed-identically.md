---
id: CP-025
type: capability
title: UC-25 Verify two runs executed identically
summary: same code and same inputs must execute the same — every node, every attempt, same outcomes — with completion order, clock readings, and worker identity never counting as differences
date: 2026-10-14
status: current
---

# UC-25 Verify two runs executed identically

## Scenario

- A campaign is re-run — after a move, an upgrade, or a suspicion — and the question is whether it executed the same as before.
- Comparing two record files line by line answers it badly: completion order, clock readings, and worker names differ even when the execution was identical.

## Acceptance

- Two runs of the same campaign on the same code and inputs compare equal.
- A different outcome is pinpointed: which node path, on which inputs, which attempt, and exactly which facts differ.
- Work in one run but not the other — a node attempted here, skipped there — is listed.
- Repeated identical executions are counted, not collapsed: a changed fan-out count shows as an extra/missing `occurrence`.
- Completion order, clock readings, durations, and worker names never count as differences; neither does the run's own identity.
- The comparison result is plain data: printable, storable, passable to other tools.

## Evidence

- `tests/flow/test_runlog_tools.py` — two real two-stage runs compare equal; a flaky difference pinpointed to node path, inputs, attempt, and fields; extra work listed; timing-only differences ignored; what counts as equal stated as policy.
- `tests/flow/test_hardening.py` — a changed number of identical calls and a reordered multiset.

## Owns

- The identical-execution need and its comparison acceptance.

## Excludes

- How the need is met: `INFO-002` (shipped surface), `INFO-011` (engine design).
- The compact account of one run: `CP-024`.
- Re-running completed work: out of scope — the comparison never executes anything.
