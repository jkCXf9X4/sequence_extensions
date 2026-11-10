# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [3.0.1] - 2026-11-10

### Changed

- **Ruff pinned to 0.16.x.** The whole tree is formatted with `ruff format`
  (0.16.10); pre-commit and the CI format check now share one formatter.
- **CI hardening.** `tests.yml` and `wheels.yml` are stricter: timeout,
  wheel/sdist build and smoke-test, and a checkout-left-clean check.

