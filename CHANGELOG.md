# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **Generic node layer in `graph`** (IMP-008): the node structure and
  the DAG manipulation patterns move to a domain-free layer that the
  workflow specializes. Op shapes, the commit protocol, `AdaptationOp`
  and the history format are unchanged.
  - `sequence_extensions.graph.node` — `Node` (ordered `children` +
    optional `name`) with identity-based `contains`, depth-first
    `locate` and deep `clone` (a per-class `_copy` hook receives the
    opaque overrides), and `Group` (the container specialization).
    `Action` is now a `Node` leaf; `Sequential` / `Parallel` are
    `Group`s.
  - `sequence_extensions.graph.handle` — `TreeHandle`: a scoped handle
    over a node tree with the intent-level patterns
    (`fan_out` / `select` / `skip` / `skip_following` / `repeat`),
    the clone ops and the write primitives. It never mutates: a domain
    supplies validation, op recording and empty-group policy through
    hooks (`_emit`, `_check_writable`, `_check_target`,
    `_check_nodes`, `_empty_group`).
  - `DAGHandle` and `ReplayHandle` are now `TreeHandle` subclasses:
    they share the manipulation flows by construction instead of
    hand-mirroring them. The workflow keeps its policy (validation
    rules and messages, `AdaptationOp` + the dynamic-node bound, the
    empty-`Sequential` skip sentinel, `adjust`); replay keeps the
    fake-tree reads and functional clone/select ops, and the
    write-only patterns stay explicit no-ops.
  - New exports: `Node`, `Group`, `TreeHandle` (from
    `sequence_extensions` and `sequence_extensions.graph`).

### Changed
- Pattern-raised errors (`fan_out` / `select` / `repeat` /
  `following_group` argument and lookup failures) lose the
  ``dynamic adaptation:`` prefix — they now come from the generic
  `TreeHandle` layer. Every documented failure condition still raises
  `ValueError` with the same meaning; the handle's own policy messages
  (read-only parallel scope, executed target, out-of-scope target,
  node types, bound) are unchanged.
- Replay `select` error path unifies with the live handle's (the two
  had drifted: different message wording and default-miss behavior);
  successful replay is unaffected.

### Added
- **DAGHandle combinators** (IMP-006): intent-level methods that cover the
  recurring driver patterns, each recording the same primitive
  ``AdaptationOp``s a hand-written driver would (the engine commit path,
  op semantics, and history records are unchanged):
  - ``dag.fan_out(overrides)`` — clone the declared downstream scope once
    per override set and replace it (map; the paper's Listing 5).
  - ``dag.select(name, default=None)`` — pick the named child of the
    declared downstream group and replace the group with it (branch);
    returns the chosen child.
  - ``dag.skip()`` — replace the declared downstream group with an empty
    group (the body never runs).
  - ``dag.skip_following()`` — replace every following sibling with an
    empty group (first-success).
  - ``dag.repeat(**overrides)`` — append copies of the preceding body plus
    a fresh copy of the acting action itself at the scope end (the
    copy-to-end iteration form).
  - ``dag.copy_self(**overrides)`` — clone the acting action itself (the
    node the iteration drivers re-append; previously each driver rebuilt
    it by hand via ``Action(check.function, **check.params)``, breaking
    the "functions never build nodes" rule).
- **Scope snapshots record group names** — a history record's ``scope``
  snapshot now records a named group sibling's label and its named
  children's names, and replay materializes them: branching drivers
  (``evaluate_goal``) replay deterministically (``ReplayHandle.select``).
- The eight adaptation drivers are rewritten onto the combinators — one
  call each, no node construction in library functions.

### Changed
- The ``evaluate_goal`` / ``select`` error messages for an unknown
  alternative are now prefixed ``dynamic adaptation:`` (the selection
  logic moved from the driver into the handle).

### Fixed
- **Cloned groups keep their `name`** — `dag.copy` (and the history
  replay clone) now preserves a group's optional scope label. Previously
  a clone of `<scope name="solvers">` lost its name (falling back to its
  kind in addressing and losing its label downstream).

### Added
- **Workflow artifact store** (IMP-005): an opt-in, by-reference data
  plane for bulk data. Control data (verdicts, counts, paths, summaries)
  keeps flowing by value through kwargs — unchanged, paper parity —
  while artifacts (simulation outputs, reports, datasets) flow by
  reference through a new ``workflow.artifacts`` module and never enter
  kwargs. The store is coupled to the DAG and decoupled from the engine
  (it imports the schema only, like ``workflow.history``).
  - ``ArtifactStore(root)`` — one store per run: the run directory and
    a fresh append-only ``manifest.jsonl`` are created at run start; a
    root that already contains a manifest is refused (recorded evidence
    is never silently appended to). ``run_workflow`` /
    ``Test_Framework`` accept ``artifacts=`` (default ``None`` = no
    store, zero behavior change; ``artifacts`` then stays an ordinary
    parameter name).
  - **Minted addresses** — an action's address is its call-time tree
    position: enclosing scope labels (a ``name``d scope by name, an
    unnamed one by kind) plus the function name, each with a collision
    suffix on repeat (``name``, ``name_2``, ... — the kwargs vocabulary,
    in path space). Addresses are minted at submission time (walk
    order, never thread scheduling), recorded in the manifest (one
    entry per executed action: ``seq`` / ``address`` / ``function`` /
    the action's own ``params`` / ``dynamic``), and never recomputed —
    sweep clones and iteration bodies get fresh directories
    (``sequential``, ``sequential_2``, ...), preserving every clone's
    outputs.
  - **Scoped ``ArtifactHandle``** — injected as the reserved
    ``artifacts`` kwarg into functions that declare one (the registry's
    cached ``wants_artifacts`` flag, mirroring ``dag``; the handle wins
    over any same-named parameter). ``out_dir()`` is the node's own
    directory (the only writable one); ``read(path)`` reads a received
    pointer scope-checked (the causal past — the same actions whose
    results fan into the call's kwargs; parallel siblings are
    information barriers); ``branches(name)`` enumerates every
    completed parallel group named ``name`` in the causal past, the
    fan-in view for cross-branch comparison.
  - **History linkage and replay** — with a store, every
    ``ExecutionRecord.artifacts`` carries the action's minted address
    (the join key into the manifest). ``replay(history, registry,
    artifacts=store)`` re-invokes artifacts-declaring functions with a
    ``ReplayArtifacts`` handle (reads from the recorded manifest,
    ``out_dir()`` returning the original node directory) so the
    replayed result — returned pointers included — matches the
    recorded one.
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
- **Dynamic adaptation** (design principle 2): actions may now adjust
  downstream actions at runtime, restricted to their own grouping scope,
  with execution strictly downstream (DAG, no loops) to stay deterministic.
  - **Scoped DAG handle** (``workflow/adaptation.py``): a function that
    declares a ``dag`` parameter receives a scoped ``DAGHandle`` exposing
    its own grouping scope — ``following()`` / ``preceding()`` /
    ``following_group()`` reads, and ``replace`` / ``adjust`` / ``copy`` /
    ``append`` / ``adjusted`` write ops. Writes are validated eagerly and
    applied transactionally at function return (one engine-lock
    acquisition; if the function raised, nothing is applied). Children of a
    ``Parallel`` scope get a read-only handle (every write raises
    ``ValueError``). ``DAGHandle`` / ``AdaptationOp`` / ``ADAPTATION_BOUND``
    are exported from ``sequence_extensions.workflow``.
  - **Bounded adaptation** (decision D5): the engine counts dynamic nodes
    added; exceeding ``ADAPTATION_BOUND`` (default 10 000) raises a
    deterministic ``ValueError`` so a runaway adaptation terminates instead
    of hanging.
  - **Lazy tree-walking engine** (``workflow/engine.py``): the engine is
    rewritten from "eagerly build all futures" to a lazy interpreter that
    walks the live node tree, re-reading each group's children every step so
    runtime splices are seen immediately. Every action still runs on a pool
    worker via a ``GraphFuture`` leaf; a ``Parallel`` group wires all of its
    action futures at once through a join node and waits with one
    ``pool.result`` (wire-then-wait), so a group's children start
    concurrently. The return-nodes protocol is kept as a backward-compatible
    shortcut (a splice may now replace a next-sibling *action*, not only a
    group); a function that declares ``dag`` **and** returns nodes raises
    ``ValueError`` (one mechanism per action).
  - **Schema** (``workflow/schema.py``): a new ``<scope
    type="sequential|parallel">`` element (``type`` required and validated,
    optional ``name``) that names each action's grouping scope;
    ``<sequential>`` / ``<parallel>`` remain aliases (no deprecation
    warnings). ``name`` is a keyword on ``_Group.__init__``.
  - **Library** (``workflow/library.py``): ``find_files`` /
    ``parameter_sweep`` are re-expressed via the handle (they clone the
    declared downstream scope per file / per value instead of building
    nodes; their own return value is their result). Two new objective-2
    drivers: ``evaluate_goal`` (branch to the named alternative of the
    declared downstream alternatives scope based on an upstream result field;
    unknown alternative → ``ValueError``; optional default) and
    ``check_convergence`` (copy-to-end iteration until an upstream field
    converges; returns a summary; runaway → the dynamic-node bound).
    ``register_library()`` now registers 9 functions (still opt-in).
  - **History & replay** (``workflow/history.py``): ``ExecutionRecord``
    gains ``adaptations`` (the committed op descriptors, plain data) and
    ``scope`` (a snapshot of the acting action's sibling list + index,
    recorded at injection). ``replay`` strips the recorded ``dag`` kwarg and
    re-injects a ``ReplayHandle`` (reads served from a fake tree materialized
    from the snapshot; writes are no-ops), so replaying an adapting run is
    deterministic and never mutates the live tree.
  - **Docs** (closes the investigation's F3): ``docs/API.md`` gains a full
    ``workflow`` section (schema, engine, registry, library, history, the
    adaptation contract table, and the non-Turing-completeness statement);
    ``README.md`` gains a ``<scope>`` example.

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