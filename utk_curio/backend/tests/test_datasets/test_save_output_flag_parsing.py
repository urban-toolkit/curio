"""``saveOutputDataset`` string parsing on both execution routes.

The frontend can send this flag as a string. Backend and sandbox share one
falsy vocabulary (``0/false/no/off``); ``'off'`` was the last one to be aligned
and had no test, so a regression would silently start persisting a computed
dataset for every run of a node the user had opted out of.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from utk_curio.backend.tests.test_datasets.computed_test_helpers import auth_headers

FALSY = ["0", "false", "False", "FALSE", "no", "off", "OFF", " off "]
TRUTHY = ["1", "true", "True", "yes", "on"]


def _capture(monkeypatch):
    captured = {}
    resp = MagicMock()
    resp.json.return_value = {"stdout": "", "stderr": "", "output": {}}

    def fake_call(method, path, **kwargs):
        captured["body"] = json.loads(kwargs["data"])
        return resp

    monkeypatch.setattr("utk_curio.backend.app.api.routes._sandbox_call", fake_call)
    return captured


def _post(client, token, route, flag):
    return client.post(
        route,
        data=json.dumps({
            "code": "    return arg\n",
            "nodeType": "PYTHON_COMPUTATION",
            "input": {"path": "", "dataType": "str"},
            "saveOutputDataset": flag,
        }),
        headers=auth_headers(token),
    )


@pytest.mark.parametrize("route", ["/processPythonCode", "/processJavaScriptCode"])
@pytest.mark.parametrize("flag", FALSY)
def test_falsy_strings_disable_saving(client, user_and_token, monkeypatch, route, flag):
    _, token = user_and_token
    captured = _capture(monkeypatch)
    resp = _post(client, token, route, flag)
    assert resp.status_code == 200, resp.get_data(as_text=True)
    assert captured["body"]["save_dataset"] is False, flag


@pytest.mark.parametrize("route", ["/processPythonCode", "/processJavaScriptCode"])
@pytest.mark.parametrize("flag", TRUTHY)
def test_truthy_strings_enable_saving(client, user_and_token, monkeypatch, route, flag):
    _, token = user_and_token
    captured = _capture(monkeypatch)
    resp = _post(client, token, route, flag)
    assert resp.status_code == 200, resp.get_data(as_text=True)
    assert captured["body"]["save_dataset"] is True, flag
