"""The Street View Fetcher and HF CV Inference routes are gone.

Street-level images come from the Discovery Catalog now, and a model runs in
the sandbox through Image Segmentation, so nothing answers under
``/api/streetvision`` any more: not the fetch that took a Google key in its
body, and not the inference thread.
"""

import json
import uuid

import pytest

REMOVED = [
    ("GET", "/api/streetvision/health"),
    ("GET", "/api/streetvision/models/search?q=cityscapes"),
    ("GET", "/api/streetvision/data/streetview/search_place?q=Lincoln+Park"),
    ("POST", "/api/streetvision/data/streetview/coverage"),
    ("POST", "/api/streetvision/data/streetview/fetch"),
    ("POST", "/api/streetvision/inference/run"),
    ("GET", "/api/streetvision/inference/results/job-1"),
    ("GET", "/api/streetvision/inference/overlay/a.jpg"),
]


def _token(client) -> str:
    resp = client.post(
        "/api/auth/signup",
        data=json.dumps({"name": "Alice", "username": f"sv_{uuid.uuid4().hex[:10]}",
                         "password": "password123"}),
        content_type="application/json",
    )
    assert resp.status_code == 201, resp.get_data(as_text=True)
    return resp.get_json()["token"]


def test_no_rule_is_left_under_the_prefix(app):
    # A request's 404 alone cannot tell a removed route from one that said
    # "job not found"; the URL map can.
    rules = sorted(r.rule for r in app.url_map.iter_rules() if r.rule.startswith("/api/streetvision"))
    assert rules == []


@pytest.mark.parametrize("method,path", REMOVED, ids=[p for _, p in REMOVED])
def test_the_route_answers_404(client, method, path):
    headers = {"Authorization": f"Bearer {_token(client)}"}
    resp = client.open(path, method=method, headers=headers, json={} if method == "POST" else None)
    assert resp.status_code == 404, (path, resp.status_code)
