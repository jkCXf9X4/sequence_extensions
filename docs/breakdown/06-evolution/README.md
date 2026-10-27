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
- **Retire** — the completed IMP leaves the tree, archived via `pb archive add --deprecated`. The tree holds current state and open candidates only (`DR-006`).

## Boundary

- Holds only candidates for change.
- Never restates current state.
- Never holds accepted decisions (those live in the owning leaf and the archive `docs/archive/archive.zip`).

## Open IMPs

- `IMP-018` — pickle payload tier for run-log values.
- `IMP-020` — split `ext` from `flow` at a future release.

Direction pointers: `INFO-013`.

## Contents

<!-- pb:index:start -->
<!-- GENERATED FILE — do not edit. Regenerate with pb-registers. -->
- **INFO-013** [Roadmap](roadmap.md) — Direction pointers for the flow engine — parallelism local and at HPC, determinism and audit, engine hygiene; rows cite canonical homes by ID
<!-- pb:index:end -->
