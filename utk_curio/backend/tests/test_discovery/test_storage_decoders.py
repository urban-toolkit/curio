"""A collection file is decoded only as the format its bytes show.

The index and the thumbnails read files a manifest points at: an operator's
folder, a public bucket, a Hugging Face repo. Their names are not evidence of
what they are, so every decoder is handed a file only when its first bytes
are a format its kind may be, and only with the one reader for that format.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from urllib.parse import quote

import pytest

from utk_curio.backend.tests.test_discovery.conftest import (
    a_storage_manifest,
    write_files,
    write_source,
)

REPO = Path(__file__).resolve().parents[4]
EXAMPLE_FILES = REPO / "docs" / "examples" / "data" / "storage"
SOURCE = "source.example.folder@1"


@pytest.fixture()
def auth(user_and_token):
    _user, token = user_and_token
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(autouse=True)
def _fresh():
    from utk_curio.backend.app.discovery.application import media, scan

    scan.listings.reset()
    media.index_cache._rows.clear()
    yield
    scan.listings.reset()


def _added(client, auth, resource_id):
    res = client.post(
        f"/api/discovery/sources/{SOURCE}/resources/{quote(resource_id, safe='')}/acquire",
        headers=auth, json={},
    )
    assert res.status_code == 202, res.get_data(as_text=True)
    job_id = res.get_json()["jobId"]
    deadline = time.time() + 15
    while time.time() < deadline:
        job = client.get(f"/api/discovery/jobs/{job_id}", headers=auth).get_json()
        if job["status"] in ("completed", "failed", "refused", "cancelled"):
            assert job["status"] == "completed", job.get("error")
            return job["dataset"]
        time.sleep(0.02)
    raise AssertionError("the add never finished")


class TestANameIsNotAFormat:
    def test_files_whose_bytes_are_not_their_kind_keep_a_row_and_are_never_drawn(
        self, client, auth, app, discovery_dir, tmp_path
    ):
        import pandas as pd

        root = write_files(tmp_path / "f", {
            "tiles/t.tif": "plain text, not a raster",
            "clips/c.mp4": "plain text, not a video",
            "pics/p.jpg": "plain text, not an image",
        })
        write_source(discovery_dir, SOURCE, a_storage_manifest(root, [
            {"id": "tiles", "name": "Tiles", "kind": "rasters", "path": "tiles/*"},
            {"id": "clips", "name": "Clips", "kind": "videos", "path": "clips/*"},
            {"id": "pics", "name": "Pictures", "kind": "images", "path": "pics/*"},
        ]))
        for resource_id, noun in (("tiles", "raster"), ("clips", "video"), ("pics", "image")):
            dataset = _added(client, auth, resource_id)
            row = pd.read_parquet(dataset["path"]).iloc[0]
            assert noun in row["probe_error"] and "Curio reads" in row["probe_error"]
            thumb = client.get(
                f"/api/datasets/{dataset['id']}/media/{row['file_id']}?variant=thumb", headers=auth
            )
            assert thumb.status_code == 415, thumb.get_data(as_text=True)

    def test_each_reader_is_pinned_to_the_format_the_bytes_show(self, monkeypatch):
        import av
        import rasterio
        from PIL import Image

        from utk_curio.backend.app.discovery.application import probe

        seen: dict[str, object] = {}

        def spy(name, real, key):
            def wrapper(*args, **kwargs):
                seen[name] = kwargs.get(key)
                return real(*args, **kwargs)
            return wrapper

        monkeypatch.setattr(rasterio, "open", spy("raster", rasterio.open, "driver"))
        monkeypatch.setattr(av, "open", spy("av", av.open, "format"))
        monkeypatch.setattr(Image, "open", spy("image", Image.open, "formats"))

        assert "probe_error" not in probe.probe_raster(EXAMPLE_FILES / "orthos" / "2024" / "tile_0001.tif")
        assert seen["raster"] == "GTiff"
        assert "probe_error" not in probe.probe_video(EXAMPLE_FILES / "survey" / "2025" / "clip_01.mp4")
        assert seen["av"] == "mov"
        assert "probe_error" not in probe.probe_audio(EXAMPLE_FILES / "noise" / "sensor_01" / "20240501_060000.wav")
        assert seen["av"] == "wav"
        assert "probe_error" not in probe.probe_image(EXAMPLE_FILES / "survey" / "2024" / "IMG_0001.jpg")
        assert seen["image"] == ["JPEG"]

    def test_a_raster_kind_takes_only_tiff_and_jpeg_2000(self, tmp_path):
        from utk_curio.backend.app.discovery.application import probe

        png = tmp_path / "t.tif"
        png.write_bytes((EXAMPLE_FILES / "survey" / "2024" / "IMG_0001.jpg").read_bytes())
        assert "not a GeoTIFF or JPEG 2000 raster" in probe.probe_raster(png)["probe_error"]


class TestProbingAPartialFile:
    def test_a_png_probed_from_its_first_bytes_keeps_its_size(self, tmp_path):
        """A bucket image is indexed from its first 64 KiB. A PNG larger than
        that has its size in the header and nothing else yet."""
        import numpy as np
        from PIL import Image

        from utk_curio.backend.app.discovery.application import probe
        from utk_curio.backend.app.discovery.application.index_collection import PROBE_BYTES

        whole = tmp_path / "whole.png"
        noise = np.random.default_rng(1).integers(0, 255, (400, 300, 3), dtype=np.uint8)
        Image.fromarray(noise).save(whole)
        assert whole.stat().st_size > PROBE_BYTES
        head = tmp_path / "head.png"
        head.write_bytes(whole.read_bytes()[:PROBE_BYTES])
        details = probe.probe_image(head)
        assert "probe_error" not in details, details
        assert (details["width"], details["height"]) == (300, 400)


class TestThumbnailBounds:
    def test_an_image_past_the_pixel_limit_has_no_thumbnail(self, monkeypatch):
        from utk_curio.backend.app.discovery.application import media

        monkeypatch.setattr(media, "MAX_THUMB_SOURCE_PIXELS", 100)
        with pytest.raises(media.MediaUnavailable, match="too large to preview"):
            media._image(EXAMPLE_FILES / "survey" / "2024" / "IMG_0001.jpg")

    def test_two_requests_can_draw_the_same_thumbnail_at_once(self, monkeypatch, tmp_path):
        from PIL import Image

        from utk_curio.backend.app.discovery.application import media

        racers = 6
        barrier = threading.Barrier(racers)

        def draw(_found, _variant):
            barrier.wait(timeout=10)
            return Image.new("RGB", (8, 8), (10, 20, 30))

        monkeypatch.setattr(media, "_draw", draw)
        row = media.IndexRow("a" * 16, "x.jpg", "jpg", "image", 1, "0")
        found = media.Located(dataset_id="d", row=row, local=tmp_path / "x.jpg", provider=None)
        target = tmp_path / "thumb.jpg"
        errors: list[BaseException] = []

        def run():
            try:
                media._render(found, "thumb", target)
            except BaseException as exc:  # noqa: BLE001 - collected for the assertion
                errors.append(exc)

        threads = [threading.Thread(target=run) for _ in range(racers)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert not errors, errors
        assert target.is_file()
        assert not list(tmp_path.glob("*.part"))
