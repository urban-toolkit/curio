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
    # Its bottom circle, where to cut, is input_1: None when nothing is wired there.
    "split-video": (
        "from media_collections import split_video",
        {"BLOCK_SECONDS": 60.0, "WIDTH": 960, "MAX_FRAMES": 30000},
        "split_video(input_0, curio_derived_file, input_1, block_seconds=BLOCK_SECONDS, width=WIDTH, "
        "max_frames=MAX_FRAMES)",
    ),
    "mosaic-rasters": (
        "from scout_rasters.mosaic import mosaic_collection",
        {},
        "mosaic_collection(input_0, curio_output_file)",
    ),
}
#: What each module the starters import offers node code: its ``__all__``.
OFFERED = {
    "media_collections": ["sample_video_frames", "split_audio", "split_video"],
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


def test_the_manifest_validates_and_names_four_nodes():
    from utk_curio.backend.app.packages.repositories.manifests import load_package_manifest

    manifest = load_package_manifest(PACKAGE)
    raw = json.loads((PACKAGE / "manifest.json").read_text(encoding="utf-8"))
    assert [t["id"] for t in raw["templates"]] == ["video-frames", "split-audio", "split-video", "mosaic-rasters"]
    assert manifest.python_deps["av"] and manifest.python_deps["rasterio"]


def test_split_video_has_a_top_circle_and_an_optional_bottom_one():
    """Split Video's two circles: the collection's rows on top, one edge; where
    to cut below, which nothing need be wired to (``[0,1]``). A node of two
    ports takes one edge on each, and the roster says the bottom one may
    stay empty."""
    from utk_curio.backend.app.packages.application.templates import _input_arity
    from utk_curio.backend.app.packages.repositories.manifests import load_package_manifest

    (template,) = [t for t in load_package_manifest(PACKAGE).templates if t.template_id == "split-video"]
    assert [port.cardinality for port in template.input_ports] == ["1", "[0,1]"]
    inputs, capacity = _input_arity(template)
    assert [(port["min"], port["max"]) for port in inputs] == [(1, 1), (0, 1)]
    assert capacity == 2


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


def test_sample_video_frames_reads_each_video_once_with_frame_threading(folder_collection, tmp_path, monkeypatch):
    """Sample Video Frames reads a video once, from its start, with frame
    threading, as Track Objects and Split Video read one. On dev its defaults,
    a frame every 2 s and 300 at most, ran past a node's 300 s on the 864 s
    SideSeeing walk, whose key frames are 8.3 s apart: it sought each of the
    300 frames, decoding from the key frame before it, about 125 frames for
    each, with slice threading."""
    import importlib

    import av

    media, helpers = _walks(folder_collection, tmp_path, {"walk.mp4": 7.0})
    module = importlib.import_module(MODULE)
    reads, seeks = [], []
    real_open = av.open

    class _Recording:
        """The container the node opens, noting each read, how it is threaded, and each seek."""

        def __init__(self, container):
            self._container = container

        def __enter__(self):
            self._container.__enter__()
            return self

        def __exit__(self, *exc):
            return self._container.__exit__(*exc)

        def __getattr__(self, name):
            return getattr(self._container, name)

        def seek(self, *args, **kwargs):
            seeks.append(args)
            return self._container.seek(*args, **kwargs)

        def decode(self, *args, **kwargs):
            threading = args[0].thread_type if args else None
            reads.append(getattr(threading, "name", threading))
            return self._container.decode(*args, **kwargs)

    monkeypatch.setattr(module.av, "open", lambda *args, **kwargs: _Recording(real_open(*args, **kwargs)))
    frames = run_node("video-frames", media, helpers, EVERY_SECONDS=0.5)
    # The same frames as before: the first at or past each half second.
    assert list(frames["t_s"]) == [k / 2 for k in range(14)]
    assert list(frames["frame"]) == [5 * k for k in range(14)]
    assert (reads, seeks) == (["AUTO"], []), (reads, seeks)


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


# ---------------------------------------------------------------------------
# Split Video
# ---------------------------------------------------------------------------

def _clip(path: Path, seconds: float, rate: int = 10, size: tuple[int, int] = (96, 64)) -> None:
    """A clip *seconds* long at *rate* frames a second, an orange box crossing a
    dark street, in MPEG-4 Part 2, which every FFmpeg build reads and writes."""
    import av
    import numpy as np

    width, height = size
    with av.open(str(path), "w") as out:
        stream = out.add_stream("mpeg4", rate=rate)
        stream.width, stream.height, stream.pix_fmt = width, height, "yuv420p"
        for index in range(round(seconds * rate)):
            image = np.full((height, width, 3), 40, dtype=np.uint8)
            left = (4 * index) % (width - 16)
            image[20:44, left:left + 16] = (230, 120, 40)
            for packet in stream.encode(av.VideoFrame.from_ndarray(image, format="rgb24")):
                out.mux(packet)
        for packet in stream.encode():
            out.mux(packet)


def _walks(folder_collection, tmp_path: Path, clips: dict[str, float]):
    """``(rows, helpers)`` for a folder of clips, each ``{name: seconds}``."""
    root = tmp_path / "walks"
    root.mkdir()
    for name, seconds in clips.items():
        _clip(root / name, seconds)
    return folder_collection(
        root, {"id": "walks", "name": "Walks", "kind": "videos", "path": "*", "extensions": ["mp4"]}
    )


def run_split(media, helpers, cuts=None, **settings):
    """Split Video's code run as the canvas runs it: the collection on its top
    circle, and *cuts* on its bottom one, or nothing wired there when None,
    which its code reads as ``input_1`` None."""
    from utk_curio.sandbox.util.input_names import call_as_node

    body = "\n".join("    " + line for line in node_source("split-video", **settings).splitlines())
    if cuts is None:
        return call_as_node(body, dict(helpers), media, [0])
    return call_as_node(body, dict(helpers), [media, cuts], [0, 1])


def _played(path) -> tuple:
    """``(codec, pixel format, width, height, frame times)`` of a block's file."""
    import av

    with av.open(str(path)) as video:
        context = video.streams.video[0].codec_context
        times = [round(float(frame.time), 3) for frame in video.decode(video=0)]
        return context.name, context.pix_fmt, context.width, context.height, times


def _written(tmp_path: Path) -> list[str]:
    """The names of the blocks written under the media directory."""
    return sorted(path.name for path in (tmp_path / "media").rglob("*.mp4"))


def test_with_nothing_on_its_bottom_circle_split_video_cuts_every_block_seconds(folder_collection, tmp_path):
    """Nothing wired below is ``input_1`` None, and each video is cut every
    BLOCK_SECONDS, the last block what is left. Each block is an H.264 file in
    yuv420p no wider than its video, whose frames play at their own times from
    its start, named after the video, where the block starts and ends and the
    width; its row leads with block, t_s and end_s, where it starts and ends
    in the video, and Simple View plays it."""
    media, helpers = _walks(folder_collection, tmp_path, {"corner.mp4": 7.0})
    video = media.iloc[0]
    blocks = run_split(media, helpers, BLOCK_SECONDS=2.0)
    assert list(blocks.columns[:3]) == ["block", "t_s", "end_s"]
    assert list(blocks["block"]) == [1, 2, 3, 4]
    assert list(blocks["t_s"]) == [0.0, 2.0, 4.0, 6.0]
    assert list(blocks["end_s"]) == [2.0, 4.0, 6.0, 7.0]
    assert list(blocks["duration_s"]) == [2.0, 2.0, 2.0, 1.0]
    assert list(blocks["file_id"]) == [
        f"{video['file_id']}@{start}-to{end}w960.mp4"
        for start, end in ((0, 2000), (2000, 4000), (4000, 6000), (6000, 7000))
    ]
    assert set(blocks["kind"]) == {"video"} and set(blocks["video_file_id"]) == {video["file_id"]}
    assert set(blocks["name"]) == {"corner.mp4"} and set(blocks["dataset_id"]) == {video["dataset_id"]}
    assert blocks["thumbnail"].str.contains("variant=thumb").all() and blocks["audio_url"].isna().all()
    for row in blocks.itertuples():
        codec, pixels, width, height, times = _played(row.path)
        assert (codec, pixels, width, height) == ("h264", "yuv420p", 96, 64)
        assert times == [round(k / 10, 3) for k in range(round(row.duration_s * 10))]


def test_a_block_keeps_its_videos_fields_and_time(collection, folder_collection, tmp_path):
    """A block keeps the video's own fields, as a frame does, and its
    taken_at moves forward by where the block starts."""
    import pandas as pd

    media, helpers = collection("survey")
    blocks = run_split(media, helpers, BLOCK_SECONDS=0.5)
    assert list(blocks["t_s"]) == [0.0, 0.5]
    assert "year" in blocks.columns  # the video's own field travels with its blocks

    media, helpers = _walks(folder_collection, tmp_path, {"corner.mp4": 3.0})
    began = pd.Timestamp("2026-10-26 21:03:17.016")
    blocks = run_split(media.assign(taken_at=began), helpers, BLOCK_SECONDS=1.5)
    assert list(blocks["taken_at"]) == [began, began + pd.Timedelta(seconds=1.5)]


def test_split_video_cuts_where_its_bottom_circle_says_and_keeps_each_cuts_columns(folder_collection, tmp_path):
    """Each row on the bottom circle is a block: from its t_s to its end_s,
    else to where the next starts, else to the video's end, in the order of
    t_s. Its own columns, a street's name say, come right after block, so a
    card's caption leads with them; a cut's columns that a block has of its
    own, such as a frame's width, describe another file and stay out."""
    import pandas as pd

    media, helpers = _walks(folder_collection, tmp_path, {"walk.mp4": 7.0})
    cuts = pd.DataFrame([
        {"t_s": 0.0, "street": "N Halsted St", "from": "W Washington St", "to": "W Randolph St"},
        {"t_s": 4.0, "end_s": 5.0, "street": "N Union Ave", "from": "W Randolph St", "to": "W Lake St"},
        {"t_s": 2.5, "street": "W Randolph St", "from": "N Halsted St", "to": "N Union Ave"},
    ]).assign(width=1920, path="frame.jpg")
    blocks = run_split(media, helpers, cuts, BLOCK_SECONDS=2.0)
    assert list(blocks.columns[:6]) == ["block", "street", "from", "to", "t_s", "end_s"]
    assert list(blocks["street"]) == ["N Halsted St", "W Randolph St", "N Union Ave"]
    assert list(blocks["t_s"]) == [0.0, 2.5, 4.0]
    assert list(blocks["end_s"]) == [2.5, 4.0, 5.0]
    assert list(blocks["width"]) == [96, 96, 96] and "frame.jpg" not in set(blocks["path"])
    assert [len(_played(path)[4]) for path in blocks["path"]] == [25, 15, 10]
    assert blocks["file_id"].iloc[1].endswith("@2500-to4000w960.mp4")


def test_a_cut_with_a_video_file_id_cuts_that_video_and_one_without_every_video(folder_collection, tmp_path):
    import pandas as pd

    media, helpers = _walks(folder_collection, tmp_path, {"a.mp4": 3.0, "b.mp4": 3.0})
    a, b = (media.loc[media["name"] == name, "file_id"].iloc[0] for name in ("a.mp4", "b.mp4"))
    blocks = run_split(media, helpers, pd.DataFrame([{"t_s": 0.0, "video_file_id": a}, {"t_s": 1.0, "video_file_id": a}]))
    # b is no row's: it gets no block.
    assert list(zip(blocks["video_file_id"], blocks["t_s"])) == [(a, 0.0), (a, 1.0)]
    blocks = run_split(media, helpers, pd.DataFrame([{"t_s": 1.0}]))
    assert sorted(blocks["video_file_id"]) == sorted([a, b]) and set(blocks["t_s"]) == {1.0}


EMPTY = object()


@pytest.mark.parametrize(("cuts", "settings", "says"), [
    pytest.param([{"start": 1.0}], {}, "need a t_s column", id="no-t_s"),
    pytest.param(EMPTY, {}, "hold no row", id="no-row"),
    pytest.param([{"t_s": "soon"}], {}, "is a number of seconds", id="t_s-not-a-number"),
    pytest.param([{"t_s": -1.0}], {}, "a block starts at -1 s", id="before-the-start"),
    pytest.param([{"t_s": 9.0}], {}, "lasts 7.000 s, and a block starts at 9 s", id="past-the-end"),
    pytest.param([{"t_s": 0.0, "end_s": 3.0}, {"t_s": 2.0}], {}, "overlaps the one from 2 s", id="overlap"),
    pytest.param([{"t_s": 1.0}, {"t_s": 1.0}], {}, "two blocks start at 1 s", id="same-start"),
    pytest.param([{"t_s": 1.0, "end_s": 0.5}], {}, "before it starts", id="ends-first"),
    pytest.param([{"t_s": 1.0, "end_s": 1.05}], {}, "shorter than one of its frames", id="under-a-frame"),
    pytest.param([{"t_s": 0.0, "video_file_id": "ffffffffffffffff"}], {}, "No row of the cuts", id="no-video"),
    pytest.param(None, {"MAX_FRAMES": 50}, "hold about 70 frames", id="max-frames"),
    pytest.param(None, {"BLOCK_SECONDS": 0}, "BLOCK_SECONDS is the length", id="no-block-length"),
    pytest.param(None, {"WIDTH": 1}, "WIDTH is the widest", id="too-narrow"),
])
def test_split_video_stops_before_it_writes_a_block(folder_collection, tmp_path, cuts, settings, says):
    import re

    import pandas as pd

    media, helpers = _walks(folder_collection, tmp_path, {"corner.mp4": 7.0})
    table = pd.DataFrame(columns=["t_s"]) if cuts is EMPTY else None if cuts is None else pd.DataFrame(cuts)
    with pytest.raises(ValueError, match=re.escape(says)):
        run_split(media, helpers, table, **settings)
    assert _written(tmp_path) == []


def test_split_video_names_a_video_not_on_this_machine(collection, tmp_path):
    media, helpers = collection("survey")
    media = media.copy()
    media["path"] = None
    with pytest.raises(ValueError, match="cache the collection's files first"):
        run_split(media, helpers)
    assert _written(tmp_path) == []


def _no_length(folder_collection, tmp_path: Path):
    root = tmp_path / "clips"
    root.mkdir()
    _raw_mjpeg(root / "raw.mjpeg")
    return folder_collection(
        root, {"id": "clips", "name": "Clips", "kind": "videos", "path": "*", "extensions": ["mjpeg"]}
    )


def test_a_video_that_gives_no_length_is_cut_as_its_frames_come(folder_collection, tmp_path):
    """Raw MJPEG says nothing of its length, 25 frames at 25 a second: its
    blocks are made as its frames come, the last one what is left."""
    media, helpers = _no_length(folder_collection, tmp_path)
    blocks = run_split(media, helpers, BLOCK_SECONDS=0.4)
    assert list(blocks["t_s"]) == [0.0, 0.4, 0.8]
    assert [len(_played(path)[4]) for path in blocks["path"]] == [10, 10, 5]


def test_a_cut_past_the_end_of_a_video_that_gives_no_length_stops_the_node_at_its_end(folder_collection, tmp_path):
    import pandas as pd

    media, helpers = _no_length(folder_collection, tmp_path)
    with pytest.raises(ValueError, match="has no frame from 5 s on, where a block starts"):
        run_split(media, helpers, pd.DataFrame([{"t_s": 0.0}, {"t_s": 5.0}]))


def test_past_max_frames_a_video_that_gives_no_length_stops_and_its_half_written_block_goes(
    folder_collection, tmp_path,
):
    """Its frames cannot be counted before it is read: the 13th of MAX_FRAMES
    12 stops the node, and the block it would have gone in is removed."""
    media, helpers = _no_length(folder_collection, tmp_path)
    with pytest.raises(ValueError, match="re-encodes in one run"):
        run_split(media, helpers, BLOCK_SECONDS=0.4, MAX_FRAMES=12)
    # Block 1, ten frames, was done; block 2 had two when the 13th frame came.
    assert _written(tmp_path) == ["0-to400w960.mp4"]


def test_the_same_blocks_write_the_same_files_and_another_end_or_width_others(folder_collection, tmp_path):
    media, helpers = _walks(folder_collection, tmp_path, {"corner.mp4": 4.0})
    first = run_split(media, helpers, BLOCK_SECONDS=2.0)
    assert list(run_split(media, helpers, BLOCK_SECONDS=2.0)["path"]) == list(first["path"])
    longer = run_split(media, helpers, BLOCK_SECONDS=3.0)
    narrower = run_split(media, helpers, BLOCK_SECONDS=2.0, WIDTH=48)
    # Each starts at 0, and the files differ by the block's end or the width.
    assert len({first["path"].iloc[0], longer["path"].iloc[0], narrower["path"].iloc[0]}) == 3
    assert len({*first["path"], *longer["path"], *narrower["path"]}) == 6
    assert _played(narrower["path"].iloc[0])[2:4] == (48, 32)
    assert _played(first["path"].iloc[0])[2:4] == (96, 64)


def test_a_tail_shorter_than_a_frame_is_the_last_blocks(folder_collection, tmp_path):
    """2.1 s cut every 2.05 s leaves 0.05 s, half a frame: no block of its own."""
    media, helpers = _walks(folder_collection, tmp_path, {"corner.mp4": 2.1})
    blocks = run_split(media, helpers, BLOCK_SECONDS=2.05)
    assert list(blocks["t_s"]) == [0.0] and list(blocks["duration_s"]) == [2.1]
    assert len(_played(blocks["path"].iloc[0])[4]) == 21


def test_the_blocks_of_a_video_with_a_position_keep_it(folder_collection, tmp_path):
    import geopandas as gpd

    media, helpers = _walks(folder_collection, tmp_path, {"corner.mp4": 3.0})
    placed = gpd.GeoDataFrame(media, geometry=gpd.points_from_xy([-87.6475], [41.8842]), crs="EPSG:4326")
    blocks = run_split(placed, helpers, BLOCK_SECONDS=1.5)
    assert isinstance(blocks, gpd.GeoDataFrame) and blocks.crs == placed.crs
    assert list(blocks.geometry.x) == [-87.6475, -87.6475]


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
