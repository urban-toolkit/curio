"""Every API path the evaluation harnesses call is a real route.

The browser tier and the live-model driver build their URLs as f-strings, so a
wrong prefix is invisible until a browser run reaches it: the reconstruction
e2e posted to ``/api/datasets/dataflows/<id>/datasets/install`` for a week and
failed only as an HTTP 404 in CI. This matches each literal ``/api/...`` path
against the app's URL map instead, with no browser and no server.
"""

import re
from pathlib import Path

import pytest
from werkzeug.exceptions import MethodNotAllowed, NotFound

REPO = Path(__file__).resolve().parents[4]
FILES = [
    "utk_curio/backend/app/agents/evaluation/live.py",
    "utk_curio/backend/tests/test_frontend/test_example_reconstruction_e2e.py",
]
# An f-string whose path starts at /api/, optionally after one {base} part.
URL = re.compile(r'f"(?:\{[^}]*\})?(/api/[^"?]*)')


@pytest.mark.parametrize("rel", FILES)
def test_every_api_path_the_harness_calls_is_a_route(app, rel):
    adapter = app.url_map.bind("localhost")
    missing = []
    for match in URL.finditer((REPO / rel).read_text(encoding="utf-8")):
        path = re.sub(r"\{[^}]+\}", "x", match.group(1))
        try:
            adapter.match(path, method="POST")
        except MethodNotAllowed:
            pass  # served under another method: the path exists
        except NotFound:
            missing.append(match.group(1))
    assert not missing, f"{rel} calls paths no blueprint serves: {missing}"
