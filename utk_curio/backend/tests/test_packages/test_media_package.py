"""The ``curio.media@1`` nodes, run the way the canvas runs them.

Each template's source is indented as ``PythonInterpreter.ts`` does and run as
the sandbox runs it (``input_names.call_as_node``), fed the rows ``curio_load_collection`` returns
for the example storage source's collections, so the input is what a Data
Loading node would hand it. A starter is its settings and a call into a
module: Media's ``media_collections``, or Rasterization's ``scout_rasters``,
which Media names in ``dependencies.packages``. Both are staged for each run
as the sandbox stages a node's modules (the ``package_modules`` fixture).
"""

from __future__ import annotations

import ast
import json
import math
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[4]
PACKAGE = REPO / "packages" / "curio.media@1"
EXAMPLE = REPO / "discovery" / "source.curio.example-storage@1"
RASTERIZATION = REPO / "packages" / "curio.rasterization@1"
#: Media's module, and Rasterization's, whose mosaic Mosaic Rasters calls.
MODULE = "media_collections"
RASTER_MODULE = "scout_rasters"
#: The modules a run of a Media node is handed: its own package's first, then
#: Rasterization's (``python_modules.modules_for_node``).
MODULES = [
    {"root": str(PACKAGE / "sources"), "names": [MODULE]},
    {"root": str(RASTERIZATION / "sources"), "names": [RASTER_MODULE]},
]
#: Each starter's import, its settings with their values, and the call it returns.
STARTERS = {
    "video-frames": (
        "from media_collections import sample_video_frames",
        {"EVERY_SECONDS": 2.0, "MAX_FRAMES_PER_VIDEO": 300},
        "sample_video_frames(input_0, curio_derived_file, every_seconds=EVERY_SECONDS, "
        "max_frames_per_video=MAX_FRAMES_PER_VIDEO)",
    ),
    "split-audio": (
        "from media_collections import split_audio",
        {"WINDOW_SECONDS": 5.0, "MAX_WINDOWS_PER_RECORDING": 2000},
        "split_audio(input_0, curio_derived_file, window_seconds=WINDOW_SECONDS, "
        "max_windows_per_recording=MAX_WINDOWS_PER_RECORDING)",
    ),
    "mosaic-rasters": (
        "from scout_rasters.mosaic import mosaic_collection",
        {},
        "mosaic_collection(input_0, curio_output_file)",
    ),
}
#: What each module the starters import offers node code: its ``__all__``.
OFFERED = {
    "media_collections": ["sample_video_frames", "split_audio"],
    "scout_rasters.mosaic": ["mosaic_rasters", "mosaic_collection"],
}


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


def run_node(name: str, value, namespace: dict, **settings):
    from utk_curio.sandbox.util.input_names import call_as_node

    body = "\n".join("    " + line for line in node_source(name, **settings).splitlines())
    return call_as_node(body, dict(namespace), value, [0])


def collection_rows(manifest, resource_id: str, tmp_path: Path):
    """``(rows, helpers)``: what ``curio_load_collection`` returns for a resource of
    *manifest*, and the helpers a node runs with."""
    from utk_curio.backend.app.discovery.application import index_collection, scan
    from utk_curio.backend.app.discovery.infrastructure.storage import storage_root
    from utk_curio.backend.app.discovery.providers import build_storage
    from utk_curio.sandbox.util.collections import make_collection_helpers

    provider = build_storage(manifest, None)
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
        str(tmp_path / "media"),
        output_dir=str(tmp_path / "outputs"),
    )
    return helpers["curio_load_collection"](f"imported.x{resource_id}"), helpers


@pytest.fixture()
def package_modules(tmp_path):
    """While the test runs, the modules a run of a Media node is handed
    (``MODULES``) import by name, staged into a folder of the run's own as the
    sandbox stages them (``staging.stage_package_modules``). Yields what was
    staged."""
    from utk_curio.sandbox.util.package_modules import importable
    from utk_curio.sandbox.util.staging import stage_package_modules

    run = tmp_path / "run-media"
    run.mkdir()
    staged = stage_package_modules(MODULES, str(run))
    with importable(str(run / staged["root"]) if staged else None, staged["names"] if staged else []):
        yield staged


@pytest.fixture()
def collection(tmp_path, package_modules):
    """``(rows_for(resource_id), helpers)`` over the example source, with the
    modules a Media node's run is handed importable (``package_modules``)."""
    from utk_curio.backend.app.discovery.domain.manifest import load_source_manifest

    manifest = load_source_manifest(EXAMPLE)
    return lambda resource_id: collection_rows(manifest, resource_id, tmp_path)


@pytest.fixture()
def folder_collection(tmp_path, package_modules):
    """``(rows, helpers)`` for one resource over a folder a test writes, with
    the modules a Media node's run is handed importable (``package_modules``)."""
    from utk_curio.backend.app.discovery.domain.manifest import load_source_manifest
    from utk_curio.backend.tests.test_discovery.conftest import a_storage_manifest, write_source

    def rows_over(root: Path, resource: dict):
        source = write_source(
            tmp_path / "discovery", "source.example.folder@1", a_storage_manifest(root, [resource])
        )
        return collection_rows(load_source_manifest(source), resource["id"], tmp_path)

    return rows_over


def test_the_manifest_validates_and_names_three_nodes():
    from utk_curio.backend.app.packages.repositories.manifests import load_package_manifest

    manifest = load_package_manifest(PACKAGE)
    raw = json.loads((PACKAGE / "manifest.json").read_text(encoding="utf-8"))
    assert [t["id"] for t in raw["templates"]] == ["video-frames", "split-audio", "mosaic-rasters"]
    assert manifest.python_deps["av"] and manifest.python_deps["rasterio"]


def test_media_names_rasterization_and_ships_one_module():
    """Mosaic Rasters calls Rasterization's mosaic, so Media's manifest names
    Rasterization in ``dependencies.packages``, as Deep Umbra's does. Media's
    own module, which Sample Video Frames and Split Audio call, is
    ``media_collections``."""
    from utk_curio.backend.app.packages.repositories.manifests import load_package_manifest
    from utk_curio.backend.app.packages.repositories.python_modules import module_names

    raw = json.loads((PACKAGE / "manifest.json").read_text(encoding="utf-8"))
    assert raw["dependencies"]["packages"] == {"curio.rasterization@1": "*"}
    manifest = load_package_manifest(PACKAGE)
    assert dict(manifest.package_deps) == {"curio.rasterization@1": "*"}
    assert module_names(PACKAGE, manifest) == frozenset({MODULE})


def test_a_run_of_a_media_node_is_handed_its_module_then_rasterizations(tmp_curio, package_modules):
    """A run of each Media node is handed Media's module, then Rasterization's,
    its own first, as any node of a package that names another is
    (``python_modules.modules_for_node``), and a run stages both."""
    from utk_curio.backend.app.packages.application.python_modules import modules_for_node
    from utk_curio.backend.app.packages.application.store_install import install_package_from_directory
    from utk_curio.backend.app.packages.repositories.store import package_dir

    for package in (RASTERIZATION, PACKAGE):
        install_package_from_directory("guest", package)
    handed = [
        {"root": str(package_dir("guest", PACKAGE.name) / "sources"), "names": [MODULE]},
        {"root": str(package_dir("guest", RASTERIZATION.name) / "sources"), "names": [RASTER_MODULE]},
    ]
    for template in STARTERS:
        assert modules_for_node("guest", f"curio.media/{template}") == handed, template
    assert package_modules == {"root": "package_modules", "names": [MODULE, RASTER_MODULE]}, package_modules


@pytest.mark.parametrize("template", sorted(STARTERS))
def test_each_starter_is_its_settings_and_a_call_into_a_module(template):
    """A node's logic is in functions of its package's modules, and its code
    holds its settings and a short call: its docstring, the import of one
    function of a module, its settings as constants, and the return of that
    function's call, which reads every setting. No other statement, so no
    logic of its own, and nothing of Curio's code."""
    imported, settings, call = STARTERS[template]
    code = node_source(template)
    assert "utk_curio" not in code
    body = ast.parse("def node():\n" + "\n".join("    " + line for line in code.splitlines())).body[0].body
    kinds = [type(statement).__name__ for statement in body]
    assert kinds == ["Expr", "ImportFrom", *["Assign"] * len(settings), "Return"], kinds
    assert isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str), ast.dump(body[0])
    assert ast.unparse(body[1]) == imported
    assigned = {
        statement.targets[0].id: ast.literal_eval(statement.value)
        for statement in body[2:-1]
        if len(statement.targets) == 1 and isinstance(statement.targets[0], ast.Name)
    }
    assert assigned == settings
    assert ast.unparse(body[-1].value) == call


def test_the_modules_offer_the_functions_their_all_names(package_modules):
    """What node code calls is what each module's ``__all__`` names: Media's
    ``media_collections`` and Rasterization's ``scout_rasters.mosaic``. Each
    name is a function the module defines, whose docstring's first paragraph
    says what it does, and each starter calls one of them."""
    import importlib
    import inspect

    for name, offered in OFFERED.items():
        module = importlib.import_module(name)
        assert list(module.__all__) == offered, (name, module.__all__)
        for function in offered:
            value = getattr(module, function)
            assert inspect.isfunction(value) and value.__module__ == name, (name, function)
            assert (inspect.getdoc(value) or "").split("\n\n")[0].strip(), (name, function)
    for imported, _settings, call in STARTERS.values():
        module, function = imported.removeprefix("from ").split(" import ")
        assert function in OFFERED[module] and call.startswith(f"{function}("), imported


def test_sample_video_frames_makes_image_rows(collection):
    from PIL import Image

    media, helpers = collection("survey")
    frames = run_node("video-frames", media, helpers, EVERY_SECONDS=0.5)
    # A one-second clip at 10 fps: its frames are 0.0 to 0.9, so there is no
    # frame at 1.0 to sample.
    assert list(frames["t_s"]) == [0.0, 0.5]
    assert list(frames["frame"]) == [0, 5]
    assert set(frames["kind"]) == {"frame"}
    assert set(frames["sequence"]) == {"clip_01.mp4"}
    assert all(fid.endswith(f"@{ms}") for fid, ms in zip(frames["file_id"], (0, 500)))
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


def test_the_uhvi_zonal_node_reads_a_mosaic(collection, tmp_path):
    """The mosaic is the RASTER a zonal-statistics node takes: UHVI Zonal
    Stats averages it under a polygon, as it does any raster. Its code calls
    UHVI's module ``uhvi_statistics``, staged for the run as the sandbox
    stages a UHVI node's modules."""
    import geopandas as gpd
    import numpy as np
    from rasterio.features import geometry_mask
    from shapely.geometry import box

    from utk_curio.sandbox.util.input_names import call_as_node
    from utk_curio.sandbox.util.package_modules import importable
    from utk_curio.sandbox.util.staging import stage_package_modules

    tiles, helpers = collection("orthos")
    mosaic = run_node("mosaic-rasters", tiles[tiles["year"] == 2024], helpers)
    west, south, east, north = mosaic.bounds
    # The mosaic's left half: one tile's footprint.
    zone = box(west, south, (west + east) / 2, north)
    zones = gpd.GeoDataFrame({"zone": ["left"]}, geometry=[zone], crs=mosaic.crs)
    uhvi = REPO / "packages" / "ai.utk.uhvi@1"
    code = (uhvi / "sources" / "uhvi-zonal.py").read_text(encoding="utf-8")
    body = "\n".join("    " + line for line in code.splitlines())
    run = tmp_path / "run-uhvi"
    run.mkdir()
    staged = stage_package_modules({"root": str(uhvi / "sources"), "names": ["uhvi_statistics"]}, str(run))
    assert staged == {"root": "package_modules", "names": ["uhvi_statistics"]}, staged

    # The raster on circle 0 and the zones on circle 1.
    with importable(str(run / staged["root"]), staged["names"]):
        out = call_as_node(body, {}, [mosaic, zones], [0, 1])
    band = mosaic.read(1).astype(float)
    inside = geometry_mask([zone], transform=mosaic.transform, invert=True, out_shape=band.shape)
    assert out["uhvi_mean"].iloc[0] == pytest.approx(float(np.mean(band[inside])))


def test_mosaic_rasters_names_what_differs(collection):
    tiles, helpers = collection("orthos")
    mixed = tiles.copy()
    mixed.loc[mixed.index[0], "crs"] = "EPSG:4326"
    with pytest.raises(ValueError, match="differ in crs"):
        run_node("mosaic-rasters", mixed, helpers)


def test_mosaic_rasters_refuses_a_rotated_tile(collection):
    tiles, helpers = collection("orthos")
    rotated = tiles[tiles["year"] == 2024].copy()
    transform = json.loads(rotated["transform"].iloc[0])
    transform[1] = 0.2
    rotated.loc[rotated.index[0], "transform"] = json.dumps(transform)
    with pytest.raises(ValueError, match="a tile is rotated; only north-up tiles make a mosaic"):
        run_node("mosaic-rasters", rotated, helpers)


def test_mosaic_rasters_code_is_a_short_call_into_rasterizations_mosaic():
    """Mosaic Rasters' code is the call of ``mosaic_collection``, from
    Rasterization's ``scout_rasters.mosaic``, which holds the mosaic, and
    imports nothing of Curio's."""
    code = node_source("mosaic-rasters")
    assert "utk_curio" not in code
    assert "\nfrom scout_rasters.mosaic import mosaic_collection\n" in code
    assert code.rstrip("\n").endswith("\nreturn mosaic_collection(input_0, curio_output_file)")
    assert "<VRTDataset" not in code


def test_an_uncached_file_is_named_not_crashed_on(collection):
    media, helpers = collection("survey")
    media = media.copy()
    media["path"] = None
    with pytest.raises(ValueError, match="cache the collection's files first"):
        run_node("video-frames", media, helpers)


def _raw_mjpeg(path: Path, frames: int = 25) -> None:
    """A video whose file gives no length: raw MJPEG, read at 25 fps."""
    import av
    import numpy as np

    out = av.open(str(path), "w", format="mjpeg")
    stream = out.add_stream("mjpeg", rate=25)
    stream.width, stream.height, stream.pix_fmt = 32, 24, "yuvj420p"
    for i in range(frames):
        image = np.full((24, 32, 3), i * 9, dtype=np.uint8)
        for packet in stream.encode(av.VideoFrame.from_ndarray(image, format="rgb24")):
            out.mux(packet)
    for packet in stream.encode():
        out.mux(packet)
    out.close()


def test_a_video_that_gives_no_length_is_sampled_all_through(folder_collection, tmp_path):
    root = tmp_path / "clips"
    root.mkdir()
    _raw_mjpeg(root / "raw.mjpeg")
    media, helpers = folder_collection(
        root, {"id": "clips", "name": "Clips", "kind": "videos", "path": "*", "extensions": ["mjpeg"]}
    )
    frames = run_node("video-frames", media, helpers, EVERY_SECONDS=0.5)
    assert list(frames["t_s"]) == [0.0, 0.52]


def _stereo_left_only(path: Path, seconds: float = 1.0, rate: int = 8000) -> None:
    """A stereo recording with a 0.5-amplitude tone on its left channel only."""
    import av
    import numpy as np

    t = np.arange(int(seconds * rate)) / rate
    left = (0.5 * np.sin(2 * np.pi * 440 * t) * 32767).astype(np.int16)
    both = np.stack([left, np.zeros_like(left)], axis=1).reshape(1, -1)
    out = av.open(str(path), "w", format="wav")
    stream = out.add_stream("pcm_s16le", rate=rate, layout="stereo")
    frame = av.AudioFrame.from_ndarray(both, format="s16", layout="stereo")
    frame.sample_rate = rate
    for packet in stream.encode(frame):
        out.mux(packet)
    for packet in stream.encode():
        out.mux(packet)
    out.close()


def test_split_audio_measures_every_channel_and_keeps_them(folder_collection, tmp_path):
    import wave

    root = tmp_path / "noise"
    root.mkdir()
    _stereo_left_only(root / "left.wav")
    media, helpers = folder_collection(root, {"id": "noise", "name": "Noise", "kind": "audio", "path": "*"})
    windows = run_node("split-audio", media, helpers, WINDOW_SECONDS=0.5)
    assert len(windows) == 2
    # Over both channels: RMS sqrt((0.5^2 / 2 + 0) / 2) = 0.25, peak 0.5.
    assert windows["level_dbfs"].iloc[0] == pytest.approx(20 * math.log10(0.25), abs=0.3)
    assert windows["peak_dbfs"].iloc[0] == pytest.approx(20 * math.log10(0.5), abs=0.3)
    with wave.open(windows["path"].iloc[0]) as clip:
        assert clip.getnchannels() == 2 and clip.getnframes() == 4000


def _tile(path: Path, x0: float, values, nodata=None) -> None:
    """A 4x4 one-band tile, north-up at *x0*, 1 m pixels, in UTM 16N."""
    import numpy as np
    import rasterio
    from rasterio.transform import from_origin

    data = np.array(values, dtype=np.uint8).reshape(4, 4)
    with rasterio.open(
        path, "w", driver="GTiff", width=4, height=4, count=1, dtype="uint8",
        crs="EPSG:32616", transform=from_origin(x0, 4641000.0, 1.0, 1.0), nodata=nodata,
    ) as dst:
        dst.write(data, 1)


def test_mosaic_rasters_lets_a_tiles_empty_pixels_show_the_tile_below(folder_collection, tmp_path):
    root = tmp_path / "tiles"
    root.mkdir()
    _tile(root / "a.tif", 447000.0, [7] * 16, nodata=0)
    # Two columns over a's right half, the first of them empty.
    _tile(root / "b.tif", 447002.0, [0, 9, 9, 9] * 4, nodata=0)
    tiles, helpers = folder_collection(root, {"id": "t", "name": "Tiles", "kind": "rasters", "path": "*.tif"})
    mosaic = run_node("mosaic-rasters", tiles, helpers)
    assert mosaic.read(1)[0].tolist() == [7, 7, 7, 9, 9, 9]


def test_mosaic_rasters_lays_the_tiles_side_by_side_in_a_vrt_that_points_at_them(folder_collection, tmp_path):
    """The mosaic is a VRT that names each tile's file, each tile where its
    corner falls and the mosaic's corner the north-west tile's."""
    import numpy as np

    root = tmp_path / "tiles"
    root.mkdir()
    _tile(root / "a.tif", 447000.0, list(range(1, 17)), nodata=255)
    _tile(root / "b.tif", 447004.0, list(range(17, 33)), nodata=255)
    tiles, helpers = folder_collection(root, {"id": "t", "name": "Tiles", "kind": "rasters", "path": "*.tif"})
    mosaic = run_node("mosaic-rasters", tiles, helpers)
    with open(mosaic.name, encoding="utf-8") as handle:
        text = handle.read()
    assert len(tiles) == 2 and all(str(path) in text for path in tiles["path"]), text
    left, right = np.arange(1, 17).reshape(4, 4), np.arange(17, 33).reshape(4, 4)
    assert mosaic.read(1).tolist() == np.hstack([left, right]).tolist()
    assert tuple(mosaic.transform)[:6] == (1.0, 0.0, 447000.0, 0.0, -1.0, 4641000.0)


def test_mosaic_rasters_refuses_tiles_whose_empty_value_differs(folder_collection, tmp_path):
    root = tmp_path / "tiles"
    root.mkdir()
    _tile(root / "a.tif", 447000.0, [7] * 16, nodata=0)
    _tile(root / "b.tif", 447004.0, [9] * 16, nodata=255)
    tiles, helpers = folder_collection(root, {"id": "t", "name": "Tiles", "kind": "rasters", "path": "*.tif"})
    with pytest.raises(ValueError, match="differ in nodata"):
        run_node("mosaic-rasters", tiles, helpers)


def test_mosaic_rasters_names_a_tile_that_is_not_georeferenced(folder_collection, tmp_path):
    import numpy as np
    import rasterio

    root = tmp_path / "tiles"
    root.mkdir()
    _tile(root / "a.tif", 447000.0, [7] * 16)
    with rasterio.open(root / "plain.tif", "w", driver="GTiff", width=2, height=2, count=1, dtype="uint8") as dst:
        dst.write(np.zeros((2, 2), dtype=np.uint8), 1)
    tiles, helpers = folder_collection(root, {"id": "t", "name": "Tiles", "kind": "rasters", "path": "*.tif"})
    with pytest.raises(ValueError, match="plain.tif cannot be placed on a map: not georeferenced"):
        run_node("mosaic-rasters", tiles, helpers)
