# 01-product — Product

What is delivered and what is out of scope: the capabilities, requirements, and externally observable behavior others rely on.

## Ask

"What did we promise?" — the deliverable, the public API surface, the out-of-scope items.

## When to Read

- Before promising or changing a capability.
- When an integrator asks what the package delivers.

## Boundary

- Holds the promise only.
- Not internal organizing decisions: `02-architecture/`.
- Not how the code is written: `03-implementation/`.
- Scope and vision: `00-intent/` (INFO-001).

## Contents

<!-- pb:index:start -->
<!-- GENERATED FILE — do not edit. Regenerate with pb-registers. -->
- **CP-016** [UC-16 Define a flow in Python](uc-16-define-a-flow-in-python.md) — A campaign is decorated functions — @flow and @task; no schema, no XML, plain calls run sequential
- **CP-017** [UC-17 Run independent tasks concurrently](uc-17-run-independent-tasks-concurrently.md) — task.submit() maps a list comprehension onto the run pool; default 16 workers; flow returns only after drain
- **CP-018** [UC-18 Order dependent tasks — general DAG](uc-18-order-dependent-tasks-general-dag.md) — Futures passed as submit arguments are dependency edges; diamonds allowed; cycles raise at submit time
- **CP-019** [UC-19 Retry, back off, and bound a task](uc-19-retry-back-off-and-bound-a-task.md) — retries and retry_delay_seconds drive an attempt loop inside the task wrapper; timeout bounds one attempt; TaskTimeoutError names the task
- **CP-020** [UC-20 Audit a run](uc-20-audit-a-run.md) — One JSON-lines file per run records run_start, every task attempt, skipped nodes, and run_end; paths log as path plus sha256
- **CP-021** [UC-21 Bound the concurrency](uc-21-bound-the-concurrency.md) — max_workers sizes the run pool; a caller-owned GraphPool is accepted and never settled by the flow
- **INFO-002** [Deliverables](deliverables.md) — What sequence_extensions delivers — three subpackages, the public API surface, and explicit out-of-scope items
- **INFO-010** [Use cases](use-cases.md) — The use-case catalog — six capability leaves (CP-016 to CP-021) concretizing the INFO-001 goal
<!-- pb:index:end -->
