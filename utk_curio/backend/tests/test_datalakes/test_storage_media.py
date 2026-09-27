"""A collection's files as the browser sees them: by id, sniffed, bounded."""

from __future__ import annotations

import io
import json
import os
import time
from urllib.parse import quote

import pytest

from utk_curio.backend.tests.test_datalakes.conftest import (
    a_storage_manifest,
    write_files,
    write_source,
)

EXAMPLE = "lake.curio.example-storage@1"


@pytest.fixture()
def auth(user_and_token):
    _user, token = user_and_token
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(autouse=True)
def _fresh():
    from utk_curio.backend.app.datalakes.application import media, scan

    scan.listings.reset()
    media.index_cache._rows.clear()
    yield
    scan.listings.reset()


def wait_for(client, auth, job_id, timeout=15.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = client.get(f"/api/datalakes/jobs/{job_id}", headers=auth).get_json()
        if body["status"] in ("completed", "failed", "refused", "cancelled"):
            return body
        time.sleep(0.02)
    raise AssertionError("job never finished")


def collection(client, auth, resource_id, source=EXAMPLE):
    res = client.post(
        f"/api/datalakes/sources/{source}/resources/{quote(resource_id, safe='')}/acquire",
        headers=auth, json={},
    )
    job = wait_for(client, auth, res.get_json()["jobId"])
    assert job["status"] == "completed", job.get("error")
    import pandas as pd

    dataset = job["dataset"]
    return dataset, pd.read_parquet(dataset["path"]).set_index("name")


def media(client, headers, dataset_id, file_id, variant="thumb", **extra):
    return client.get(
        f"/api/datasets/{dataset_id}/media/{file_id}?variant={variant}", headers={**headers, **extra}
    )


def file_id_of(index, name: str) -> str:
    """The first file called *name*: names repeat across folders."""
    rows = index.loc[[name], "file_id"]
    return rows.iloc[0]


def _image_size(data: bytes):
    from PIL import Image

    with Image.open(io.BytesIO(data)) as image:
        return image.size


class TestThumbnails:
    @pytest.mark.parametrize("resource_id, name", [
        ("survey", "IMG_0001.jpg"),
        ("orthos", "tile_0001.tif"),
        ("dashcam", "trip01_000001.jpg"),
        ("noise", "20240501_060000.wav"),
        ("survey", "clip_01.mp4"),
    ])
    def test_every_kind_has_a_jpeg_thumbnail(self, client, auth, app, shipped_root, resource_id, name):
        dataset, index = collection(client, auth, resource_id)
        res = media(client, auth, dataset["id"], file_id_of(index, name))
        assert res.status_code == 200, res.get_data(as_text=True)
        assert res.mimetype == "image/jpeg"
        assert res.headers["X-Content-Type-Options"] == "nosniff"
        width, height = _image_size(res.data)
        assert max(width, height) <= 384

    def test_a_video_has_a_poster_and_an_image_does_not(self, client, auth, app, shipped_root):
        dataset, index = collection(client, auth, "survey")
        assert media(client, auth, dataset["id"], index.loc["clip_01.mp4", "file_id"], "poster").status_code == 200
        assert media(client, auth, dataset["id"], index.loc["IMG_0001.jpg", "file_id"], "poster").status_code == 415

    def test_thumbnails_are_cached_outside_the_source(self, client, auth, app, shipped_root):
        from utk_curio.backend.app.datalakes.infrastructure.storage import storage_root
        from utk_curio.backend.app.datalakes.domain.manifest import load_source_manifest
        from utk_curio.backend.tests.test_datalakes.conftest import SHIPPED_ROOT

        root = storage_root(load_source_manifest(SHIPPED_ROOT / EXAMPLE))
        before = sorted(p.as_posix() for p in root.rglob("*"))
        dataset, index = collection(client, auth, "noise")
        media(client, auth, dataset["id"], index["file_id"].iloc[0])
        assert sorted(p.as_posix() for p in root.rglob("*")) == before


class TestOriginals:
    def test_an_image_video_and_recording_are_served_as_themselves(self, client, auth, app, shipped_root):
        dataset, index = collection(client, auth, "survey")
        photo = media(client, auth, dataset["id"], index.loc["IMG_0001.jpg", "file_id"], "original")
        assert photo.status_code == 200 and photo.mimetype == "image/jpeg"
        clip = media(client, auth, dataset["id"], index.loc["clip_01.mp4", "file_id"], "original",
                     Range="bytes=0-99")
        assert clip.status_code == 206 and clip.mimetype == "video/mp4" and len(clip.data) == 100
        noise, rows = collection(client, auth, "noise")
        wav = media(client, auth, noise["id"], rows["file_id"].iloc[0], "original")
        assert wav.status_code == 200 and wav.mimetype == "audio/wav"

    def test_a_raster_is_never_served_raw(self, client, auth, app, shipped_root):
        dataset, index = collection(client, auth, "orthos")
        assert media(client, auth, dataset["id"], index["file_id"].iloc[0], "original").status_code == 415

    def test_a_file_that_is_not_what_its_name_says_is_refused(self, client, auth, app, lake_root, tmp_path):
        root = write_files(tmp_path / "evil", {"page.jpg": "<html><script>alert(1)</script></html>"})
        write_source(lake_root, "lake.example.folder@1", a_storage_manifest(root, [
            {"id": "pics", "name": "Pics", "kind": "images", "path": "*"}
        ]))
        dataset, index = collection(client, auth, "pics", source="lake.example.folder@1")
        file_id = index.loc["page.jpg", "file_id"]
        assert media(client, auth, dataset["id"], file_id, "original").status_code == 415
        assert media(client, auth, dataset["id"], file_id, "thumb").status_code == 415


class TestWhoCanSeeIt:
    def test_a_token_is_required(self, client, auth, app, shipped_root):
        dataset, index = collection(client, auth, "noise")
        assert media(client, {}, dataset["id"], index["file_id"].iloc[0]).status_code == 401

    def test_another_account_cannot_reach_it(self, client, auth, app, shipped_root, db):
        from utk_curio.backend.app.users.models import User, UserSession

        dataset, index = collection(client, auth, "noise")
        bob = User(username="bob", name="Bob", email="bob@test.com")
        db.session.add(bob)
        db.session.flush()
        db.session.add(UserSession(user_id=bob.id, token="bob-token"))
        db.session.commit()
        res = media(client, {"Authorization": "Bearer bob-token"}, dataset["id"], index["file_id"].iloc[0])
        assert res.status_code == 404

    def test_an_unknown_file_id_is_not_found(self, client, auth, app, shipped_root):
        dataset, _index = collection(client, auth, "noise")
        assert media(client, auth, dataset["id"], "0" * 16).status_code == 404
        assert media(client, auth, dataset["id"], "../../etc").status_code == 404


class TestSignedLinks:
    def _link(self, client, auth, dataset_id, file_id):
        res = client.post(f"/api/datasets/{dataset_id}/media/{file_id}/link", headers=auth)
        assert res.status_code == 200, res.get_data(as_text=True)
        return res.get_json()["url"]

    def test_a_link_plays_without_a_token_and_with_range(self, client, auth, app, shipped_root):
        dataset, index = collection(client, auth, "survey")
        url = self._link(client, auth, dataset["id"], index.loc["clip_01.mp4", "file_id"])
        assert url.startswith("/api/media/")
        whole = client.get(url)
        assert whole.status_code == 200 and whole.mimetype == "video/mp4"
        part = client.get(url, headers={"Range": "bytes=10-19"})
        assert part.status_code == 206 and part.data == whole.data[10:20]

    def test_a_tampered_link_is_refused(self, client, auth, app, shipped_root):
        dataset, index = collection(client, auth, "noise")
        url = self._link(client, auth, dataset["id"], index["file_id"].iloc[0])
        assert client.get(url[:-2] + ("aa" if not url.endswith("aa") else "bb")).status_code == 404

    def test_a_link_expires(self, client, auth, app, shipped_root, monkeypatch):
        from utk_curio.backend.app.datalakes.application import media as media_module

        dataset, index = collection(client, auth, "noise")
        url = self._link(client, auth, dataset["id"], index["file_id"].iloc[0])
        monkeypatch.setattr(media_module, "LINK_TTL_SECONDS", -1)
        assert client.get(url).status_code == 404

    def test_no_link_is_minted_for_what_a_browser_cannot_show(self, client, auth, app, shipped_root):
        dataset, index = collection(client, auth, "orthos")
        res = client.post(f"/api/datasets/{dataset['id']}/media/{index['file_id'].iloc[0]}/link", headers=auth)
        assert res.status_code == 415


def test_the_sniffer_knows_the_allowlisted_formats():
    from utk_curio.backend.app.datalakes.application.media import sniff

    assert sniff(b"\xff\xd8\xff\xe0") == "image/jpeg"
    assert sniff(b"\x89PNG\r\n\x1a\n") == "image/png"
    assert sniff(b"RIFF\x00\x00\x00\x00WAVE") == "audio/wav"
    assert sniff(b"\x00\x00\x00\x18ftypisom") == "video/mp4"
    assert sniff(b"<svg xmlns=") is None
    assert sniff(b"<html>") is None


class TestDerivedFiles:
    def test_a_frame_a_node_wrote_is_served_by_its_id(self, client, auth, app, shipped_root, user_and_token):
        from PIL import Image

        from utk_curio.backend.app.datalakes.infrastructure import media_dirs
        from utk_curio.sandbox.util.collections import make_collection_helpers

        user, _token = user_and_token
        dataset, index = collection(client, auth, "survey")
        video_id = file_id_of(index, "clip_01.mp4")
        derive = make_collection_helpers(None, {}, str(media_dirs.media_work_root(str(user.id))))[
            "curio_derived_file"
        ]
        row = derive(dataset["id"], video_id, 500)
        Image.new("RGB", (64, 48), (200, 30, 30)).save(row["path"], "JPEG")
        thumb = client.get(row["thumbnail"], headers=auth)
        assert thumb.status_code == 200 and thumb.mimetype == "image/jpeg"
        original = client.get(row["image_url"], headers=auth)
        assert original.status_code == 200 and original.mimetype == "image/jpeg"
        assert media(client, auth, dataset["id"], f"{video_id}@999").status_code == 404

    def test_only_a_video_or_recording_has_derived_files(self, client, auth, app, shipped_root):
        dataset, index = collection(client, auth, "survey")
        photo = file_id_of(index, "IMG_0001.jpg")
        assert media(client, auth, dataset["id"], f"{photo}@500").status_code == 404


class TestExecutionResolution:
    def test_code_that_reads_a_collection_gets_its_root_and_a_media_directory(
        self, client, auth, app, shipped_root, user_and_token
    ):
        from flask import g

        from utk_curio.backend.app.api.routes import _resolve_exec_collections, _resolve_exec_dataset_paths
        from utk_curio.backend.app.datalakes.infrastructure.storage import storage_root
        from utk_curio.backend.app.datalakes.domain.manifest import load_source_manifest
        from utk_curio.backend.tests.test_datalakes.conftest import SHIPPED_ROOT

        user, _token = user_and_token
        dataset, _index = collection(client, auth, "noise")
        code = f'    frame = curio_collection("{dataset["id"]}")\n    x = curio_collection("imported.xnone")\n'
        with app.test_request_context():
            g.user = user
            collections, media_dir = _resolve_exec_collections(code, str(user.id))
            paths = _resolve_exec_dataset_paths(code, None)
        root = storage_root(load_source_manifest(SHIPPED_ROOT / EXAMPLE))
        assert collections == {dataset["id"]: {"kind": "audio", "root": str(root)}}
        assert media_dir and media_dir.endswith(os.path.join(str(user.id), "media"))
        assert paths[dataset["id"]] == dataset["path"]

    def test_a_collection_call_counts_as_using_the_dataset(self):
        from utk_curio.backend.app.datasets.domain.code_refs import (
            collection_ids_in_code,
            dataset_ids_in_code,
        )

        code = 'a = curio_collection("imported.xa@1")\nb = curio_dataset_path("imported.xb")'
        assert dataset_ids_in_code(code) == ["imported.xa@1", "imported.xb"]
        assert collection_ids_in_code(code) == ["imported.xa@1"]


class TestSampleThumbnails:
    def test_a_rows_samples_are_drawn_by_position(self, client, auth, app, shipped_root):
        for _ in range(100):
            body = client.get(f"/api/datalakes/sources/{EXAMPLE}/search", headers=auth).get_json()
            if body["sources"][0]["status"] == "ok":
                break
            time.sleep(0.05)
        row = next(r for r in body["resources"] if r["resourceId"] == "orthos")
        assert row["samples"]
        res = client.get(f"/api/datalakes/sources/{EXAMPLE}/thumbnails/0/orthos", headers=auth)
        assert res.status_code == 200 and res.mimetype == "image/jpeg"
        assert client.get(f"/api/datalakes/sources/{EXAMPLE}/thumbnails/99/orthos", headers=auth).status_code == 404
        assert client.get(f"/api/datalakes/sources/{EXAMPLE}/thumbnails/0/orthos").status_code == 401
