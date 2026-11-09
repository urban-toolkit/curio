"""Two writes of an account's model records at once both stay.

``model_catalog.remember_models`` read the account's model suggestions, added
an endpoint's listing and wrote the file back, and
``remember_chat_capabilities`` did the same with what a trial found a model
can do. Neither held a lock, and both wrote through one fixed ``<file>.tmp``:
two writes at once (two requests, or two backend processes) each wrote what
it had read plus its own record, so the later one dropped the other's.

Each test forks a write that stops after its read, then writes another
record from this process (``_support/two_processes.py``).
"""
from __future__ import annotations

ACCOUNT = "7"
API = "openai_compatible"


def test_two_endpoints_remembered_at_once_are_both_kept(tmp_curio, monkeypatch):
    from utk_curio.backend.app.agents.repositories import model_catalog
    from utk_curio.backend.tests._support.two_processes import Window, race

    window = Window()
    read = model_catalog._load

    def _read_then_stop(user_key):
        providers = read(user_key)
        window.stop_here()
        return providers

    monkeypatch.setattr(model_catalog, "_load", _read_then_stop)

    raced = race(
        window,
        lambda: model_catalog.remember_models(ACCOUNT, API, "https://a.example/v1", ["model-a"]),
        lambda: model_catalog.remember_models(ACCOUNT, API, "https://b.example/v1", ["model-b"]),
        monkeypatch,
    )

    assert raced.child_exit == 0, raced.child_error
    kept = {
        url: model_catalog.remembered_models(ACCOUNT, API, url)[0]
        for url in ("https://a.example/v1", "https://b.example/v1")
    }
    assert kept == {"https://a.example/v1": ["model-a"], "https://b.example/v1": ["model-b"]}, (
        f"an endpoint's models were lost to a write made at the same time: {kept}"
    )


def test_two_models_tried_at_once_are_both_remembered(tmp_curio, monkeypatch):
    from utk_curio.backend.app.agents.repositories import model_catalog
    from utk_curio.backend.tests._support.two_processes import Window, race

    window = Window()
    read = model_catalog._load_sidecar

    def _read_then_stop(user_key, filename, section):
        entries = read(user_key, filename, section)
        window.stop_here()
        return entries

    monkeypatch.setattr(model_catalog, "_load_sidecar", _read_then_stop)
    url = "https://models.example/v1"

    def _try(model):
        return lambda: model_catalog.remember_chat_capabilities(
            ACCOUNT, API, url, model, {"tools": True, "structuredOutput": False, "reason": f"{model} called a tool"},
        )

    raced = race(window, _try("model-a"), _try("model-b"), monkeypatch)

    assert raced.child_exit == 0, raced.child_error
    reasons = {
        model: (model_catalog.remembered_chat_capabilities(ACCOUNT, API, url, model) or {}).get("reason")
        for model in ("model-a", "model-b")
    }
    assert reasons == {"model-a": "model-a called a tool", "model-b": "model-b called a tool"}, (
        f"a model's capabilities were lost to a write made at the same time: {reasons}"
    )
