"""SAM 3's image path: its Segment Images node and the package module it calls,
``sources/sam3_images.py``.

Segment Images finds what its LABELS name in each image of a collection, or
each frame Sample Video Frames sampled, with SAM 3's image model: the detector
of the video checkpoint Track Objects reads, loaded from the same folder.
These tests run on the tiny SAM 3 ``test_sam3_package`` builds and saves where
``--model-weights-dir`` puts the package's weights, every file the package
fetches, read through ``curio_load_model`` as a run of the node reads it: no
weights are fetched and no socket opened. Its detection thresholds at 0 let
random weights find something, and what they find moves with the platform,
so the tests assert what every run keeps: the columns and their order, counts
and shares that agree with each other, and overlays named and sized as they
should be.

torch and transformers are imported inside the tests, so a checkout without
them fails each test on its own.
"""

from __future__ import annotations

import ast
import contextlib
import importlib
import os
import re
import shutil
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from utk_curio.backend.tests.test_packages.test_sam3_package import (
    EVERY,
    MODEL_ID,
    PACKAGE,
    _collection,
    _loaded,
    _manifest,
    _street,
    _tiny_config,
    _tiny_weights,
)

REPO = Path(__file__).resolve().parents[4]
SOURCE = PACKAGE / "sources" / "segment-images.py"
MODULE = "sam3_images"
MODULE_SOURCE = PACKAGE / "sources" / f"{MODULE}.py"
#: The modules a run of either SAM 3 node is handed, and those the tests stage
#: beside them: Media's, whose Sample Video Frames makes the frames, and
#: Segmentation's, whose overlays' names Segment Images' follow.
STAGED = [
    {"root": str(PACKAGE / "sources"), "names": [MODULE, "sam3_tracking"]},
    {"root": str(REPO / "packages" / "curio.media@1" / "sources"), "names": ["media_collections"]},
    {"root": str(REPO / "packages" / "curio.segmentation@1" / "sources"), "names": ["semantic_segmentation"]},
]
#: Each setting of the code tab, and the argument of the call it is handed as.
SETTINGS = {"LABELS": "labels", "THRESHOLD": "threshold", "WIDTH": "width", "MAX_IMAGES": "max_images"}
TWO = ["pole", "person"]
#: How many objects the tiny SAM 3 can find in an image for one label: its
#: detector's queries. At a threshold of 0 it keeps each of them.
QUERIES = 5
#: The result columns of a call on TWO, in their order.
RESULTS = [
    "dominant_class", "dominant_pct", "pole_pct", "pole_objects", "person_pct", "person_objects",
    "overlay_url", "segment_error",
]


@pytest.fixture(scope="module")
def weights(tmp_path_factory):
    """The tiny SAM 3 Track Objects' tests use, saved where
    ``--model-weights-dir`` puts the package's weights."""
    return _tiny_weights(tmp_path_factory, _tiny_config())


@pytest.fixture
def few_threads(monkeypatch):
    """A few CPU threads for torch, whatever the runner shows, and no hub."""
    import torch

    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    monkeypatch.setenv("TRANSFORMERS_OFFLINE", "1")
    threads = torch.get_num_threads()
    torch.set_num_threads(min(4, os.cpu_count() or 1))
    yield
    torch.set_num_threads(threads)


@pytest.fixture
def videos(tmp_path):
    """``(rows, helpers)`` for a folder holding Track Objects' tests' 2 s clip."""
    return _collection(tmp_path)


@pytest.fixture
def catalog_copy(tmp_path):
    """The catalog's copy of the package without its weights, as a clone, CI
    and a pip install hold it."""
    folder = tmp_path / "catalog" / PACKAGE.name
    folder.mkdir(parents=True)
    shutil.copyfile(PACKAGE / "manifest.json", folder / "manifest.json")
    return folder


@contextlib.contextmanager
def _staged(tmp_path: Path):
    """The modules of ``STAGED``, importable as a run of a node imports them:
    staged into a folder of the run's own, then imported by name."""
    from utk_curio.sandbox.util.package_modules import importable
    from utk_curio.sandbox.util.staging import stage_package_modules

    run = Path(tempfile.mkdtemp(prefix="run-", dir=tmp_path))
    staged = stage_package_modules(STAGED, str(run))
    with importable(str(run / staged["root"]), staged["names"]):
        yield {name: importlib.import_module(name) for name in staged["names"]}


def _node_source(**settings) -> str:
    """The node's code with each setting given set at the top, as a person
    edits it."""
    code = SOURCE.read_text(encoding="utf-8")
    for name, value in settings.items():
        # LABELS is a list over several lines; every other setting is one line.
        if name == "LABELS":
            pattern, flags = r"^LABELS = \[.*?^\]$", re.M | re.S
        else:
            pattern, flags = rf"^{name} = .*$", re.M
        code, count = re.subn(pattern, lambda _m, n=name, v=value: f"{n} = {v!r}", code, count=1, flags=flags)
        assert count == 1, f"the node sets no {name}"
    return code


def _run(rows, helpers, *, model_folder: Path, weights: Path | None, **settings):
    """The node's output on *rows*: its code, with *settings* set, run as the
    canvas runs it, with the package's modules importable (``_staged``)."""
    from utk_curio.sandbox.util.input_names import call_as_node

    namespace = {**helpers, "curio_load_model": _loaded(model_folder, weights)}
    body = "\n".join("    " + line for line in _node_source(**settings).splitlines())
    return call_as_node(body, namespace, rows, [0])


def _frames(modules, videos):
    """``(frames, helpers)``: Sample Video Frames' frames of the 2 s clip, one
    every EVERY seconds."""
    rows, helpers = videos
    frames = modules["media_collections"].sample_video_frames(rows, helpers["curio_derived_file"], every_seconds=EVERY)
    assert list(frames["t_s"]) == [0.0, 0.5, 1.0, 1.5] and set(frames["kind"]) == {"frame"}
    return frames, helpers


def _overlay(url: str, tmp_path: Path) -> Path:
    """The overlay file a row's ``overlay_url`` serves, in the media folder."""
    served = url.split("/media/", 1)[1].split("?", 1)[0]
    file_id, stem = served.split("@", 1)
    (found,) = [path for path in (tmp_path / "media" / "overlays").rglob(f"{stem.split('.')[0]}.png")
                if path.parent.name == file_id]
    return found


# ---------------------------------------------------------------------------
# The node and its module
# ---------------------------------------------------------------------------

def test_the_code_tab_holds_its_settings_and_one_call_of_the_image_module():
    """Segment Images' logic is the package's image module: its code tab
    imports the module's function, sets the node's settings, the package's 35
    labels first, and returns one call of it, which hands it Curio's plumbing,
    the model by the literal id the backend reads and ``curio_derived_file``,
    and each setting as its argument."""
    code = SOURCE.read_text(encoding="utf-8")
    assert f'curio_load_model("{MODEL_ID}")' in code
    body = ast.parse("def node(input_0):\n" + "\n".join("    " + line for line in code.splitlines())).body[0].body
    imports, assigns, returned = body[:1], body[1:-1], body[-1]
    assert [ast.unparse(statement) for statement in imports] == [f"from {MODULE} import find_in_images"]
    assert all(isinstance(statement, ast.Assign) for statement in assigns), [ast.unparse(s) for s in assigns]
    settings = {statement.targets[0].id: ast.literal_eval(statement.value) for statement in assigns}
    assert list(settings) == list(SETTINGS)
    assert settings["LABELS"] == _manifest()["model"]["labels"]
    assert (settings["THRESHOLD"], settings["WIDTH"], settings["MAX_IMAGES"]) == (0.5, 960, 300)
    assert isinstance(returned, ast.Return) and isinstance(returned.value, ast.Call), ast.unparse(returned)
    call = returned.value
    assert ast.unparse(call.func) == "find_in_images"
    assert [ast.unparse(arg) for arg in call.args] == ["input_0", f"curio_load_model('{MODEL_ID}')", "curio_derived_file"]
    assert {keyword.arg: ast.unparse(keyword.value) for keyword in call.keywords} == {
        argument: setting for setting, argument in SETTINGS.items()}


def test_the_image_module_offers_find_in_images_and_is_handed_curios_plumbing():
    """The Functions header above the node's code lists what the module's
    ``__all__`` names, each with the first paragraph of its docstring. The
    module imports nothing of Curio's and calls none of Curio's functions; it
    picks SAM 3's device and draws an object as Track Objects does, from the
    package's other module."""
    tree = ast.parse(MODULE_SOURCE.read_text(encoding="utf-8"))
    (offered,) = [
        statement for statement in tree.body
        if isinstance(statement, ast.Assign) and [ast.unparse(t) for t in statement.targets] == ["__all__"]
    ]
    assert ast.literal_eval(offered.value) == ["find_in_images"]
    (function,) = [s for s in tree.body if isinstance(s, ast.FunctionDef) and s.name == "find_in_images"]
    first = " ".join((ast.get_docstring(function) or "").split("\n\n", 1)[0].split())
    assert "SAM 3" in first and len(first) <= 600, first
    assert [arg.arg for arg in function.args.args] == ["images", "model", "derived_file"]
    assert [arg.arg for arg in function.args.kwonlyargs] == list(SETTINGS.values())
    imported = [alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names]
    imported += [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    assert "sam3_tracking" in imported
    assert not [name for name in imported if name.split(".")[0] == "utk_curio"]
    assert not [node.id for node in ast.walk(tree) if isinstance(node, ast.Name) and node.id.startswith("curio_")]


def test_a_run_of_either_sam3_node_is_handed_both_of_the_packages_modules(tmp_curio):
    """Both modules are the package's: a run of Track Objects or of Segment
    Images gets them both, so the image module reads the tracking module's
    device and drawing, isolated or not."""
    from utk_curio.backend.app.packages.application.python_modules import modules_for_node
    from utk_curio.backend.app.packages.application.store_install import install_package_from_directory
    from utk_curio.backend.app.packages.repositories.store import package_dir

    install_package_from_directory("guest", PACKAGE)
    for template in ("track-objects", "segment-images"):
        handed = modules_for_node("guest", f"{MODEL_ID}/{template}")
        assert handed["root"] == str(package_dir("guest", PACKAGE.name) / "sources"), handed
        assert sorted(handed["names"]) == [MODULE, "sam3_tracking"], handed


# ---------------------------------------------------------------------------
# The node, run
# ---------------------------------------------------------------------------

def test_without_its_weights_the_node_says_how_to_fetch_them(videos, catalog_copy, few_threads, tmp_path):
    from utk_curio.sandbox.util.models import NOT_FETCHED

    with _staged(tmp_path) as modules:
        frames, helpers = _frames(modules, videos)
        with pytest.raises(RuntimeError) as raised:
            _run(frames, helpers, model_folder=catalog_copy, weights=None)
    assert str(raised.value) == NOT_FETCHED.format(model_id=MODEL_ID)


def test_segment_images_finds_each_label_in_each_frame_sample_video_frames_sampled(
        videos, catalog_copy, weights, few_threads, tmp_path):
    """Each frame comes back with the results first, as Image Segmentation's:
    the label covering the most and its share, then each label's share and
    count, the overlay and the error; then the frame's own columns, its t_s
    among them. Each overlay is a PNG of the frame's size, named after its
    video at the frame's time and after what the call asked, as Image
    Segmentation names an overlay of a sampled frame."""
    from PIL import Image

    with _staged(tmp_path) as modules:
        frames, helpers = _frames(modules, videos)
        out = _run(frames, helpers, model_folder=catalog_copy, weights=weights, LABELS=TWO, THRESHOLD=0.0)
        tag = modules[MODULE]._tag(TWO, 0.0, 960)
    assert list(out.columns) == [*RESULTS, *frames.columns]
    assert list(out["t_s"]) == list(frames["t_s"]) and list(out["file_id"]) == list(frames["file_id"])
    # At a threshold of 0 every query of the detector is kept.
    assert out["pole_objects"].eq(QUERIES).all() and out["person_objects"].eq(QUERIES).all()
    assert out["segment_error"].isna().all()
    for row in out.to_dict("records"):
        shares = {"pole": row["pole_pct"], "person": row["person_pct"]}
        assert all(0 <= share <= 100 for share in shares.values()), shares
        # The label covering the most, the first of LABELS on a tie; none where nothing covers any.
        best = max(shares.values())
        assert row["dominant_pct"] == best
        assert row["dominant_class"] == (max(shares, key=lambda label: shares[label]) if best > 0 else None)
        video, t_ms = row["file_id"].split("@")
        assert row["overlay_url"].endswith(f"/media/{video}@{t_ms}-{tag}.png?variant=original"), row["overlay_url"]
        with Image.open(_overlay(row["overlay_url"], tmp_path)) as overlay:
            assert (overlay.format, overlay.size) == ("PNG", (96, 64))


def test_where_sam3_finds_nothing_each_label_counts_none_and_no_label_dominates(
        videos, catalog_copy, weights, few_threads, tmp_path):
    """A threshold no score passes: no object, no share, no dominant label,
    and the overlay is the frame as it is."""
    with _staged(tmp_path) as modules:
        frames, helpers = _frames(modules, videos)
        out = _run(frames, helpers, model_folder=catalog_copy, weights=weights, LABELS=TWO, THRESHOLD=1.0)
    assert out["pole_objects"].eq(0).all() and out["person_objects"].eq(0).all()
    assert out["pole_pct"].eq(0).all() and out["dominant_pct"].eq(0).all()
    assert out["dominant_class"].isna().all() and out["overlay_url"].notna().all()


def test_photos_get_overlays_named_after_themselves_and_a_row_without_an_image_says_why(
        catalog_copy, weights, few_threads, tmp_path):
    """A collection's photos: each overlay is named after its photo, a photo
    wider than WIDTH is read and drawn WIDTH wide, and a photo that is gone or
    is not an image gets no results and says why."""
    import numpy as np
    from PIL import Image

    from utk_curio.backend.app.discovery.domain.manifest import load_source_manifest
    from utk_curio.backend.tests.test_discovery.conftest import a_storage_manifest, write_source
    from utk_curio.backend.tests.test_packages.test_media_package import collection_rows

    root = tmp_path / "photos"
    root.mkdir()
    Image.fromarray(_street(1)).save(root / "a.png")
    Image.fromarray(np.kron(_street(3), np.ones((30, 30, 1), dtype=np.uint8))).save(root / "b.png")
    (root / "c.png").write_bytes(b"not an image")
    Image.fromarray(_street(5)).save(root / "d.png")
    resource = {"id": "photos", "name": "Photos", "kind": "images", "path": "*"}
    source = write_source(tmp_path / "discovery", "source.example.folder@1", a_storage_manifest(root, [resource]))
    rows, helpers = collection_rows(load_source_manifest(source), "photos", tmp_path)
    (root / "d.png").unlink()

    with _staged(tmp_path):
        out = _run(rows, helpers, model_folder=catalog_copy, weights=weights, LABELS=TWO, THRESHOLD=0.0)
    by_name = {row["name"]: row for row in out.to_dict("records")}
    assert by_name["c.png"]["segment_error"] == "the image could not be read"
    assert by_name["d.png"]["segment_error"] == "the image is not on this machine"
    for name in ("c.png", "d.png"):
        assert by_name[name]["pole_objects"] is None or np.isnan(by_name[name]["pole_objects"])
        assert by_name[name]["overlay_url"] is None or by_name[name]["overlay_url"] != by_name[name]["overlay_url"]
    for name, size in (("a.png", (96, 64)), ("b.png", (960, 640))):
        row = by_name[name]
        assert row["segment_error"] is None and row["pole_objects"] == QUERIES
        assert f"/media/{row['file_id']}@0-sam3" in row["overlay_url"], row["overlay_url"]
        with Image.open(_overlay(row["overlay_url"], tmp_path)) as overlay:
            assert overlay.size == size


def test_overlays_are_named_as_image_segmentation_names_them(tmp_path):
    """Segment Images' overlays follow Image Segmentation's rule: a
    collection's photo or frame by itself, a frame a node sampled from a video
    by its video at its time, and no other derived file."""
    video = "0123456789abcdef"
    rows = [
        {"file_id": video, "kind": "image"},
        {"file_id": video, "kind": "frame"},
        {"file_id": f"{video}@1500", "kind": "frame"},
        {"file_id": f"{video}@1500-sam3abcdef012345.png", "kind": "image"},
        {"file_id": f"{video}@1500-sam3abcdef012345", "kind": "frame"},
        {"file_id": f"{video}@0.mp4", "kind": "video"},
    ]
    with _staged(tmp_path) as modules:
        ours, theirs = modules[MODULE]._overlay_source, modules["semantic_segmentation"]._overlay_source
        assert [ours(row) for row in rows] == [theirs(row) for row in rows]
        assert [ours(row) for row in rows][:3] == [(video, 0, "image"), (video, 0, "image"), (video, 1500, "video")]


def test_calls_that_ask_differently_keep_overlays_of_their_own(videos, catalog_copy, weights, few_threads, tmp_path):
    """The overlay's name holds the labels, the threshold and the width, so a
    call that asks otherwise of the same frames keeps files of its own, and one
    that asks the same writes the same files again."""
    with _staged(tmp_path) as modules:
        tag = modules[MODULE]._tag
        assert len({tag(TWO, 0.5, 960), tag(["pole"], 0.5, 960), tag(TWO, 0.4, 960), tag(TWO, 0.5, 480)}) == 4
        frames, helpers = _frames(modules, videos)
        first = _run(frames, helpers, model_folder=catalog_copy, weights=weights, LABELS=TWO, THRESHOLD=0.0)
        again = _run(frames, helpers, model_folder=catalog_copy, weights=weights, LABELS=TWO, THRESHOLD=0.0)
        other = _run(frames, helpers, model_folder=catalog_copy, weights=weights, LABELS=["pole"], THRESHOLD=0.0)
    assert list(first["overlay_url"]) == list(again["overlay_url"])
    assert not set(first["overlay_url"]) & set(other["overlay_url"])


def test_each_stop_comes_before_sam3_loads_and_writes_nothing(videos, tmp_path):
    """Empty labels, a label named twice, labels whose results would share a
    column, a limit under one image, more images than one run looks at and
    rows with no path each stop the call before SAM 3 loads: the model here
    names a folder that holds nothing. An input with no row loads nothing and
    gives the result columns."""
    nothing = SimpleNamespace(path=str(tmp_path / "no-weights"))
    with _staged(tmp_path) as modules:
        frames, helpers = _frames(modules, videos)
        derived = helpers["curio_derived_file"]
        find = modules[MODULE].find_in_images
        stops = {}
        for name, call in {
            "no label": lambda: find(frames, nothing, derived, labels=[]),
            "twice": lambda: find(frames, nothing, derived, labels=["pole", "pole"]),
            "one column": lambda: find(frames, nothing, derived, labels=["dominant", "pole"]),
            "no image": lambda: find(frames, nothing, derived, labels=TWO, max_images=0),
            "too many": lambda: find(frames, nothing, derived, labels=TWO, max_images=3),
            "no path": lambda: find(frames.drop(columns=["path"]), nothing, derived, labels=TWO),
        }.items():
            with pytest.raises(ValueError) as stopped:
                call()
            stops[name] = str(stopped.value)
        empty = find(frames.iloc[:0], nothing, derived, labels=TWO)
    assert stops == {
        "no label": "LABELS is empty: name at least one thing to look for",
        "twice": "LABELS names 'pole' more than once",
        "one column": "LABELS would give two results one column: dominant_pct; rename a label",
        "no image": "MAX_IMAGES is 0: a run looks at one image at least, so set it to 1 or more",
        "too many": (
            "Segment Images looks at 3 images in one run (MAX_IMAGES), and its input has 4: sample fewer "
            "frames, keep fewer rows, or raise MAX_IMAGES"
        ),
        "no path": "Segment Images reads rows with a path, as curio_load_collection gives them",
    }
    assert empty.empty and list(empty.columns[:len(RESULTS)]) == RESULTS
    assert not list((tmp_path / "media").rglob("*.png"))


def test_a_positioned_frames_table_comes_back_with_its_positions(videos, catalog_copy, weights, few_threads, tmp_path):
    import geopandas as gpd

    with _staged(tmp_path) as modules:
        frames, helpers = _frames(modules, videos)
        placed = gpd.GeoDataFrame(frames, geometry=gpd.points_from_xy([-87.6475] * 4, [41.8842] * 4), crs="EPSG:4326")
        out = _run(placed, helpers, model_folder=catalog_copy, weights=weights, LABELS=["pole"], THRESHOLD=1.0)
    assert isinstance(out, gpd.GeoDataFrame) and out.crs == placed.crs
    assert list(out.geometry.x) == [-87.6475] * 4
