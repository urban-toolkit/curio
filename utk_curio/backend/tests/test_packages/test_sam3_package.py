"""SAM 3's model package, ``model.curio.sam3@1``, and its Track Objects node.

SAM 3's weights are Meta's, gated on Hugging Face and 3.4 GB: no clone, image
or pip install holds them, and no test fetches them. These tests run the
node's own code, ``sources/track-objects.py``, as the canvas runs it
(``input_names.call_as_node``), on the rows Data Loading gives for a folder of
videos, with a tiny SAM 3 video model built here with random weights:

- saved where ``--model-weights-dir`` puts the package's weights, every file
  the package's ``fetch`` lists, and read in place, as ``curio_load_model``
  gives a node its ``model.path``;
- with its detection thresholds at 0, so random weights find something, and
  at most six objects, which keeps a run to seconds.

What random weights find moves with BLAS and the platform, so the tests
assert what every run keeps: one tracks row per object, counts that add up to
it, times in order, an overlay frame for each frame looked at, and an overlay
a browser plays (H.264 in yuv420p).

torch, transformers and av are imported inside the tests, so a checkout
without them fails each test on its own.
"""

from __future__ import annotations

import ast
import json
import os
import re
import shutil
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[4]
PACKAGE = REPO / "packages" / "model.curio.sam3@1"
MODEL_ID = "model.curio.sam3"
SOURCE = PACKAGE / "sources" / "track-objects.py"
#: SAM 3 at the revision sideseeing-tools pins.
REVISION = "3c879f39826c281e95690f02c7821c4de09afae7"
#: The files Transformers reads of it; sam3.pt, the original code's, is not one.
CHECKPOINT_FILES = [
    "config.json", "model.safetensors", "processor_config.json", "tokenizer.json",
    "tokenizer_config.json", "special_tokens_map.json", "vocab.json", "merges.txt",
]
#: What the node looks for until its LABELS change.
DEFAULT_LABELS = [
    "curb ramp", "curb cut", "tactile paving", "bollard", "pole",
    "construction barrier", "traffic cone", "person",
]
#: The tracks table's columns.
TRACK_COLUMNS = [
    "video_file_id", "video", "object_id", "label", "start_s", "end_s", "frames", "largest_share", "mean_score",
]
#: The side of the tiny model's square input.
SIZE = 224
#: The synthetic clip: 2 s at 4 frames a second, sampled every half second.
CLIP_SECONDS, CLIP_RATE, EVERY = 2.0, 4, 0.5
SAMPLED = [0.0, 0.5, 1.0, 1.5]


def _manifest() -> dict:
    return json.loads((PACKAGE / "manifest.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# The tiny SAM 3
# ---------------------------------------------------------------------------

def _tiny_tokenizer(folder: Path):
    """A CLIP tokenizer over a vocab of single letters and digits, its bos,
    eos and pad ids inside the tiny text model's vocab."""
    from transformers import CLIPTokenizer

    vocab = {"<|startoftext|>": 0, "<|endoftext|>": 1}
    for char in "abcdefghijklmnopqrstuvwxyz0123456789":
        vocab[char] = len(vocab)
        vocab[char + "</w>"] = len(vocab)
    (folder / "vocab.json").write_text(json.dumps(vocab), encoding="utf-8")
    (folder / "merges.txt").write_text("#version: 0.2\n", encoding="utf-8")
    return CLIPTokenizer(
        str(folder / "vocab.json"), str(folder / "merges.txt"), pad_token="<|endoftext|>", model_max_length=32,
    )


def _tiny_config():
    """A Sam3VideoConfig of about 5.8 M parameters that tracks text prompts:
    four FPN scale factors as SAM 3's; a hidden size of 128, a multiple of the
    64-wide memory, as SAM 3's 256 is; ``image_size`` on the video config;
    detection thresholds at 0, so random weights detect; six objects at most."""
    from transformers import (
        Sam3Config,
        Sam3DETRDecoderConfig,
        Sam3DETREncoderConfig,
        Sam3GeometryEncoderConfig,
        Sam3MaskDecoderConfig,
        Sam3TrackerVideoConfig,
        Sam3TrackerVideoMaskDecoderConfig,
        Sam3TrackerVideoPromptEncoderConfig,
        Sam3VideoConfig,
        Sam3ViTConfig,
        Sam3VisionConfig,
    )

    hidden = 128
    backbone = Sam3ViTConfig(
        hidden_size=32, num_hidden_layers=2, num_attention_heads=4, intermediate_size=64,
        num_channels=3, image_size=SIZE, patch_size=14, window_size=8, global_attn_indexes=[0, 1],
    )
    vision = Sam3VisionConfig(backbone_config=backbone, fpn_hidden_size=hidden, scale_factors=[4.0, 2.0, 1.0, 0.5])
    text = {
        "vocab_size": 1000, "hidden_size": 64, "intermediate_size": 128, "projection_dim": hidden,
        "num_hidden_layers": 2, "num_attention_heads": 4, "max_position_embeddings": 32, "hidden_act": "gelu",
        "bos_token_id": 0, "eos_token_id": 1, "pad_token_id": 1,
    }
    detector = Sam3Config(
        vision_config=vision,
        text_config=text,
        geometry_encoder_config=Sam3GeometryEncoderConfig(
            hidden_size=hidden, num_layers=1, num_attention_heads=4, intermediate_size=2 * hidden,
            mask_fuser_hidden_size=hidden, mask_fuser_num_layers=1,
        ),
        detr_encoder_config=Sam3DETREncoderConfig(
            hidden_size=hidden, num_layers=1, num_attention_heads=4, intermediate_size=2 * hidden,
        ),
        detr_decoder_config=Sam3DETRDecoderConfig(
            hidden_size=hidden, num_layers=1, num_queries=5, num_attention_heads=4, intermediate_size=2 * hidden,
        ),
        mask_decoder_config=Sam3MaskDecoderConfig(hidden_size=hidden, num_upsampling_stages=2),
    )
    tracker = Sam3TrackerVideoConfig(
        vision_config=vision,
        prompt_encoder_config=Sam3TrackerVideoPromptEncoderConfig(hidden_size=hidden, image_size=SIZE, patch_size=14),
        mask_decoder_config=Sam3TrackerVideoMaskDecoderConfig(hidden_size=hidden),
        num_maskmem=2,
        memory_attention_hidden_size=hidden,
        memory_attention_num_layers=1,
        memory_attention_feed_forward_hidden_size=2 * hidden,
        memory_attention_rope_feat_sizes=[SIZE // 14, SIZE // 14],
        memory_encoder_hidden_size=hidden,
        memory_encoder_output_channels=64,
        mask_downsampler_embed_dim=hidden,
        memory_fuser_embed_dim=hidden,
        memory_fuser_intermediate_dim=2 * hidden,
        max_object_pointers_in_encoder=4,
    )
    config = Sam3VideoConfig(
        detector_config=detector, tracker_config=tracker,
        score_threshold_detection=0.0, new_det_thresh=0.0, hotstart_delay=0,
        low_res_mask_size=SIZE * 288 // 1008,
    )
    config.image_size = SIZE
    config.max_num_objects = 6
    return config


@pytest.fixture(scope="module")
def weights(tmp_path_factory):
    """The package's folder under ``--model-weights-dir``, its entry holding a
    tiny SAM 3 and its processor: every file the package's ``fetch`` lists."""
    import torch
    from transformers import Sam2VideoVideoProcessor, Sam3ImageProcessor, Sam3VideoModel, Sam3VideoProcessor

    root = tmp_path_factory.mktemp("model-weights") / PACKAGE.name
    checkpoint = root / _manifest()["model"]["entry"]
    checkpoint.mkdir(parents=True)
    words = tmp_path_factory.mktemp("tokenizer")
    size = {"height": SIZE, "width": SIZE}
    processor = Sam3VideoProcessor(
        Sam3ImageProcessor(size=size), Sam2VideoVideoProcessor(size=size), _tiny_tokenizer(words),
    )
    torch.manual_seed(0)
    Sam3VideoModel(_tiny_config()).save_pretrained(checkpoint)
    processor.save_pretrained(checkpoint)
    # The checkpoint as Hugging Face holds SAM 3's: the tokenizer's vocabulary
    # and merges beside its tokenizer.json, and its special tokens.
    for name in ("vocab.json", "merges.txt"):
        shutil.copyfile(words / name, checkpoint / name)
    (checkpoint / "special_tokens_map.json").write_text(json.dumps({
        "bos_token": "<|startoftext|>", "eos_token": "<|endoftext|>",
        "pad_token": "<|endoftext|>", "unk_token": "<|endoftext|>",
    }), encoding="utf-8")
    return root


@pytest.fixture
def few_threads(monkeypatch):
    """A few CPU threads for torch, whatever the runner shows: an arcade runner
    shows 192 CPUs, and torch would take half of them."""
    import torch

    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    monkeypatch.setenv("TRANSFORMERS_OFFLINE", "1")
    threads = torch.get_num_threads()
    torch.set_num_threads(min(4, os.cpu_count() or 1))
    yield
    torch.set_num_threads(threads)


# ---------------------------------------------------------------------------
# The clip and the node
# ---------------------------------------------------------------------------

def _clip(path: Path) -> None:
    """A clip of an orange box crossing a dark street, in MPEG-4 Part 2, which
    every FFmpeg build reads and writes, so the overlay alone needs H.264."""
    import av
    import numpy as np

    width, height = 96, 64
    with av.open(str(path), "w") as out:
        stream = out.add_stream("mpeg4", rate=CLIP_RATE)
        stream.width, stream.height, stream.pix_fmt = width, height, "yuv420p"
        for index in range(int(CLIP_SECONDS * CLIP_RATE)):
            image = np.full((height, width, 3), 40, dtype=np.uint8)
            image[20:44, 8 + 8 * index:24 + 8 * index] = (230, 120, 40)
            for packet in stream.encode(av.VideoFrame.from_ndarray(image, format="rgb24")):
                out.mux(packet)
        for packet in stream.encode():
            out.mux(packet)


@pytest.fixture
def videos(tmp_path):
    """``(rows, helpers)``: what Data Loading's ``curio_load_collection`` gives
    for a folder holding one clip, and the helpers a node runs with."""
    from utk_curio.backend.app.discovery.domain.manifest import load_source_manifest
    from utk_curio.backend.tests.test_discovery.conftest import a_storage_manifest, write_source
    from utk_curio.backend.tests.test_packages.test_media_package import collection_rows

    root = tmp_path / "walk"
    root.mkdir()
    _clip(root / "corner.mp4")
    resource = {"id": "walk", "name": "Walk", "kind": "videos", "path": "*", "extensions": ["mp4"]}
    source = write_source(tmp_path / "discovery", "source.example.folder@1", a_storage_manifest(root, [resource]))
    return collection_rows(load_source_manifest(source), "walk", tmp_path)


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
    """The node's output on *rows*, its model the package in *model_folder*,
    its weights read in place in *weights*, as a run on a Curio started with
    ``--model-weights-dir`` reads them."""
    from utk_curio.sandbox.util.catalog_helpers import install_catalog_helpers
    from utk_curio.sandbox.util.input_names import call_as_node

    namespace = dict(helpers)
    loaders = {}
    install_catalog_helpers(
        loaders, data_path=str, formats={}, collections={}, media_dir=None,
        models={MODEL_ID: str(model_folder)}, model_weights={MODEL_ID: str(weights)} if weights else None,
    )
    namespace["curio_load_model"] = loaders["curio_load_model"]
    body = "\n".join("    " + line for line in _node_source(**settings).splitlines())
    return call_as_node(body, namespace, rows, [0])


@pytest.fixture
def catalog_copy(tmp_path):
    """The catalog's copy of the package without its weights, as a clone, CI
    and a pip install hold it: its manifest names what to fetch."""
    folder = tmp_path / "catalog" / PACKAGE.name
    folder.mkdir(parents=True)
    shutil.copyfile(PACKAGE / "manifest.json", folder / "manifest.json")
    return folder


# ---------------------------------------------------------------------------
# The package
# ---------------------------------------------------------------------------

def test_the_package_is_a_concept_segmentation_model_whose_node_is_its_own_source():
    from utk_curio.backend.app.packages.repositories.manifests import load_package_manifest

    manifest = load_package_manifest(PACKAGE)
    block = manifest.model
    assert (manifest.kind, block.type, block.runtime, block.entry) == (
        "model", "concept-segmentation", "transformers", "models/checkpoint")
    assert [(t.template_id, t.label, t.source) for t in manifest.templates] == [
        ("track-objects", "Track Objects", "sources/track-objects.py")]
    deps = dict(manifest.python_deps)
    assert deps["transformers"] == ">=5.0,<6.0" and "safetensors" in deps
    # torch and torchvision are the images' own, built for CUDA, which examples
    # 27 to 30 use: removing the model uninstalls the libraries only it
    # declares, so it declares neither.
    assert not {"torch", "torchvision"} & set(deps)


def test_the_weights_are_fetched_at_the_pinned_revision_and_never_shipped():
    block = _manifest()["model"]
    fetch = block["fetch"]
    assert (fetch["huggingface"], fetch["revision"]) == ("facebook/sam3", REVISION)
    assert [item["path"] for item in fetch["files"]] == CHECKPOINT_FILES
    digests = {item["path"]: set(item) - {"path"} for item in fetch["files"]}
    # Hugging Face stores the weights with Git LFS, which lists a SHA-256; the
    # other files by their git blob.
    assert digests.pop("model.safetensors") == {"sha256"}
    assert set(map(frozenset, digests.values())) == {frozenset({"gitSha1"})}
    assert block["sizeBytes"] == 3_444_996_474
    assert "downloadOnFirstUse" not in _manifest()
    # The package's own files, which a clone that fetched the weights into
    # the package's folder holds beside them.
    integrity = json.loads((PACKAGE / "integrity.json").read_text(encoding="utf-8"))["sha256"]
    assert sorted(integrity) == sorted(["LICENSE", "README.md", "manifest.json", "sources/track-objects.py"] + [
        f"skills/{path.relative_to(PACKAGE / 'skills').as_posix()}"
        for path in (PACKAGE / "skills").rglob("*") if path.is_file() and not path.name.startswith(".")
    ])


def test_the_labels_are_the_35_prompts_and_the_readme_groups_them_in_seven():
    labels = _manifest()["model"]["labels"]
    assert len(labels) == len(set(labels)) == 35
    readme = (PACKAGE / "README.md").read_text(encoding="utf-8")
    section = readme.split("## Labels", 1)[1].split("\n## ", 1)[0]
    rows = [line for line in section.splitlines() if line.startswith("| ") and not line.startswith("| Group")]
    groups = [[label.strip() for label in row.split("|")[2].split(",")] for row in rows]
    assert len(groups) == 7, groups
    assert [label for group in groups for label in group] == labels


def test_the_weights_license_is_metas_sam_license():
    block = _manifest()["model"]
    assert (block["license"], block["licenseFile"]) == ("SAM License", "LICENSE")
    text = (PACKAGE / block["licenseFile"]).read_text(encoding="utf-8")
    assert text.startswith("SAM License\n") and "SAM Materials" in text


def test_the_node_calls_only_curios_plumbing_and_shows_its_settings_first():
    """Its logic is its own code: it loads the model by the id the backend
    scans and keeps its files where the media route serves them, and calls
    nothing else of Curio's."""
    code = SOURCE.read_text(encoding="utf-8")
    tree = ast.parse("def node(input_0):\n" + "\n".join("    " + line for line in code.splitlines()))
    called = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name) and node.id.startswith("curio_")}
    assert called == {"curio_load_model", "curio_derived_file"}
    imported = [alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names]
    imported += [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    assert not [name for name in imported if name.split(".")[0] == "utk_curio"]
    assert f'curio_load_model("{MODEL_ID}")' in code
    settings = {}
    for statement in tree.body[0].body:
        if isinstance(statement, ast.Assign) and isinstance(statement.targets[0], ast.Name):
            if statement.targets[0].id.isupper() and statement.targets[0].id != "PER_FILE":
                try:
                    settings[statement.targets[0].id] = ast.literal_eval(statement.value)
                except ValueError:
                    continue
    assert settings["LABELS"] == DEFAULT_LABELS
    assert set(DEFAULT_LABELS) <= set(_manifest()["model"]["labels"])
    assert (settings["EVERY_SECONDS"], settings["FROM_SECONDS"], settings["TO_SECONDS"]) == (0.5, 0, None)
    assert settings["MAX_SECONDS"] > 0 and settings["WIDTH"] % 2 == 0
    assert code.index("LABELS = [") < code.index("curio_load_model(")


# ---------------------------------------------------------------------------
# The node, run
# ---------------------------------------------------------------------------

def test_without_its_weights_the_node_says_how_to_fetch_them(videos, catalog_copy, few_threads):
    from utk_curio.sandbox.util.models import NOT_FETCHED

    rows, helpers = videos
    with pytest.raises(RuntimeError) as raised:
        _run(rows, helpers, model_folder=catalog_copy, weights=None)
    assert str(raised.value) == NOT_FETCHED.format(model_id=MODEL_ID)


def test_empty_labels_stop_the_node_before_it_loads_the_model(videos, catalog_copy):
    rows, helpers = videos
    with pytest.raises(ValueError, match="LABELS is empty: name at least one thing to look for"):
        _run(rows, helpers, model_folder=catalog_copy, weights=None, LABELS=[])


def test_track_objects_follows_each_object_through_a_clip(videos, catalog_copy, weights, few_threads):
    import av
    import pandas as pd

    rows, helpers = videos
    (video,) = rows[rows["kind"] == "video"].to_dict("records")
    out = _run(rows, helpers, model_folder=catalog_copy, weights=weights, EVERY_SECONDS=EVERY)

    assert len(out) == 1
    row = out.iloc[0]
    # The row is the overlay, a video Simple View plays, made from the clip.
    assert (row["kind"], row["file_id"]) == ("video", f"{video['file_id']}@0-sam3.mp4")
    assert (row["video_file_id"], row["name"], row["dataset_id"]) == (video["file_id"], video["name"], video["dataset_id"])
    assert row["thumbnail"].endswith(f"/media/{row['file_id']}?variant=thumb")
    assert (row["t_s"], row["duration_s"], row["fps"]) == (0.0, len(SAMPLED) * EVERY, 1 / EVERY)
    assert Path(row["path"]).is_file()

    with av.open(row["path"]) as overlay:
        stream = overlay.streams.video[0]
        frames = list(overlay.decode(stream))
        codec, pix_fmt = stream.codec_context.name, stream.codec_context.pix_fmt
    encoder = av.codec.Codec("h264", "w").name
    assert codec == "h264" and pix_fmt == "yuv420p", (
        f"the overlay is {codec} in {pix_fmt}, written with av's {encoder} encoder")
    assert len(frames) == len(SAMPLED)
    assert (frames[0].width, frames[0].height) == (row["width"], row["height"]) == (96, 64)

    tracks = pd.read_parquet(row["tracks"])
    assert list(tracks.columns) == TRACK_COLUMNS
    # Thresholds at 0: random weights find something, six things at most.
    assert 1 <= len(tracks) <= 6
    assert tracks["object_id"].is_unique
    assert set(tracks["video_file_id"]) == {video["file_id"]} and set(tracks["video"]) == {video["name"]}
    assert set(tracks["label"]) <= set(DEFAULT_LABELS)
    assert (tracks["start_s"] <= tracks["end_s"]).all()
    assert set(tracks["start_s"]) | set(tracks["end_s"]) <= set(SAMPLED)
    assert tracks["frames"].between(1, len(SAMPLED)).all()
    assert tracks["largest_share"].between(0, 1).all()
    counts = {label: int(row[label.replace(" ", "_") + "_objects"]) for label in DEFAULT_LABELS}
    assert sum(counts.values()) == len(tracks)
    assert counts == {label: int((tracks["label"] == label).sum()) for label in DEFAULT_LABELS}


def test_a_part_longer_than_one_run_takes_stops_before_any_file_is_written(
    videos, catalog_copy, weights, few_threads, tmp_path,
):
    """The 2 s clip against a limit of 1 s: the node names the limit and the
    settings that pick a part, and writes no overlay and no tracks."""
    rows, helpers = videos
    relpath = rows["relpath"].iloc[0]
    with pytest.raises(ValueError) as raised:
        _run(rows, helpers, model_folder=catalog_copy, weights=weights, MAX_SECONDS=1)
    assert str(raised.value) == (
        f"{relpath}: Track Objects takes 1 s of video in one run; "
        "set FROM_SECONDS and TO_SECONDS to the part to track, such as 0 and 1"
    )
    assert not (tmp_path / "media" / "videos").exists() and not (tmp_path / "media" / "tables").exists()
    # The same clip tracked from 1 s to 2 s is a part of 1 s, which runs.
    out = _run(rows, helpers, model_folder=catalog_copy, weights=weights, MAX_SECONDS=1, FROM_SECONDS=1,
               TO_SECONDS=2, EVERY_SECONDS=EVERY)
    assert (out["file_id"].iloc[0], out["t_s"].iloc[0]) == (f"{rows['file_id'].iloc[0]}@1000-sam3.mp4", 1.0)


def test_a_video_not_on_this_machine_says_to_cache_it(videos, catalog_copy, weights, few_threads):
    rows, helpers = videos
    relpath = rows["relpath"].iloc[0]
    rows = rows.copy()
    rows["path"] = None
    with pytest.raises(ValueError, match=re.escape(f"{relpath} is not on this machine yet; cache the collection's files first")):
        _run(rows, helpers, model_folder=catalog_copy, weights=weights)
