"""Session guard: the committed fixtures must not change during a test run.

The golden is evidence only if the run that verifies it cannot rewrite it.  A
normal run never writes ``ref/`` or ``cases/``, so any drift between session
start and session finish is either a bug or a silent regeneration.  This guard
hashes both trees at start, compares at finish, and fails the session naming
the changed paths.

Skipped when ``UPDATE_REF`` (or ``UPDATE_GOLDENS``) is set: regeneration is the
one reviewed path that is allowed to write ``ref/`` — and it is refused in CI
by :func:`e2e.golden.save_reference`.

The hooks live in ``tests/conftest.py``; this module is the state machine.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

E2E = Path(__file__).resolve().parent

#: The committed trees a verify run must leave alone.
ROOTS = (E2E / "ref", E2E / "cases")

_SKIP_ENV = ("UPDATE_GOLDENS", "UPDATE_REF")
_STATE: dict[Path, dict[str, str]] = {}


def _skipped() -> bool:
    return any(os.environ.get(name) for name in _SKIP_ENV)


def _digest(root: Path) -> dict[str, str]:
    """Relative path -> sha256 for every file below ``root``, bytecode excluded."""
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"
    }


def snapshot(roots=ROOTS) -> None:
    """Record the committed trees before the session runs anything."""
    if _skipped():
        return
    for root in roots:
        if root.is_dir():
            _STATE[root] = _digest(root)


def check(session) -> None:
    """Fail the session if a committed fixture changed while it ran."""
    if _skipped():
        return
    drifted = []
    for root, before in _STATE.items():
        after = _digest(root)
        drifted += [
            f"{root.name}/{name}"
            for name in sorted(set(before) | set(after))
            if before.get(name) != after.get(name)
        ]
    if not drifted:
        return
    session.exitstatus = 1
    reporter = session.config.pluginmanager.get_plugin("terminalreporter")
    message = "committed fixtures changed during the run:\n" + "\n".join(
        f"  {d}" for d in drifted
    )
    if reporter:
        reporter.write_line(message, red=True)
    else:
        print(message)
