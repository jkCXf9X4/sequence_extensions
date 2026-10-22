"""Run and record identity: the clock, safe names, and run ids.

One source for values stamped into the log, so the run boundary and the
attempt loop cannot drift on timestamp format or id shape.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime


def utcnow() -> str:
    """Current UTC instant as an ISO 8601 string (log timestamp format)."""
    return datetime.now(UTC).isoformat()


def safe_name(name: str) -> str:
    """A file-name-safe form of a node name (never empty)."""
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", name).strip("-") or "node"


def new_run_id(name: str, *, fixed: bool) -> str:
    """A run id: ``<name>-<UTC stamp>-<short uuid>``, or ``<name>-fixed``.

    ``fixed=True`` pins the id for reference-mode logs (one file per node
    name); the caller enforces exclusivity.
    """
    safe = safe_name(name)
    if fixed:
        return f"{safe}-fixed"
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    return f"{safe}-{stamp}-{uuid.uuid4().hex[:8]}"
