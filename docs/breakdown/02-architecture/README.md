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
- The flow engine's execution model: INFO-011.

## Contents

<!-- pb:index:start -->
<!-- GENERATED FILE — do not edit. Regenerate with pb-registers. -->
- **INFO-003** [Components](components.md) — Component decomposition of ext/, graph/, flow/ — responsibilities, data flow, and interface contracts
- **INFO-011** [Flow engine — decorators over the graph substrate](flow-engine-decorators-over-the-graph-substrate.md) — The flow layer wraps plain functions with @task policy and @flow wiring; futures as arguments are dependency edges; the run log is the executed truth of a run
<!-- pb:index:end -->
