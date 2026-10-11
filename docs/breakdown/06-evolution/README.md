# 06-evolution — Evolution

What might change, and why.

Holds change candidates:
- Undecided IMPs (evidence-backed pain or risk).
- Selected-but-not-yet-implemented work.

## Ask

"What might change, and why?" — the open improvement candidates and the work selected for implementation.

## How ideas flow

Idea to IMP to decision to task, per the change pipeline:

- **Idea** — a pain or risk, with evidence.
- **IMP** — a scoped candidate, filed under `selected/`. Not yet decided.
- **Decision record** — required when the change alters the accepted baseline or spans layers. Filed via `pb archive add` into `docs/archive/archive.zip`.
- **Task** — concrete work from the accepted IMP or decision. Only tasks produce code changes.
- **Implement and verify** — the owning layer adopts the state.
- **Move** — the completed IMP moves to `implemented/`. No longer tracked.

## Boundary

- Holds only candidates for change.
- Never restates current state.
- Never holds accepted decisions (those live in the owning leaf and the archive `docs/archive/archive.zip`).

## Open IMPs

- `IMP-007` — Decouple artifact store from engine — structural
  derivation. Engine sheds all store knowledge; a walk context (own node
  plus ancestry) is the only injection; the store derives address,
  causal past and branches structurally at call time via registry
  wrapping.

## Implemented (not tracked)

`implemented/` holds completed IMPs as historical records only. No longer cross-listed or tracked.

- `IMP-001` — Dynamic adaptation — design investigation. Complete. Design implemented via `DR-001` and `DR-002`.
- `IMP-002` — Replace named parameter elements with generic `<argument key value>`.
- `IMP-003` — Tier 1 workflow library functions: `aggregate`, `guard`, `while_condition`.
- `IMP-004` — Tier 2 workflow library functions: `try_action`, `retry`, `fallback`, `regression_gate`.
- `IMP-005` — Artifact store — design investigation. Store core and fan-in implemented via `DR-004` (design in `INFO-008`); P0 control-plane hygiene and P3 tooling remain open.
- `IMP-006` — Simplify DAG manipulation surface for adaptation drivers. `copy_self` plus five intent-level combinators (`fan_out` / `select` / `skip` / `skip_following` / `repeat`); the eight drivers rewritten onto them.
- `IMP-008` — Generic node layer in graph. `graph.node` (`Node` / `Group` + tree operations) and `graph.handle` (`TreeHandle` + the manipulation patterns, hook-parameterized); the workflow schema, `DAGHandle` and `ReplayHandle` become specializations.
