"""Sink-node-type filtering: version tolerance + Python/TS drift guard (#169).

Palette-dragged builtins carry the versioned canonical type
(``curio.builtin/vis-vega@1``); programmatic nodes use the unversioned enum.
Every sink check must normalize before membership, and the Python and TS sink
sets must stay set-equal — this module regexes the TS sources so a one-sided
edit fails CI instead of silently leaking duplicate computed datasets.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from utk_curio.backend.app.datasets.application.auto_install import _is_sink_node
from utk_curio.backend.app.packages.spec_packages import unversioned_node_type
from utk_curio.backend.app.projects.services import _SINK_NODE_TYPES, _is_sink_node_type


def test_unversioned_node_type_strips_major_suffix():
    assert unversioned_node_type("curio.builtin/vis-vega@1") == "curio.builtin/vis-vega"
    assert unversioned_node_type("curio.builtin/vis-vega") == "curio.builtin/vis-vega"
    assert unversioned_node_type("ai.urbanlab.uhvi/uhvi-load@12") == "ai.urbanlab.uhvi/uhvi-load"
    # Only a trailing @<major> is stripped; other @s stay.
    assert unversioned_node_type("weird@name") == "weird@name"
    assert unversioned_node_type(None) is None


@pytest.mark.parametrize("node_type", [
    "curio.builtin/vis-vega",
    "curio.builtin/vis-vega@1",
    "curio.builtin/vis-simple@2",
])
def test_sink_check_tolerates_versioned_types(node_type):
    assert _is_sink_node_type(node_type) is True
    assert _is_sink_node(node_type) is True


@pytest.mark.parametrize("node_type", [
    "curio.builtin/data-transformation",
    "curio.builtin/data-transformation@1",
    None,
    "",
])
def test_non_sink_types_pass(node_type):
    assert _is_sink_node_type(node_type) is False
    assert _is_sink_node(node_type) is False


# --------------------------------------------------------------------------- #
# Drift guard: the TS sink set must stay set-equal with _SINK_NODE_TYPES.
# --------------------------------------------------------------------------- #

_FRONTEND_SRC = (
    Path(__file__).resolve().parents[3] / "frontend" / "urban-workflows" / "src"
)


def _ts_enum_values() -> dict[str, str]:
    constants = (_FRONTEND_SRC / "constants.ts").read_text(encoding="utf-8")
    return dict(re.findall(r"(\w+)\s*=\s*\"([^\"]+)\"", constants))


def _ts_sink_set() -> set[str]:
    source = (_FRONTEND_SRC / "utils" / "saveOutputDataset.ts").read_text(encoding="utf-8")
    m = re.search(
        r"NON_PRODUCING_NODE_TYPES[^=]*=\s*new Set\(\[(.*?)\]\)",
        source,
        re.DOTALL,
    )
    assert m, "NON_PRODUCING_NODE_TYPES set literal not found in saveOutputDataset.ts"
    enum_values = _ts_enum_values()
    entries: set[str] = set()
    for member in re.findall(r"NodeType\.(\w+)", m.group(1)):
        assert member in enum_values, f"NodeType.{member} not found in constants.ts"
        entries.add(enum_values[member])
    for literal in re.findall(r"\"([^\"]+)\"", m.group(1)):
        entries.add(literal)
    return entries


@pytest.mark.skipif(
    not (_FRONTEND_SRC / "utils" / "saveOutputDataset.ts").is_file(),
    reason="frontend tree not present in this checkout",
)
def test_python_and_ts_sink_sets_stay_equal():
    assert _ts_sink_set() == set(_SINK_NODE_TYPES)


def test_sink_entries_are_unversioned():
    # Entries must be unversioned — checks normalize, the lists never carry @N.
    assert all("@" not in entry for entry in _SINK_NODE_TYPES)
