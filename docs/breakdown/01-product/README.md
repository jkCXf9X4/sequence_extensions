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
- **CP-017** [UC-17 Run independent tasks concurrently](uc-17-run-independent-tasks-concurrently.md) — independent nodes inside one run execute at the same time; the run returns only once every node has finished
- **CP-018** [UC-18 Order dependent tasks — general DAG](uc-18-order-dependent-tasks-general-dag.md) — nodes may depend on other nodes in any shape, joins and diamonds included; a dependent node receives its dependency's result; cycles are rejected at declaration
- **CP-019** [UC-19 Retry, back off, and bound a task](uc-19-retry-back-off-and-bound-a-task.md) — a flaky node is tried again after a pause; a hanging node is cut off by a per-attempt wall-clock budget
- **CP-020** [UC-20 Audit a run](uc-20-audit-a-run.md) — every run leaves one complete, ordered record — each attempt, each skip, and the run's verdict, readable with plain tools
- **CP-021** [UC-21 Bound the concurrency](uc-21-bound-the-concurrency.md) — concurrent nodes never exceed a limit the caller chooses; a caller may instead supply one shared pool that serves several runs
- **CP-022** [UC-22 Run CPU-bound tasks in parallel](uc-22-run-cpu-bound-tasks-in-parallel.md) — compute-heavy tasks run on several cores of one machine at the same time, without rewriting the campaign or losing its record
- **CP-023** [UC-23 Run flows concurrently in one process](uc-23-run-flows-concurrently-in-one-process.md) — several campaigns run at the same time in one process without interfering with each other
- **CP-024** [UC-24 See what a run did](uc-24-see-what-a-run-did.md) — a completed run read back at a glance — per task the attempts, the statuses, and the time spent, plus the run's verdict — without reading raw records
- **CP-025** [UC-25 Verify two runs executed identically](uc-25-verify-two-runs-executed-identically.md) — same code and same inputs must execute the same — every node, every attempt, same outcomes — with completion order, clock readings, and worker identity never counting as differences
- **CP-026** [UC-26 Set a run's parameters outside the code](uc-26-set-a-runs-parameters-outside-the-code.md) — run options and node defaults live in one TOML file; explicit decorator keywords keep winning; the file launches the run without a code change
- **CP-027** [UC-27 Embed the engine in a host application](uc-27-embed-the-engine-in-a-host-application.md) — host application calls execute_flow with per-call RunOptions, reads the returned Run — no service, no global configuration, no dependencies
- **CP-028** [UC-28 Start runs from a shell or pipeline](uc-28-start-runs-from-a-shell-or-pipeline.md) — make, CI, cron, and batch scripts start flows through flow-runner, branch on exit codes, keep the run log as the artifact
- **CP-029** [UC-29 Keep a run log byte-stable for reference storage](uc-29-keep-a-run-log-byte-stable-for-reference-storage.md) — reference mode: fixed_clock pins run id, timing, worker, and record order — identical runs produce byte-identical log files
- **CP-030** [UC-30 Compose nodes — a node inside a node](uc-30-compose-nodes-a-node-inside-a-node.md) — a reusable node tree runs as a step in a larger node tree — one run, one log, future-first fan-out, and composite policy for the subtree
- **INFO-010** [Use cases](use-cases.md) — The use-case catalog — fifteen capability leaves (CP-016 to CP-030) concretizing the INFO-001 goal
<!-- pb:index:end -->
