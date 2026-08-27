"""The overlay route serves the caller's own overlay, and nobody else's.

``/inference/overlay/<image_id>`` carries no ``@require_auth`` (the CV Gallery
is a package behavior that may run in a ``--no-project`` install), so it
resolves the user from the Bearer token and falls back to the shared guest key.
That makes the header load-bearing in a way that is easy to miss: the gallery
used to load overlays through a plain ``<img src>``, which cannot carry one, so
every signed-in user's request resolved to "guest", missed, and rendered
"Overlay unavailable" over an overlay that existed on disk the whole time.

These tests pin both halves of the contract: with the token you get your file,
without it you do not get somebody else's.
"""

import json
import os

from utk_curio.backend.app.streetvision.services import cache


def _signup(client, username="alice"):
    resp = client.post(
        "/api/auth/signup",
        data=json.dumps(
            {"name": username.title(), "username": username, "password": "password123"}
        ),
        content_type="application/json",
    )
    assert resp.status_code == 201, resp.get_data(as_text=True)
    body = resp.get_json()
    return body["user"]["id"], body["token"]


def _write_overlay(user_key: str, image_id: str) -> str:
    stem = os.path.splitext(image_id)[0]
    target = os.path.join(cache.overlays_dir(user_key), f"{stem}_overlay.png")
    with open(target, "wb") as handle:
        handle.write(b"\x89PNG-overlay-bytes")
    return target


class TestOverlayIsScopedToTheCaller:
    def test_bearer_token_reaches_that_users_overlay(self, client):
        user_id, token = _signup(client)
        _write_overlay(str(user_id), "pano.jpg")

        resp = client.get(
            "/api/streetvision/inference/overlay/pano.jpg",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert resp.status_code == 200, resp.get_data(as_text=True)
        assert resp.mimetype == "image/png"
        assert resp.get_data() == b"\x89PNG-overlay-bytes"

    def test_without_the_header_a_users_overlay_is_not_served(self, client):
        """The regression: a header-less request resolves to guest and misses.

        This is exactly what a bare ``<img src>`` produced, and it is also the
        cross-user read the per-user cache split exists to prevent, so the 404
        is the correct answer rather than something to relax.
        """
        user_id, _token = _signup(client)
        _write_overlay(str(user_id), "pano.jpg")

        resp = client.get("/api/streetvision/inference/overlay/pano.jpg")

        assert resp.status_code == 404

    def test_one_users_token_does_not_reach_anothers_overlay(self, client):
        owner_id, _owner_token = _signup(client, "alice")
        _other_id, other_token = _signup(client, "bob")
        _write_overlay(str(owner_id), "pano.jpg")

        resp = client.get(
            "/api/streetvision/inference/overlay/pano.jpg",
            headers={"Authorization": f"Bearer {other_token}"},
        )

        assert resp.status_code == 404
