"""
Execution engine for the V&V workflow layer.

The engine executes the node tree produced by
:mod:`sequence_extensions.workflow.schema` (``Action`` / ``Sequential`` /
``Parallel``) on top of the :class:`sequence_extensions.graph` substrate
(``GraphFuture`` / ``GraphPool``).  The semantics follow the paper
"Automation Nation: Taming Complex V&V Workflows" (16th International
Modelica & FMI Conference, September 2025, Lucerne, Switzerland;
DOI 10.3384/ecp218751), section 4.2:

* **Sequential** — children execute in strict order: child ``i + 1`` depends
  on child ``i``.
* **Parallel** — children are independent and run CONCURRENTLY on the
  ``GraphPool``'s thread pool; the group's result is the ordered list of its
  children's results, and each child's result is also passed to the next
  sibling as its own keyword argument (fan-in).
* **Global parameters** — the root group's ``.globals`` (the
  ``<VerificationWorkflow>`` wrapper's parameter elements, overridden by the
  run-time ``parameters`` of ``run_workflow`` / ``Test_Framework``, which win
  on a name clash) are passed as default keyword arguments to EVERY function;
  an action's own ``.params`` win over globals, and upstream results win over
  both.  (Template placeholders also resolve against the merged globals — the
  engine re-parses the XML with them merged before executing, so a run-time
  parameter joins the global tier of template binding.)
* **Dynamic adaptation** — a registered function may return an
  ``Action`` / ``Sequential`` / ``Parallel`` node (or a list of them); the
  returned node(s) are spliced into the workflow in place of the action's
  next sibling — a group (the paper's Listing 5) or an action (the
  paper's Listing 7 inner case).  The replaced subtree is cancelled (its
  actions do not run).  A splice attempt that is out of scope, or from
  inside a ``Parallel`` parent, raises ``ValueError``.  A function may
  instead declare a ``dag`` parameter and receive a scoped
  :class:`~.adaptation.DAGHandle` (validated write ops, transactional
  commit at function return) — but not both (one mechanism per action).
* **At most once** — every action executes at most once; the engine never
  re-runs a function (no feedback loops).

The engine is a lazy tree-walking interpreter: it walks the live node tree
as it executes (re-reading each group's children every step, so runtime
splices are seen immediately) instead of pre-building a future graph.  Every
action still runs on a pool worker thread via a :class:`GraphFuture` leaf;
parallel groups wire all their action futures at once through a join node
and wait on it with a single ``pool.result`` call.  Parallel group children
(branch groups) each run on their own daemon thread while the engine is
within ``BRANCH_THREAD_BOUND`` (finding 5b) live branch threads; beyond the
bound a branch's walk runs inline on its parent's thread — the same runner,
just no new thread — so deeply nested, wide campaigns degrade to
sequential branch walking instead of unbounded multiplicative thread
creation.

Public surface (pinned): :func:`run_workflow`, :func:`Test_Framework`.
Internal but unit-testable: :func:`check_splice_scope`.

Opt-in execution history: pass ``history=RunHistory()`` (see
:mod:`sequence_extensions.workflow.history`) to ``run_workflow`` /
``Test_Framework`` to record per-action evidence — including actions
spliced in at runtime by dynamic adaptation, in true completion order —
and replay it deterministically with
:func:`sequence_extensions.workflow.history.replay`.  Without a
``history`` argument the engine behaves exactly as before.

Run options (all keyword-only on ``run_workflow`` / ``Test_Framework``,
all defaulting to the current behavior): ``params_mode`` ("full" |
"summary" — recorded param payloads become item counts), ``max_workers``
(the ``GraphPool`` size), ``adaptation_bound`` (the dynamic-node bound),
``executor`` (a caller-owned ``GraphPool``), ``dry_run`` (plan mode:
validate and walk with no-op functions, and return the tree instead of a
result — the answer to the paper's opacity criticism, "it is not possible
to determine how the function find_files will alter the downstream actions
by only looking at the representation") and ``action_timeout`` (the
per-action wall-clock budget in seconds; expiry raises
:class:`ActionTimeoutError`, so one hung simulator action cannot deadlock
an unattended campaign).  ``fail_fast`` (the parallel failure policy:
``False`` = the historical drain-then-report, ``True`` = stop a parallel
group at the first failure — not-yet-run siblings skip, in-flight ones are
abandoned, and the first error is raised promptly, so a runtime-sized
unattended campaign does not pay for every remaining sibling after the
first failure).  See the two functions' docstrings.

Opt-in artifact store (IMP-005, IMP-007): pass ``artifacts=ArtifactStore(root)``
(see :mod:`sequence_extensions.workflow.artifacts`) to give the run a
by-reference data plane.  The ENGINE carries no store knowledge: the
wiring point in :func:`run_workflow` / :func:`Test_Framework` opens the
store (``store._begin()``) and swaps in a wrapped registry view
(``store.wrap_registry(registry)``) whose functions derive their own
addressing at call time from the walk context the engine injects (the
generic ``walk_context`` parameter, mirroring ``dag``).  Without an
``artifacts`` argument the engine behaves exactly as before (no
directory is created, no manifest is written).
"""

from __future__ import annotations

import concurrent.futures
import threading
import time
from typing import TYPE_CHECKING, Any, Callable, NoReturn, Union

from ..graph import GraphFuture, GraphPool
from ..graph.graph_future import _LIVE_NODES
from .adaptation import ADAPTATION_BOUND, AdaptationOp, DAGHandle
from .history import (
    ExecutionRecord,
    RunHistory,
    _workflow_digest,
    recordable_result,
    resolve_group_path,
)
from .params import normalize_params
from .registry import DEFAULT_REGISTRY, FunctionRegistry
from .schema import Action, Parallel, Sequential, parse_workflow

if TYPE_CHECKING:  # the engine is store-free at runtime (IMP-007); the
    # wiring point in run_workflow / Test_Framework talks to the store
    # through its documented protocol (``_begin`` / ``wrap_registry``).
    from .artifacts import ArtifactStore

__all__ = [
    "ActionTimeoutError",
    "CapturedError",
    "Test_Framework",
    "WalkContext",
    "check_splice_scope",
    "run_python_workflow",
    "run_workflow",
]

_Node = Union[Action, Sequential, Parallel]
_Group = Union[Sequential, Parallel]


# --------------------------------------------------------------------------- #
# Dynamic adaptation: splice / scope check
# --------------------------------------------------------------------------- #


def check_splice_scope(
    parent: _Group | None,
    index: int,
    returned: Any,
) -> None:
    """
    Validate that a function's returned node(s) may be spliced into the
    workflow (paper section 4.2, dynamic adaptation).

    A function may return an ``Action`` / ``Sequential`` / ``Parallel`` node
    (or a list of them); the node(s) are spliced into the workflow in place
    of the action's NEXT SIBLING — a group (the paper's Listing 5) or an
    action (the paper's Listing 7 inner case: ``inner_action_1`` may alter
    ``inner_action_2``, which is an action).  The splice stays within the
    returning action's own grouping scope: an action may only alter what is
    downstream of it inside the group it belongs to, never siblings of that
    group.

    ``parent`` is the group containing the returning action, ``index`` is
    the action's position in ``parent.children``, and ``returned`` is the
    function's return value.

    Raises ``ValueError`` when the return value is a node (or list of nodes)
    but the action has no next sibling, or the parent is a ``Parallel``
    group (read-only parallel scopes: siblings may already be executing, so
    a splice there has no defined effect).  A plain (non-node) return value
    is always allowed.
    """
    nodes = _as_node_list(returned)
    if nodes is None:
        return
    if isinstance(parent, Parallel):
        raise ValueError(
            "dynamic adaptation: action returned workflow node(s) but runs "
            "inside a parallel scope, which is read-only; parallel siblings "
            "may already be executing, so the tree cannot be adapted here"
        )
    if parent is None or index + 1 >= len(parent.children):
        raise ValueError(
            "dynamic adaptation: action returned workflow node(s) but has no "
            "next sibling to splice them into; a splicing action must be "
            "followed by the group (or action) it adapts"
        )


def _mark_dynamic(node: _Node) -> None:
    """
    Mark ``node`` and its whole subtree as spliced in by dynamic adaptation.

    The flag is read by the history recording (an action's record carries
    ``dynamic=True`` when the action was not in the parsed workflow but was
    returned by an upstream function at runtime).  It is a plain attribute
    set, so it is inert when no history is requested.
    """
    node._engine_dynamic = True
    if isinstance(node, (Sequential, Parallel)):
        for child in node.children:
            _mark_dynamic(child)


def _as_node_list(returned: Any) -> list[_Node] | None:
    """
    Normalize a function's return value to a list of workflow nodes.

    Returns ``None`` when the value is a plain (non-node) result.  A single
    node is wrapped in a one-element list; a list/tuple must contain only
    nodes (anything else is a plain result and yields ``None``).
    """
    if isinstance(returned, (Action, Sequential, Parallel)):
        return [returned]
    if isinstance(returned, (list, tuple)):
        if returned and all(isinstance(item, (Action, Sequential, Parallel)) for item in returned):
            return list(returned)
    return None


# --------------------------------------------------------------------------- #
# Execution engine
# --------------------------------------------------------------------------- #


class _BaseExceptionCarrier(Exception):
    """
    Carries a ``BaseException`` (``KeyboardInterrupt`` / ``SystemExit``)
    raised by an action across the :class:`GraphFuture` boundary.

    ``GraphFuture._run`` only catches ``Exception``, so a ``BaseException``
    raised by an action would otherwise escape the worker thread WITHOUT
    settling the future — the parallel join (and any sequential wait) then
    blocks forever (finding 5a: a child raising ``KeyboardInterrupt``
    deadlocked the whole run).  The engine's action guard (see
    ``_submit_action``) converts such a ``BaseException`` into this carrier
    (an ``Exception``), which the future transports normally; the walker
    unwraps it (see ``run``) and re-raises the ORIGINAL ``BaseException``
    so the caller sees it — it is NOT swallowed.
    """

    def __init__(self, original: BaseException) -> None:
        super().__init__(f"action raised {type(original).__name__}: {original}")
        self.original = original


# Sentinel RESULT (not an exception) returned by the action guard when a
# sibling already failed under the fail-fast policy (finding 3e).  It is a
# result, not a future-exception, so it does not trip
# ``concurrent.futures.wait(FIRST_EXCEPTION)``; the walker treats it as
# "skipped" (no result, no error) — it is NOT a real failure, so it is
# never reported to the caller.
_SKIPPED = object()


class ActionTimeoutError(TimeoutError):
    """
    An action's function call exceeded the run's per-action timeout.

    Raised by :func:`run_workflow` / :func:`Test_Framework` when an action
    was still running after ``action_timeout`` seconds (the option's value
    is in the message).  Subclasses the builtin :class:`TimeoutError` so a
    caller catching ``TimeoutError`` (or ``OSError``) still matches, while
    carrying the action's name and the timeout that fired.

    The action's worker thread cannot be killed (Python threads are not
    killable), so the run abandons it: the pool is shut down without
    waiting for it and the process moves on.  See ``run_workflow``'s
    ``action_timeout`` documentation for the full semantics.
    """


class CapturedError(dict):
    """
    The result an action produces when its scope captures the exception
    (finding 3c: the per-scope ``on_error="capture"`` policy).

    A plain-data record, not an exception: inside a capture scope a failing
    action's RESULT is this object, so the failure flows through the data
    plane (downstream kwargs, group results, the final result) exactly like
    any other result — a V&V campaign treats a scenario failure as data,
    not a crash (paper P3: branch on failures).

    It is a ``dict`` so the whole existing driver vocabulary reads it
    unchanged: :func:`.library.retry` with ``on="error"`` recognizes the
    ``ok``/``error`` keys (the :func:`.library.try_action` outcome shape)
    and treats the capture as an unacceptable result to retry; ``guard`` /
    ``fallback`` / ``aggregate`` read fields from it like from any
    mapping.  The same fields are also exposed as attributes.

    Keys / attributes (all plain, comparable data):

    * ``is_error`` — always ``True``; the marker a downstream action or
      aggregate checks (``result["is_error"]``).
    * ``ok`` — always ``False``; the try_action-compatible success flag
      (so ``retry(on="error")`` and ``fallback(field="ok")`` work on a
      captured result without any change).
    * ``function`` — the failing action's registry name.
    * ``error_type`` — the exception's class name (e.g. ``"ValueError"``).
    * ``error`` — ``str()`` of the exception (the try_action key name).
    * ``timeout`` — ``True`` when the capture came from the per-action
      timeout (an :class:`ActionTimeoutError` raised by the engine's wait
      point, not by the action's own function); ``False`` otherwise.

    ``KeyboardInterrupt`` / ``SystemExit`` are NEVER captured (they are not
    ``Exception`` subclasses): control flow stays with the caller.
    """

    def __init__(
        self,
        function: str,
        error_type: str,
        message: str,
        timeout: bool = False,
    ) -> None:
        super().__init__(
            is_error=True,
            ok=False,
            function=function,
            error_type=error_type,
            error=str(message),
            timeout=timeout,
        )

    @property
    def is_error(self) -> bool:
        """The error marker: always ``True`` on a captured result."""
        return True

    @property
    def ok(self) -> bool:
        """The success flag: always ``False`` (try_action compatibility)."""
        return False

    @property
    def function(self) -> str:
        """The failing action's registry name."""
        return self["function"]

    @property
    def error_type(self) -> str:
        """The exception's class name."""
        return self["error_type"]

    @property
    def error(self) -> str:
        """``str()`` of the exception."""
        return self["error"]

    @property
    def timeout(self) -> bool:
        """Whether the capture came from the per-action timeout."""
        return self["timeout"]

    def __repr__(self) -> str:
        return (
            f"CapturedError(function={self['function']!r}, "
            f"error_type={self['error_type']!r}, error={self['error']!r}, "
            f"timeout={self['timeout']!r})"
        )


class WalkContext:
    """
    The per-action walk context: plain structural position data (IMP-007).

    The walk recursion holds every action's ancestry natively — it is
    where it is walking — so the engine hands it out as plain data
    instead of computing store-shaped facts.  A function (typically a
    registry wrapper, e.g. the artifact store's
    :meth:`~.artifacts.ArtifactStore.wrap_registry`) that declares a
    ``walk_context`` parameter receives one; the engine's involvement
    ends at the injection (the same shape of surface as the ``dag``
    injection).

    Fields:

    * ``node`` — the action node itself (its function name, parameters
      and engine flags are readable from it).
    * ``chain`` — the action's ancestry, root down, as a tuple of
      ``(group, index)`` pairs: each entry locates the next node on the
      path from the root to the action, and the LAST entry is the
      action's own parent and index.  ``chain[0][0]`` is always the root
      group.  Groups are live tree objects (the chain is a position
      descriptor, not a snapshot).

    Everything a structural consumer needs is derivable from
    ``(node, tree)`` at call time: an action's ancestry and left flank
    are frozen from submission until call completion (mutations come
    only from preceding siblings — done before submission — the action
    itself, or later siblings; concurrent branches mutate only their own
    subtrees; parallel scopes are read-only), which is the same
    sequential invariant that makes ``dag=`` writes safe.
    """

    __slots__ = ("node", "chain")

    def __init__(self, node: Action, chain: tuple[tuple[_Group, int], ...]) -> None:
        """Bind the context to ``node`` with its ancestry ``chain``."""
        self.node: Action = node
        self.chain: tuple[tuple[_Group, int], ...] = tuple(chain)

    def __repr__(self) -> str:
        """One-liner with the action's function name and ancestry depth."""
        return f"WalkContext({self.node.function!r}, depth={len(self.chain)})"


def _action_address(action: Action) -> str | None:
    """The action's minted address, or ``None`` (no store / not minted)."""
    return getattr(action, "_engine_address", None)


#: Bound on simultaneously-live parallel-branch threads (finding 5b).
#:
#: Group children of a ``Parallel`` scope each want their own walk thread;
#: without a bound, a deeply nested and wide campaign creates threads
#: MULTIPLICATIVELY (width ``W`` at depth ``D`` wants ~``W**D`` live
#: threads — an unattended runtime-sized campaign dies at the OS thread
#: limit).  Up to this many branch walks run on their own daemon thread
#: (fully concurrent, the historical behavior for every campaign that
#: fits); beyond the bound a branch's walk runs INLINE on its parent's
#: thread — the same runner and holder/error contract, just no new thread
#: — so overflow degrades to sequential branch execution instead of
#: resource exhaustion.  The acquire is deliberately NON-blocking: a
#: blocking acquire could wait on a slot a join-blocked parent holds
#: forever (deadlock).  Actions are unaffected: they run on the
#: :class:`GraphPool`, bounded by ``max_workers``.
BRANCH_THREAD_BOUND = 32


class _Engine:
    """
    Walk and run a workflow node tree on a :class:`GraphPool`.

    The engine is a lazy tree-walking interpreter: it does NOT pre-build a
    future graph.  Instead it walks the live tree — re-reading each group's
    ``children`` list every step, so nodes spliced in at runtime by dynamic
    adaptation are seen immediately — and executes each action on a pool
    worker thread through a :class:`GraphFuture` leaf.  A function that
    returns workflow node(s) has them spliced in place of the action's next
    sibling (a group); the replaced group is marked executed (its actions
    do not run), and the spliced group's results become the action's result.
    """

    def __init__(
        self,
        root: _Group,
        registry: FunctionRegistry,
        parameters: dict[str, Any] | None = None,
        history: RunHistory | None = None,
        *,
        source: str | None = None,
        params_mode: str = "full",
        max_workers: int | None = None,
        adaptation_bound: int | None = None,
        executor: GraphPool | None = None,
        dry_run: bool = False,
        action_timeout: float | None = None,
        fail_fast: bool = False,
    ) -> None:
        """Create an engine for ``root``; the keyword options mirror ``run_workflow``'s."""
        self._registry = registry
        self._globals: dict[str, Any] = dict(root.globals)
        if parameters:
            self._globals.update(parameters)
        self._root = root
        self._lock = threading.Lock()
        self._pool: GraphPool | None = None
        # Bounded adaptation (decision D5): the engine counts dynamic nodes
        # added by handle commits; exceeding the bound raises a
        # deterministic ValueError (a runaway adaptation terminates).
        self._dynamic_count = 0
        self._adaptation_bound = (
            ADAPTATION_BOUND if adaptation_bound is None else adaptation_bound
        )
        if self._adaptation_bound < 0:
            raise ValueError(
                f"adaptation bound must be >= 0, got {adaptation_bound}"
            )
        # Opt-in execution history (None = record nothing; the engine then
        # behaves exactly as if this feature did not exist).
        self._history = history
        # Run identity (IMP-011): the workflow digest stamped on the history
        # at run start (None only when no history was requested).
        self._source = source
        if params_mode not in ("full", "summary"):
            raise ValueError(
                f"unknown params_mode {params_mode!r} (expected 'full' or 'summary')"
            )
        # The recorded-params shape ("full" keeps the resolved kwargs as
        # before; "summary" records bulk payloads as their item counts —
        # the call itself is unchanged).
        self._params_mode = params_mode
        self._max_workers = max_workers
        # A caller-supplied pool wins over ``max_workers`` and is NOT shut
        # down at run end (it stays owned by the caller).
        self._executor = executor
        # Plan mode (IMP-013): the walk runs with no-op functions, so nothing
        # executes and nothing is spliced or adapted; the tree is the result.
        self._dry_run = dry_run
        # Per-action wall-clock timeout (finding 3d): None = no timeout
        # (the historical behavior — a hung action blocks its worker).  A
        # positive number bounds every action's function call; expiry
        # raises ActionTimeoutError naming the action.
        if action_timeout is not None and action_timeout <= 0:
            raise ValueError(
                f"action_timeout must be > 0 seconds or None, got {action_timeout}"
            )
        self._action_timeout = action_timeout
        # First action-timeout error observed in this run (first-wins): the
        # walk unwinds through sibling waits, which re-raise THIS error so
        # the caller sees one clear cause instead of a cascade of secondary
        # timeouts from actions that were merely downstream of the hang.
        self._timeout_error: ActionTimeoutError | None = None
        # Fail-fast policy (finding 3e): when True, a parallel group stops
        # waiting as soon as one child fails — not-yet-started siblings are
        # cancelled and the first error is raised promptly instead of after
        # every sibling has settled.  False (the default) keeps the
        # historical drain-then-report behavior.
        self._fail_fast = fail_fast
        # Set when a fail-fast run abandons in-flight siblings: the pool is
        # then torn down WITHOUT waiting for the abandoned workers (a thread
        # cannot be killed), exactly like the action-timeout path.
        self._abandoned_workers = False
        # Run-level abort signal for the fail-fast policy (finding 3e): set
        # the moment any action fails, so not-yet-run siblings (queued
        # behind the pool) skip their function call instead of doing work.
        # Inert unless ``fail_fast`` is True.
        self._fail_fast_abort = threading.Event()
        # Branch-thread bound (finding 5b): up to BRANCH_THREAD_BOUND
        # parallel-branch walks run on their own daemon thread; beyond
        # that the walk runs inline on its parent's thread (see
        # ``_walk_parallel``).  The acquire is non-blocking, so a
        # slot-holding parent never waits on a slot a child needs.
        self._branch_slots = threading.Semaphore(BRANCH_THREAD_BOUND)

    # ------------------------------------------------------------ #
    # Public entry point
    # ------------------------------------------------------------ #
    def run(self) -> Any:
        """
        Execute the workflow and return the final result.

        The final result is the result of the last action in the root
        group's execution order (the last child, resolved recursively into
        groups).  Raises ``ValueError`` for an unknown function name or an
        out-of-scope splice attempt, and propagates any exception raised by
        a function.
        """
        pool = (
            self._executor
            if self._executor is not None
            else GraphPool(
                max_workers=16 if self._max_workers is None else self._max_workers
            )
        )
        owned = self._executor is None
        self._pool = pool
        try:
            if self._history is not None:
                # Run identity (IMP-011): the workflow digest, stamped at run
                # start (the history's ``run_id`` was created with it).
                self._history.source = self._source
                # The recorded-params shape the run actually used (the
                # history's default is "full"; the run's option wins).
                self._history.params_mode = self._params_mode
            # Eager validation: every action's function name must resolve
            # BEFORE any execution starts (parity with the old build pass).
            self._validate_node(self._root)
            try:
                self._walk_group(self._root, [], ())
            except _BaseExceptionCarrier as carrier:
                # An action raised a BaseException (KeyboardInterrupt /
                # SystemExit): the action guard carried it across the
                # GraphFuture boundary (finding 5a) — re-raise the ORIGINAL
                # so the caller sees it, not the transport wrapper.
                raise carrier.original
            if self._dry_run:
                # Plan mode: the walk ran with no-op functions, so there is no
                # final result to resolve — the effective plan tree (the tree
                # as it stood at the end of the walk) is the return value.
                return self._root
            # The tree may have been spliced during execution, so the final
            # action is resolved AFTER the run (the last child of the root,
            # resolved recursively into groups).
            final_action = self._final_action(self._root)
            if final_action is None:
                return None
            result = final_action._engine_result
            if self._history is not None:
                self._mark_final(final_action)
            return result
        finally:
            self._pool = None
            if owned:
                if self._timeout_error is not None or self._abandoned_workers:
                    # A per-action timeout fired, or a fail-fast run
                    # abandoned in-flight siblings: at least one worker is
                    # still inside a function call, and a thread cannot be
                    # killed — so the pool is shut down WITHOUT waiting
                    # for it (pending nodes are cancelled, the abandoned
                    # workers finish on their own).  GraphPool's
                    # context-manager exit blocks on running workers, which
                    # is exactly the deadlock this option exists to break.
                    pool._shutdown = True
                    for node in list(_LIVE_NODES):
                        if not node.future.done():
                            node.future.cancel()
                    if pool._executor is not None:
                        pool._executor.shutdown(wait=False, cancel_futures=True)
                        pool._executor = None
                else:
                    # An engine-owned pool is shut down here (the
                    # with-statement equivalent); a caller-supplied executor
                    # stays owned by the caller and is NOT shut down.
                    pool.__exit__(None, None, None)

    # ------------------------------------------------------------ #
    # Pre-validation (eager unknown-function errors)
    # ------------------------------------------------------------ #
    def _validate_node(self, node: _Node) -> None:
        """Resolve every action's function name in ``node``'s subtree."""
        if isinstance(node, Action):
            self._registry.get(node.function)
            return
        for child in node.children:
            self._validate_node(child)

    # ------------------------------------------------------------ #
    # Tree walking (the lazy interpreter core)
    # ------------------------------------------------------------ #
    def _walk_group(
        self, group: _Group, pairs: list, ancestry: tuple[tuple[_Group, int], ...]
    ) -> tuple[Any, list]:
        """
        Walk ``group`` (sequential or parallel) seeded with ``pairs``.

        Returns ``(group result, direct pairs)`` where ``direct pairs``
        are the ``(action, result)`` pairs of the group's DIRECT action
        children (one-level flattening, matching the old engine's fan-in
        chain: a group contributes its direct children's futures to the
        chain, and only action futures carry results into keyword
        arguments).

        ``ancestry`` is ``group``'s own root-down chain of
        ``(parent, index)`` pairs (``()`` for the root walk); each child
        the walk reaches gets ``ancestry + ((group, i),)`` — the walk
        recursion holds every action's position natively, which is what
        the injected walk context is derived from.
        """
        if isinstance(group, Sequential):
            return self._walk_sequential(group, pairs, ancestry)
        return self._walk_parallel(group, pairs, ancestry)

    def _walk_sequential(
        self, group: Sequential, pairs: list, ancestry: tuple[tuple[_Group, int], ...]
    ) -> tuple[Any, list]:
        """
        Walk a ``Sequential`` group: strict child order.

        The live ``children`` list is RE-READ every step (``while i < len``),
        so nodes spliced in at runtime are picked up immediately.  Each
        action contributes its own ``(action, result)`` pair to the local
        chain; a group child contributes its direct action children's pairs
        (one-level flattening).  Children already executed (replaced by a
        splice) are skipped without adding pairs.
        """
        chain: list = list(pairs)
        direct: list = []
        i = 0
        while i < len(group.children):
            child = group.children[i]
            if getattr(child, "_engine_executed", False):
                # Replaced by a runtime splice: its actions already ran (or
                # never will); it contributes neither a result nor a pair.
                i += 1
                continue
            if isinstance(child, Action):
                future = self._submit_action(child, chain, ancestry + ((group, i),))
                try:
                    raw = self._wait_action(child, future)
                except Exception as exc:
                    # Per-scope error capture (finding 3c): inside a
                    # ``on_error="capture"`` scope the action's failure
                    # becomes its RESULT (a CapturedError record) instead
                    # of failing the run — the walk continues.  Retry /
                    # fallback drivers (if any) already ran inside the
                    # function call: capture is the LAST resort, after
                    # them.  A timeout raised by the engine's own wait
                    # point composes the same way (``timeout=True``).
                    captured = self._capture_for(group, child, exc)
                    if captured is None:
                        raise
                    raw = captured
                result = self._handle_result(child, group, i, raw, chain, ancestry)
                chain.append((child, result))
                direct.append((child, result))
            else:
                _, child_direct = self._walk_group(child, chain, ancestry + ((group, i),))
                chain.extend(child_direct)
            i += 1
        return self._group_result(group), direct

    def _walk_parallel(
        self, group: Parallel, pairs: list, ancestry: tuple[tuple[_Group, int], ...]
    ) -> tuple[Any, list]:
        """
        Walk a ``Parallel`` group: independent, concurrent children.

        The children are SNAPSHOTTED once (a parallel group's children are
        independent, so the walk does not re-read the list).  ACTION children
        are submitted as :class:`GraphFuture` leaves on the pool; GROUP
        children run on their own daemon thread while the engine is within
        ``BRANCH_THREAD_BOUND`` live branch threads, and INLINE on the
        parent's thread beyond that bound (never on pool workers — a walk
        task occupying a worker could starve the pool and deadlock).
        All action futures are wired at once through a single join future
        (``pool.result`` on the join — the wire-then-wait pattern), and the
        first exception in child order is raised.  Two policies then govern
        the wait (the run option ``fail_fast``):

        * ``fail_fast=False`` (the default) — DRAIN-THEN-REPORT: the join
          is awaited (every action settles), the threads are joined, and
          the first exception in child order is raised after every child
          has settled.
        * ``fail_fast=True`` — FAIL-FAST: the group stops waiting as soon
          as one action fails (``_await_fail_fast``); not-yet-started
          siblings skip their function call via the run-level abort event
          (a queued action costs nothing), in-flight ones are abandoned
          (a thread cannot be killed — the pool is torn down without
          waiting for them), and the first error is raised promptly
          instead of after every sibling has settled.

        The information barrier is structural: every child is submitted
        with the SAME pre-group upstream pairs (siblings never see each
        other, exactly as they never see each other's results), and each
        branch group child is walked with its own ancestry below the
        group — on its own thread within the branch-thread bound, inline
        beyond it (the barrier is the walk's pair seeding, not the
        thread it runs on).
        """
        children = list(group.children)
        upstream = list(pairs)
        submitted: list[tuple[int, Action, GraphFuture]] = []
        threads: list[tuple[int, threading.Thread, dict]] = []
        # Wire every action leaf FIRST (in child order, matching the old
        # engine's build order), then start the group-child threads: the
        # pool's FIFO then runs the actions in the same order the old
        # engine submitted them.
        for position, child in enumerate(children):
            if getattr(child, "_engine_executed", False):
                continue
            if isinstance(child, Action):
                child_ancestry = ancestry + ((group, position),)
                future = self._submit_action(child, upstream, child_ancestry)
                submitted.append((position, child, future))
        if submitted:
            # Wire-then-wait: bind the whole graph (submitting every leaf)
            # with a zero-timeout probe that never blocks on a result.
            probe = GraphFuture(_join_results, *[f for _, _, f in submitted])
            try:
                self._pool.result(probe, timeout=0)
            except concurrent.futures.TimeoutError:
                pass
        for position, child in enumerate(children):
            if getattr(child, "_engine_executed", False) or isinstance(child, Action):
                continue
            holder: dict = {}
            # Branch-thread bound (finding 5b): a slot means the branch's
            # walk runs on its own daemon thread (fully concurrent); no
            # slot means it runs INLINE on THIS thread — the same runner
            # and holder/error contract, just no new thread.  The acquire
            # is non-blocking by design: a blocking acquire could wait on
            # a slot held by a join-blocked parent (deadlock), while the
            # inline fallback bounds live threads at
            # BRANCH_THREAD_BOUND without ever blocking.
            if self._branch_slots.acquire(blocking=False):
                thread = threading.Thread(
                    target=self._walk_child_thread,
                    args=(
                        child,
                        upstream,
                        holder,
                        ancestry + ((group, position),),
                        True,
                    ),
                    daemon=True,
                )
                threads.append((position, thread, holder))
                thread.start()
            else:
                # Over the bound: run the branch's walk inline (the runner
                # releases the slot only when it OWNS one — this inline
                # call does not, so the release stays balanced).
                self._walk_child_thread(
                    child, upstream, holder, ancestry + ((group, position),)
                )
                threads.append((position, None, holder))
        results: list[Any] = [None] * len(children)
        errors: list[tuple[int, BaseException]] = []
        # Per-scope error capture (finding 3c) composes with fail_fast by
        # degrading THIS group's wait to the drain: a captured failure is a
        # result, not an error, so there is nothing to fail fast on —
        # abandoning the not-yet-settled siblings (the fail-fast contract)
        # would drop results the capture policy just promised to keep.
        # The guard already refrains from setting the abort event for a
        # failure this scope will capture, so queued siblings run too.
        capturing = getattr(group, "on_error", None) == "capture"
        if submitted:
            if self._fail_fast and not capturing:
                # Fail-fast (finding 3e): raise the first action error
                # promptly, abandoning the in-flight siblings (their queued
                # actions skip via the abort event; running ones finish in
                # the background — a thread cannot be killed).
                self._await_fail_fast(
                    submitted, results, errors, group, upstream, ancestry
                )
                if errors:
                    self._abandoned_workers = True
                    for _, exc in sorted(errors, key=lambda item: item[0]):
                        raise exc
            else:
                join = GraphFuture(_join_results, *[f for _, _, f in submitted])
                try:
                    self._await_join(join, submitted)
                except Exception:
                    # The join settles once every dependency has settled —
                    # EXCEPT under a per-action timeout, where a hung child
                    # abandons its future and the join never settles.  The
                    # per-future loop below then reports the recorded timeout
                    # at the hung action's position (its guard replaces a
                    # blocking wait); otherwise the result() calls there are
                    # non-blocking and the first in-order failure is
                    # re-raised after all children (threads included) have
                    # settled.
                    pass
                for position, action, future in submitted:
                    try:
                        if (
                            self._timeout_error is not None
                            and not future.done()
                        ):
                            # A sibling's timeout already fired and this
                            # future is still unsettled (hung or abandoned):
                            # report the recorded error at this action's
                            # position instead of blocking forever on its
                            # result.
                            self._raise_recorded_timeout()
                        raw = future.result()
                        if raw is _SKIPPED:
                            # Fail-fast skip: a sibling already failed and
                            # this queued action never ran its function —
                            # no result, no error, no pair.  (Defensive:
                            # with ``fail_fast`` off the guard never skips,
                            # so the drain branch cannot see the sentinel.)
                            continue
                        results[position] = self._handle_result(
                            action, group, position, raw, upstream, ancestry
                        )
                    except BaseException as exc:
                        # BaseException (matching _walk_child_thread): a
                        # KeyboardInterrupt from an action is collected too,
                        # so every child still settles, and the first failure
                        # in child order is re-raised below.
                        captured = self._capture_for(group, action, exc)
                        if captured is not None:
                            # Per-scope error capture (finding 3c): the
                            # sibling's failure is its result, not the
                            # group's error — the drain continues.
                            results[position] = self._handle_result(
                                action, group, position, captured, upstream, ancestry
                            )
                            continue
                        errors.append((position, exc))
        for _, thread, _ in threads:
            if thread is not None:
                thread.join()
        for position, _thread, holder in threads:
            if "error" in holder:
                errors.append((position, holder["error"]))
            else:
                results[position] = holder.get("result")
        for _, exc in sorted(errors, key=lambda item: item[0]):
            raise exc
        direct = [
            (child, child._engine_result)
            for child in children
            if isinstance(child, Action)
            and not getattr(child, "_engine_executed", False)
            # A skipped sibling (fail-fast) produced no result: it is not
            # a data-plane pair (the sentinel never reaches downstream
            # kwargs), and neither is an action that was never handled.
            and getattr(child, "_engine_result", _SKIPPED) is not _SKIPPED
        ]
        return results, direct

    def _walk_child_thread(
        self,
        child: _Group,
        upstream: list,
        holder: dict,
        ancestry: tuple[tuple[_Group, int], ...],
        owns_slot: bool = False,
    ) -> None:
        """
        Run a parallel group child's walk; capture its outcome in ``holder``.

        The child's walk growth (direct pairs) stays INSIDE the branch: a
        parallel branch is an information barrier, so nothing it
        accumulated reaches the group's siblings or downstream.

        The runner runs on its own daemon thread when a branch-thread slot
        was available (``owns_slot=True``; the slot is released when the
        walk settles — see ``BRANCH_THREAD_BOUND``), or INLINE on the
        parent's thread when the engine is over the bound (``owns_slot=
        False``; no slot is taken or released).  The two paths share this
        one runner, so the holder/error contract is identical either way.
        """
        try:
            holder["result"], _direct = self._walk_group(child, list(upstream), ancestry)
        except BaseException as exc:  # re-raised in child order by the walker
            holder["error"] = exc
        finally:
            if owns_slot:
                self._branch_slots.release()

    def _walk_spliced(
        self,
        parent: _Group,
        nodes: list,
        upstream: list,
        ancestry: tuple[tuple[_Group, int], ...],
    ) -> list:
        """
        Walk nodes spliced in by dynamic adaptation (the nested walk).

        Mirrors the old engine's temporary ``Sequential(*nodes)`` group: the
        nodes are walked in order with a local chain seeded from the actor's
        upstream pairs (a group node contributes its direct action children's
        pairs to that chain), and the actor's runtime result is the ordered
        list of the nodes' results.  Nodes replaced by a NESTED splice are
        skipped (they were marked executed by the nested surgery).

        Spliced siblings are real siblings: each is walked with its live
        position in ``parent`` (its ancestry is the parent walk's own
        ancestry plus that position), so whatever a structural consumer
        derives for it matches the parent's other children.
        """
        chain: list = list(upstream)
        results: list = []
        for node in nodes:
            if getattr(node, "_engine_executed", False):
                results.append(None)
                continue
            position = self._position_of(parent, node)
            if position < 0:
                # No longer in the live tree (replaced by a nested splice).
                results.append(None)
                continue
            if isinstance(node, Action):
                future = self._submit_action(node, chain, ancestry + ((parent, position),))
                try:
                    raw = self._wait_action(node, future)
                except Exception as exc:
                    # Per-scope error capture (finding 3c), same rule as
                    # the sequential walk: the spliced node's parent scope
                    # decides, and a capture becomes the node's result.
                    captured = self._capture_for(parent, node, exc)
                    if captured is None:
                        raise
                    raw = captured
                result = self._handle_result(node, parent, position, raw, chain, ancestry)
                chain.append((node, result))
                results.append(result)
            else:
                result, child_direct = self._walk_group(
                    node, chain, ancestry + ((parent, position),)
                )
                chain.extend(child_direct)
                results.append(result)
        return results

    def _group_result(self, group: _Group) -> Any:
        """A sequential group's result: the ordered list of its children's results."""
        return [self._child_result(child) for child in group.children
                if not getattr(child, "_engine_executed", False)]

    def _child_result(self, child: _Node) -> Any:
        """A child's contribution to its group's result list (recursive)."""
        if isinstance(child, Action):
            return child._engine_result
        return self._group_result(child)

    def _position_of(self, parent: _Group, node: _Node) -> int:
        """The live index of ``node`` in ``parent.children`` (-1 if absent)."""
        for i, child in enumerate(parent.children):
            if child is node:
                return i
        return -1

    # ------------------------------------------------------------ #
    # Action execution (every action runs on a pool worker)
    # ------------------------------------------------------------ #
    def _submit_action(
        self, action: Action, upstream: list, ancestry: tuple[tuple[_Group, int], ...]
    ) -> GraphFuture:
        """
        Submit one action's function call as a :class:`GraphFuture` leaf.

        The upstream pairs are passed as positional arguments so the future
        registers them as dependencies (strict ordering); the corresponding
        actions are passed separately for result keying.  The function call
        itself runs on a pool worker thread.

        ``ancestry`` is the action's own root-down chain (the walk's
        ancestry plus its position in the group).  When the callee declares
        a ``walk_context`` parameter (the registry's cached flag), it is
        bound into a :class:`WalkContext` and handed to the call — plain
        position data the callee derives from (the artifact store's
        registry wrapping does exactly that; the engine itself keeps no
        addressing state).
        """
        fn = self._registry.get(action.function)
        params = normalize_params(action.params)
        actions = [act for act, _ in upstream]
        context = (
            WalkContext(action, ancestry)
            if self._registry.wants_context(action.function)
            else None
        )
        # Per-scope error capture (finding 3c): the action's PARENT scope
        # decides whether a failure is captured (a result) or fatal.  The
        # guard runs on the worker thread, before the walker can decide,
        # so the policy travels with the call — a captured failure must
        # not trip the fail-fast abort (it is a result, not an error).
        capture = getattr(ancestry[-1][0], "on_error", None) if ancestry else None
        return GraphFuture(
            self._guarded_action,
            *[result for _, result in upstream],
            fn=fn,
            params=params,
            actions=actions,
            action=action,
            context=context,
            capture=capture,
        )

    def _guarded_action(
        self,
        *upstream_results: Any,
        fn: Callable[..., Any],
        params: dict[str, Any],
        actions: list[Action | None],
        action: Action,
        context: WalkContext | None = None,
        capture: str | None = None,
    ) -> Any:
        """
        The action guard: run ``_run_action`` with two engine-level policies.

        * **Fail-fast skip (finding 3e)** — when ``fail_fast`` is on and a
          sibling has already failed (the run-level abort event is set), a
          not-yet-run action returns the ``_SKIPPED`` sentinel instead of
          calling its function: the campaign stops paying for siblings
          after the first failure.  Inert unless ``fail_fast`` is True.
        * **BaseException carriage (finding 5a)** — ``GraphFuture._run``
          only catches ``Exception``, so a ``KeyboardInterrupt`` /
          ``SystemExit`` raised by an action would escape the worker
          WITHOUT settling the future, deadlocking the join (and any
          sequential wait).  The guard converts such a ``BaseException``
          into a :class:`_BaseExceptionCarrier` (an ``Exception``) that the
          future transports normally; the walker unwraps it and re-raises
          the original.

        On a real failure the guard sets the abort event (fail-fast only)
        so the remaining queued siblings skip.
        """
        if self._fail_fast and self._fail_fast_abort.is_set():
            return _SKIPPED
        try:
            return self._run_action(
                *upstream_results,
                fn=fn,
                params=params,
                actions=actions,
                action=action,
                context=context,
            )
        except BaseException as exc:
            if self._fail_fast and not (
                capture == "capture" and isinstance(exc, Exception)
            ):
                # Fail-fast abort — but NOT for a failure the action's
                # scope will capture (finding 3c): a captured failure is
                # a result, not an error, so siblings must not skip.
                self._fail_fast_abort.set()
            if not isinstance(exc, Exception):
                # KeyboardInterrupt / SystemExit: carry across the future
                # boundary (finding 5a) — the walker re-raises the original.
                raise _BaseExceptionCarrier(exc) from exc
            raise

    # ------------------------------------------------------------ #
    # Per-action timeout (finding 3d)
    # ------------------------------------------------------------ #
    def _wait_action(self, action: Action, future: GraphFuture) -> Any:
        """
        Wait for one action's result, honoring the run's per-action timeout.

        This is the engine's wait point for a sequential or spliced action
        (``pool.result`` without a timeout would block forever on a hung
        function — the unattended-campaign deadlock of finding 3d).  With
        ``action_timeout=None`` (the default) the wait is unbounded, so the
        behavior is exactly the historical one.

        The budget is measured from the action's worker-side start stamp
        (``_engine_started``, set in ``_run_action``), not from submission:
        an action queued behind others in a campaign larger than the pool
        still gets its full per-action budget once it starts.  An action
        that has not STARTED within one budget of waiting also fails: the
        pool is then saturated (every worker inside a call that outlived
        its own budget), so the campaign cannot proceed and an unattended
        run must fail loudly rather than wait forever.

        On expiry the still-running function is ABANDONED, not killed: a
        Python thread cannot be killed, and :class:`GraphPool`'s
        cancellation only reaches futures that have not started (its
        ``__exit__`` cancels pending nodes but then BLOCKS on running
        workers — the very deadlock this option exists to break).  The
        engine records the error, lets the walk unwind, and tears its own
        pool down without waiting (see ``run``).  Sibling waits re-raise
        the recorded error so the caller sees one clear cause.
        """
        if self._action_timeout is None:
            return self._pool.result(future)
        if self._timeout_error is not None:
            # A sibling already timed out: unwind instead of waiting (and
            # possibly timing out again) on this action.
            self._raise_recorded_timeout()
        wait_start = time.monotonic()
        while True:
            started = getattr(action, "_engine_started", None)
            if started is None:
                # Not started yet: one full budget for it to start in.
                remaining = self._action_timeout - (time.monotonic() - wait_start)
            else:
                remaining = self._action_timeout - (time.monotonic() - started)
            if remaining <= 0:
                raise self._action_timed_out(action) from None
            try:
                return self._pool.result(future, timeout=remaining)
            except concurrent.futures.TimeoutError:
                if future.done():
                    # Settled in the race window between expiry and the
                    # exception surfacing: return the settled outcome.
                    return future.result()
                # Not settled: re-evaluate the budget (an action that
                # started late still has budget left; the loop is bounded
                # because every round consumes wall-clock time).

    def _await_join(self, join: GraphFuture, submitted: list) -> Any:
        """
        Wait for a parallel group's join future under the per-action timeout.

        The join settles only when EVERY submitted action has settled, so
        an unbounded wait would hang the whole group on one hung sibling —
        the parallel form of the finding-3d deadlock.  The wait is a
        deadline loop: each round waits only until the SOONEST expiry
        among the group's still-unsettled actions (execution-based for
        started actions, one budget from the wait's start for queued
        ones — the same rule as ``_wait_action``), and the first action
        past its deadline is named in the raised error.  With
        ``action_timeout=None`` the wait is unbounded (historical
        behavior).
        """
        if self._action_timeout is None:
            return self._pool.result(join)
        if self._timeout_error is not None:
            self._raise_recorded_timeout()
        wait_start = time.monotonic()

        def _deadline(action: Action, future: GraphFuture) -> float | None:
            """This action's expiry (monotonic), or None once settled."""
            if future.done():
                return None
            started = getattr(action, "_engine_started", None)
            if started is None:
                return wait_start + self._action_timeout
            return started + self._action_timeout

        while True:
            now = time.monotonic()
            for _position, action, future in submitted:
                deadline = _deadline(action, future)
                if deadline is not None and deadline <= now:
                    raise self._action_timed_out(action) from None
            remaining = self._action_timeout
            for _position, action, future in submitted:
                deadline = _deadline(action, future)
                if deadline is not None and deadline - now < remaining:
                    remaining = deadline - now
            if remaining <= 0:
                # An expiry just passed between the scan and here; the
                # next scan raises for it (bounded: the scan is re-run).
                continue
            try:
                return self._pool.result(join, timeout=remaining)
            except concurrent.futures.TimeoutError:
                # Re-scan: a settled action may have unblocked the join, an
                # expired one raises, and a late starter gets a new budget.
                continue

    def _await_fail_fast(
        self,
        submitted: list,
        results: list,
        errors: list,
        group: Parallel,
        upstream: list,
        ancestry: tuple[tuple[_Group, int], ...],
    ) -> None:
        """
        Wait for a parallel group's actions ONLY until the first failure
        (finding 3e: after one sibling fails, the campaign must not pay
        for the remaining ones).

        This is the fail-fast sibling of ``_await_join``: instead of waiting
        for the group's join (every action settled), the wait is
        ``concurrent.futures.wait(FIRST_EXCEPTION)`` over the group's action
        futures — it returns as soon as one action FAILS, or once every
        action has settled (the no-failure case: the same total wait as the
        drain).  A skipped sibling's ``_SKIPPED`` is a result, not an
        exception, so it never trips the wait.  Settled futures are then
        collected exactly like the drain branch (``_handle_result`` per
        success — history records and splices still finalize — and one
        ``(position, exc)`` per failure); not-yet-settled siblings are left
        behind: their queued nodes skip via the run-level abort event (a
        queued action costs nothing), running ones finish in the background
        (a thread cannot be killed), and the caller marks the run as having
        abandoned workers so the pool is torn down without waiting for them
        (see ``run``).  The caller raises the first error in child order.

        Composes with ``action_timeout``: the wait is a deadline loop with
        the same rule as ``_await_join`` (execution-based deadlines for
        started actions, one budget from the wait's start for queued ones),
        and the first action past its deadline raises
        :class:`ActionTimeoutError` — a timed-out action is an error like
        any other, and the first error in time wins.
        """
        raw_futures = [future.future for _, _, future in submitted]
        if self._action_timeout is None:
            # One blocking wait: FIRST_EXCEPTION returns as soon as one
            # action fails, or once every action has settled.
            concurrent.futures.wait(
                raw_futures, return_when=concurrent.futures.FIRST_EXCEPTION
            )
        else:
            if self._timeout_error is not None:
                self._raise_recorded_timeout()
            wait_start = time.monotonic()

            def _deadline(action: Action, future: GraphFuture) -> float | None:
                """This action's expiry (monotonic), or None once settled."""
                if future.done():
                    return None
                started = getattr(action, "_engine_started", None)
                if started is None:
                    return wait_start + self._action_timeout
                return started + self._action_timeout

            while True:
                if all(future.done() for _, _, future in submitted):
                    break
                now = time.monotonic()
                for _position, action, future in submitted:
                    deadline = _deadline(action, future)
                    if deadline is not None and deadline <= now:
                        raise self._action_timed_out(action) from None
                remaining = self._action_timeout
                for _position, action, future in submitted:
                    deadline = _deadline(action, future)
                    if deadline is not None and deadline - now < remaining:
                        remaining = deadline - now
                if remaining <= 0:
                    # An expiry just passed between the scan and here; the
                    # next scan raises for it (bounded: the scan is re-run).
                    continue
                concurrent.futures.wait(
                    raw_futures,
                    timeout=remaining,
                    return_when=concurrent.futures.FIRST_EXCEPTION,
                )
                if any(
                    future.done()
                    and not future.cancelled()
                    and future.exception() is not None
                    for _, _, future in submitted
                ):
                    # A sibling failed (now or while this round waited):
                    # stop waiting — the first error in time wins, even if
                    # another sibling's deadline has not expired yet.
                    break
                # Re-scan: a settled action may have unblocked the wait, an
                # expired one raises, and a late starter gets a new budget.
        for position, action, future in submitted:
            if not future.done():
                # Not-yet-settled sibling: left behind (its queued node
                # skips via the abort event; a running one finishes in the
                # background — the caller marks the run as having abandoned
                # workers, so the pool is torn down without waiting).
                continue
            try:
                raw = future.result()
                if raw is not _SKIPPED:
                    results[position] = self._handle_result(
                        action, group, position, raw, upstream, ancestry
                    )
            except BaseException as exc:
                # BaseException (matching the drain branch): a
                # KeyboardInterrupt arrives as a ``_BaseExceptionCarrier``
                # and is collected like any error — the caller re-raises it
                # in child order and ``run`` unwraps the carrier.
                captured = self._capture_for(group, action, exc)
                if captured is not None:
                    # Per-scope error capture (finding 3c): the failure is
                    # the sibling's result; fail-fast keeps waiting for the
                    # remaining settled siblings, then returns normally.
                    results[position] = self._handle_result(
                        action, group, position, captured, upstream, ancestry
                    )
                    continue
                errors.append((position, exc))

    def _capture_for(
        self, group: _Group, action: Action, exc: BaseException
    ) -> CapturedError | None:
        """
        Decide whether ``group``'s error policy captures ``exc`` (finding 3c).

        Returns the :class:`CapturedError` record that becomes the action's
        RESULT when the scope declares ``on_error="capture"`` and the
        exception is an ordinary failure (an ``Exception``; a
        ``KeyboardInterrupt`` / ``SystemExit`` — or the
        ``_BaseExceptionCarrier`` transporting one — is never captured:
        control flow belongs to the caller).  Returns ``None`` otherwise
        (the default policy: the exception propagates and the run fails).

        Composition rules (documented in ``run_workflow``):

        * retry / fallback — they are library drivers that run INSIDE the
          action's function call, so they have already exhausted themselves
          by the time the exception reaches the engine: capture is the
          last resort, after them.
        * ``action_timeout`` — a timeout raised by the engine's own wait
          point (``ActionTimeoutError``) is captured like any other
          failure, with ``timeout=True`` on the record.  The hung worker
          is abandoned exactly as without capture (a thread cannot be
          killed); only the run's outcome changes.
        * ``fail_fast`` — capture wins over the abort: a captured failure
          is a result, not an error, so it never sets the abort event and
          never skips siblings (the guard only sets the event on a
          failure that will propagate).
        """
        if getattr(group, "on_error", None) != "capture":
            return None
        if isinstance(exc, _BaseExceptionCarrier) or not isinstance(exc, Exception):
            return None
        if isinstance(exc, ActionTimeoutError) and self._timeout_error is not None:
            # Timeout composition (finding 3c + 3d): the captured timeout
            # becomes this action's result, so the run-level unwind signal
            # must be cleared — otherwise sibling waits would re-raise the
            # recorded error (``_raise_recorded_timeout``) and the capture
            # would be undone one wait later.  The hung worker itself is
            # still abandoned (a thread cannot be killed); only the run's
            # outcome changes.  First-wins is preserved: a timeout that is
            # NOT captured keeps its recorded error.
            self._timeout_error = None
        return CapturedError(
            function=action.function,
            error_type=type(exc).__name__,
            message=str(exc),
            timeout=isinstance(exc, ActionTimeoutError),
        )

    def _action_timed_out(self, action: Action) -> ActionTimeoutError:
        """
        Build (and record, first-wins) the timeout error for ``action``.

        The message names the action, the timeout and the option, and how
        long the function had actually been executing, so an unattended
        campaign's log says exactly which simulator call hung and under
        which setting.
        """
        started = getattr(action, "_engine_started", None)
        elapsed = time.monotonic() - started if started is not None else None
        error = ActionTimeoutError(
            f"action {action.function!r} timed out: its function call did not "
            f"finish within the per-action timeout of {self._action_timeout} "
            f"seconds (run option 'action_timeout')"
            + (
                f" after {elapsed:.3f} seconds of execution"
                if elapsed is not None
                else ""
            )
        )
        if self._timeout_error is None:
            self._timeout_error = error
        return error

    def _raise_recorded_timeout(self) -> NoReturn:
        """Re-raise the run's recorded timeout error (sibling-wait unwind)."""
        raise self._timeout_error from None

    def _handle_result(
        self,
        action: Action,
        parent: _Group,
        index: int,
        raw: Any,
        upstream: list,
        ancestry: tuple[tuple[_Group, int], ...],
    ) -> Any:
        """
        Settle an action's raw result on the WALKER thread.

        A plain result is stored and returned.  A node-list result is a
        dynamic-adaptation splice: the scope is checked, the replaced group
        is marked executed, the returned nodes are spliced into the live
        tree and walked (nested sequential walk seeded with the actor's
        upstream pairs), and the actor's runtime result becomes the ordered
        list of the spliced nodes' results.  Splice handling runs on the
        walker thread (never inside a pool worker) so a nested walk can
        submit to the pool without starving it.

        The spliced walk shares the parent walk's ``ancestry`` — spliced
        siblings are real siblings — so each spliced node is walked at its
        live position in the parent.
        """
        nodes = _as_node_list(raw)
        if nodes is None:
            action._engine_result = raw
            return raw
        check_splice_scope(parent, index, raw)
        next_sibling = parent.children[index + 1]
        next_sibling._engine_executed = True
        with self._lock:
            parent.children[index + 1 : index + 2] = nodes
        for node in nodes:
            _mark_dynamic(node)
        # Eager validation of the spliced nodes (parity with the old
        # engine's upfront build pass: unknown functions raise before the
        # spliced actions execute).
        for node in nodes:
            self._validate_node(node)
        results = self._walk_spliced(parent, nodes, list(upstream), ancestry)
        for node in nodes:
            node._engine_executed = True
        action._engine_result = results
        return results

    def _run_action(
        self,
        *upstream_results: Any,
        fn: Callable[..., Any],
        params: dict[str, Any],
        actions: list[Action | None],
        action: Action,
        context: WalkContext | None = None,
    ) -> Any:
        """
        Execute one action's function (runs on a pool worker thread).

        The call kwargs are, in precedence order (own parameters win): the
        action's own parameters, the upstream results (keyed by the
        producing action's function name, with collision suffixes), and the
        global parameters.  The raw return value is passed back to the
        walker thread, which handles any returned-node splice.

        When the function's signature declares a ``dag`` parameter (the
        registry's cached ``wants_dag`` flag), a scoped
        :class:`~.adaptation.DAGHandle` is injected for the call and its op
        log is committed at function return — on this same thread, under
        one engine-lock acquisition (the commit protocol, plan section 4).
        ``dag`` is a reserved kwarg name: the injected handle wins over any
        same-named parameter.  A function that declares ``dag`` AND returns
        workflow node(s) raises ``ValueError`` (one adaptation mechanism
        per action).

        When the callee declares a ``walk_context`` parameter (the
        registry's cached ``wants_context`` flag — every function of a
        store-wrapped registry does), the action's
        :class:`WalkContext` is injected the same way.  ``walk_context``
        is then a reserved kwarg name too; with no declaring callee
        nothing is injected and nothing changes.
        """
        kwargs: dict[str, Any] = dict(self._globals)
        used: dict[str, int] = {}
        for result, act in zip(upstream_results, actions):
            if act is None:
                continue
            name = act.function
            if name in used:
                used[name] += 1
                key = f"{name}_{used[name]}"
            else:
                used[name] = 1
                key = name
            kwargs[key] = result
        kwargs.update(params)
        # Worker-side start stamp for the per-action timeout (finding 3d):
        # the budget is measured from when the function call actually
        # begins, not from submission, so queued actions keep their full
        # budget.  Inert when no timeout is configured.
        action._engine_started = time.monotonic()
        handle = self._make_handle(action)
        if handle is not None:
            # Reserved kwarg name: the injected handle wins over any
            # same-named parameter (globals, upstream results, own params).
            kwargs["dag"] = handle
        if context is not None:
            # Reserved kwarg name (same rule as ``dag``): the walk context
            # wins over any same-named parameter.
            kwargs["walk_context"] = context
        if self._history is None:
            result = fn(**kwargs)
        else:
            result = self._record_call(action, fn, kwargs)
            if handle is not None:
                # Snapshot of the acting action's sibling list + index,
                # recorded at injection (plan section 9; replay
                # materializes a fake tree from it — Phase 6).
                record = getattr(action, "_engine_record", None)
                if record is not None:
                    record.scope = {
                        "index": handle.index,
                        "siblings": [
                            _describe_sibling(child) for child in handle.scope.children
                        ],
                    }
        if handle is not None:
            if _as_node_list(result) is not None:
                raise ValueError(
                    "dynamic adaptation: a function that declares a 'dag' "
                    "parameter must not also return workflow node(s); use "
                    "either the handle or the return-nodes protocol, not both"
                )
            self._commit(handle, action)
        return result

    # ------------------------------------------------------------ #
    # Dynamic adaptation: handle injection and the commit protocol
    # ------------------------------------------------------------ #
    def _make_handle(self, action: Action) -> DAGHandle | None:
        """
        Build the scoped handle for ``action``'s call, or ``None``.

        Returns ``None`` when the action's function does not declare a
        ``dag`` parameter (the registry's cached flag) or when the action's
        parent is not known (a detached node).  Children of a ``Parallel``
        scope get a READ-ONLY handle (finding F4): every write op raises.
        """
        if not self._registry.adapts(action.function):
            return None
        parent, index = self._locate_action(action)
        if parent is None:
            return None
        return DAGHandle(
            parent,
            index,
            read_only=isinstance(parent, Parallel),
            bound=self._adaptation_bound - self._dynamic_count,
        )

    def _locate_action(self, action: Action) -> tuple[_Group | None, int]:
        """Return ``(parent, index)`` of ``action`` in the live tree."""
        with self._lock:
            return self._root.locate(action)

    def _commit(self, handle: DAGHandle, action: Action) -> None:
        """
        Apply a handle's recorded ops (the commit protocol, plan section 4).

        Runs at function return, on the same thread the function ran on,
        under ONE engine-lock acquisition: re-validate every op against the
        live tree, apply the tree surgery (children-list edits, in-place
        ``params.update`` for adjust, appends at the scope end), check the
        dynamic-node bound, record the ``adaptations`` on the action's
        ``ExecutionRecord`` and mark the inserted nodes dynamic.  An empty
        op log is a no-op.  Re-validation failures raise before any op is
        applied (the ops of one commit are atomic).
        """
        ops = handle.ops
        if not ops:
            return
        with self._lock:
            for op in ops:
                self._revalidate(op)
            for op in ops:
                self._apply(op)
            self._dynamic_count += sum(len(op.nodes) for op in ops)
            if self._dynamic_count > self._adaptation_bound:
                raise ValueError(
                    f"dynamic adaptation: the dynamic-node bound "
                    f"({self._adaptation_bound}) was exceeded; a runaway "
                    f"adaptation is terminated deterministically instead "
                    f"of hanging"
                )
            for node in (n for op in ops for n in op.nodes):
                _mark_dynamic(node)
        # Eager validation of the inserted nodes (parity with the
        # return-nodes splice path: an unknown function raises before the
        # inserted actions execute).
        for op in ops:
            for node in op.nodes:
                self._validate_node(node)
        record = getattr(action, "_engine_record", None)
        if record is not None:
            record.adaptations = [op.describe() for op in ops]

    def _revalidate(self, op: AdaptationOp) -> None:
        """
        Re-check one op against the live tree (under the engine lock).

        The op's target must still be in the tree and must not have started
        (``_engine_executed``).  The parallel-scope rule (finding F4) is
        enforced on the ACTOR side — a child of a ``Parallel`` scope gets a
        read-only handle, so no ops can exist for it — not on the target
        side: an action in a sequential scope may adapt the subtree of a
        FOLLOWING parallel group, because every position after the actor
        is unwalked while its function runs (the paper's Listing 7 outer
        case).
        """
        if op.kind == "append":
            return
        parent, _index = self._root.locate(op.target)
        if parent is None:
            raise ValueError(
                "dynamic adaptation: the op's target is no longer in the "
                "workflow tree; the tree changed after the op was recorded"
            )
        if getattr(op.target, "_engine_executed", False):
            raise ValueError(
                "dynamic adaptation: the op's target has already executed; "
                "only nodes that have not started may be adapted"
            )

    def _apply(self, op: AdaptationOp) -> None:
        """Apply one op's tree surgery (under the engine lock)."""
        if op.kind == "append":
            group = op.scope if op.scope is not None else self._root
            group.children.extend(op.nodes)
            return
        if op.kind == "adjust":
            _apply_params(op.target, op.params)
            return
        if op.kind == "replace":
            parent, index = self._root.locate(op.target)
            parent.children[index : index + 1] = list(op.nodes)
            return
        raise ValueError(f"dynamic adaptation: unknown op kind {op.kind!r}")

    # ------------------------------------------------------------ #
    # Execution history (opt-in)
    # ------------------------------------------------------------ #
    def _record_call(
        self,
        action: Action,
        fn: Callable[..., Any],
        kwargs: dict[str, Any],
    ) -> Any:
        """
        Call ``fn(**kwargs)`` and record the call as an ExecutionRecord.

        The record captures what ACTUALLY executed: the action's registry
        name, the resolved function's name, the resolved parameters (the
        exact ``kwargs`` the function received, minus the engine's reserved
        kwarg names — see below), the result (a dynamic-adaptation return
        normalized by ``recordable_result``) or the exception, timestamps
        taken around the call, the group path at call time, and whether the
        action was spliced in at runtime.  The record is appended to the
        history when the call completes, so the history is in true completion
        order.  An exception is re-raised after being recorded.

        The engine's reserved kwarg names (``dag``, ``walk_context``) carry
        engine-injected handles, not user data — their evidence lives in
        ``record.scope`` and the store's manifest — so exactly the injected
        names are stripped from the recorded ``params`` and the record holds
        plain, comparable data.  A same-named parameter that the engine did
        NOT inject (no ``dag``-declaring function, no store) is user data and
        stays.

        The artifact address (``record.artifacts``) is read AFTER the
        call: a wrapped registry view mints at call entry (IMP-007), so
        the address exists once the function has started — on both the
        success and the exception path.  ``None`` when the run has no
        store.
        """
        params = dict(kwargs)
        # Strip exactly the engine-injected reserved kwargs: their evidence
        # lives structurally in record.scope / the store's manifest.
        if self._registry.adapts(action.function):
            params.pop("dag", None)
        if self._registry.wants_context(action.function):
            params.pop("walk_context", None)
        if self._params_mode == "summary":
            # Summary mode: bulk dict/list/tuple payloads become item counts
            # (the shape library functions emit); the call itself is
            # unchanged — this is the history-side half of the by-reference
            # split (the artifact store is the by-reference plane).
            params = {
                key: len(value) if isinstance(value, (dict, list, tuple)) else value
                for key, value in params.items()
            }
        record = ExecutionRecord(
            name=action.function,
            function=getattr(fn, "__name__", type(fn).__name__),
            params=params,
            run_id=self._history.run_id,
            group_path=self._path_of(action),
            dynamic=getattr(action, "_engine_dynamic", False),
            description=getattr(action, "description", None),
        )
        # Identity-keyed link so the final action's record can be found
        # exactly, even if a later splice shifts tree positions.
        action._engine_record = record
        mono_start = time.monotonic()
        record.started_at = time.time()
        try:
            result = fn(**kwargs)
        except BaseException as exc:
            record.ended_at = time.time()
            record.duration = time.monotonic() - mono_start
            record.exception = exc
            record.artifacts = _action_address(action)
            self._history.add(record)
            raise
        record.ended_at = time.time()
        record.duration = time.monotonic() - mono_start
        record.artifacts = _action_address(action)
        record.result = recordable_result(result)
        self._history.add(record)
        return result

    def _path_of(self, action: Action) -> str:
        """
        The action's group path, read under the engine lock.

        Splices mutate ``children`` lists under the same lock, so taking it
        here guarantees the walk sees a consistent tree (the path as it
        stood at call time).
        """
        with self._lock:
            return resolve_group_path(self._root, action)

    def _mark_final(self, final_action: Action) -> None:
        """
        Mark the run's final action on the history (for ``replay``).

        ``replay`` returns the replayed value of the run's final action —
        the action whose result ``run_workflow`` / ``Test_Framework``
        returned — so the engine records that action's completion-order
        index on the history after a successful run.  The record is found
        by identity (``action._engine_record``, set in ``_record_call``),
        which stays exact even when a late splice shifts tree positions
        after the action recorded its group path.
        """
        record = getattr(final_action, "_engine_record", None)
        if record is not None:
            self._history.final_order = record.order

    # ------------------------------------------------------------ #
    # Final-result resolution
    # ------------------------------------------------------------ #
    def _final_action(self, group: _Group) -> Action | None:
        """
        Return the last action in ``group``'s execution order.

        Resolves the last child recursively: if it is an action, it is the
        final action; if it is a group, recurse into it.  Returns ``None``
        for an empty group (the run's result is then ``None``).
        """
        children = group.children
        if not children:
            return None
        last = children[-1]
        if isinstance(last, Action):
            return last
        return self._final_action(last)


def _join_results(*_results: Any) -> None:
    """A join node: it runs once every dependency has settled (value unused)."""
    return None


def _wire_store(
    registry: FunctionRegistry,
    artifacts: ArtifactStore | None,
    history: RunHistory | None = None,
) -> FunctionRegistry:
    """
    The artifact store's wiring point (IMP-007): the one place the engine
    layer talks to the store, through its documented protocol only.

    Opens the store (a fresh run root and manifest) and returns the
    store's wrapped registry view: every function wrapped, addressing
    derived at call time from the injected walk context.  With no store
    (``None``), the registry passes through unchanged and nothing happens
    — the opt-in contract.

    When the run has a history and the store was constructed without
    one, the history is attached before the store opens, so the
    manifest's run header carries the run's identity (``run_id``).  A
    store the caller constructed WITH a history keeps it (caller
    ownership).
    """
    if artifacts is None:
        return registry
    if history is not None and artifacts._history is None:
        artifacts._history = history
    artifacts._begin()
    return artifacts.wrap_registry(registry)


def _dry_noop(**kwargs: Any) -> None:
    """A dry-run function stub: it runs nothing and returns ``None``."""
    return None


def _dry_run_registry(registry: FunctionRegistry) -> FunctionRegistry:
    """
    The dry-run registry view: every registered name maps to a no-op stub.

    The NAME SET matches the real registry, so the engine's eager
    unknown-function validation still rejects an unknown name in plan mode.
    Nothing else does: the stubs declare no reserved kwarg names, so nothing
    is injected, and they return ``None`` — a plan run splices nothing,
    adapts nothing and mints nothing.
    """
    dry = FunctionRegistry()
    for name in registry.names():
        dry.register(name, _dry_noop)
    return dry


def _apply_params(target: _Node, params: dict[str, Any]) -> None:
    """
    Apply an ``adjust`` op's parameter overrides to ``target`` in place.

    An ``Action`` gets its ``params`` dict updated (existing keys
    overwritten, missing keys added); a group applies the overrides to
    every action in its subtree (the "retune the declared downstream scope"
    form).
    """
    if isinstance(target, Action):
        target.params.update(params)
        return
    for child in target.children:
        _apply_params(child, params)


def _describe_sibling(node: _Node) -> dict[str, Any]:
    """A plain descriptor of a scope snapshot's sibling (for history)."""
    if isinstance(node, Action):
        return {"kind": "action", "function": node.function}
    kind = "sequential" if isinstance(node, Sequential) else "parallel"
    descriptor = {"kind": kind, "children": len(node.children)}
    # A named group's label is part of its declared identity — recorded
    # so a replayed branching driver can find its named alternatives.
    if node.name is not None:
        descriptor["name"] = node.name
    # The children's names (position-aligned, None for unnamed) let a
    # replayed branching driver resolve the named alternative branches
    # one level below the snapshot's sibling list.
    child_names = [getattr(child, "name", None) for child in node.children]
    if any(name is not None for name in child_names):
        descriptor["child_names"] = child_names
    return descriptor


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #


def run_workflow(
    xml_source: str | bytes,
    registry: FunctionRegistry | None = None,
    parameters: dict[str, Any] | None = None,
    history: RunHistory | None = None,
    artifacts: ArtifactStore | None = None,
    *,
    params_mode: str = "full",
    max_workers: int | None = None,
    adaptation_bound: int | None = None,
    executor: GraphPool | None = None,
    dry_run: bool = False,
    action_timeout: float | None = None,
    fail_fast: bool = False,
) -> Any:
    """
    Parse a workflow XML document and execute it; return the final result.

    ``xml_source`` is the workflow XML (see
    :func:`sequence_extensions.workflow.schema.parse_workflow`).  ``registry``
    is the function registry (defaults to ``DEFAULT_REGISTRY``).
    ``parameters`` are extra global parameters: they are merged over the
    XML's global parameters (``<VerificationWorkflow>`` wrapper elements),
    with ``parameters`` winning on a name clash.  The final result is the
    return value of the last action in the root group's execution order.
    ``parameters`` also reach ``<use-template>`` placeholders: the workflow
    is re-parsed with them merged over the XML globals before executing.

    ``history`` is OPT-IN execution recording (default ``None`` = record
    nothing, zero behavior change): pass a
    :class:`sequence_extensions.workflow.history.RunHistory` to capture
    per-action evidence — including actions spliced in at runtime by
    dynamic adaptation, in true completion order — which can then be
    replayed deterministically with
    :func:`sequence_extensions.workflow.history.replay`.

    ``artifacts`` is the OPT-IN by-reference artifact store (default
    ``None`` = no store, zero behavior change): pass an
    :class:`sequence_extensions.workflow.artifacts.ArtifactStore` to mint
    one directory per executed action under the store's run root
    (recorded in an append-only manifest) and hand a scoped
    ``ArtifactHandle`` to every function that declares an ``artifacts``
    parameter — write to the node directory, read the causal past,
    enumerate completed parallel groups' branches.  The engine itself
    carries no store knowledge: the wiring here opens the store and
    swaps in the store's wrapped registry view, whose functions derive
    their addressing at call time from the engine's injected walk
    context.  See :mod:`sequence_extensions.workflow.artifacts`.

    Run options (keyword-only):

    * ``params_mode`` — the recorded-params shape: ``"full"`` (the
      default) records the resolved kwargs as before; ``"summary"``
      records each dict/list/tuple payload as its item count (the call
      itself is unchanged — the by-reference plane for bulk payloads is
      the artifact store).  Unknown values raise ``ValueError``.
    * ``max_workers`` — the ``GraphPool`` worker count (default 16).
    * ``adaptation_bound`` — the dynamic-node bound (default
      ``ADAPTATION_BOUND``); must be >= 0.
    * ``executor`` — a caller-owned :class:`GraphPool` (it wins over
      ``max_workers`` and is NOT shut down at run end — the caller keeps
      its lifecycle).  The pool is thread-based: CPU-bound Python
      functions (a GIL-bound simulation) see no speed-up from it — see
      :mod:`sequence_extensions.graph`.
    * ``dry_run`` — plan mode: the workflow is parsed (templates
      expanded), every function name is validated, and the walk runs with
      no-op functions; ``run_workflow`` returns the workflow tree (the
      effective plan) instead of a result, and ``history`` still records
      (each record shows what the action WOULD have been called with).
      Nothing executes: no side effects, no splices, no store directories
      (``artifacts`` is ignored — a plan mints nothing).
    * ``action_timeout`` — per-action wall-clock budget in seconds
      (default ``None`` = no timeout, the historical behavior: a hung
      action blocks its worker forever).  A positive number bounds every
      action's function call; an action still running past its budget
      raises :class:`ActionTimeoutError` (a :class:`TimeoutError`
      subclass) naming the action, the timeout and the option, so an
      unattended campaign fails loudly instead of deadlocking.  The
      budget is measured from when the call starts on its worker (an
      action queued behind others keeps its full budget); an action that
      cannot even START within one budget (a saturated pool) fails the
      same way.  The hung function is abandoned, not killed — Python
      threads cannot be killed — so the engine tears its own pool down
      without waiting for it and the run unwinds; the abandoned worker
      finishes in the background (a caller-owned ``executor`` is never
      shut down by the engine).  Must be > 0 or ``None``.
    * ``fail_fast`` — the parallel failure policy (default ``False`` =
      the historical drain-then-report: a failing parallel group waits
      for every sibling to settle before raising the first error in child
      order — the safe default, because a caller that inspects state after
      a failed run sees every sibling's side effects accounted for).
      ``True`` stops a parallel group at the FIRST failure: not-yet-run
      siblings skip their function call (a queued action costs nothing),
      in-flight ones are abandoned (a thread cannot be killed — the pool
      is torn down without waiting for them, exactly like the
      ``action_timeout`` path), and the first error is raised promptly.
      Built for runtime-sized unattended campaigns, where paying for
      every remaining sibling after the first failure is unacceptable.
      Composes with ``action_timeout`` (a timed-out action is an error
      like any other).

    Raises ``ValueError`` for invalid XML, an unknown function name (naming
    the function), an out-of-scope dynamic-adaptation splice attempt, an
    unknown ``params_mode``, a negative ``adaptation_bound``, or a
    non-positive ``action_timeout``.  Raises :class:`ActionTimeoutError`
    when the ``action_timeout`` option fires.
    """
    root = parse_workflow(xml_source)
    if parameters:
        merged = {**root.globals, **parameters}
        if merged != root.globals:
            # Run-time parameters reach template placeholders: re-parse with
            # the merged globals (two cheap, deterministic parses; template
            # expansion sees the run-time overrides).
            root = parse_workflow(xml_source, merged)
    effective_registry = (
        registry if registry is not None else DEFAULT_REGISTRY
    )
    engine = _Engine(
        root,
        (
            _dry_run_registry(effective_registry)
            if dry_run
            else _wire_store(effective_registry, artifacts, history)
        ),
        parameters,
        history,
        source=_workflow_digest(xml_source=xml_source),
        params_mode=params_mode,
        max_workers=max_workers,
        adaptation_bound=adaptation_bound,
        executor=executor,
        dry_run=dry_run,
        action_timeout=action_timeout,
        fail_fast=fail_fast,
    )
    return engine.run()


def Test_Framework(
    seq: _Group,
    parameters: dict[str, Any] | None = None,
    registry: FunctionRegistry | None = None,
    history: RunHistory | None = None,
    artifacts: ArtifactStore | None = None,
    *,
    params_mode: str = "full",
    max_workers: int | None = None,
    adaptation_bound: int | None = None,
    executor: GraphPool | None = None,
    dry_run: bool = False,
    action_timeout: float | None = None,
    fail_fast: bool = False,
) -> Any:
    """
    Execute a workflow built via the Python API (the paper's Listing 10).

    ``seq`` is the root group (``Sequential`` / ``Parallel``); ``parameters``
    are global parameters passed to every function (an action's own
    parameters win); ``registry`` is the function registry (defaults to
    ``DEFAULT_REGISTRY``).  Returns the final result: the return value of
    the last action in the root group's execution order.

    ``history`` is OPT-IN execution recording (default ``None`` = record
    nothing, zero behavior change); see :func:`run_workflow`.

    ``artifacts`` is the OPT-IN by-reference artifact store (default
    ``None`` = no store, zero behavior change); see :func:`run_workflow`.

    The keyword-only run options mirror :func:`run_workflow` (``params_mode``,
    ``max_workers``, ``adaptation_bound``, ``executor``, ``dry_run`` — with
    ``dry_run=True`` returning the workflow tree instead of a result — and
    ``action_timeout``, the per-action wall-clock budget in seconds whose
    expiry raises :class:`ActionTimeoutError`; see :func:`run_workflow`).
    ``fail_fast`` is the parallel failure policy (default ``False`` = the
    historical drain-then-report; ``True`` stops a parallel group at the
    first failure — not-yet-run siblings skip, in-flight ones are
    abandoned, and the first error is raised promptly; see
    :func:`run_workflow`).

    The paper's call form ``Test_Framework(parameters=common_parameters,
    seq=top_seq)`` executes the workflow and returns its final result.
    """
    effective_registry = (
        registry if registry is not None else DEFAULT_REGISTRY
    )
    engine = _Engine(
        seq,
        (
            _dry_run_registry(effective_registry)
            if dry_run
            else _wire_store(effective_registry, artifacts, history)
        ),
        parameters,
        history,
        source=_workflow_digest(root=seq),
        params_mode=params_mode,
        max_workers=max_workers,
        adaptation_bound=adaptation_bound,
        executor=executor,
        dry_run=dry_run,
        action_timeout=action_timeout,
        fail_fast=fail_fast,
    )
    return engine.run()


#: The Python-API run entry point under a name that does not read as a test
#: utility (the paper's Listing 10 call form; ``Test_Framework`` is kept for
#: paper parity).
run_python_workflow = Test_Framework
