<!-- GENERATED FILE — do not edit. Regenerate with `pb registers`. -->

# Traceability Map

Generated from record front-matter: each decision names the leaf that
holds its outcome (`state:`). The breakdown never references a record —
the leaf is the source of truth; the record is how the state got there.

### Intent

- **DR-005** — State: `docs/breakdown/02-architecture/flow-engine-decorators-over-the-graph-substrate.md` (docs/breakdown/02-architecture/flow-engine-decorators-over-the-graph-substrate.md) · Artifacts: `src/sequence_extensions/flow/`, `tests/flow/`
- **DR-009** — State: `docs/breakdown/00-intent/vision.md` (docs/breakdown/00-intent/vision.md) · Artifacts: `docs/breakdown/00-intent/vision.md`, `docs/breakdown/00-intent/README.md`, `docs/breakdown/01-product/use-cases.md`, `docs/breakdown/01-product/uc-23-run-flows-concurrently-in-one-process.md`, `docs/breakdown/01-product/deliverables.md`, `README.md`, `docs/API.md`, `pyproject.toml`
- **DR-020** — State: `docs/breakdown/00-intent/vision.md` (docs/breakdown/00-intent/vision.md) · Artifacts: `src/sequence_extensions/flow/_plan.py`, `src/sequence_extensions/flow/run.py`
- **DR-021** — State: `docs/breakdown/00-intent/vision.md` (docs/breakdown/00-intent/vision.md) · Artifacts: `tests/test_package.py`

### Product

- **DR-008** — State: `docs/breakdown/01-product/uc-22-run-cpu-bound-tasks-in-parallel.md` (docs/breakdown/01-product/uc-22-run-cpu-bound-tasks-in-parallel.md) · Artifacts: `src/sequence_extensions/flow/process_pool.py`, `src/sequence_extensions/flow/task.py`, `src/sequence_extensions/flow/__init__.py`, `tests/flow/test_process_pool.py`, `CHANGELOG.md`
- **DR-010** — State: `docs/breakdown/01-product/use-cases.md` (docs/breakdown/01-product/use-cases.md) · Artifacts: `docs/breakdown/01-product/use-cases.md`, `docs/breakdown/01-product/uc-16-define-a-flow-in-python.md`, `docs/breakdown/01-product/uc-17-run-independent-tasks-concurrently.md`, `docs/breakdown/01-product/uc-18-order-dependent-tasks-general-dag.md`, `docs/breakdown/01-product/uc-19-retry-back-off-and-bound-a-task.md`, `docs/breakdown/01-product/uc-20-audit-a-run.md`, `docs/breakdown/01-product/uc-21-bound-the-concurrency.md`, `docs/breakdown/01-product/uc-22-run-cpu-bound-tasks-in-parallel.md`, `docs/breakdown/01-product/uc-23-run-flows-concurrently-in-one-process.md`, `docs/breakdown/02-architecture/flow-engine-decorators-over-the-graph-substrate.md`, `docs/breakdown/01-product/README.md`
- **DR-011** — State: `docs/breakdown/02-architecture/deliverables.md` (docs/breakdown/02-architecture/deliverables.md) · Artifacts: `docs/breakdown/02-architecture/deliverables.md`, `docs/breakdown/01-product/README.md`, `docs/breakdown/02-architecture/README.md`, `docs/breakdown/README.md`
- **DR-012** — State: `docs/breakdown/01-product/uc-25-verify-two-runs-executed-identically.md` (docs/breakdown/01-product/uc-25-verify-two-runs-executed-identically.md) · Artifacts: `src/sequence_extensions/flow/runlog.py`, `src/sequence_extensions/flow/__init__.py`, `tests/flow/test_runlog_tools.py`, `docs/API.md`, `README.md`, `CHANGELOG.md`
- **DR-015** — State: `docs/breakdown/02-architecture/flow-engine-decorators-over-the-graph-substrate.md` (docs/breakdown/02-architecture/flow-engine-decorators-over-the-graph-substrate.md) · Artifacts: `src/sequence_extensions/config.py`, `src/sequence_extensions/flow_runner/__init__.py`, `src/sequence_extensions/flow_runner/__main__.py`, `src/sequence_extensions/flow/task.py`, `src/sequence_extensions/flow/flow.py`, `src/sequence_extensions/flow/process_pool.py`, `src/sequence_extensions/graph/graph_future.py`, `src/sequence_extensions/flow/__init__.py`, `tests/flow/test_config.py`, `tests/runner/flows.py`, `tests/runner/test_runner.py`, `docs/API.md`, `README.md`, `CHANGELOG.md`
- **DR-016** — State: `docs/breakdown/01-product/uc-29-keep-a-run-log-byte-stable-for-reference-storage.md` (docs/breakdown/01-product/uc-29-keep-a-run-log-byte-stable-for-reference-storage.md) · Artifacts: `src/sequence_extensions/flow/runlog.py`, `src/sequence_extensions/flow/flow.py`, `src/sequence_extensions/config.py`, `tests/flow/test_runlog.py`, `tests/flow/test_config.py`, `tests/e2e/test_flows.py`, `docs/API.md`, `README.md`, `CHANGELOG.md`
- **DR-017** — State: `docs/breakdown/02-architecture/flow-engine-decorators-over-the-graph-substrate.md` (docs/breakdown/02-architecture/flow-engine-decorators-over-the-graph-substrate.md) · Artifacts: `src/sequence_extensions/flow/_options.py`, `src/sequence_extensions/flow/_context.py`, `src/sequence_extensions/flow/node.py`, `src/sequence_extensions/flow/run.py`, `src/sequence_extensions/flow/runlog.py`, `src/sequence_extensions/flow/process_pool.py`, `src/sequence_extensions/flow_runner/__init__.py`, `tests/flow/test_node.py`, `tests/flow/test_run.py`, `tests/flow/test_options.py`, `tests/flow/test_process_pool.py`, `tests/runner/test_runner.py`, `tests/e2e/test_flows.py`
- **DR-018** — State: `docs/breakdown/02-architecture/flow-engine-decorators-over-the-graph-substrate.md` (docs/breakdown/02-architecture/flow-engine-decorators-over-the-graph-substrate.md) · Artifacts: `src/sequence_extensions/flow/_context.py`, `src/sequence_extensions/flow/_options.py`, `src/sequence_extensions/flow/node.py`, `src/sequence_extensions/flow/run.py`, `src/sequence_extensions/flow/runlog.py`, `src/sequence_extensions/flow/process_pool.py`, `src/sequence_extensions/graph/graph_future.py`, `tests/flow/test_nested.py`, `tests/flow/test_node.py`, `tests/flow/test_run.py`, `tests/flow/test_options.py`, `tests/flow/test_process_pool.py`, `tests/flow/test_runlog_tools.py`

### Architecture

- **DR-001** — State: `02-architecture/workflow-engine.md` (02-architecture/workflow-engine.md) · Artifacts: `src/sequence_extensions/workflow/adaptation.py`, `src/sequence_extensions/workflow/schema.py`, `src/sequence_extensions/workflow/library.py`
- **DR-002** — State: `02-architecture/workflow-engine.md` (02-architecture/workflow-engine.md) · Artifacts: `src/sequence_extensions/workflow/engine.py`, `src/sequence_extensions/workflow/adaptation.py`
- **DR-004** — State: `02-architecture/workflow-artifacts-by-reference-data-plane.md` (02-architecture/workflow-artifacts-by-reference-data-plane.md) · Artifacts: `src/sequence_extensions/workflow/artifacts.py`, `src/sequence_extensions/workflow/engine.py`, `src/sequence_extensions/workflow/registry.py`, `src/sequence_extensions/workflow/history.py`
- **DR-007** — State: `docs/breakdown/02-architecture/flow-engine-decorators-over-the-graph-substrate.md` (docs/breakdown/02-architecture/flow-engine-decorators-over-the-graph-substrate.md) · Artifacts: `src/sequence_extensions/graph/graph_future.py`, `src/sequence_extensions/flow/task.py`, `tests/graph/test_graph_future.py`, `tests/flow/test_flow.py`
- **DR-019** — State: `docs/breakdown/04-verification/stress-hardening-findings-and-dispositions.md` (docs/breakdown/04-verification/stress-hardening-findings-and-dispositions.md) · Artifacts: `src/sequence_extensions/ext/list_ext.py`, `src/sequence_extensions/flow/node.py`, `src/sequence_extensions/flow/run.py`, `src/sequence_extensions/flow/runlog.py`, `src/sequence_extensions/flow_runner/__init__.py`, `src/sequence_extensions/graph/graph_future.py`, `tests/flow/test_hardening.py`, `tests/flow/test_runlog_tools.py`, `tests/e2e/ref/campaign.jsonl`, `tests/e2e/ref/failing_campaign.jsonl`

### Verification

- **DR-013** — State: `docs/breakdown/04-verification/testing.md` (docs/breakdown/04-verification/testing.md) · Artifacts: `e2e/flows.py`, `e2e/test_flows.py`, `e2e/README.md`, `e2e/ref/campaign.jsonl`, `e2e/ref/failing-campaign.jsonl`, `pyproject.toml`
- **DR-014** — State: `docs/breakdown/04-verification/testing.md` (docs/breakdown/04-verification/testing.md) · Artifacts: `tests/e2e/flows.py`, `tests/e2e/test_flows.py`, `tests/e2e/README.md`, `tests/e2e/ref/campaign.jsonl`, `tests/e2e/ref/failing_campaign.jsonl`, `tests/e2e/out/logs/campaign-fixed.jsonl`, `tests/e2e/out/logs/failing_campaign-fixed.jsonl`, `pyproject.toml`

### Operation

- **DR-003** — State: `README.md` (Product Breakdown — sequence_extensions) · Artifacts: `docs/breakdown/pb.toml`, `docs/archive/archive.zip`, `docs/references/paper_44_yBqbPyj1.pdf`, `docs/breakdown/06-evolution/implemented/dynamic-adaptation.md`
- **DR-006** — State: `README.md` (Product Breakdown — sequence_extensions) · Artifacts: `docs/archive/archive.zip`, `docs/breakdown/06-evolution/README.md`, `docs/breakdown/06-evolution/roadmap.md`, `docs/breakdown/05-operation/running-flows-local-and-at-hpc.md`
