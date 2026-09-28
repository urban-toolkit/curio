"""What the inference worker will open, and who can read a job.

The request body names every image. A local path is accepted only inside the
caller's own image cache, an http(s) URL is fetched through the egress policy,
and a job answers only the account that started it.
"""

import json
import os
import time

import pytest

from utk_curio.backend.app.agents import egress
from utk_curio.backend.app.streetvision import jobs
from utk_curio.backend.app.streetvision.services import cache
from utk_curio.backend.app.streetvision.services import inference as inference_svc


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


@pytest.fixture()
def seen(monkeypatch):
    """Record what reaches the model instead of running one."""
    prepared = []

    def fake_run_batch(images, *_args, progress_cb=None, **_kwargs):
        prepared.extend(images)
        for img in images:
            yield {"image_id": img.get("image_id"), "ok": True}

    monkeypatch.setattr(inference_svc, "run_batch", fake_run_batch)
    return prepared


def _run(images, user_key):
    job_id = jobs.create_job(total_images=len(images), owner=user_key)
    jobs.start_inference(
        job_id=job_id, images=images, model_id="m", model_type="segmentation",
        classes=[], user_key=user_key,
    )
    for _ in range(200):
        job = jobs.get_job(job_id, owner=user_key)
        if job["status"] in ("completed", "failed"):
            return job
        time.sleep(0.01)
    raise AssertionError("worker did not finish")


class TestLocalPaths:
    def test_a_file_in_the_callers_cache_is_used(self, app, seen):
        cached = os.path.join(cache.images_dir("guest"), "img_cached.jpg")
        with open(cached, "wb") as handle:
            handle.write(b"jpeg")
        job = _run([{"image_id": "a", "local_path": cached}], "guest")
        assert job["status"] == "completed"
        assert [img["local_path"] for img in seen] == [cached]

    def test_a_path_outside_the_cache_is_refused(self, app, seen, tmp_path):
        outside = tmp_path / "private.jpg"
        outside.write_bytes(b"jpeg")
        job = _run(
            [
                {"image_id": "a", "local_path": str(outside)},
                {"image_id": "b", "image_url": str(outside)},
            ],
            "guest",
        )
        assert seen == []
        errors = [r for r in job["results"] if "error" in r]
        assert {r["image_id"] for r in errors} == {"a", "b"}


class TestRemoteImages:
    def test_a_url_goes_through_the_egress_policy(self, app, seen, monkeypatch):
        calls = []

        def fake_download(url, *, sink, max_bytes, **_kwargs):
            calls.append((url, max_bytes))
            sink(b"jpeg")
            return egress.DownloadResult(
                url=url, final_url=url, status=200, content_type="image/jpeg",
                bytes_written=4, sha256="0" * 64,
            )

        monkeypatch.setattr(egress, "download", fake_download)
        _run([{"image_id": "a", "image_url": "https://example.org/a.jpg"}], "guest")
        assert calls == [("https://example.org/a.jpg", jobs.MAX_IMAGE_BYTES)]
        assert len(seen) == 1

    def test_a_private_address_is_refused(self, app, seen):
        job = _run([{"image_id": "a", "image_url": "http://127.0.0.1:9/a.jpg"}], "guest")
        assert seen == []
        assert "EgressRefused" in job["results"][0]["error"]


class TestJobsBelongToTheirOwner:
    def test_run_requires_a_signed_in_caller(self, client):
        resp = client.post("/api/streetvision/inference/run", json={"images": []})
        assert resp.status_code == 401

    def test_another_account_cannot_read_a_job(self, client, seen):
        _alice, alice_token = _signup(client, "alice")
        _bob, bob_token = _signup(client, "bob")
        resp = client.post(
            "/api/streetvision/inference/run",
            json={
                "images": [{"image_id": "a", "image_url": "not-a-url"}],
                "model": {"model_id": "m", "model_type": "segmentation"},
            },
            headers={"Authorization": f"Bearer {alice_token}"},
        )
        assert resp.status_code == 200, resp.get_data(as_text=True)
        job_id = resp.get_json()["job_id"]

        own = client.get(
            f"/api/streetvision/inference/results/{job_id}",
            headers={"Authorization": f"Bearer {alice_token}"},
        )
        other = client.get(
            f"/api/streetvision/inference/results/{job_id}",
            headers={"Authorization": f"Bearer {bob_token}"},
        )
        assert own.status_code == 200
        assert "owner" not in own.get_json()
        assert other.status_code == 404
