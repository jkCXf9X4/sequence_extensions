---
id: INFO-001
type: info
title: 00-intent — Vision & Goals
summary: Vision, goal, requirements, design principles, and success criteria for sequence_extensions, distilled from the source paper
date: 2026-10-09
status: current
---
# 00-intent — Vision & Goals

Source: `docs/references/paper_44_yBqbPyj1.pdf` — *"Automation Nation: Taming Complex V&V Workflows"*, Rosenlund, Hällqvist, Braun, Krus (Saab Aeronautics / Linköping University), 16th International Modelica & FMI Conference 2025, DOI 10.3384/ecp218741.

## Vision

> "Any use of a model in a context where it can not be proved to be credible is by definition not credible." (Balci and Ormsby 2000)

- Manual execution and documentation of a handful of verification scenarios no longer scales as systems and models grow.
- Vision: model verification that is automated yet fully traceable and repeatable, while remaining comprehensible to humans.
- Every simulation result audits back to the model version, parameters, and workflow that produced it.
- Decisions rest on "known knowns" and "known unknowns": credible simulation through automation without losing transparency.

## Goal

- Research question: how can automated model verification be traceable, repeatable, and comprehensible?
- The answer couples two things:
  - A lightweight XML workflow schema for complex V&V workflows.
    - Readable and editable by engineers.
    - Parseable and executable by machines.
  - Git-based change management embedded in model archives (FMI/SSP).
    - Versions every transformation and intermediate artifact.
    - Results are reproducible and auditable.
    - Aligned with SSP Traceability and the Credible Simulation Process.
- The paper designs and evaluates the solution via the "Industry-as-laboratory" method.
- The setting: an in-house V&V automation framework supporting model exploration, verification, validation, and design optimization.

## Requirements

- **Traceability** — verification activities and their results can be traced (SSP Traceability)
- **Repeatability** — every operation is deterministic; results can be reproduced
- **Automation** — workflows run unattended; enables regression testing
- **Human & machine readable** — supports manual design/inspection and a high level of automation
- **Customization** — similar operations reusable between models (templates, parameterization)
- **Resource utilization** — expensive operations parallelize (locally or distributed, e.g. HPC)

## Design principles

- **Hierarchical grouping** — nested `<sequential>`/`<parallel>` structures express complex workflows while staying readable; parallel groups mark independent activities for concurrent execution.
- **Dynamic adaptation** — actions may adjust downstream actions at runtime (e.g. per file found, per iteration), restricted to their own grouping scope; execution is strictly downstream (DAG, no loops) to stay deterministic.
- **Complexity in the library, not the schema** — the workflow representation stays small and declarative; advanced behavior lives in the registered function library.
- **Reuse via templates** — actions with parameters form templates for common verification scenarios, limiting duplication between workflows.

## What this means for `sequence_extensions`

The package realizes the *workflow layer* of the paper as a reusable open-source library on top of `graph.graph_future` (`GraphFuture`/`GraphPool`):

- XML workflow schema (`VerificationWorkflow`, global parameters, actions, nested groups)
- A named function registry that actions reference
- A Python API mirroring the XML (`Action`, `Sequential`, `Parallel`, `Test_Framework`)
- A DAG execution engine with sequential/parallel grouping, global parameter propagation, and scope-restricted dynamic adaptation

Out of scope (framework-level concerns from the paper): Git-in-archive version control, STMD/SRMD traceability metadata, FMI/SSP packaging, HPC distribution.

Completed work, cited by ID:
- `IMP-002` — schema evolution: generic `<argument key value>` replaces named parameter elements.
- `IMP-001` — design study of principle 2 (dynamic adaptation); committed choice `DR-001`, engine architecture `DR-002`.

## Success criteria

- Workflows are traceable and reproducible: the full history of verification activities is preserved and results can be replayed.
- The representation is perceived as clearer and easier to navigate than previous solutions, with less code duplication between projects.
- Parallelization of slow activities (simulations) yields major speed-ups, with stable behavior under scaling, clear error handling, and effective dynamic adaptation.
