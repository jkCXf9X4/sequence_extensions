"""
Parameter normalization for the V&V workflow engine.

Workflow parameters arrive in two shapes: the XML form (all values are
strings, e.g. ``values="5, 10, 15"``) and the Python API form (native
types, e.g. ``values=[5, 10, 15]``).  Exactly one parameter name is
normalized across both shapes: ``values`` (a comma-separated string becomes
a list, numeric strings become numbers) — every other parameter name passes
through as-is, and the library functions coerce their own comparison
operands (``library._coerce_operand``).  The ``values`` conversion makes a
registered function receive the same shape no matter how the workflow was
built (paper section 4.2).

Per-function parameter schemas (opt-in, see
:mod:`sequence_extensions.workflow.registry`) add generic type coercion at
injection time: a function registered with a schema receives its declared
parameters coerced to their types (XML string ``"10"`` → ``int 10``,
``"true"`` → ``bool True``, etc.), so custom functions driven from XML
receive typed values without hand-rolling coercion.  Functions registered
without a schema keep the exact current behavior.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "ParameterCoercionError",
    "coerce_param",
    "coerce_params",
    "coerce_value",
    "normalize_params",
    "normalize_values",
]


def coerce_value(item: Any) -> Any:
    """
    Normalize one sweep value.

    Strings are stripped and converted to ``int`` (then ``float``) when
    possible; other values are returned unchanged.
    """
    if isinstance(item, str):
        text = item.strip()
        try:
            return int(text)
        except ValueError:
            pass
        try:
            return float(text)
        except ValueError:
            return text
    return item


def normalize_values(values: Any) -> list[Any]:
    """
    Normalize a ``values`` parameter to a list.

    A string is split on commas; a list or tuple is used as-is; ``None``
    yields an empty list.  Each item is stripped (if a string), empty items
    are dropped, and numeric strings are converted to ``int`` (or ``float``).
    """
    if values is None:
        return []
    items = values.split(",") if isinstance(values, str) else list(values)
    normalized: list[Any] = []
    for item in items:
        if isinstance(item, str) and not item.strip():
            continue
        normalized.append(coerce_value(item))
    return normalized


def normalize_params(params: dict[str, Any]) -> dict[str, Any]:
    """
    Normalize an action's own parameters before the function runs.

    A ``values`` parameter given as a comma-separated string (the XML form,
    e.g. ``"5, 10, 15"``) is converted to a list of values (``[5, 10, 15]``)
    so functions receive the same shape from the XML and the Python API.
    """
    if "values" in params and isinstance(params["values"], str):
        return {**params, "values": normalize_values(params["values"])}
    return params


# --------------------------------------------------------------------------- #
# Per-function parameter schema coercion (opt-in)
# --------------------------------------------------------------------------- #


class ParameterCoercionError(ValueError):
    """
    Raised when a parameter value cannot be coerced to its declared type.

    The message names the parameter, the function, the declared type, and
    the offending value, so a mis-declared schema or a bad XML value is easy
    to diagnose.  Subclasses ``ValueError`` so existing ``except ValueError``
    handlers still catch it.
    """

    def __init__(
        self, function_name: str, param_name: str, target_type: type, value: Any
    ) -> None:
        self.function_name = function_name
        self.param_name = param_name
        self.target_type = target_type
        self.value = value
        super().__init__(
            f"cannot coerce parameter {param_name!r} of function "
            f"{function_name!r} to {target_type.__name__}: "
            f"got {value!r} ({type(value).__name__})"
        )


#: The accepted spellings for a boolean string (case-insensitive).
_BOOL_TRUE = frozenset({"true", "1", "yes"})
_BOOL_FALSE = frozenset({"false", "0", "no"})


def _parse_bool(text: str) -> bool:
    """
    Parse a boolean string.

    Case-insensitive: ``"true"`` / ``"1"`` / ``"yes"`` → ``True``;
    ``"false"`` / ``"0"`` / ``"no"`` → ``False``.  Anything else raises
    ``ValueError``.
    """
    lowered = text.strip().lower()
    if lowered in _BOOL_TRUE:
        return True
    if lowered in _BOOL_FALSE:
        return False
    raise ValueError(f"not a boolean: {text!r}")


def coerce_param(
    value: Any, target_type: type, *, function_name: str, param_name: str
) -> Any:
    """
    Coerce one parameter value to its declared type.

    Coercion rules (documented):

    1. **Already the right type** — the value is returned unchanged, with
       two caveats: a ``bool`` is never "already an ``int``" (it is converted
       to ``int`` below), and an ``int`` is promoted to ``float`` below.
    2. **String** — the value is parsed to the target type:

       - ``int``: ``int(text)`` (a valid integer literal, e.g. ``"10"``).
       - ``float``: ``float(text)`` (e.g. ``"10.5"``).
       - ``bool``: case-insensitive ``"true"``/``"1"``/``"yes"`` → ``True``;
         ``"false"``/``"0"``/``"no"`` → ``False``.
       - ``str``: the value is returned unchanged.
       - other types: ``target_type(text)``.

    3. **Non-string** — ``target_type(value)`` is attempted (e.g. an
       ``int`` → ``float`` promotion, a numeric → ``bool``, or a value →
       ``str``).
    4. **Failure** — a :class:`ParameterCoercionError` is raised, naming the
       parameter, the function, the declared type, and the value.

    The coerced value is plain Python data (``int`` / ``float`` / ``bool`` /
    ``str``), with no XML remnants, so it is safe to record in history and
    manifests.
    """
    # 1. Already the right type?
    if target_type is bool:
        if isinstance(value, bool):
            return value
    elif target_type is int:
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    elif target_type is float:
        if isinstance(value, float):
            return value
    elif target_type is str:
        if isinstance(value, str):
            return value
    # 2. String parsing.
    if isinstance(value, str):
        text = value.strip()
        if target_type is bool:
            try:
                return _parse_bool(text)
            except ValueError:
                pass
        else:
            try:
                return target_type(text)
            except (ValueError, TypeError):
                pass
        raise ParameterCoercionError(function_name, param_name, target_type, value)
    # 3. Non-string: attempt target_type(value).
    try:
        return target_type(value)
    except (ValueError, TypeError):
        pass
    # 4. Failure.
    raise ParameterCoercionError(function_name, param_name, target_type, value)


def coerce_params(
    params: dict[str, Any], types: dict[str, type], *, function_name: str
) -> dict[str, Any]:
    """
    Coerce a params dict per a type mapping.

    ``types`` maps parameter names to their declared types.  Only the params
    that have a declared type AND are present in ``params`` are coerced; all
    other params pass through unchanged.  Returns a new dict (the input is
    not mutated).

    Raises :class:`ParameterCoercionError` if a present value cannot be
    coerced to its declared type.
    """
    coerced = dict(params)
    for name, target_type in types.items():
        if name in coerced:
            coerced[name] = coerce_param(
                coerced[name],
                target_type,
                function_name=function_name,
                param_name=name,
            )
    return coerced
