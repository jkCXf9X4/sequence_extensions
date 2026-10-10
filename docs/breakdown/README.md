# Product Breakdown — sequence_extensions

Current-state record for sequence_extensions: higher-order function extensions for Python sequences, dependency-graph futures, and the V&V workflow layer. For authors and agents.

## The Seven Layers

- `00-intent/` — why does the project exist, who is it for?
- `01-product/` — what is delivered, out of scope?
- `02-architecture/` — how are deliverables, evidence, and work organized?
- `03-implementation/` — with what concrete assets is it realized?
- `04-verification/` — how do we know it satisfies the requirements?
- `05-operation/` — how do authors run, maintain, release?
- `06-evolution/` — what controlled changes come next?
- the decision stream (`docs/archive/archive.zip`) — flat, dated history: never current state; read record-by-record via `pb archive read`, never browsed

## Boundary Rule

A document's home is the layer whose question it answers; information flows downward only.
- Current state: the layer leaves, present tense.
- History: the decision stream (`docs/archive/archive.zip`), dated records.
- Tracking: the generated registers in `docs/archive/` (`README.md`, `design-choice-log.md`, `traceability-map.md`).
- This file indexes current state only.

## Reading Order

1. This file, then the layer index that owns the concern.
2. The index `## Contents` rows carry stable ID plus one-line summary; open the one leaf whose summary matches.
3. Stop when the fact is found; never keep reading for context.

## Find a Fact

- Current state: this file, then the owning layer index, then the one leaf.
- History: the archive (`docs/archive/archive.zip`) record-by-record via `pb archive read`; never browse the stream.
- Candidates: `06-evolution/` IMPs and roadmap.
- Cite nodes by stable ID (INFO-002), never by path.

## Route an Edit

- Current-state fact: update the owning layer leaf.
- Dated choice: a decision record via `pb archive add` into `docs/archive/archive.zip`.
- Candidate change: an IMP in `06-evolution/selected/`.
- One fact has exactly one home; defer cross-layer material by ID.
- Never hand-edit generated registers or index `## Contents` lists.

## Excludes

- Implementation detail and durable rationale: `docs/` (runtime-coupled), outside this tree.
- `docs/API.md`, `docs/alignment_report.md` — runtime-coupled docs, outside this breakdown.
