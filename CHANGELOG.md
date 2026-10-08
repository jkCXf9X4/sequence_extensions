# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed
- **Workflow XML schema**: parameters are now written as
  `<argument key="name" value="..."/>` elements, both as `<action>`
  parameters and as global parameters inside `<VerificationWorkflow>`
  (e.g. `<argument key="model" value="./model_1"/>`).  The previous
  element-name-as-parameter form (`<param_name value="..."/>`) is no
  longer accepted and is rejected as an unknown element, so parameter
  names can no longer clash with the structural element names
  (`<action>`, `<sequential>`, `<parallel>`) and the schema is uniform:
  an element's name is never a parameter name, the `key` attribute
  carries it.  The parser additionally rejects an `<argument>` missing
  its `key` or `value` attribute, a duplicate `key` on one action, an
  `<argument>` containing child elements, and non-`<argument>` children
  of `<action>` / `<VerificationWorkflow>`.
- **`parameter_sweep` test stub**: the `parameter` spelling alias for
  `parameter_name` is removed; both the XML form
  (`<argument key="parameter_name" ...>`) and the Python API form
  (`Action("parameter_sweep", parameter_name=...)`) use `parameter_name`.
- **Package structure**: restructured the package into three subpackages for
  easier navigation — `ext/` (the `list_ext` / `dict_ext` / `gen_ext`
  helpers), `graph/` (the dependency-graph future substrate), and `workflow/`
  (the V&V workflow layer).  The former `workflow_engine` module is split
  into `workflow/schema.py`, `workflow/registry.py`, `workflow/params.py`,
  and `workflow/engine.py`; the paper's stub functions are test resources
  (`tests/resources/workflow_stubs.py`), not package modules.  The
  top-level public API (`from sequence_extensions import ...`) is unchanged;
  only the internal module paths moved.

## [0.2.0] - 2026-09-10

### Changed
- **graph_future pool lifecycle**: fixed behavior around the `graph_future` pool lifecycle (pool teardown/cleanup semantics).
- **list/dict extension semantics**: corrected semantics of list and dict extension helpers (mapping, chaining, conversion behavior).
- **Docs**: expanded and corrected documentation.
- **CI**: added GitHub Actions CI matrix (Python 3.9–3.13) running tests, coverage, lint, format check, and build.
- **Lint**: added pre-commit hooks (ruff check + format, trailing whitespace, EOF fixer) and pinned dev dependencies.
- **Packaging**: migrated to PEP 639 license metadata, single-source the version from `sequence_extensions.__version__`, and added explicit src-layout package discovery.

## [0.1.4] - 2026-09-10

### Added
- Initial release: higher-order function extensions for Python lists, dicts, generators, and dependency-graph futures.