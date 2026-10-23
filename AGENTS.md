# AGENTS

## Vision first (required)

Before you read code, edit files, or plan a change, read the project vision:

**`docs/breakdown/00-intent/vision.md`**

It states why this repository exists, what it commits to, and what it refuses to
become. It is the first document to read, not a reference of last resort.

- Read it in full before making any change to code, tests, docs, or artifacts.
- Judge every proposed change against it. If a change conflicts with the vision,
  its commitments, goals, or non-goals, stop and surface the conflict; do not
  implement it silently.
- If the work shows the long-term direction is wrong, change the vision
  deliberately first, then the code. Never let the repository drift away from
  its stated intent.

## Rules

1. **Don't assume. Surface tradeoffs.** If a contract is ambiguous, stop and say
   so rather than picking a behaviour silently.
2. **Minimum code that solves the problem.** Nothing speculative.
3. **Touch only what you must.** Clean up only your own mess.
4. **Define success criteria and verify.**

## Repository Focus

`sequence_extensions` provides higher-order helpers for Python sequences plus a
mini flow engine on dependency-graph futures: bounded parallel campaigns,
deterministic policy, and a JSON-lines run log, local or at HPC.

- `src/sequence_extensions/ext/` holds the list, dict, and generator helpers.
- `src/sequence_extensions/graph/` holds `GraphFuture` and `GraphPool`, the
  dependency-graph substrate.
- `src/sequence_extensions/flow/` holds `@node`, `execute_flow`, the run log,
  and the process pool; `src/sequence_extensions/flow_runner/` holds the
  `flow-runner` CLI.
- The run log is the executed truth of a run; re-running is a fresh run.

## Hard constraints

- **Zero runtime dependencies.** Python >= 3.11 and the standard library only.
- **The run log is the product.** It must be complete the moment a flow
  returns, and diffable, greppable, and readable without the code beside it.
- **Deterministic by default.** Same code and inputs give the same verdict; the
  same run log compares equal.
- **No scheduler integration.** HPC is reached through recipes (a task that
  sbatches and polls), never adapters.
- **Payloads belong to the caller.** A node payload is data the caller already
  owns; the engine does not reach into another project's internals.
- **Standard artifacts first at library borders.** If no standard covers the
  need, only a documented public API type may cross; internal modules, private
  objects, and adapter-only structures never do.
- **One node primitive.** `@node` wraps plain functions with policy; futures
  passed as arguments are dependency edges. Do not add a second execution model.

## Code guidelines

- Campaigns are ordinary Python: functions, loops, decorators. Do not introduce
  a representation the user has to learn.
- Keep the engine small; prefer a clear standard-library implementation over a
  dependency or an abstraction layer.
- Preserve the log schema as a contract; changes to it need a deliberate
  migration, not an incidental edit.

## Conventions

- `docs/breakdown/` holds current state, in the seven layers.
- Dated history lives in `docs/archive/archive.zip`; read it record-by-record
  and never treat it as current state.
- Candidate changes live in `docs/breakdown/06-evolution/selected/`; the
  roadmap is `docs/breakdown/06-evolution/roadmap.md`.
- Current-state leaves are present tense. One fact has exactly one home.
- Generated registers in `docs/archive/` are not hand-edited.

## Environment

- Install for development with `pip install -e ".[dev]"`.
- Run tests with `pytest` (the repo config sets `pythonpath`); coverage target
  is 90 percent (`pytest --cov`).
- Lint with `ruff check src tests` (line length 100, target py311).
