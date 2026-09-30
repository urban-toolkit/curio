"""The skip that tells a network outage from a regression (see utils.py).

Pure logic: no browser, no servers of its own.
"""
from __future__ import annotations

import pytest

from . import utils
from .utils import external_fetch_failure_host, skip_if_external_host_unreachable

DUCKDB_FAILURE = (
    "Node pbf-viz (AUTK_GRAMMAR) execution failed with Error\n"
    "--- node error output ---\n"
    "Failed to execute 'send' on 'XMLHttpRequest': Failed to load "
    "'https://extensions.duckdb.org/v1.5.4/wasm_eh/spatial.duckdb_extension.wasm'."
)


def test_the_duckdb_extension_failure_names_its_host():
    assert external_fetch_failure_host(DUCKDB_FAILURE) == "extensions.duckdb.org"


@pytest.mark.parametrize("text", [
    None,
    "",
    "Node x (AUTK_GRAMMAR) execution failed with Error",
    "Failed to load 'https://example.com/spatial.wasm'.",
    "Failed to load 'https://extensions.duckdb.org.evil.test/x.wasm'.",
])
def test_anything_else_is_not_an_external_fetch_failure(text):
    assert external_fetch_failure_host(text) is None


def test_an_unreachable_host_skips(monkeypatch):
    monkeypatch.setattr(utils, "external_host_reachable", lambda host, **kw: False)
    with pytest.raises(pytest.skip.Exception, match="extensions.duckdb.org"):
        skip_if_external_host_unreachable(DUCKDB_FAILURE)


def test_a_reachable_host_leaves_the_failure_standing(monkeypatch):
    monkeypatch.setattr(utils, "external_host_reachable", lambda host, **kw: True)
    skip_if_external_host_unreachable(DUCKDB_FAILURE)  # returns; caller re-raises


def test_an_unrelated_failure_is_never_probed(monkeypatch):
    def boom(host, **kw):
        raise AssertionError("probed for a failure that names no external host")
    monkeypatch.setattr(utils, "external_host_reachable", boom)
    skip_if_external_host_unreachable("Node x failed: KeyError 'geometry'")
