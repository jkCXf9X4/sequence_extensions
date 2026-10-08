"""
Parameter normalization for the V&V workflow engine.

Workflow parameters arrive in two shapes: the XML form (all values are
strings, e.g. ``values="5, 10, 15"``) and the Python API form (native
types, e.g. ``values=[5, 10, 15]``).  These helpers convert the XML form to
the Python form so a registered function receives the same shape no matter
how the workflow was built (paper section 4.2).
"""

from __future__ import annotations

from typing import Any

__all__ = [
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
