# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- **Caller-owned pools drain when the root node fails.** Every failed run set
  the cancellation flag, which is the engine-owned pool's settle signal; a node
  still queued on a caller-owned pool could be aborted before its body ran. The
  flag is now set only for engine-owned pools and run-level timeouts, so
  caller-owned work is drained as documented and the run log stays complete.

## [3.1.0] - 2026-11-13

### Added

- **`flow-plan/2` JSON Schema.** `sequence_extensions.flow.plan_schema()`
  returns a JSON Schema (draft 2020-12) for the strict, fully-emitted plan
  document, and the same schema ships as
  `sequence_extensions/schemas/flow-plan-2.schema.json` in the wheel, sdist,
  and GitHub release. Host applications can validate plans against the
  published contract instead of hand-mirroring the document shape. The
  checked-in artifact is guarded by a drift test asserting it equals
  `plan_schema()`, and `execute_plan` still accepts looser input without a
  `value` per parameter.

- **Identity-addressed node overrides.** `NodeIdentity(name, path, instance)`
  identifies one submitted occurrence: `instance` counts submissions sharing
  `(name, path)` in submission order, so it survives a body that returns
  futures out of order. `RunOptions.parameters` / `node_policies` accept a
  name (legacy, every occurrence) or an identity (exact, wins over name).
  `apply_override` node entries accept `path` + `instance` to target one
  occurrence; both together or neither, and an unknown identity is an error.

### Changed

- **Plan document paths include the run root.** `nodes[].path` now mirrors a
  real run (`["campaign", "simulate"]`), not the plan-time bare name. The
  plan pass runs the root body with the root on the path, so document and
  runtime identities match for `execute_plan`.

## [3.0.1] - 2026-11-10

### Changed

- **Ruff pinned to 0.16.x.** The whole tree is formatted with `ruff format`
  (0.16.10); pre-commit and the CI format check now share one formatter.
- **CI hardening.** `tests.yml` and `wheels.yml` are stricter: timeout,
  wheel/sdist build and smoke-test, and a checkout-left-clean check.

