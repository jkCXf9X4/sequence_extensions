"""
Higher-order helpers for built-in sequences: ``list``, ``dict``, generators.

Modules:

* :mod:`~sequence_extensions.ext.list_ext` — the ``list_ext`` class
  (functional map/filter, windows, conversions, predicates).
* :mod:`~sequence_extensions.ext.dict_ext` — the ``dict_ext`` class and
  ``KeyValueTuple`` (functional helpers over ``(key, value)`` pairs).
* :mod:`~sequence_extensions.ext.gen_ext` — ``gen_ext`` static helpers for
  generators and iterables.
"""

from sequence_extensions.ext.dict_ext import KeyValueTuple, dict_ext
from sequence_extensions.ext.gen_ext import gen_ext
from sequence_extensions.ext.list_ext import list_ext

__all__ = [
    "KeyValueTuple",
    "dict_ext",
    "gen_ext",
    "list_ext",
]
