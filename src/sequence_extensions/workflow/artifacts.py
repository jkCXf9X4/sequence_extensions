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
  the schema and registry only (never the engine), like :mod:`.history`.
  It plugs in at the run wiring point by WRAPPING the registry
  (:meth:`ArtifactStore.wrap_registry`): every function is wrapped, the
  wrapper declares a ``walk_context`` parameter and receives the
  engine's injected walk context (plain structural position data — the
  action's node plus its ancestry chain), and derives everything else
  from it.  The engine carries no store knowledge at runtime; its whole
  contribution is the generic ``walk_context`` injection (the same shape
  of surface as the ``dag`` injection).
* **Addresses are structural, minted at call time, never recomputed** —
  an address is the action's tree position: the function name's rank
  among its same-function siblings, below each ancestor group's rank
  among its same-label group siblings (the kwargs collision-suffix
  vocabulary — ``name``, ``name_2`` — in path space, where collisions
  are harmless).  Ranks are scheduling-independent, which is what makes
  call-time minting deterministic.  The derived address is stored on the
  action node (``_engine_address``), recorded in an append-only
  manifest (the executed truth), and NEVER recomputed: positions shift
  under later adaptation, minted addresses never move.
* **Scopes are structural, not conventional** — write scope is the
  action's own directory; read scope is the action's causal past (exactly
  the actions whose results the engine fans into its kwargs).  The same
  sequential invariant that makes ``dag=`` writes safe proves the
  derivation settled: an action's ancestry and left flank are frozen
  from submission until call completion (mutations come only from
  preceding siblings — done before submission — the action itself, or
  later siblings; concurrent branches mutate only their own subtrees;
  parallel parents are read-only).  Parallel groups are information
  barriers — a branch sees the pre-group snapshot, never its siblings —
  and a completed group's branches become enumerable downstream
  (:meth:`ArtifactHandle.branches`), which is how cross-branch
  comparison reaches data that kwargs deliberately do not carry.
* **Deterministic** — every address is a structural rank, never a
  function of thread scheduling.  The manifest's global sequence
  numbers are assigned at call entry under a lock, in call order: within
  a sequential walk that is identical to the walk order, and entries
  minted inside concurrently-walked parallel branches (or parallel
  action children) interleave, which the manifest records as executed
  (the SET of entries and every address are deterministic; only the
  interleaving of independent calls is not).
* **Traceable** — the manifest is not only structural: it carries
  wall-clock evidence.  A RUN HEADER (the first line of the manifest)
  records the run's identity (``run_id`` — the run history's id, when a
  history was passed to the store — and ``started_at``, the wall-clock
  time the run began); every entry carries a ``timestamp`` (the
  wall-clock time the action was minted, i.e. its call entry).  The
  header's ``ended_at`` is the last entry's timestamp (the run's last
  mint), exposed by :meth:`ArtifactStore.header`.  The header is
  written at run start (``_begin``), so a run that dies before any
  action still leaves a header behind.
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
import time
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any, Callable, Union

from .params import normalize_params
from .registry import FunctionRegistry, wants_artifacts
from .schema import Action, Parallel, Sequential

if TYPE_CHECKING:  # the store is history-free at runtime (IMP-007); the
    # run header reuses the history's run identity without importing it.
    from .history import RunHistory

__all__ = [
    "ArtifactHandle",
    "ArtifactStore",
    "MANIFEST_NAME",
    "ReplayArtifacts",
    "WrappedRegistry",
]

_Node = Union[Action, Sequential, Parallel]
_Group = Union[Sequential, Parallel]

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


def _is_header(entry: dict[str, Any]) -> bool:
    """
    True when a parsed manifest line is the run header, not an entry.

    The header is the manifest's first line and is the only line without
    a ``seq`` (entries are numbered 0, 1, 2, ... in mint order).  The
    check is structural, so a header written by an older store version
    (no ``run_id`` / ``started_at`` keys) is still recognized.
    """
    return "seq" not in entry


# --------------------------------------------------------------------------- #
# Structural derivation (IMP-007): the walk context is the only input
# --------------------------------------------------------------------------- #


def _child_segment(parent: _Group, index: int) -> str:
    """
    The path segment of ``parent``'s group child at ``index``.

    The kwargs collision-suffix vocabulary in path space: the child's
    label (``group_label``), with ``_2``, ``_3`` ... on repeat among the
    parent's group children — exactly the ordinals the walk's group
    entries consume, recomputed from the live tree.  Called only for
    children that are groups (the ancestry chain's intermediate nodes).
    """
    label = group_label(parent.children[index])
    ordinal = 1 + sum(
        1
        for sibling in parent.children[:index]
        if not isinstance(sibling, Action) and group_label(sibling) == label
    )
    return label if ordinal == 1 else f"{label}_{ordinal}"


def _action_segment(parent: _Group, index: int) -> str:
    """
    The path segment of ``parent``'s action child at ``index``.

    The action's function name, with the same collision-suffix
    vocabulary among the parent's action children — exactly the mint
    ranks the walk's submissions consume, recomputed from the live tree.
    """
    name = parent.children[index].function
    rank = 1 + sum(
        1
        for sibling in parent.children[:index]
        if isinstance(sibling, Action) and sibling.function == name
    )
    return name if rank == 1 else f"{name}_{rank}"


def _derive_address(context: Any) -> str:
    """
    The action's address, derived from its walk context.

    One segment per ancestry level (the group child's label ordinal —
    the ROOT level contributes none, its path is the run root) plus the
    action's own function rank.  Rank-based, so scheduling-independent:
    the same node derives the same address no matter how the pool ran
    it.  See :meth:`ArtifactStore.wrap_registry` for the freeze
    argument that makes call-time derivation sound.
    """
    chain = context.chain
    segments = [
        _safe_segment(_child_segment(group, index)) for group, index in chain[:-1]
    ]
    parent, index = chain[-1]
    segments.append(_safe_segment(_action_segment(parent, index)))
    return "/".join(segments)


def _flank_addresses(group: _Group, path: list[str], readable: list[str]) -> None:
    """
    The addresses a completed preceding group child contributes to the
    causal past of later siblings (mirroring the by-value flow exactly).

    A ``Parallel`` group passes only its DIRECT action children's
    results out of the group (one-level flattening — the barrier); a
    ``Sequential`` group is transparent: every action child, and every
    group child's contribution recursively, flows on.
    """
    if isinstance(group, Parallel):
        for position, child in enumerate(group.children):
            if isinstance(child, Action) and not getattr(child, "_engine_executed", False):
                readable.append(
                    "/".join([*path, _safe_segment(_action_segment(group, position))])
                )
        return
    for position, child in enumerate(group.children):
        if isinstance(child, Action):
            readable.append(
                "/".join([*path, _safe_segment(_action_segment(group, position))])
            )
        else:
            _flank_addresses(
                child, [*path, _safe_segment(_child_segment(group, position))], readable
            )


def _derive_readable(context: Any) -> tuple[str, ...]:
    """
    The action's causal past as addresses, derived from its walk context.

    For every SEQUENTIAL level of the ancestry (a parallel level is a
    barrier — its children are concurrent, not causal), the one-level
    left flank: preceding action children, plus the contribution of
    preceding group children (one-level flattening per level, recursive
    through sequential structure).  Identical, position for position,
    to the addresses whose results the engine fans into the action's
    kwargs.
    """
    readable: list[str] = []
    path: list[str] = []
    chain = context.chain
    for level, (group, index) in enumerate(chain):
        if isinstance(group, Sequential):
            for position, child in enumerate(group.children[:index]):
                if isinstance(child, Action):
                    readable.append(
                        "/".join([*path, _safe_segment(_action_segment(group, position))])
                    )
                else:
                    _flank_addresses(
                        child, [*path, _safe_segment(_child_segment(group, position))], readable
                    )
        if level + 1 < len(chain):
            path.append(_safe_segment(_child_segment(group, index)))
    return tuple(readable)


def _branch_directories(group: Parallel, path: list[str]) -> tuple[str, ...]:
    """
    One branch directory per child of a completed parallel group, in
    child order: the action child's minted address, or the child
    group's path segment.
    """
    directories: list[str] = []
    for position, child in enumerate(group.children):
        if getattr(child, "_engine_executed", False):
            continue
        if isinstance(child, Action):
            directories.append(
                "/".join([*path, _safe_segment(_action_segment(group, position))])
            )
        else:
            directories.append(
                "/".join([*path, _safe_segment(_child_segment(group, position))])
            )
    return tuple(directories)


def _completed_groups(group: _Group, path: list[str], groups: list) -> None:
    """
    The parallel-group completions a preceding group child passes up to
    its parent walk, in causal (walk) order.

    A ``Parallel`` group contributes ITSELF (its branch directories —
    the fan-in view); its internals stay behind the barrier.  A
    ``Sequential`` group is transparent: the completions of its group
    children flow on recursively.
    """
    if isinstance(group, Parallel):
        groups.append((group_label(group), _branch_directories(group, path)))
        return
    for position, child in enumerate(group.children):
        if not isinstance(child, Action):
            _completed_groups(
                child, [*path, _safe_segment(_child_segment(group, position))], groups
            )


def _derive_groups(context: Any) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """
    The completed parallel groups visible to the action, in causal
    order, derived from its walk context.

    For every SEQUENTIAL level of the ancestry, the preceding group
    children's completions (never through a parallel barrier — a
    concurrent branch's accumulations stay inside the branch).
    """
    groups: list[tuple[str, tuple[str, ...]]] = []
    path: list[str] = []
    chain = context.chain
    for level, (group, index) in enumerate(chain):
        if isinstance(group, Sequential):
            for position, child in enumerate(group.children[:index]):
                if not isinstance(child, Action):
                    _completed_groups(
                        child, [*path, _safe_segment(_child_segment(group, position))], groups
                    )
        if level + 1 < len(chain):
            path.append(_safe_segment(_child_segment(group, index)))
    return tuple(groups)


class ArtifactStore:
    """
    An opt-in, by-reference store for one workflow run.

    ``root`` is the run directory (created at run start).  The store is
    driven through its REGISTRY WRAPPING: the run's wiring point
    (:func:`.engine.run_workflow` / :func:`.engine.Test_Framework`)
    opens it (``_begin`` — a root that already contains a manifest is
    refused, so recorded evidence is never silently extended) and swaps
    in :meth:`wrap_registry`'s view, whose wrapped functions mint one
    address per executed action (append-only manifest entry) and hand
    each artifacts-declaring function a scoped :class:`ArtifactHandle`.
    Constructing the store touches no disk; the root and the manifest
    are created when the run begins.

    After a run, the store is plain files: everything under ``root`` is
    readable by external tools with no engine involved, and
    :meth:`entries` parses the manifest (skipping the run header, which
    :meth:`header` returns).  The handle APIs exist to make the
    DURING-run discipline structural (write scope, causal reads,
    parallel barriers), not to gate post-run access.
    """

    def __init__(
        self,
        root: str | Path,
        history: "RunHistory | None" = None,
    ) -> None:
        """
        Create a store for the run directory ``root`` (nothing on disk yet).

        ``history`` is the run's :class:`~.history.RunHistory` (optional):
        when given, the manifest's run header reuses its ``run_id`` as the
        run's identity, so the manifest and the history name the same run.
        Without it the header's ``run_id`` is ``None`` (the store is a
        standalone opt-in; the history is a separate one).
        """
        self._root = Path(root)
        self._lock = threading.Lock()
        self._seq = 0
        self._opened = False
        self._addresses: set[str] = set()
        self._history = history

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
        echoes upstream results), ``dynamic`` (spliced in at runtime),
        and ``timestamp`` (the wall-clock time the action was minted —
        its call entry; the run's wall-clock evidence).  The run header
        (the manifest's first line) is not an entry and is skipped here
        (see :meth:`header`).  Returns an empty list before the run
        begins.
        """
        manifest = self.manifest_path
        if not manifest.exists():
            return []
        lines = manifest.read_text(encoding="utf-8").splitlines()
        return [
            json.loads(line)
            for line in lines
            if line.strip() and not _is_header(json.loads(line))
        ]

    def header(self) -> dict[str, Any] | None:
        """
        The manifest's run header, or ``None`` before the run begins.

        The header is the manifest's first line: ``run_id`` (the run's
        identity — the run history's ``run_id`` when a history was
        passed to the store, else ``None``) and ``started_at`` (the
        wall-clock time the run began, ``time.time()`` at ``_begin``).
        The returned dict is AUGMENTED with ``ended_at``: the last
        entry's ``timestamp`` (the run's last mint — the wall-clock
        evidence of when the run's work finished), or ``None`` when the
        run minted no entries.  The header itself is never rewritten
        (the manifest is append-only); ``ended_at`` is derived, not
        stored.
        """
        manifest = self.manifest_path
        if not manifest.exists():
            return None
        lines = manifest.read_text(encoding="utf-8").splitlines()
        for line in lines:
            if not line.strip():
                continue
            parsed = json.loads(line)
            if _is_header(parsed):
                header = dict(parsed)
                entries = self.entries()
                header["ended_at"] = (
                    entries[-1]["timestamp"] if entries else None
                )
                return header
        return None

    def __repr__(self) -> str:
        """One-liner with the run root and the minted-address count."""
        return f"ArtifactStore({str(self._root)!r}, minted={len(self._addresses)})"

    # ------------------------------------------------------------ #
    # Engine-driven protocol (called by the engine, not by users)
    # ------------------------------------------------------------ #
    def _begin(self) -> None:
        """
        Open the store for a run: create the root and a fresh manifest.

        The manifest opens with the RUN HEADER (the first line): the
        run's identity (``run_id`` — the run history's id when a history
        was passed to the store, else ``None``) and ``started_at`` (the
        wall-clock time the run began).  The header is written before
        any entry, so a run that dies before any action still leaves
        wall-clock evidence of when it started.

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
            header = {
                "run_id": (
                    self._history.run_id if self._history is not None else None
                ),
                "started_at": time.time(),
            }
            self.manifest_path.write_text(
                json.dumps(header) + "\n", encoding="utf-8"
            )
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

        Called at call entry by the store's registry wrapper, so the
        global ``seq`` is CALL order (within a sequential walk identical
        to the walk order); the store lock makes concurrent branch
        entries unique and gapless, with an interleaving that reflects
        execution.  The entry's ``timestamp`` is the wall-clock time of
        the mint (the action's call entry) — the manifest's per-action
        wall-clock evidence (the run header's ``started_at`` / derived
        ``ended_at`` bound the whole run).
        """
        entry = {
            "seq": self._seq,
            "address": address,
            "function": function,
            "params": dict(params),
            "dynamic": bool(dynamic),
            "timestamp": time.time(),
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

    # ------------------------------------------------------------ #
    # Registry wrapping (the plug-in point, IMP-007)
    # ------------------------------------------------------------ #
    def wrap_registry(self, registry: FunctionRegistry) -> WrappedRegistry:
        """
        A per-run wrapped view of ``registry`` for the run's wiring point.

        Every function is wrapped (lazily, cached per name): the wrapper
        declares the engine's ``walk_context`` parameter, derives the
        action's address, causal past and completed groups structurally
        at call entry, mints the manifest row and injects the scoped
        :class:`ArtifactHandle` for functions that declare an
        ``artifacts`` parameter.  The inner registry is never mutated
        (a shared ``DEFAULT_REGISTRY`` stays untouched); the wrapped
        view preserves the inner functions' ``dag`` and ``artifacts``
        flags, so handle injection and the one-mechanism rule are
        unaffected.  Called by :func:`.engine.run_workflow` /
        :func:`.engine.Test_Framework` — nowhere else.
        """
        return WrappedRegistry(registry, self)


# --------------------------------------------------------------------------- #
# Registry wrapping (IMP-007): the store's plug-in point
# --------------------------------------------------------------------------- #


def _wrap_function(fn: Callable[..., Any], store: ArtifactStore) -> Callable[..., Any]:
    """
    Wrap one registered function with the store's call-time addressing.

    The wrapper declares the ``walk_context`` parameter, so the engine
    injects the action's structural position into the WRAPPER call (the
    reserved-name rule: the injected context wins over any same-named
    parameter, and the wrapped function never sees it).  At call entry
    the wrapper derives the address, the causal past and the completed
    groups from the context, mints the manifest row, records the address
    on the node (``_engine_address`` — the engine's history reads it
    there), and injects the scoped :class:`ArtifactHandle` when the
    wrapped function declares an ``artifacts`` parameter.  Everything
    else — including an engine-injected ``dag`` handle — passes through
    to the wrapped function untouched.

    Soundness (the freeze argument): the derivation reads the live tree
    at call entry, and an action's ancestry and left flank are frozen
    from submission until call completion — mutations come only from
    preceding siblings (done before submission), the action itself, or
    later siblings; concurrent branches mutate only their own subtrees;
    parallel scopes are read-only.  That is the same sequential
    invariant the ``dag=`` write protocol relies on.
    """

    inner_wants_artifacts = wants_artifacts(fn)

    def wrapper(walk_context=None, **kwargs: Any) -> Any:
        node = walk_context.node
        address = _derive_address(walk_context)
        # Write-once: the node attribute and the manifest row.  Positions
        # shift under later adaptation; minted addresses never move.
        node._engine_address = address
        store._mint(
            address=address,
            function=node.function,
            params=normalize_params(node.params),
            dynamic=getattr(node, "_engine_dynamic", False),
        )
        if inner_wants_artifacts:
            kwargs["artifacts"] = ArtifactHandle(
                store,
                address,
                _derive_readable(walk_context),
                _derive_groups(walk_context),
            )
        return fn(**kwargs)

    # Record fidelity: the history records the resolved callable's name.
    wrapper.__name__ = getattr(fn, "__name__", "wrapped")
    wrapper.__qualname__ = getattr(fn, "__qualname__", wrapper.__name__)
    return wrapper


class WrappedRegistry(FunctionRegistry):
    """
    A per-run wrapped view of a registry: the artifact store's plug-in
    point at the run wiring (IMP-007).

    :meth:`ArtifactStore.wrap_registry` returns one; the engine then
    talks to it through the ordinary registry surface and stays free of
    store knowledge:

    * :meth:`get` returns a LAZY, CACHED wrapper per name
      (:func:`_wrap_function` — call-time addressing from the injected
      walk context).
    * ``adapts`` / ``uses_artifacts`` delegate to the wrapped registry —
      the inner functions' own flags — so ``dag`` injection and the
      one-mechanism rule are preserved untouched.
    * ``wants_context`` is ``True`` for every name: every wrapper
      declares the walk context.
    * ``register`` delegates to the wrapped registry (this view never
      holds registrations of its own; a re-registered name's wrapper is
      dropped from the cache).  The wrapped registry itself is never
      mutated.
    """

    def __init__(self, inner: FunctionRegistry, store: ArtifactStore) -> None:
        """Create the wrapped view of ``inner`` bound to ``store``."""
        super().__init__()
        self._inner = inner
        self._store = store
        self._wrapped: dict[str, Callable[..., Any]] = {}

    def register(self, name: str, fn: Callable[..., Any]) -> None:
        """Delegate to the wrapped registry; drop the cached wrapper."""
        self._inner.register(name, fn)
        self._wrapped.pop(name, None)

    def get(self, name: str) -> Callable[..., Any]:
        """The wrapped function for ``name`` (lazy, cached per name)."""
        self._inner.get(name)  # unknown-name parity: raises ValueError
        wrapper = self._wrapped.get(name)
        if wrapper is None:
            wrapper = _wrap_function(self._inner.get(name), self._store)
            self._wrapped[name] = wrapper
        return wrapper

    def adapts(self, name: str) -> bool:
        """The wrapped function's own ``dag`` flag (preserved, not wrapped)."""
        return self._inner.adapts(name)

    def uses_artifacts(self, name: str) -> bool:
        """The wrapped function's own ``artifacts`` flag (preserved)."""
        return self._inner.uses_artifacts(name)

    def wants_context(self, name: str) -> bool:
        """Always ``True``: every wrapper declares the walk context."""
        self._inner.get(name)  # unknown-name parity: raises ValueError
        return True

    def names(self) -> list[str]:
        """The wrapped registry's names, in registration order."""
        return self._inner.names()

    def __contains__(self, name: object) -> bool:
        """True if ``name`` is registered in the wrapped registry."""
        return name in self._inner


class ArtifactHandle:
    """
    A scoped, per-action view of the :class:`ArtifactStore`.

    The store's registry wrapper constructs one handle per call to a
    function that declares an ``artifacts`` parameter; ``artifacts`` is
    then a reserved kwarg name — the injected handle wins over any
    same-named parameter.  The handle is plain data (address + the
    causal-past and completed-group views derived at call entry), so it
    is safe to build and use on a pool worker.

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
