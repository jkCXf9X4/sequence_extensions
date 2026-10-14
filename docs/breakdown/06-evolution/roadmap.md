---
id: INFO-013
type: info
title: Roadmap
summary: Direction pointers for the flow engine — parallelism local and at HPC, determinism and audit, engine hygiene; rows cite canonical homes by ID
date: 2026-10-14
status: current
---

# Roadmap

Direction: the `INFO-001` goal — parallel, deterministic, audited. This file points; it holds no state, no status, no dates. IMP status lives in each IMP header alone.

## Parallelism

- Local, bounded: `CP-017`, `CP-021`.
- CPU-bound processes: `CP-022` (shipped 1.1.0, `DR-008`).
- Concurrent flows in one process: `CP-023` (shipped 1.1.0, `DR-007`).
- HPC through recipes: `INFO-012`; no open candidate — file an IMP when recipe limits bite.

## Determinism and audit

- Retry, timeout, verdict: `CP-019`.
- The run log: `CP-020`; payload tier for non-JSON values: `IMP-018`.

## Engine hygiene

- Package split: `IMP-020`.
- Substrate reopen pair shipped 1.1.0 (`DR-007`): public bind, pool-scoped cancellation.

## Owns

- The direction pointers and their grouping.

## Excludes

- The goal text: `INFO-001`.
- IMP status: each IMP header, nothing else.
- Current state: the owning layer leaves.
