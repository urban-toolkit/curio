"""``curio_segment``: a Model Catalog model over a collection's images.

Runs the real DDRNet23-Slim export on two of example 10's committed photos,
and the synthetic graph the Hugging Face model fixtures use. onnxruntime is
the Street Vision package's one library, which a stack's boot installs with
the examples' packages; it is imported, not skipped, so a stack without it
fails here.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pandas as pd
import pytest

from utk_curio.sandbox.util.collections import make_collection_helpers
from utk_curio.sandbox.util.vision import CLASS_COLOURS, make_curio_segment, palette

REPO = Path(__file__).resolve().parents[3]
DDRNET = REPO / "models" / "model.curio.ddrnet23-slim@1"
SAMPLE = "data.curio.mapillary-sample"
STORAGE = REPO / "docs" / "examples" / "data" / "storage"
SYNTHETIC = REPO / "utk_curio" / "backend" / "tests" / "test_discovery" / "fixtures" / "huggingface-models" / "synthetic-segmentation.onnx"
STREET = ["vegetation", "terrain", "sky", "road", "sidewalk", "building"]


@pytest.fixture
def photos(tmp_path):
    """Two of the committed photos, as a node's curio_load_collection gives them."""
    index = REPO / "datasets" / f"{SAMPLE}@1" / "data" / "index.parquet"
    helpers = make_collection_helpers(
        lambda _id: str(index), {SAMPLE: {"kind": "images", "root": str(STORAGE)}}, str(tmp_path / "media")
    )
    frame = helpers["curio_load_collection"](SAMPLE).head(2)
    return frame, helpers


def test_ddrnet_labels_the_photos(photos):
    frame, helpers = photos
    out = make_curio_segment(helpers["curio_derived_file"])(frame, str(DDRNET), STREET)
    assert len(out) == 2 and type(out).__name__ == "GeoDataFrame"
    for name in STREET:
        assert out[f"{name}_pct"].between(0, 100).all()
    # Street panoramas: sky and road are always there.
    assert (out["sky_pct"] > 5).all() and (out["road_pct"] > 5).all()
    assert out["dominant_class"].isin(STREET).all()
    assert out["segment_error"].isna().all()


def test_a_share_is_of_all_the_pixels(photos):
    """Not of the classes asked for: asked for vegetation alone, an image with
    some vegetation does not read 100% (HF CV Inference's renormalization)."""
    frame, helpers = photos
    segment = make_curio_segment(helpers["curio_derived_file"])
    alone = segment(frame, str(DDRNET), ["vegetation"])
    every = segment(frame, str(DDRNET), None)
    assert (alone["vegetation_pct"] < 100).all()
    assert list(alone["vegetation_pct"]) == list(every["vegetation_pct"])
    labels = json.loads((DDRNET / "manifest.json").read_text(encoding="utf-8"))["labels"]
    totals = every[[f"{name}_pct" for name in labels]].sum(axis=1)
    assert totals.between(99.5, 100.5).all()


def test_each_photo_gets_an_overlay_served_by_id(photos):
    frame, helpers = photos
    out = make_curio_segment(helpers["curio_derived_file"])(frame, str(DDRNET), STREET)
    for url, file_id in zip(out["overlay_url"], frame["file_id"]):
        assert url == f"/api/datasets/{SAMPLE}/media/{file_id}@0?variant=original"


def test_the_results_lead_the_row(photos):
    """A card's caption is the row's first columns, so what the model found
    has to come before the collection's own file columns."""
    frame, helpers = photos
    out = make_curio_segment(helpers["curio_derived_file"])(frame, str(DDRNET), STREET)
    assert list(out.columns[:2]) == ["dominant_class", "dominant_pct"]
    assert list(out.columns[2:2 + len(STREET)]) == [f"{name}_pct" for name in STREET]
    assert list(out.columns[2 + len(STREET):]) == [
        "overlay_url", "segment_error", *frame.columns,
    ]


def test_a_class_named_like_a_column_keeps_the_column(tmp_path, photos):
    """ADE20K labels a class "path": its share must not replace the image's."""
    frame, helpers = photos
    model = tmp_path / "model"
    (model / "files").mkdir(parents=True)
    shutil.copyfile(SYNTHETIC, model / "files" / "model.onnx")
    labels = ["path", *[f"c{i}" for i in range(1, 150)]]
    (model / "manifest.json").write_text(json.dumps({
        "runtime": "onnx", "entry": "files/model.onnx", "labels": labels,
        "input": {"width": 64, "height": 64, "dtype": "float32"},
    }), encoding="utf-8")
    out = make_curio_segment(helpers["curio_derived_file"])(frame, str(model), None)
    assert list(out["path"]) == list(frame["path"])
    assert out["path_pct"].between(0, 100).all()


def test_without_a_collection_there_is_no_overlay(photos):
    frame, _helpers = photos
    out = make_curio_segment(None)(frame, str(DDRNET), STREET)
    assert out["overlay_url"].isna().all() and out["dominant_class"].notna().all()


def test_a_class_the_model_lacks_names_the_ones_it_has(photos):
    frame, helpers = photos
    with pytest.raises(ValueError, match="no class 'tree'.*vegetation"):
        make_curio_segment(helpers["curio_derived_file"])(frame, str(DDRNET), ["tree"])


def test_a_row_without_its_file_says_so(photos):
    frame, helpers = photos
    frame = frame.copy()
    frame.loc[frame.index[0], "path"] = None
    out = make_curio_segment(helpers["curio_derived_file"])(frame, str(DDRNET), STREET)
    assert out["segment_error"].iloc[0] == "the image is not on this machine"
    assert out["dominant_class"].iloc[1] in STREET


def test_rows_without_paths_are_refused():
    with pytest.raises(ValueError, match="rows with a path"):
        make_curio_segment(None)(pd.DataFrame({"x": [1]}), str(DDRNET))


def test_a_float_graph_with_normalized_input(tmp_path, photos):
    """An ONNX export from Hugging Face, as the Discovery Catalog adds one:
    float32 pixels, scaled and normalized as its preprocessor config says."""
    frame, helpers = photos
    model = tmp_path / "model"
    (model / "files").mkdir(parents=True)
    shutil.copyfile(SYNTHETIC, model / "files" / "model.onnx")
    (model / "manifest.json").write_text(json.dumps({
        "runtime": "onnx", "entry": "files/model.onnx", "labels": [f"c{i}" for i in range(150)],
        "input": {"width": 64, "height": 64, "dtype": "float32", "scale": 1 / 255,
                  "mean": [0.485, 0.456, 0.406], "std": [0.229, 0.224, 0.225]},
    }), encoding="utf-8")
    out = make_curio_segment(helpers["curio_derived_file"])(frame, str(model), None)
    labels = [f"c{i}_pct" for i in range(150)]
    assert out[labels].sum(axis=1).between(99.5, 100.5).all()


def test_a_manifest_naming_other_labels_is_refused(tmp_path, photos):
    frame, helpers = photos
    model = tmp_path / "model"
    (model / "files").mkdir(parents=True)
    shutil.copyfile(SYNTHETIC, model / "files" / "model.onnx")
    (model / "manifest.json").write_text(json.dumps({
        "runtime": "onnx", "entry": "files/model.onnx", "labels": ["a", "b"],
        "input": {"width": 64, "height": 64, "dtype": "float32"},
    }), encoding="utf-8")
    with pytest.raises(RuntimeError, match="answered 150 classes; its manifest names 2"):
        make_curio_segment(None)(frame, str(model), None)


def test_street_classes_keep_their_colours():
    colours = palette(["road", "vegetation", "something else", "Sky"])
    assert colours[0] == CLASS_COLOURS["road"] and colours[1] == CLASS_COLOURS["vegetation"]
    assert colours[3] == CLASS_COLOURS["sky"] and colours[2] not in CLASS_COLOURS.values()


def test_a_transformers_model_without_its_libraries_says_what_to_install(tmp_path, photos, monkeypatch):
    import builtins

    real_import = builtins.__import__

    def no_torch(name, *args, **kwargs):
        if name in ("torch", "transformers"):
            raise ImportError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_torch)
    model = tmp_path / "model"
    (model / "files").mkdir(parents=True)
    (model / "manifest.json").write_text(json.dumps({"runtime": "transformers", "entry": "files"}), encoding="utf-8")
    frame, _helpers = photos
    # The way out it names has to exist: adding the model is what installs them.
    with pytest.raises(RuntimeError, match="runs on Transformers.*add it again from the Discovery "
                                           "Catalog.*torch, transformers and safetensors"):
        make_curio_segment(None)(frame, str(model), None)
