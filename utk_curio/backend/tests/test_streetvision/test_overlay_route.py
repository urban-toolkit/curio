"""The overlay route serves the caller's own overlay, and nobody else's.

``/inference/overlay/<image_id>`` requires a signed-in caller and resolves the
overlay cache from that caller. A plain ``<img src>`` cannot carry the header,
so Simple View fetches these with the token and renders the bytes through an
object URL.

These tests pin the contract: with the token you get your file, without it you
get nothing, and another account's token does not reach it.
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
        user_id, _token = _signup(client)
        _write_overlay(str(user_id), "pano.jpg")

        resp = client.get("/api/streetvision/inference/overlay/pano.jpg")

        assert resp.status_code == 401

    def test_an_id_cannot_climb_out_of_the_overlay_directory(self, client, tmp_path):
        user_id, token = _signup(client)
        _write_overlay(str(user_id), "pano.jpg")
        outside = os.path.join(cache.user_root(str(user_id)), "secret_overlay.png")
        with open(outside, "wb") as handle:
            handle.write(b"not-an-overlay")

        resp = client.get(
            "/api/streetvision/inference/overlay/../secret.png",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 404
        assert cache.overlay_path(str(user_id), "../secret.png") is None

    def test_one_users_token_does_not_reach_anothers_overlay(self, client):
        owner_id, _owner_token = _signup(client, "alice")
        _other_id, other_token = _signup(client, "bob")
        _write_overlay(str(owner_id), "pano.jpg")

        resp = client.get(
            "/api/streetvision/inference/overlay/pano.jpg",
            headers={"Authorization": f"Bearer {other_token}"},
        )

        assert resp.status_code == 404
