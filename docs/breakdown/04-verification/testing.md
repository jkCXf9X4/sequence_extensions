---
id: INFO-006
type: info
title: Test strategy
summary: How the pytest suite verifies the package: run commands, per-area coverage, and claim verification
date: 2026-10-09
status: current
---

# Test strategy

The suite is pytest (>= 8, < 9) with pytest-cov. `pytest` runs it as-is: `pyproject.toml` sets `pythonpath = ["src"]` and `testpaths = ["tests"]`. `xfail_strict = true` makes a passing xfail a failure. The coverage floor is 90% (`fail_under = 90`).

## Run

- `pytest` — full suite
- `pytest --cov=sequence_extensions --cov-report=term-missing` — suite with the coverage floor enforced
- CI runs the same suite with coverage on Python 3.9 to 3.13; the routine steps live in `INFO-007`

## Areas

- `tests/test_package.py` — package-level smoke tests: root re-exports and public methods (30)
- `tests/ext/` — `list_ext` (51), `dict_ext` (44), `gen_ext` (6)
- `tests/graph/test_graph_future.py` — DAG execution, pool lifecycle, timeouts, cycle detection (22)
- `tests/workflow/test_schema.py` — `parse_workflow` and every XML rejection rule (14)
- `tests/workflow/test_templates.py` — `Template` and the XML template surface (56)
- `tests/workflow/test_registry.py` — `FunctionRegistry`, decorators, name conflicts (12)
- `tests/workflow/test_engine.py` — ordering, concurrency, adaptation splicing, scope (11)
- `tests/workflow/test_history.py` — execution history and deterministic replay (26)
- `tests/workflow/test_library.py` — the seven shipped library functions (18)
- `tests/workflow/test_scaling.py` — concurrency stability under scaling (4)
- `tests/workflow/test_integration_alignment.py` — one workflow composing all four features (1)

## Fixtures and claim verification

- `tests/resources/workflows/` — XML documents mirroring the paper's listings (2, 3, 5, 7, 9) plus template examples; `invalid/` holds one file per rejection rule
- `tests/resources/workflow_stubs.py` — the paper's seven functions as deterministic stubs; they self-register in `DEFAULT_REGISTRY` on import
- Vision claims (`INFO-001`) are verified by fixture: paper listings run end-to-end, scaling tests prove the speed-up claim, history tests prove traceability and replay
- The engine under test is `INFO-004`; the product claims it verifies are `INFO-002`
