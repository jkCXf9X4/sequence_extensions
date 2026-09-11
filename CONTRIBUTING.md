# Contributing to sequence_extensions

Thanks for your interest in contributing! This document covers the basics of
setting up a development environment, running tests and lint, and opening a
pull request.

## Development setup

1. Clone the repository and enter the project directory.
2. Create a virtual environment (Python 3.9+):

   ```bash
   python -m venv .venv
   source .venv/bin/activate   # Windows: .venv\Scripts\activate
   ```

3. Install the package in editable mode with dev dependencies:

   ```bash
   pip install -e ".[dev]"
   ```

4. (Optional) Install the pre-commit hooks:

   ```bash
   pip install pre-commit
   pre-commit install
   ```

## Running tests

```bash
pytest
```

Run tests with coverage (the project enforces a 90% coverage floor):

```bash
pytest --cov=sequence_extensions --cov-report=term-missing
```

## Running lint and format

```bash
ruff check .
ruff format --check .
```

To auto-fix lint issues and format your changes:

```bash
ruff check . --fix
ruff format .
```

## Pull request process

1. Create a feature branch from `main` (`git checkout -b my-feature`).
2. Make your changes, keeping the scope focused.
3. Add or update tests for your changes; all tests must pass.
4. Run `ruff check .` and `ruff format --check .` and fix any issues.
5. Update `CHANGELOG.md` under the "Unreleased" section (or the next version
   entry) describing your change.
6. Commit your changes with a clear, descriptive message.
7. Push the branch and open a pull request against `main`.
8. Ensure the CI checks (tests, coverage, lint, format, build) pass on your PR.

## Reporting issues

Please report bugs and request features via the
[issue tracker](https://github.com/jkCXf9X4/sequence_extensions/issues).