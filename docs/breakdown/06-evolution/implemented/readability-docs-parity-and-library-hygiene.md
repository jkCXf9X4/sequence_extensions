---
id: IMP-013
type: imp
title: Readability, docs parity, and library hygiene
summary: Dry-run plan mode, node description attribute, XSD, deviations-from-paper table, DOI harmonization, library hygiene fixes
date: 2026-10-12
status: current
---

# Readability, docs parity, and library hygiene

Fifth of five patch batches from the 2026-10-12 implementation review. Build order:
IMP-009 first, then IMP-010, IMP-011, IMP-012, IMP-013.

## Pain

- The paper's opacity criticism (its discussion section: "it is not possible to
  determine how the function find_files will alter the downstream actions by
  only looking at the representation") is mitigated only by docstrings; no way
  to see the effective post-adaptation plan.
- The paper requires comments on workflow parts ("allow comments, fostering
  clarity"); XML comments parse fine but are dropped; no per-node description
  reaches the history.
- The paper's XML-format rationale includes schema validation (its
  markup-language section); the repo ships no XSD.
- Repo and paper divergence (scoped handle instead of the full DAG, parse-time
  templates, 16 instead of 7 library functions, no start and end group nodes)
  is implicit; spread across the analysis doc and module docstrings.
- The paper itself prints two DOI strings, both wrong for this paper: the
  first page shows `10.3384/ecp218741` (which resolves to a different paper
  in the same proceedings volume) and the running footer shows
  `10.3384/ecp12076741` (which does not resolve); the resolved authoritative
  DOI is `10.3384/ecp218751` (the paper's page on the publisher site).
  The package's module docstrings and `INFO-001` (vision) now all carry the
  resolved DOI.
* `aggregate` sorts groups by `str(key)`; int keys sort lexicographically
  (`"10"` before `"2"`).
- Type-coercion responsibility is split: `params.py` normalizes the `values`
  key only; `library.py` `_coerce_operand` coerces comparison operands. Undocumented.
- `Test_Framework` reads as a test utility; the name exists for paper Listing 10
  parity only.

## Change

- Dry-run plan mode: `run_workflow` / `Test_Framework` gain `dry_run=False`;
  with `dry_run=True` the engine validates function names, then walks with a
  no-op wrapping registry and returns the final tree (plus records when history
  is on). Shows the effective post-adaptation plan.
- Schema gains an optional `description` attribute on actions and groups; the
  parser passes it through and the engine records it on `ExecutionRecord`.
- Ship `docs/schema.xsd` mirroring the parser's validation rules.
- `docs/API.md` gains a "Deviations from the paper" section: scoped handle,
  parse-time templates, library growth, no start and end group nodes — one
  line each, with the reason.
- DOI: verify the authoritative DOI against the publisher page, then
  standardize the four module docstrings and `INFO-001` on it.
- `library.py` `aggregate` sorts groups with a `(type-name, value)` sort key;
  the `values`-only normalization split is documented in `docs/API.md` and
  `params.py`; `run_python_workflow` alias added for `Test_Framework`, paper
  name kept.

## Verification

- `tests/workflow/test_engine.py`: dry-run plan tree equals the tree an
  equivalent inline workflow produces; description reaches the records.
- The XSD validates every fixture under `tests/resources/workflows/`.
- Suite green; `pb check --strict` green.
