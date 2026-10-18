"""Tests for Phase 2 cache.py scaffold — no-op contract."""
import os

from utk_curio.backend.app.projects import cache


def test_content_key_deterministic():
    k1 = cache.content_key("print(1)", ["a.data", "b.data"], {"n": 5})
    k2 = cache.content_key("print(1)", ["b.data", "a.data"], {"n": 5})
    assert k1 == k2
    assert len(k1) == 64


def test_content_key_varies_with_code():
    k1 = cache.content_key("print(1)", [], {})
    k2 = cache.content_key("print(2)", [], {})
    assert k1 != k2


def test_lookup_returns_none_when_flag_off():
    os.environ.pop("CURIO_PROJECT_EXEC_CACHE", None)
    assert cache.lookup("proj-1", "abc123") is None


def test_store_is_noop_when_flag_off():
    os.environ.pop("CURIO_PROJECT_EXEC_CACHE", None)
    cache.store("proj-1", "activity1", "key1", "out.data")


def test_lookup_returns_none_even_with_flag_on():
    os.environ["CURIO_PROJECT_EXEC_CACHE"] = "true"
    try:
        assert cache.lookup("proj-1", "abc123") is None
    finally:
        os.environ.pop("CURIO_PROJECT_EXEC_CACHE", None)
