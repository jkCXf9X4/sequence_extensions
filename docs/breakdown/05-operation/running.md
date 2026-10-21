---
id: INFO-007
type: info
title: Install, run, and maintain
summary: Install, run, test, lint, and release steps for sequence_extensions, as present in the repo
date: 2026-10-13
status: current
---

# Install, run, and maintain

The product is a library plus one CLI (`INFO-002`): no service to deploy. Day-to-day operation is install, run, test, lint, and release.

## Install

- `pip install sequence-extensions-flow` — from PyPI
- `pip install .` — from a source checkout
- `pip install -e ".[dev]"` — editable install with dev extras (pytest, pytest-cov, ruff)
- Requires Python >= 3.11; the package has no runtime dependencies

## Run

- Use the Python API: `from sequence_extensions.flow import execute_flow, gather, node, RunOptions` — embedding a host application (`CP-027`)
- `execute_flow` writes its run log to `runs/<run_id>.jsonl` under the working directory (default); pass `RunOptions(log=...)` to choose the directory
- CPU-bound campaigns run on `ProcessGraphPool` (`CP-022`); build the fan-out in the root/parent body, because a process worker cannot submit or return a live future. Running at an HPC cluster follows the recipe pattern: `INFO-012`
- Run from a config file, no driver script (`CP-026`): `flow-runner config.toml` (or `python -m sequence_extensions.flow_runner config.toml`)
  - The file selects the module and node (`[run]`), sets inputs (`[inputs]`), tunes run options (`[run]`) and node defaults (`[node]`)
  - `--flow NAME` overrides the selection; `--list` shows the nodes in the module
  - Exit codes: 0 ok, 1 flow failure, 2 usage or config error — cron, CI, SLURM can branch on them (`CP-028`)
  - The config file names a module to import; treat it as trusted code

## Test and lint

- `pytest` — full suite
- `pytest --cov=sequence_extensions --cov-report=term-missing` — with the 90% coverage floor
- `ruff check .` and `ruff format --check .` — lint and format check
- `ruff check . --fix` and `ruff format .` — auto-fix
- Optional pre-commit hooks (`.pre-commit-config.yaml`): ruff, ruff-format, trailing-whitespace, end-of-file-fixer

## CI and release

- CI (`.github/workflows/ci.yml`) runs on push to `main` and on PRs: matrix Python 3.11 to 3.13, install dev extras, pytest with coverage, ruff check, ruff format check, `python -m build`
- No Makefile and no release automation
- Release is manual: bump `__version__` in `src/sequence_extensions/__init__.py`, record the change in `CHANGELOG.md` (Keep a Changelog, SemVer), merge after CI passes
- `CONTRIBUTING.md` defines the PR process: branch from `main`, tests and lint pass, CHANGELOG updated under Unreleased
