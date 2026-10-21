---
id: CP-020
type: capability
title: UC-20 Audit a run
summary: every run leaves one complete, ordered record — each attempt, each skip, and the run's verdict, readable with plain tools
date: 2026-10-14
status: current
---

# UC-20 Audit a run

## Scenario

- A verdict must be defensible: which case ran, which failed on which attempt, what value each produced, and when.
- The record must outlive the run: readable later, with standard tools, one entry per line.

## Acceptance

- The campaign's record holds 16 entries: 2 bookends, the root node, 7 simulate attempts (6 cases plus one retried), and 6 evaluations.
- Each case's attempts are numbered in order; a failed first attempt is recorded, then the successful one.
- A node whose dependency failed gets exactly one record marking it skipped.
- The record is complete the moment the campaign returns.
- The record is plain text, one entry per line, greppable and diffable.

## Evidence

- `tests/flow/test_runlog.py` — serialization policy, writer thread safety, schema 2.
- `tests/flow/test_run.py` — skipped records, bookends, summary mode.
- `tests/flow/test_acceptance.py` — full log assertions.

## Owns

- The audit need and its record-completeness acceptance.

## Excludes

- How the need is met: `INFO-002` (shipped surface), `INFO-011` (engine design).
- The retry behavior that produces the attempts: `CP-019`.
- Replay of a run: out of scope.
