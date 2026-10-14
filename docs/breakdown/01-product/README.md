# 01-product — Product

What users need: the use-case catalog — needs stated in user-observable terms, each with acceptance and evidence.

## Ask

"What do users need?" — the use cases, their acceptance, their evidence.

## When to Read

- Before promising or changing a capability.
- When an integrator asks what the engine must do for its users.

## Boundary

- Holds the needs only.
- Not the delivered surface or the design: `02-architecture/`.
- Not how the code is written: `03-implementation/`.
- Scope and vision: `00-intent/` (INFO-001).

## Contents

<!-- pb:index:start -->
<!-- GENERATED FILE — do not edit. Regenerate with pb-registers. -->
- **CP-016** [UC-16 Define a flow in Python](uc-16-define-a-flow-in-python.md) — an engineer authors a campaign as ordinary Python — functions, calls, returns; no schema, no XML
- **CP-017** [UC-17 Run independent tasks concurrently](uc-17-run-independent-tasks-concurrently.md) — independent tasks inside one campaign run at the same time; the campaign returns only once every task has finished
- **CP-018** [UC-18 Order dependent tasks — general DAG](uc-18-order-dependent-tasks-general-dag.md) — tasks may depend on other tasks in any shape, joins and diamonds included; a dependent task receives its dependency's result; cycles are rejected at declaration
- **CP-019** [UC-19 Retry, back off, and bound a task](uc-19-retry-back-off-and-bound-a-task.md) — a flaky task is tried again after a pause; a hanging task is cut off by a per-attempt wall-clock budget
- **CP-020** [UC-20 Audit a run](uc-20-audit-a-run.md) — every run leaves one complete, ordered record — each attempt, each skip, and the run's verdict, readable with plain tools
- **CP-021** [UC-21 Bound the concurrency](uc-21-bound-the-concurrency.md) — concurrent tasks never exceed a limit the caller chooses; a caller may instead supply one shared execution context that serves several campaigns
- **CP-022** [UC-22 Run CPU-bound tasks in parallel](uc-22-run-cpu-bound-tasks-in-parallel.md) — compute-heavy tasks run on several cores of one machine at the same time, without rewriting the campaign or losing its record
- **CP-023** [UC-23 Run flows concurrently in one process](uc-23-run-flows-concurrently-in-one-process.md) — several campaigns run at the same time in one process without interfering with each other
- **INFO-010** [Use cases](use-cases.md) — The use-case catalog — eight capability leaves (CP-016 to CP-023) concretizing the INFO-001 goal
<!-- pb:index:end -->
