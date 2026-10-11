"""
By-reference artifact store for the V&V workflow layer.

The engine's data plane is by value: results flow through keyword
arguments, so every payload an action returns is carried by the run's
result chain and mirrored into the history's recorded parameters.  That
is right for control data (verdicts, counts, paths, summaries) and wrong
for bulk data (simulation outputs, reports, datasets), which the V&V
domain produces as files.  This module adds the missing reference plane
(design investigation ``IMP-005``, ``docs/breakdown/06-evolution/``):

* **Split by weight** — control data keeps flowing by value through
  kwargs (unchanged, paper parity); artifacts flow by reference through
  the store and never enter kwargs.  The convention is modeled by the
  functions themselves: write the payload into the node directory, return
  a small pointer (the root-relative address of the file).
* **Coupled to the DAG, decoupled from the engine** — the store imports
  the schema only (never the engine), like :mod:`.history`.  The engine's
  whole involvement is injecting a scoped handle into functions that
  declare an ``artifacts`` parameter (mirroring the ``dag`` injection).
* **Addresses are minted at call time, never recomputed** — an address
  is the tree position the action occupied when it ran: the enclosing
  named scopes' labels plus the function name, each with a collision
  suffix (``name``, ``name_2``, ...) on repeat.  Positions shift under
  dynamic adaptation, so addresses are captured as the walker reaches
  each node and recorded in an append-only manifest.  The manifest is the
  executed truth; the workflow XML is the declared truth; together they
  are the run's evidence.
* **Scopes are structural, not conventional** — write scope is the
  action's own directory; read scope is the action's causal past (exactly
  the actions whose results the engine fans into its kwargs).  The same
  sequential invariant that makes ``dag=`` writes safe proves artifact
  reads settled: everything behind the walker is frozen, everything
  ahead is unwalked.  Parallel groups are information barriers — a
  branch sees the pre-group snapshot, never its siblings — and a
  completed group's branches become enumerable downstream
  (:meth:`ArtifactHandle.branches`), which is how cross-branch
  comparison reaches data that kwargs deliberately do not carry.
* **Deterministic** — addresses derive from walk order (submission
  order, child order), never from thread scheduling.  The manifest's
  global sequence numbers are assigned under a lock; entries minted
  inside concurrently-walked parallel branches interleave, which the
  manifest records as executed (the SET of entries and every address are
  deterministic; only the interleaving of independent branches is not).
* **Replay** — :func:`.history.replay` re-invokes recorded calls; a
  function that declared ``artifacts`` is re-invoked with a
  :class:`ReplayArtifacts` handle injected instead: reads are served
  from the recorded manifest, ``out_dir()`` returns the ORIGINAL node
  directory (a deterministic function rewrites identical content, so
  the replayed result matches the recorded one).

Recording is opt-in: ``run_workflow`` / ``Test_Framework`` accept an
``artifacts=ArtifactStore(root)`` argument (default ``None``).  Without
it the engine behaves exactly as before — no directory is created, no
manifest is written, and ``artifacts`` remains an ordinary parameter
name.
"""

from __future__ import annotations

import json
import re
import threading
from pathlib import Path, PurePosixPath
from typing import Any, Union

from .schema import Action, Parallel, Sequential

__all__ = [
    "ArtifactHandle",
    "ArtifactStore",
    "MANIFEST_NAME",
    "ReplayArtifacts",
]

_Node = Union[Action, Sequential, Parallel]

#: The manifest file name (JSON lines, one entry per minted action, in
#: mint order — the run's executed truth).
MANIFEST_NAME = "manifest.jsonl"

# Characters allowed in an address segment.  Anything else (path
# separators included) is collapsed to ``_`` so a label can never escape
# its directory or forge a different node's path.
_SAFE_SEGMENT = re.compile(r"[^A-Za-z0-9._-]+")


def _safe_segment(label: str) -> str:
    """
    Sanitize one address segment (a scope label or function name).

    Address segments are also directory names, so path separators and
    other unsafe characters are replaced with ``_``; the result is never
    empty and never ``.`` or ``..``.  Deterministic: the same label
    always sanitizes to the same segment.
    """
    cleaned = _SAFE_SEGMENT.sub("_", label).strip("_") or "_"
    if cleaned in (".", ".."):
        cleaned = "_"
    return cleaned


def group_label(group: _Node) -> str:
    """
    A group's address label: its ``name`` if it has one, else its kind.

    Named scopes (``<scope name="sweep">``) address by name; unnamed
    groups address by kind (``sequential`` / ``parallel``).
    """
    name = getattr(group, "name", None)
    if name:
        return _safe_segment(name)
    if isinstance(group, Sequential):
        return "sequential"
    return "parallel"


def _under(path: PurePosixPath, directory: str) -> bool:
    """True when ``path`` is ``directory`` or lies below it."""
    return path == PurePosixPath(directory) or path.is_relative_to(directory)


class ArtifactStore:
    """
    An opt-in, by-reference store for one workflow run.

    ``root`` is the run directory (created at run start).  The engine
    drives the store: it mints one address per executed action
    (append-only manifest entry) and hands each artifacts-declaring
    function a scoped :class:`ArtifactHandle`.  Constructing the store
    touches no disk; the root and the manifest are created when the run
    begins, and a root that already contains a manifest is REFUSED (one
    store per run — recorded evidence is never appended to silently).

    After a run, the store is plain files: everything under ``root`` is
    readable by external tools with no engine involved, and
    :meth:`entries` parses the manifest.  The handle APIs exist to make
    the DURING-run discipline structural (write scope, causal reads,
    parallel barriers), not to gate post-run access.
    """

    def __init__(self, root: str | Path) -> None:
        """Create a store for the run directory ``root`` (nothing on disk yet)."""
        self._root = Path(root)
        self._lock = threading.Lock()
        self._seq = 0
        self._opened = False
        self._addresses: set[str] = set()

    # ------------------------------------------------------------ #
    # Introspection
    # ------------------------------------------------------------ #
    @property
    def root(self) -> Path:
        """The run directory every address is relative to."""
        return self._root

    @property
    def manifest_path(self) -> Path:
        """The append-only manifest file (``root/manifest.jsonl``)."""
        return self._root / MANIFEST_NAME

    def entries(self) -> list[dict[str, Any]]:
        """
        The manifest entries, in mint (walk) order.

        Each entry is a plain dict: ``seq`` (global mint index),
        ``address`` (the node's root-relative directory), ``function``
        (the registry name), ``params`` (the action's OWN declared
        parameters — not the merged kwargs, so the manifest never
        echoes upstream results), and ``dynamic`` (spliced in at
        runtime).  Returns an empty list before the run begins.
        """
        manifest = self.manifest_path
        if not manifest.exists():
            return []
        lines = manifest.read_text(encoding="utf-8").splitlines()
        return [json.loads(line) for line in lines if line.strip()]

    def __repr__(self) -> str:
        """One-liner with the run root and the minted-address count."""
        return f"ArtifactStore({str(self._root)!r}, minted={len(self._addresses)})"

    # ------------------------------------------------------------ #
    # Engine-driven protocol (called by the engine, not by users)
    # ------------------------------------------------------------ #
    def _begin(self) -> None:
        """
        Open the store for a run: create the root and a fresh manifest.

        Refuses a root that already holds a manifest (recorded evidence
        is never silently extended) and a store that already ran one
        workflow.  Raises ``ValueError`` in both cases.
        """
        with self._lock:
            if self._opened:
                raise ValueError(
                    f"artifact store {str(self._root)!r} already ran a "
                    f"workflow; use a fresh ArtifactStore per run"
                )
            if self.manifest_path.exists():
                raise ValueError(
                    f"artifact store root {str(self._root)!r} already "
                    f"contains {MANIFEST_NAME}; pass a fresh run directory "
                    f"(recorded evidence is never appended to)"
                )
            self._root.mkdir(parents=True, exist_ok=True)
            self.manifest_path.write_text("", encoding="utf-8")
            self._opened = True

    def _mint(
        self,
        address: str,
        function: str,
        params: dict[str, Any],
        dynamic: bool,
    ) -> None:
        """
        Append one action's manifest entry (the mint).

        Called by the engine at submission time, in walk order, on the
        walking thread; the global ``seq`` is assigned under the store
        lock, so concurrent branch walks produce unique, gapless
        indices whose interleaving reflects execution.
        """
        entry = {
            "seq": self._seq,
            "address": address,
            "function": function,
            "params": dict(params),
            "dynamic": bool(dynamic),
        }
        with self._lock:
            self._seq += 1
            self._addresses.add(address)
            with open(self.manifest_path, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, default=str) + "\n")

    def _node_dir(self, address: str) -> Path:
        """The node directory for ``address`` (created on first use)."""
        directory = self._root / address
        directory.mkdir(parents=True, exist_ok=True)
        return directory


class ArtifactHandle:
    """
    A scoped, per-action view of the :class:`ArtifactStore`.

    The engine constructs one handle per call to a function that
    declares an ``artifacts`` parameter (the registry's cached
    ``wants_artifacts`` flag); ``artifacts`` is then a reserved kwarg
    name — the injected handle wins over any same-named parameter.
    The handle is plain data (address + the causal-past snapshots
    taken at submission), so it is safe to build on the walking thread
    and use on a pool worker.

    * ``address`` — the action's root-relative directory (e.g.
      ``"sweep/simulate"``); the pointer convention returns addresses
      like ``f"{handle.address}/result.csv"`` so pointers stay
      portable across run roots.
    * :meth:`out_dir` — the node's own directory (the ONLY writable
      one), created on first use.
    * :meth:`read` — a scope-checked read of a file in the causal
      past (the actions whose results the engine fans into this
      call's kwargs, plus this action's own directory).
    * :meth:`branches` — the branch directories of a COMPLETED
      parallel group in the causal past (the fan-in view).
    """

    def __init__(
        self,
        store: ArtifactStore,
        address: str,
        readable: list[str] | tuple[str, ...] = (),
        groups: list | tuple = (),
    ) -> None:
        """Bind the handle to ``address`` with its causal-past snapshots."""
        self._store = store
        self.address = address
        self._readable: tuple[str, ...] = tuple(readable)
        self._groups: tuple[tuple[str, tuple[str, ...]], ...] = tuple(groups)

    def __repr__(self) -> str:
        """One-liner with the node address and the readable-past size."""
        return f"ArtifactHandle({self.address!r}, reads={len(self._readable)})"

    # ------------------------------------------------------------ #
    # Writes (own node directory only)
    # ------------------------------------------------------------ #
    def out_dir(self) -> Path:
        """
        The action's own artifact directory (created on first use).

        The write scope: nothing outside this directory is offered for
        writing.  The pointer convention is to write payloads here and
        return ``f"{self.address}/<file>"`` (root-relative, portable).
        """
        return self._store._node_dir(self.address)

    # ------------------------------------------------------------ #
    # Reads (the causal past)
    # ------------------------------------------------------------ #
    def read(self, path: str | Path) -> bytes:
        """
        Read one artifact file, scope-checked, and return its bytes.

        ``path`` is the pointer another action returned: root-relative
        (``"sweep/simulate/result.csv"``) or absolute under the store
        root.  The file must lie in this action's read scope — its own
        directory, a directory of an action whose result the engine fans
        into this call's kwargs (the same information the by-value plane
        carries; parallel siblings' directories are never in scope), or
        a branch directory of a COMPLETED parallel group in the causal
        past (the fan-in view — see :meth:`branches`).  Raises
        ``ValueError`` for a path outside the readable scope,
        ``FileNotFoundError`` for a missing file.
        """
        relative = self._relative_to_root(path)
        if not self._is_readable(relative):
            raise ValueError(
                f"artifact read out of scope: {relative} is not in the "
                f"causal past of {self.address} (parallel siblings are "
                f"information barriers; only received pointers and "
                f"enumerated branches are readable)"
            )
        return (self._store.root / relative).read_bytes()

    def _is_readable(self, relative: PurePosixPath) -> bool:
        """True when ``relative`` lies in the read scope (see :meth:`read`)."""
        if _under(relative, self.address):
            return True
        if any(_under(relative, directory) for directory in self._readable):
            return True
        return any(
            _under(relative, directory)
            for _, directories in self._groups
            for directory in directories
        )

    def _relative_to_root(self, path: str | Path) -> PurePosixPath:
        """Normalize ``path`` to a root-relative POSIX path."""
        candidate = Path(path)
        if candidate.is_absolute():
            try:
                candidate = candidate.relative_to(self._store.root)
            except ValueError:
                raise ValueError(
                    f"artifact path {str(path)!r} is outside the store root "
                    f"{str(self._store.root)!r}"
                ) from None
        return PurePosixPath(*candidate.parts)

    # ------------------------------------------------------------ #
    # Fan-in (completed parallel groups in the causal past)
    # ------------------------------------------------------------ #
    def branches(self, name: str) -> list[Path]:
        """
        The branch directories of the completed parallel groups ``name``.

        The fan-in view: after a parallel group completes, the actions
        downstream of it can enumerate its branch directories (in child
        order) — the data plane's counterpart of the group's ordered
        result list, for branches whose payloads live in the store.
        Every completed group named ``name`` in the causal past
        contributes, in causal order (the same ALL-occurrences
        convention the library's upstream suffix-scan helpers use): a
        parameter sweep that clones a named parallel group yields every
        clone's branches, concatenated.  Raises ``ValueError`` when no
        such group exists there (unknown name, or a group that is still
        running — a branch cannot enumerate its own group).
        """
        directories: list[Path] = []
        for label, group_branches in self._groups:
            if label == name:
                directories.extend(self._store.root / branch for branch in group_branches)
        if not directories:
            raise ValueError(
                f"artifact store: no completed group named {name!r} in this "
                f"action's causal past (parallel groups are enumerable only "
                f"downstream of their completion)"
            )
        return directories


class ReplayArtifacts:
    """
    A replay stand-in for :class:`ArtifactHandle` (mirrors ``ReplayHandle``).

    :func:`.history.replay` re-invokes a recorded run's actions; a
    function that declared an ``artifacts`` parameter is re-invoked
    with this handle injected instead of a live one:

    * **Reads** are served from the recorded run's manifest: any path
      under a minted address is readable (the run is over — the live
      causal-past barriers protected a running tree, not settled
      evidence).
    * ``out_dir()`` returns the ORIGINAL node directory, so a
      deterministic function rewrites identical content and the
      replayed result — including returned pointers — matches the
      recorded one.  No new evidence is minted.
    * :meth:`branches` reconstructs the fan-in view from the manifest
      addresses (most recent group named ``name``; the same latest-wins
      rule as the live handle).
    """

    def __init__(self, store: ArtifactStore, address: str | None) -> None:
        """Bind to the recorded ``address``; index the manifest addresses."""
        self._store = store
        self.address = address
        self._addresses: list[str] = [entry["address"] for entry in store.entries()]

    def __repr__(self) -> str:
        """One-liner with the recorded address and the store root."""
        return f"ReplayArtifacts({self.address!r}, root={str(self._store.root)!r})"

    def out_dir(self) -> Path:
        """The ORIGINAL node directory (replay rewrites, never re-mints)."""
        if self.address is None:
            raise ValueError(
                "artifact store: this record was not minted (no artifact "
                "store was configured for the original run)"
            )
        directory = self._store.root / self.address
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def read(self, path: str | Path) -> bytes:
        """
        Read one artifact file recorded by the original run.

        ``path`` is root-relative or absolute under the store root and
        must lie under a manifest-minted address.  Raises
        ``ValueError`` otherwise, ``FileNotFoundError`` for a missing
        file.
        """
        candidate = Path(path)
        if candidate.is_absolute():
            try:
                candidate = candidate.relative_to(self._store.root)
            except ValueError:
                raise ValueError(
                    f"artifact path {str(path)!r} is outside the store root "
                    f"{str(self._store.root)!r}"
                ) from None
        relative = PurePosixPath(*candidate.parts)
        if not any(_under(relative, directory) for directory in self._addresses):
            raise ValueError(
                f"artifact read out of scope: {relative} is not under an "
                f"address recorded in the run's manifest"
            )
        return (self._store.root / relative).read_bytes()

    def branches(self, name: str) -> list[Path]:
        """
        Reconstruct the branch directories of the groups ``name``.

        Scans the manifest: every address containing a ``name`` segment
        defines a group; its branch directories are the distinct segments
        directly below that group's path.  Groups are concatenated in
        the order their first entry was minted (the replay counterpart
        of the live handle's causal-order concatenation; within one
        group, branch order is mint order, which parallel scheduling may
        interleave differently than the live child order).  Raises
        ``ValueError`` when the manifest records no group of that name.
        """
        entries = self._store.entries()
        prefixes: list[tuple[int, PurePosixPath]] = []
        seen_prefixes: set[str] = set()
        for entry in entries:
            parts = PurePosixPath(entry["address"]).parts
            for index, part in enumerate(parts):
                if part == name and index + 1 < len(parts):
                    prefix = PurePosixPath(*parts[: index + 1])
                    key = prefix.as_posix()
                    if key not in seen_prefixes:
                        seen_prefixes.add(key)
                        prefixes.append((entry["seq"], prefix))
                    break
        if not prefixes:
            raise ValueError(
                f"artifact store: the manifest records no group named "
                f"{name!r} with branches"
            )
        directories: list[Path] = []
        for _seq, prefix in prefixes:
            prefix_parts = prefix.parts
            seen: set[str] = set()
            for entry in entries:
                parts = PurePosixPath(entry["address"]).parts
                if (
                    len(parts) > len(prefix_parts)
                    and parts[: len(prefix_parts)] == prefix_parts
                ):
                    branch = parts[len(prefix_parts)]
                    if branch not in seen:
                        seen.add(branch)
                        directories.append(self._store.root / prefix / branch)
        return directories
