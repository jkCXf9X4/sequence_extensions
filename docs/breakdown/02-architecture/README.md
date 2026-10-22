# 02-architecture — Architecture

What is delivered and how it is organized: the public surface, component decomposition, data and message flow, interfaces, and structural decisions.

## Ask

"What is delivered, and how is it organized?" — the three subpackages, the public surface, the data flow, and the interface contracts.

## When to Read

- Before adding or changing a component, the public surface, or an interface.
- When tracing how a value flows from input to output.

## Boundary

- Holds the organizing design only.
- Not specific files or scripts: `03-implementation/`.
- Not the proof strategy: `04-verification/`.
- The flow engine's execution model: INFO-011.
- Library borders carry standard artifacts first; public API types are the only
  fallback, and internal objects never cross.

## Contents

<!-- pb:index:start -->
<!-- GENERATED FILE — do not edit. Regenerate with pb-registers. -->
- **INFO-002** [Deliverables](deliverables.md) — What sequence_extensions delivers — three subpackages, the public API surface, and explicit out-of-scope items
- **INFO-003** [Components](components.md) — Component decomposition of ext/, graph/, flow/ — responsibilities, data flow, and interface contracts
- **INFO-011** [Flow engine — one node primitive over the graph substrate](flow-engine-decorators-over-the-graph-substrate.md) — The flow layer wraps plain functions with @node policy; execute_flow opens a run; futures as arguments are dependency edges; the run log is the executed truth of a run
<!-- pb:index:end -->
