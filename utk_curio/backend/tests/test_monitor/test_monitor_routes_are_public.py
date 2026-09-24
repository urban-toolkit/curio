"""The monitor is public and ungated, on every instance.

Two decisions are pinned here, and both were deliberate:

1. No authentication. The page is meant to be openable by whoever is hitting a
   problem, without an operator in the loop.
2. No deploy gate. The routes exist whether or not `--deploy` was passed. An
   earlier draft gated them on deploy mode; that was dropped because a laptop
   benefits from the error log as much as a server does.

Both are the kind of thing a later "tighten this up" change would quietly undo,
which is why they get a test rather than a comment.
"""

import pytest

ROUTES = ("/api/monitor", "/api/monitor/errors")


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("no_auth", ["0", "1"])
def test_reachable_without_a_token_in_either_posture(client, monkeypatch, route, no_auth):
    # CURIO_NO_AUTH=0 is what --deploy sets; 1 is a local launch. The routes
    # must answer the same way in both.
    monkeypatch.setenv("CURIO_NO_AUTH", no_auth)
    response = client.get(route)
    assert response.status_code == 200, response.get_data(as_text=True)


@pytest.mark.parametrize("route", ROUTES)
def test_an_authorization_header_is_neither_required_nor_rejected(client, route):
    assert client.get(route).status_code == 200
    assert client.get(route, headers={"Authorization": "Bearer nonsense"}).status_code == 200


def test_the_client_error_endpoint_is_public_too(client):
    response = client.post("/api/monitor/errors/client", json={"message": "boom"})
    assert response.status_code == 204
