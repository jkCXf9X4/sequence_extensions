<!-- GENERATED FILE — do not edit. Regenerate with pb-registers. -->

# Decision Stream

Flat, dated history of every committed design choice. Current state lives
in the layer leaves named by each record's `state:` field.

Records live in the cold-storage archive; extract one with `pb archive read <ID>`.

## By Layer

### Intent

- **DR-005** — Supersede the workflow layer with an audit-first flow engine · accepted · 2026-10-13 · `DR-005`
  The declarative workflow layer (XML schema, node tree, adaptation, artifact store, replay) is superseded by @task/@flow decorators over graph_future with a JSON-lines run log as the product

### Product

- **DR-008** — ProcessGraphPool — a process-pool executor for CPU-bound tasks · accepted · 2026-10-14 · `DR-008`
  A GraphPool subclass driving a ProcessPoolExecutor behind the existing pool= seam; workers buffer run-log records and the parent writes them at future completion

### Architecture

- **DR-001** — Scoped DAG handle for dynamic adaptation · superseded · 2026-10-09 · `DR-001`
  Dynamic adaptation uses a scoped DAG handle with a <scope> element; the declarative <branch>/<case> + Repeat() option is rejected.
- **DR-002** — Lazy tree-walking engine for dynamic adaptation · superseded · 2026-10-09 · `DR-002`
  The workflow engine is a lazy tree-walking interpreter; runtime adaptation mutates the live node tree through a scoped DAGHandle with transactional commit.
- **DR-004** — By-reference artifact store coupled to the DAG · superseded · 2026-10-11 · `DR-004`
  Bulk workflow data flows through an opt-in ArtifactStore with minted addresses and an append-only manifest; the structured results-kwarg and blackboard options are rejected.
- **DR-007** — Substrate reopen — pool-scoped cancellation and a public bind · accepted · 2026-10-14 · `DR-007`
  GraphPool.__exit__ cancels only the pool's own nodes (the global _LIVE_NODES sweep is removed) and GraphPool.bind(gf) becomes the public bind-without-results; the flow layer drops its private _bind_graph call

### Operation

- **DR-003** — Breakdown restructure: decision archive, references, implemented IMPs · accepted · 2026-10-10 · `DR-003`
  The breakdown keeps history in the cold-storage archive docs/archive/archive.zip with generated registers beside it; the source paper lives in docs/references/.
- **DR-006** — Breakdown holds current state only; completed IMPs retire into the archive · accepted · 2026-10-14 · `DR-006`
  The breakdown tree keeps current state and open candidates only — completed IMPs leave the tree as archive tombstones, and committed choices live as archive records
