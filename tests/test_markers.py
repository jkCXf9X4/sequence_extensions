"""Marker policy: one level per test, directory-derived, stable selection."""

from __future__ import annotations

import pytest
from _pytest.mark.expression import Expression

from markers import LEVEL_MARKERS, level_for


def _marker_names(item):
    return {marker.name for marker in item.iter_markers()}


def _levels(item):
    return _marker_names(item) & LEVEL_MARKERS


def test_every_collected_test_has_exactly_one_level_marker(request):
    offenders = {}
    for item in request.session.items:
        levels = _levels(item)
        if len(levels) != 1:
            offenders[item.nodeid] = sorted(levels)
    assert not offenders, f"tests without exactly one level marker: {offenders}"
    assert request.session.items


def test_level_marker_follows_the_directory_policy(request):
    mismatched = {
        item.nodeid: (sorted(_levels(item)), level_for(item.path))
        for item in request.session.items
        if _levels(item) != {level_for(item.path)}
    }
    assert not mismatched, f"level marker does not follow the policy: {mismatched}"


def test_component_selection_is_stable_and_excludes_flaky_timing(request):
    expression = Expression.compile("level_component and not flaky_timing")

    def matches(item):
        names = _marker_names(item)
        return bool(expression.evaluate(lambda name: name in names))

    selected = [item.nodeid for item in request.session.items if matches(item)]
    if not selected:
        pytest.skip("no component-level tests collected")

    for item in request.session.items:
        names = _marker_names(item)
        assert matches(item) is (
            "level_component" in names and "flaky_timing" not in names
        ), item.nodeid

    # Same descriptor, second evaluation: identical membership and order.
    assert selected == [item.nodeid for item in request.session.items if matches(item)]

    flaky_component = {
        item.nodeid
        for item in request.session.items
        if "level_component" in _marker_names(item) and "flaky_timing" in _marker_names(item)
    }
    assert not flaky_component & set(selected)
