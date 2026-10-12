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

- `IMP-015` — scope-only XML vocabulary: drop the `<sequential>` / `<parallel>` aliases. Candidate, deferred for paper-listing parity.

## Implemented (not tracked)

`implemented/` holds completed IMPs as historical records only. No longer cross-listed or tracked.

- `IMP-001` — Dynamic adaptation — design investigation. Complete. Design implemented via `DR-001` and `DR-002`.
- `IMP-002` — Replace named parameter elements with generic `<argument key value>`.
- `IMP-003` — Tier 1 workflow library functions: `aggregate`, `guard`, `while_condition`.
- `IMP-004` — Tier 2 workflow library functions: `try_action`, `retry`, `fallback`, `regression_gate`.
- `IMP-005` — Artifact store — design investigation. Store core and fan-in implemented via `DR-004` (design in `INFO-008`); P0 control-plane hygiene and P3 tooling remain open.
- `IMP-006` — Simplify DAG manipulation surface for adaptation drivers. `copy_self` plus five intent-level combinators (`fan_out` / `select` / `skip` / `skip_following` / `repeat`); the eight drivers rewritten onto them.
- `IMP-007` — Decouple artifact store from engine — structural derivation. Engine store-free at runtime; `walk_context` injection (design in `INFO-009`); the store derives at call entry via `WrappedRegistry`.
- `IMP-008` — Generic node layer in graph. `graph.node` (`Node` / `Group` + tree operations) and `graph.handle` (`TreeHandle` + the manipulation patterns, hook-parameterized); the workflow schema, `DAGHandle` and `ReplayHandle` become specializations.
- `IMP-009` — kwargs precedence fixes: run-time `parameters` reach template placeholders (pre-parse re-parse with merged globals); strict upstream suffix matching; reserved-kwarg warning at registration (`warn_reserved=False` opts out). Complete.
- `IMP-010` — history record evidence: `params` holds plain data (injected handles stripped); replay checks registry drift (warns); monotonic `duration` beside the wall-clock stamps. Complete.
- `IMP-011` — run identity and by-reference history params: `RunHistory.run_id` / `source` (workflow digest) stamped at run start, carried on every record; `params_mode="summary"` records bulk payloads as item counts. Complete.
- `IMP-012` — engine resource configuration: `max_workers`, `adaptation_bound`, caller-owned `executor` seam per run; the parallel per-future loop catches `BaseException` (inspection-verified; substrate caveat noted). Complete.
- `IMP-013` — readability and docs parity: `dry_run` plan mode, node `description` labels, `docs/schema.xsd` mirror, deviations-from-paper table, DOI harmonized to `10.3384/ecp218751`, deterministic `aggregate` sort, `values`-only normalization documented, `run_python_workflow` alias. Complete.
- `IMP-014` — optional scope type for single-child scopes: a `<scope>` holding exactly one child may omit `type`; the parser builds a sequential group. Zero or several children without `type` still rejected. Complete.
