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
- **CP-001** [UC-01 Define a workflow, XML or Python](uc-01-define-a-workflow-xml-or-python.md) — One campaign authored in both schema forms; identical constructs and results
- **CP-002** [UC-02 Reuse a scenario subtree](uc-02-reuse-a-scenario-subtree.md) — One template body expands at two use sites with different parameters, at parse time
- **CP-003** [UC-03 Run a campaign unattended](uc-03-run-a-campaign-unattended.md) — One composite workflow runs to completion without operator input; deterministic final result
- **CP-004** [UC-04 Execute independent tasks concurrently](uc-04-execute-independent-tasks-concurrently.md) — A parallel group declares no dependency between its children; the engine runs them concurrently
- **CP-005** [UC-05 Bound the concurrency](uc-05-bound-the-concurrency.md) — max_workers sizes the pool; a caller-owned executor wins and is never shut down
- **CP-006** [UC-06 Order dependent tasks](uc-06-order-dependent-tasks.md) — Upstream results arrive as positional dependencies; a dependent action never starts early
- **CP-007** [UC-07 Adapt per item found](uc-07-adapt-per-item-found.md) — find_files fans out the declared downstream scope once per file, optionally in parallel
- **CP-008** [UC-08 Iterate until a condition holds](uc-08-iterate-until-a-condition-holds.md) — while_condition repeats the declared body until the check passes; strictly downstream, bounded
- **CP-009** [UC-09 Consolidate results into one outcome](uc-09-consolidate-results-into-one-outcome.md) — aggregate reduces every upstream result into the final workflow result; deterministic fold
- **CP-010** [UC-10 Handle a failure per policy](uc-10-handle-a-failure-per-policy.md) — try_action captures an error as data; retry re-runs the body; fallback skips remaining alternatives
- **CP-011** [UC-11 Gate on incomplete results](uc-11-gate-on-incomplete-results.md) — regression_gate compares against baseline; incomplete or deviating results never pass silently
- **CP-012** [UC-12 Bound a hung action](uc-12-bound-a-hung-action.md) — action_timeout raises ActionTimeoutError naming the action; the default stays unbounded
- **CP-013** [UC-13 Record and replay a run](uc-13-record-and-replay-a-run.md) — RunHistory records every action; replay re-executes the records to the same final result
- **CP-014** [UC-14 Trace data by reference](uc-14-trace-data-by-reference.md) — ArtifactStore mints one directory per action; reads limited to the causal past; append-only manifest
- **CP-015** [UC-15 Inspect the plan before execution](uc-15-inspect-the-plan-before-execution.md) — dry_run returns the expanded workflow tree, executes nothing, history still records
- **INFO-002** [Deliverables](deliverables.md) — What sequence_extensions delivers: three subpackages, the public API surface, and explicit out-of-scope items
- **INFO-010** [Use cases](use-cases.md) — The use-case catalog — 15 capability leaves (CP-001 to CP-015) concretizing the INFO-001 system goal
<!-- pb:index:end -->
