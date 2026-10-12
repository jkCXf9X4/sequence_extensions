<!-- GENERATED FILE — do not edit. Regenerate with pb-registers. -->

# Decision Stream

Flat, dated history of every committed design choice. Current state lives
in the layer leaves named by each record's `state:` field.

Records live in the cold-storage archive; extract one with `pb archive read <ID>`.

## By Layer

### Architecture

- **DR-001** — Scoped DAG handle for dynamic adaptation · accepted · 2026-10-09 · `DR-001`
  Dynamic adaptation uses a scoped DAG handle with a <scope> element; the declarative <branch>/<case> + Repeat() option is rejected.
- **DR-002** — Lazy tree-walking engine for dynamic adaptation · accepted · 2026-10-09 · `DR-002`
  The workflow engine is a lazy tree-walking interpreter; runtime adaptation mutates the live node tree through a scoped DAGHandle with transactional commit.
- **DR-004** — By-reference artifact store coupled to the DAG · accepted · 2026-10-11 · `DR-004`
  Bulk workflow data flows through an opt-in ArtifactStore with minted addresses and an append-only manifest; the structured results-kwarg and blackboard options are rejected.

### Operation

- **DR-003** — Breakdown restructure: decision archive, references, implemented IMPs · accepted · 2026-10-10 · `DR-003`
  The breakdown keeps history in the cold-storage archive docs/archive/archive.zip with generated registers beside it; the source paper lives in docs/references/.
