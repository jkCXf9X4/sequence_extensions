---
id: INFO-007
type: info
title: Install, run, and maintain
summary: Install, run, test, lint, and release steps for sequence_extensions, as present in the repo
date: 2026-10-09
status: current
---

# Install, run, and maintain

The product is a library (`INFO-002`): there is no service to deploy and no CLI to run. Day-to-day operation is install, test, lint, and release.

## Install

- `pip install sequence-extensions` — from PyPI
- `pip install .` — from a source checkout
- `pip install -e ".[dev]"` — editable install with dev extras (pytest, pytest-cov, ruff)
- Requires Python >= 3.9; the package has no runtime dependencies

## Run

- Use the Python API: `from sequence_extensions import list_ext, run_workflow, ...`
- Workflows run through `run_workflow` / `Test_Framework` from XML or node trees

## Test and lint

- `pytest` — full suite
- `pytest --cov=sequence_extensions --cov-report=term-missing` — with the 90% coverage floor
- `ruff check .` and `ruff format --check .` — lint and format check
- `ruff check . --fix` and `ruff format .` — auto-fix
- Optional pre-commit hooks (`.pre-commit-config.yaml`): ruff, ruff-format, trailing-whitespace, end-of-file-fixer

## CI and release

- CI (`.github/workflows/ci.yml`) runs on push to `main` and on PRs: matrix Python 3.9 to 3.13, install dev extras, pytest with coverage, ruff check, ruff format check, `python -m build`
- No Makefile and no release automation
- Release is manual: bump `__version__` in `src/sequence_extensions/__init__.py`, record the change in `CHANGELOG.md` (Keep a Changelog, SemVer), merge after CI passes
- `CONTRIBUTING.md` defines the PR process: branch from `main`, tests and lint pass, CHANGELOG updated under Unreleased
