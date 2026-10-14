<!-- GENERATED FILE — do not edit. Regenerate with pb-registers. -->

# Decision Stream

Flat, dated history of every committed design choice. Current state lives
in the layer leaves named by each record's `state:` field.

Records live in the cold-storage archive; extract one with `pb archive read <ID>`.

## By Layer

### Intent

- **DR-005** — Supersede the workflow layer with an audit-first flow engine · accepted · 2026-10-13 · `DR-005`
  The declarative workflow layer (XML schema, node tree, adaptation, artifact store, replay) is superseded by @task/@flow decorators over graph_future with a JSON-lines run log as the product
- **DR-009** — Re-author intent and product layers around the shipped direction · accepted · 2026-10-14 · `DR-009`
  Vision and use-case catalog still carried consolidation-era framing and supersession narrative; re-authored to lead with parallel, deterministic, audited execution — local or at HPC — with audit as the trust mechanism; CP-023 (concurrent flows) added to the catalog

### Product

- **DR-008** — ProcessGraphPool — a process-pool executor for CPU-bound tasks · accepted · 2026-10-14 · `DR-008`
  A GraphPool subclass driving a ProcessPoolExecutor behind the existing pool= seam; workers buffer run-log records and the parent writes them at future completion
- **DR-010** — Use cases are need statements, not solution descriptions · accepted · 2026-10-14 · `DR-010`
  the eight use-case leaves (CP-016 to CP-023) re-authored solution-agnostic — scenario and acceptance in user-observable terms; API names, parameters, mechanisms, and code blocks move out to deliverables (INFO-002), architecture (INFO-003, INFO-011), and the API reference; IDs stable
- **DR-011** — Deliverables live in architecture; the product layer is needs only · accepted · 2026-10-14 · `DR-011`
  INFO-002 (the shipped-surface listing) relocated from 01-product to 02-architecture, completing the needs/solution split — the product layer answers only what users need; layer questions and README prose restated
- **DR-012** — Run-log reading toolkit — filter, summarize, diff · accepted · 2026-10-14 · `DR-012`
  RunLog grows the reading side — filter selects, summarize condenses to the per-task account and verdict, diff compares two runs semantically (identity-keyed, timing excluded); IMP-022 implemented

### Architecture

- **DR-001** — Scoped DAG handle for dynamic adaptation · superseded · 2026-10-09 · `DR-001`
  Dynamic adaptation uses a scoped DAG handle with a <scope> element; the declarative <branch>/<case> + Repeat() option is rejected.
- **DR-002** — Lazy tree-walking engine for dynamic adaptation · superseded · 2026-10-09 · `DR-002`
  The workflow engine is a lazy tree-walking interpreter; runtime adaptation mutates the live node tree through a scoped DAGHandle with transactional commit.
- **DR-004** — By-reference artifact store coupled to the DAG · superseded · 2026-10-11 · `DR-004`
  Bulk workflow data flows through an opt-in ArtifactStore with minted addresses and an append-only manifest; the structured results-kwarg and blackboard options are rejected.
- **DR-007** — Substrate reopen — pool-scoped cancellation and a public bind · accepted · 2026-10-14 · `DR-007`
  GraphPool.__exit__ cancels only the pool's own nodes (the global _LIVE_NODES sweep is removed) and GraphPool.bind(gf) becomes the public bind-without-results; the flow layer drops its private _bind_graph call

### Verification

- **DR-013** — e2e reference harness — version comparison by RunLog.diff · accepted · 2026-10-14 · `DR-013`
  Two deterministic mock flows (e2e/flows.py) run against a committed reference (e2e/ref) of logs and artifact trees; RunLog.diff is the comparison, UPDATE_REF regenerates, and a failure means behavior changed between versions
- **DR-014** — e2e harness under tests — versioned scratch, pinned run id · accepted · 2026-10-14 · `DR-014`
  The e2e harness moves under tests/e2e; its scratch (out/, one stable subtree per flow) is versioned instead of ignored, and the run id is pinned per flow so repeated runs leave only timing-field differences — no file churn

### Operation

- **DR-003** — Breakdown restructure: decision archive, references, implemented IMPs · accepted · 2026-10-10 · `DR-003`
  The breakdown keeps history in the cold-storage archive docs/archive/archive.zip with generated registers beside it; the source paper lives in docs/references/.
- **DR-006** — Breakdown holds current state only; completed IMPs retire into the archive · accepted · 2026-10-14 · `DR-006`
  The breakdown tree keeps current state and open candidates only — completed IMPs leave the tree as archive tombstones, and committed choices live as archive records
