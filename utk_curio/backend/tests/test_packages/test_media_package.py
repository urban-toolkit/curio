"""The ``curio.media@1`` nodes, run the way the canvas runs them.

Each template's source is indented and wrapped in ``def userCode(arg):`` as
``PythonInterpreter.ts`` does, and fed the rows ``curio_collection`` returns
for the example storage source's collections, so the input is what a Data
Loading node would hand it.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[4]
PACKAGE = REPO / "packages" / "curio.media@1"
EXAMPLE = REPO / "datalakes" / "lake.curio.example-storage@1"


def node_source(name: str, **settings) -> str:
    code = (PACKAGE / "sources" / f"{name}.py").read_text(encoding="utf-8")
    for key, value in settings.items():
        prefix = f"{key} = "
        lines = code.splitlines()
        for index, line in enumerate(lines):
            if line.startswith(prefix):
                lines[index] = f"{prefix}{value!r}"
        code = "\n".join(lines)
    return code


def run_node(name: str, arg, namespace: dict, **settings):
    body = "\n".join("    " + line for line in node_source(name, **settings).splitlines())
    ns = dict(namespace)
    exec(f"def userCode(arg):\n{body}", ns)  # noqa: S102 - the canvas does exactly this
    return ns["userCode"](arg)


@pytest.fixture()
def collection(tmp_path):
    """``(rows_for(resource_id), helpers)`` over the example source."""
    from utk_curio.backend.app.datalakes.application import index_collection, scan
    from utk_curio.backend.app.datalakes.domain.manifest import load_source_manifest
    from utk_curio.backend.app.datalakes.infrastructure.storage import storage_root
    from utk_curio.backend.app.datalakes.providers import build_storage
    from utk_curio.sandbox.util.collections import make_collection_helpers

    manifest = load_source_manifest(EXAMPLE)
    provider = build_storage(manifest, None)
    media_dir = tmp_path / "media"

    def rows_for(resource_id: str):
        selection = scan.parse_resource_id(manifest, resource_id)
        result = scan.scan(manifest, provider, selection=selection)
        files = [f for g in result.groups for f in g.files]
        frame, columns = index_collection.to_frame(
            selection.spec, index_collection.build_rows(manifest, provider, selection.spec, files)
        )
        index_path = tmp_path / f"{resource_id}.parquet"
        index_collection.write_index(selection.spec, frame, columns, index_path)
        helpers = make_collection_helpers(
            lambda _id: str(index_path),
            {f"imported.x{resource_id}": {"root": str(storage_root(manifest))}},
            str(media_dir),
            output_dir=str(tmp_path / "outputs"),
        )
        return helpers["curio_collection"](f"imported.x{resource_id}"), helpers

    return rows_for


def test_the_manifest_validates_and_names_three_nodes():
    from utk_curio.backend.app.packages.manifest import load_packageage_manifest

    manifest = load_packageage_manifest(PACKAGE)
    raw = json.loads((PACKAGE / "manifest.json").read_text(encoding="utf-8"))
    assert [t["id"] for t in raw["templates"]] == ["video-frames", "split-audio", "mosaic-rasters"]
    assert manifest.python_deps["av"] and manifest.python_deps["rasterio"]


def test_sample_video_frames_makes_image_rows(collection):
    from PIL import Image

    media, helpers = collection("survey")
    frames = run_node("video-frames", media, helpers, EVERY_SECONDS=0.5)
    assert list(frames["t_s"]) == [0.0, 0.5, 1.0]
    assert set(frames["kind"]) == {"frame"}
    assert set(frames["sequence"]) == {"clip_01.mp4"}
    assert all(fid.endswith(f"@{ms}") for fid, ms in zip(frames["file_id"], (0, 500, 1000)))
    for path in frames["path"]:
        with Image.open(path) as image:
            assert image.format == "JPEG" and image.size == (64, 48)
    assert frames["thumbnail"].str.contains("variant=thumb").all()
    assert "year" in frames.columns  # the video's own field travels with its frames


def test_split_audio_measures_each_window(collection):
    media, helpers = collection("noise")
    windows = run_node("split-audio", media, helpers, WINDOW_SECONDS=0.25)
    quiet = windows[
        (windows["sensor"] == "sensor_01") & (windows["recorded_at"].astype(str).str.startswith("2024-05-01 06"))
    ]
    assert len(quiet) == 2
    # A 0.2-amplitude sine: RMS 0.2/sqrt(2), peak 0.2.
    assert quiet["level_dbfs"].iloc[0] == pytest.approx(20 * math.log10(0.2 / math.sqrt(2)), abs=0.3)
    assert quiet["peak_dbfs"].iloc[0] == pytest.approx(20 * math.log10(0.2), abs=0.3)
    assert str(quiet["recorded_at"].iloc[1]) == "2024-05-01 06:00:00.250000"
    assert all(Path(p).stat().st_size > 44 for p in windows["path"])


def test_mosaic_rasters_joins_adjacent_tiles(collection):
    import numpy as np
    import rasterio

    tiles, helpers = collection("orthos")
    one_year = tiles[tiles["year"] == 2024]
    mosaic = run_node("mosaic-rasters", one_year, helpers)
    assert mosaic.name.endswith(".vrt")
    assert (mosaic.width, mosaic.height, mosaic.count) == (64, 32, 3)
    assert mosaic.crs.to_epsg() == 32616
    left = rasterio.open(one_year.sort_values("tile")["path"].iloc[0]).read(1)
    assert np.array_equal(mosaic.read(1)[:, :32], left)


def test_mosaic_rasters_names_what_differs(collection):
    tiles, helpers = collection("orthos")
    mixed = tiles.copy()
    mixed.loc[mixed.index[0], "crs"] = "EPSG:4326"
    with pytest.raises(ValueError, match="differ in crs"):
        run_node("mosaic-rasters", mixed, helpers)


def test_an_uncached_file_is_named_not_crashed_on(collection):
    media, helpers = collection("survey")
    media = media.copy()
    media["path"] = None
    with pytest.raises(ValueError, match="cache the collection's files first"):
        run_node("video-frames", media, helpers)
