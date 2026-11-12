# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

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

