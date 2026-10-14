---
id: CP-024
type: capability
title: UC-24 See what a run did
summary: a completed run read back at a glance — per task the attempts, the statuses, and the time spent, plus the run's verdict — without reading raw records
date: 2026-10-14
status: current
---

# UC-24 See what a run did

## Scenario

- A run finished — or died — and the question is what actually happened: which tasks ran how many times, which failed, which never started, and how the run ended.
- Reading the raw record of every attempt answers it, but slowly, and by hand, every time.

## Acceptance

- One compact account of a completed run: per task — attempts, statuses in order, time spent — and the run's verdict.
- A task that never executed shows as skipped, not as an attempt.
- A run that died before its verdict still yields the account of what did happen.
- The records of interest — one task, every failure, a given attempt — can be selected without reading every line.
- The account and the selection are plain data: printable, storable, passable to other tools.

## Evidence

- `tests/flow/test_runlog_tools.py` — selection by kind, task, status, attempt; per-task account; skipped and interrupted runs; plain-data output; the same over logs the engine wrote.

## Owns

- The compact-account need and its selection acceptance.

## Excludes

- How the need is met: `INFO-002` (shipped surface), `INFO-011` (engine design).
- The record itself and its completeness: `CP-020`.
- Comparing two runs: `CP-025`.
