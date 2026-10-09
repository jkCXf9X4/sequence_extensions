# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **Workflow templates** (design principle 4, reuse): a named,
  parameterized subtree can be defined once and instantiated wherever its
  verification scenario is needed, limiting duplication between workflows.
  - Python API: ``Template(name, body, **defaults)`` holds the reusable
    subtree (a ``Sequential`` / ``Parallel`` group or a single ``Action``,
    wrapped in a ``Sequential``); ``Template.instantiate(**params)``
    returns a NEW node tree with every ``{placeholder}`` in an action
    parameter value bound, so instantiating the same template with
    different parameters yields distinct, independent trees.  A
    placeholder that fills a whole value is replaced by the bound value
    itself (type preserved); one embedded in a longer string is replaced
    by its string form.  Resolution is strict: every placeholder must
    resolve to a binding, a default or a same-named global parameter.
  - XML: a ``<template name="...">`` element defines a template (one body
    group plus ``<argument>`` default values) directly inside the
    ``<VerificationWorkflow>`` wrapper; a ``<use-template name="...">``
    element uses it (with ``<argument>`` bindings) anywhere a group may
    appear, including inside other template bodies.  Expansion happens at
    PARSE time — ``parse_workflow`` returns a tree of plain ``Action`` /
    ``Sequential`` / ``Parallel`` nodes, exactly what the equivalent
    inline workflow produces — so the engine, history recording and
    dynamic adaptation are unchanged.  Binding precedence: use-site
    binding > template default > same-named workflow global.
  - ``Template`` is exported from ``sequence_extensions`` and
    ``sequence_extensions.workflow``.
  - New rejection rules (``ValueError``, same style as the existing
    schema errors): ``<template>`` without a name / body, with more than
    one body, with a duplicate default key or an unknown child element;
    duplicate template names; ``<template>`` inside a grouping;
    ``<use-template>`` without a name, naming an unknown template, with
    an unknown or duplicate child element, binding an undeclared
    parameter, or leaving a required parameter unbound.
  - New example documents ``tests/resources/workflows/template_reuse.xml``
    and ``template_parallel.xml`` plus 13 invalid fixtures under
    ``tests/resources/workflows/invalid/`` (indexed in that directory's
    README).

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