# 02-architecture — Architecture

How the system is organized: component decomposition, data and message flow, interfaces, and structural decisions.

## Ask

"How is the system organized?" — the three subpackages, their dependency order, the data flow, and the interface contracts.

## When to Read

- Before adding or changing a component or an interface.
- When tracing how a value flows from input to output.

## Boundary

- Holds the organizing design only.
- Not specific files or scripts: `03-implementation/`.
- Not the proof strategy: `04-verification/`.
- The workflow engine's execution model: INFO-004.
- The workflow artifact store's data plane: INFO-008.
- The artifact store's decoupling contract: INFO-009.

## Contents

<!-- pb:index:start -->
<!-- GENERATED FILE — do not edit. Regenerate with pb-registers. -->
- **INFO-003** [Components](components.md) — Component decomposition of ext/, graph/, workflow/ — responsibilities, data flow, and interface contracts
- **INFO-004** [Workflow engine — lazy tree-walking interpreter](workflow-engine.md) — The workflow engine walks the node tree lazily, one GraphFuture per action; runtime adaptation mutates the live tree through a scoped DAGHandle with transactional commit.
- **INFO-008** [Workflow artifacts — by-reference data plane](workflow-artifacts-by-reference-data-plane.md) — The artifact store couples bulk data to the DAG, not the engine: minted addresses, an append-only manifest, a scoped handle with causal-past reads and fan-in branch enumeration
- **INFO-009** [Artifact store — decoupling contract and retrospective domain](artifact-store-decoupling-contract-and-retrospective-domain.md) — The store derives from raw position (walk context + registry wrapping); the store sees only the present and the causal past, so frozen snapshots answer every query and replay needs no engine.
<!-- pb:index:end -->
