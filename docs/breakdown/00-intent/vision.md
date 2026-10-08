# 00-intent — Vision & Goals

High-level vision and goals, extracted from the source paper
([01-intent/paper_44_yBqbPyj1.pdf](../01-intent/paper_44_yBqbPyj1.pdf)):
*"Automation Nation: Taming Complex V&V Workflows"* — Rosenlund, Hällqvist, Braun, Krus
(Saab Aeronautics / Linköping University), 16th International Modelica & FMI Conference 2025,
DOI 10.3384/ecp218741.

## Vision

> "Any use of a model in a context where it can not be proved to be credible is by definition
> not credible." (Balci and Ormsby 2000)

As systems and models grow in size and complexity, manually executing and documenting a handful
of verification scenarios no longer scales. The vision is **model verification that is automated
yet fully traceable and repeatable, while remaining comprehensible to humans** — so every
simulation result can be audited back to the model version, parameters, and workflow that produced
it, and decisions can be taken on "known knowns" and "known unknowns".

In short: *credible simulation through automation without losing transparency.*

## Goal

The paper formulates its research question as:

> How can automated model verification be conducted in a manner that is both traceable,
> repeatable and comprehensible?

The proposed answer couples two things:

1. **A lightweight workflow schema** (XML-based) for expressing complex V&V workflows — readable
   and editable by engineers, parseable and executable by machines.
2. **Git-based change management** embedded in model archives (FMI/SSP) — versioning every
   transformation and intermediate artifact so results are reproducible and auditable, aligned
   with SSP Traceability and the Credible Simulation Process.

The solution was designed and evaluated through the "Industry-as-laboratory" method inside an
in-house V&V automation framework supporting model exploration, verification, validation, and
design optimization.

## Requirements distilled from the paper

| Requirement        | Intent                                                                   |
| ------------------ | ------------------------------------------------------------------------ |
| Traceability       | Verification activities and their results can be traced (SSP Traceability) |
| Repeatability      | Every operation is deterministic; results can be reproduced               |
| Automation         | Workflows run unattended; enables regression testing                      |
| Human & machine readable | Supports manual design/inspection *and* a high level of automation   |
| Customization      | Similar operations reusable between models (templates, parameterization)  |
| Resource utilization | Expensive operations parallelize (locally or distributed, e.g. HPC)    |

## Design principles

- **Hierarchical grouping** — nested `<sequential>`/`<parallel>` structures express complex
  workflows while staying readable; parallel groups mark independent activities for concurrent
  execution.
- **Dynamic adaptation** — actions may adjust downstream actions at runtime (e.g. per file found,
  per iteration), restricted to their own grouping scope; execution is strictly downstream
  (DAG, no loops) to stay deterministic.
- **Complexity in the library, not the schema** — the workflow representation stays small and
  declarative; advanced behavior lives in the registered function library.
- **Reuse via templates** — actions with parameters form templates for common verification
  scenarios, limiting duplication between workflows.

## What this means for `sequence_extensions`

This package realizes the *workflow layer* of the paper as a reusable open-source library on top
of `graph.graph_future` (`GraphFuture`/`GraphPool`):

- XML workflow schema (`VerificationWorkflow`, global parameters, actions, nested groups)
- A named function registry that actions reference
- A Python API mirroring the XML (`Action`, `Sequential`, `Parallel`, `Test_Framework`)
- A DAG execution engine with sequential/parallel grouping, global parameter propagation, and
  scope-restricted dynamic adaptation

Explicitly out of scope here (framework-level concerns from the paper): Git-in-archive version
control, STMD/SRMD traceability metadata, FMI/SSP packaging, and HPC distribution. See
[06-evolution](../06-evolution/undeveloped_sugestins.md) for ideas on evolving the schema.

## Success criteria

- Workflows are traceable and reproducible: the full history of verification activities is
  preserved and results can be replayed.
- The representation is perceived as clearer and easier to navigate than previous solutions, with
  less code duplication between projects.
- Parallelization of slow activities (simulations) yields major speed-ups, with stable behavior
  under scaling, clear error handling, and effective dynamic adaptation.
