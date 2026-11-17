"""SAM 3's model package, ``model.curio.sam3@1``, and its Track Objects node.

Track Objects' logic is a module of the package, ``sources/sam3_tracking.py``,
whose ``track_objects`` the node's code tab calls with its settings and Curio's
plumbing (``sources/track-objects.py``). These tests run that function, and
the node's code as the canvas runs it (``input_names.call_as_node``), each with
the module staged and imported as a run of the node stages it, on the rows Data
Loading gives for a folder of videos.

SAM 3's weights are Meta's, 3.4 GB: no clone, image or pip install holds them,
a node's first run downloads them from an identical copy, and no test fetches
them. The tests use a tiny SAM 3 video model built here with random weights:

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
import contextlib
import importlib
import json
import os
import re
import shutil
import tempfile
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO = Path(__file__).resolve().parents[4]
PACKAGE = REPO / "packages" / "model.curio.sam3@1"
MODEL_ID = "model.curio.sam3"
SOURCE = PACKAGE / "sources" / "track-objects.py"
#: The package's module, which holds Track Objects' logic.
MODULE = "sam3_tracking"
MODULE_SOURCE = PACKAGE / "sources" / f"{MODULE}.py"
#: The node's settings, in its code tab's order, and the arguments they are.
SETTINGS = {
    "LABELS": "labels", "EVERY_SECONDS": "every_seconds", "FORGET_SECONDS": "forget_seconds",
    "FROM_SECONDS": "from_seconds", "TO_SECONDS": "to_seconds", "MAX_SECONDS": "max_seconds", "WIDTH": "width",
}
#: Meta's SAM 3 is gated (``facebook/sam3``, at the revision sideseeing-tools
#: pins, 3c879f39826c281e95690f02c7821c4de09afae7). Its weights download from
#: an identical copy, ungated, at this revision.
REPOSITORY = "jetjodh/sam3"
REVISION = "1aa50ce07302cb375f85d8084b68a0fb378b8d85"
#: The files Transformers reads of it, with Meta's digests: the sha256 of the
#: weights, stored with Git LFS, and the git blob hash of every other file.
#: sam3.pt, the original code's checkpoint, is not one.
CHECKPOINT_DIGESTS = {
    "config.json": ("gitSha1", "3e600e765b0f1b4c52680aed9ad242c9a90f7ed1"),
    "model.safetensors": ("sha256", "6d06f0a5f84e435071fe6603e61d0b4cc7b40e0d39d487cfd4d67d8cc11cc14a"),
    "processor_config.json": ("gitSha1", "9d3bd6df8a54852cd56087a3ae019cce051de2b2"),
    "tokenizer.json": ("gitSha1", "bd1e367764006ad6a2249b1dcc0b20879c7c211f"),
    "tokenizer_config.json": ("gitSha1", "1f20c0274c5d4581b5ccdcbdddd7a22729b5c57b"),
    "special_tokens_map.json": ("gitSha1", "cf0682d6de72c1547f41b4f6d7c59f62deffef94"),
    "vocab.json": ("gitSha1", "182766ce89b439768edadda342519f33802f5364"),
    "merges.txt": ("gitSha1", "76e821f1b6f0a9709293c3b6b51ed90980b3166b"),
}
CHECKPOINT_FILES = list(CHECKPOINT_DIGESTS)
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
#: The frame rate of the SideSeeing walk Track Objects ran on in dev's check,
#: 30.033 frames a second, at which a frame can come just before a step's time.
WALK_RATE = Fraction(30033, 1000)


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


def _tiny_config(tracking=None, **video):
    """A Sam3VideoConfig of about 5.8 M parameters that tracks text prompts:
    four FPN scale factors as SAM 3's; a hidden size of 128, a multiple of the
    64-wide memory, as SAM 3's 256 is; ``image_size`` on the video config;
    detection thresholds at 0, so random weights detect; six objects at most.
    *tracking* sets the tracker's own settings, and keywords the video's, such
    as ``max_num_objects``."""
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
    tracker = Sam3TrackerVideoConfig(**{
        "vision_config": vision,
        "prompt_encoder_config": Sam3TrackerVideoPromptEncoderConfig(hidden_size=hidden, image_size=SIZE, patch_size=14),
        "mask_decoder_config": Sam3TrackerVideoMaskDecoderConfig(hidden_size=hidden),
        "num_maskmem": 2,
        "memory_attention_hidden_size": hidden,
        "memory_attention_num_layers": 1,
        "memory_attention_feed_forward_hidden_size": 2 * hidden,
        "memory_attention_rope_feat_sizes": [SIZE // 14, SIZE // 14],
        "memory_encoder_hidden_size": hidden,
        "memory_encoder_output_channels": 64,
        "mask_downsampler_embed_dim": hidden,
        "memory_fuser_embed_dim": hidden,
        "memory_fuser_intermediate_dim": 2 * hidden,
        "max_object_pointers_in_encoder": 4,
        **(tracking or {}),
    })
    objects = video.pop("max_num_objects", 6)
    config = Sam3VideoConfig(**{
        "detector_config": detector, "tracker_config": tracker,
        "score_threshold_detection": 0.0, "new_det_thresh": 0.0, "hotstart_delay": 0,
        "low_res_mask_size": SIZE * 288 // 1008,
        **video,
    })
    config.image_size = SIZE
    config.max_num_objects = objects
    return config


def _tiny_weights(tmp_path_factory, config):
    """The package's folder under ``--model-weights-dir``, its entry holding a
    tiny SAM 3 of *config* and its processor: every file the package's
    ``fetch`` lists."""
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
    Sam3VideoModel(config).save_pretrained(checkpoint)
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


@pytest.fixture(scope="module")
def weights(tmp_path_factory):
    """The tiny SAM 3, saved where ``--model-weights-dir`` puts the package's
    weights."""
    return _tiny_weights(tmp_path_factory, _tiny_config())


@pytest.fixture(scope="module")
def steady_weights(tmp_path_factory):
    """A tiny SAM 3 whose objects stay the same from the first frame: its
    first frame's detections, all kept, fill its three objects, and it takes
    no object again from a detection nor drops one in its first frames."""
    return _tiny_weights(tmp_path_factory, _tiny_config(
        det_nms_thresh=0.0, max_num_objects=3, recondition_every_nth_frame=0,
    ))


#: The windows of the tiny SAM 3 ``windowed_weights`` saves: what SAM 3 reads
#: again of the frames before the one it looks at.
WINDOWS = {"num_maskmem": 3, "max_object_pointers_in_encoder": 4, "max_cond_frame_num": 2}


@pytest.fixture(scope="module")
def windowed_weights(tmp_path_factory):
    """A tiny SAM 3 that reads again the memory of its last two frames and of
    each object's last two conditioning frames, and pointers of its last
    three; that holds each frame back until it has seen three after it; and
    that takes every object it follows again from a detection every second
    frame, so each gains more conditioning frames than SAM 3 reads memory of."""
    return _tiny_weights(tmp_path_factory, _tiny_config(
        WINDOWS, det_nms_thresh=0.0, max_num_objects=3,
        hotstart_delay=3, hotstart_unmatch_thresh=3, hotstart_dup_thresh=3,
        recondition_every_nth_frame=2, high_conf_thresh=-1e4, high_iou_thresh=0.0,
    ))


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

def _street(index: int):
    """Frame *index* of the clip: an orange box crossing a dark street, 8
    pixels further each frame, as an RGB array."""
    import numpy as np

    image = np.full((64, 96, 3), 40, dtype=np.uint8)
    image[20:44, 8 + 8 * index:24 + 8 * index] = (230, 120, 40)
    return image


def _clip(path: Path, seconds: float = CLIP_SECONDS) -> None:
    """A clip of :func:`_street`, *seconds* long, in MPEG-4 Part 2, which every
    FFmpeg build reads and writes, so the overlay alone needs H.264."""
    import av

    with av.open(str(path), "w") as out:
        stream = out.add_stream("mpeg4", rate=CLIP_RATE)
        stream.width, stream.height, stream.pix_fmt = 96, 64, "yuv420p"
        for index in range(int(seconds * CLIP_RATE)):
            for packet in stream.encode(av.VideoFrame.from_ndarray(_street(index), format="rgb24")):
                out.mux(packet)
        for packet in stream.encode():
            out.mux(packet)


def _collection(tmp_path: Path, seconds: float = CLIP_SECONDS):
    """``(rows, helpers)``: what Data Loading's ``curio_load_collection`` gives
    for a folder holding one clip *seconds* long, and the helpers a node runs
    with."""
    from utk_curio.backend.app.discovery.domain.manifest import load_source_manifest
    from utk_curio.backend.tests.test_discovery.conftest import a_storage_manifest, write_source
    from utk_curio.backend.tests.test_packages.test_media_package import collection_rows

    root = tmp_path / "walk"
    root.mkdir()
    _clip(root / "corner.mp4", seconds)
    resource = {"id": "walk", "name": "Walk", "kind": "videos", "path": "*", "extensions": ["mp4"]}
    source = write_source(tmp_path / "discovery", "source.example.folder@1", a_storage_manifest(root, [resource]))
    return collection_rows(load_source_manifest(source), "walk", tmp_path)


@pytest.fixture
def videos(tmp_path):
    """``(rows, helpers)`` for a folder holding the 2 s clip."""
    return _collection(tmp_path)


@pytest.fixture
def walk(tmp_path):
    """A 33 s clip at the walk's rate, as ``_sample`` reads a video: from 30 s,
    its frames come 0.2 ms before 30.5 s, 0.8 ms before 31 s and 1.3 ms before
    31.5 s, each followed by the next frame 33 ms later."""
    import av
    import numpy as np

    path = tmp_path / "walk.mp4"
    image = np.full((32, 32, 3), 40, dtype=np.uint8)
    with av.open(str(path), "w") as out:
        stream = out.add_stream("mpeg4", rate=WALK_RATE)
        stream.width, stream.height, stream.pix_fmt = 32, 32, "yuv420p"
        for _ in range(int(33 * WALK_RATE)):
            for packet in stream.encode(av.VideoFrame.from_ndarray(image, format="rgb24")):
                out.mux(packet)
        for packet in stream.encode():
            out.mux(packet)
    # The clip's own times, so a writer that moved them fails here, not later.
    with av.open(str(path)) as clip:
        times = [float(frame.time) for frame in clip.decode(video=0)]
    early = [round(1000 * (step - max(t for t in times if t < step)), 1) for step in (30.5, 31.0, 31.5)]
    assert early == [0.2, 0.8, 1.3], f"the clip's frames come {early} ms before 30.5, 31 and 31.5 s"
    return {"path": str(path), "relpath": "walk.mp4"}


@pytest.fixture
def corner(tmp_path):
    """The 2 s clip at 4 frames a second, as ``_sample`` reads a video."""
    _clip(tmp_path / "corner.mp4")
    return {"path": str(tmp_path / "corner.mp4"), "relpath": "corner.mp4"}


def _times(module, video, from_seconds, end):
    """The times of the frames ``_sample`` looks at in *video*, every EVERY
    seconds from *from_seconds* up to *end*."""
    return module._sample(SimpleNamespace(width=960, from_seconds=from_seconds, every_seconds=EVERY), video, end)[1]


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


@contextlib.contextmanager
def _staged(tmp_path: Path):
    """The package's module, importable as a run of Track Objects imports it:
    staged into a folder of the run's own, then imported by its name."""
    from utk_curio.sandbox.util.package_modules import importable
    from utk_curio.sandbox.util.staging import stage_package_modules

    run = Path(tempfile.mkdtemp(prefix="run-", dir=tmp_path))
    staged = stage_package_modules([{"root": str(PACKAGE / "sources"), "names": [MODULE]}], str(run))
    assert staged == {"root": "package_modules", "names": [MODULE]}, staged
    with importable(str(run / staged["root"]), staged["names"]):
        yield importlib.import_module(MODULE)


def _loaded(model_folder: Path, weights: Path | None):
    """``curio_load_model`` for the package in *model_folder*, its weights read
    in place in *weights*, as a run on a Curio started with
    ``--model-weights-dir`` gets it."""
    from utk_curio.sandbox.util.catalog_helpers import install_catalog_helpers

    loaders = {}
    install_catalog_helpers(
        loaders, data_path=str, formats={}, collections={}, media_dir=None,
        models={MODEL_ID: str(model_folder)}, model_weights={MODEL_ID: str(weights)} if weights else None,
    )
    return loaders["curio_load_model"]


def _run(rows, helpers, tmp_path: Path, *, model_folder: Path, weights: Path | None, **settings):
    """The node's output on *rows*: its code, with *settings* set, run as the
    canvas runs it, with the package's module importable."""
    from utk_curio.sandbox.util.input_names import call_as_node

    namespace = {**helpers, "curio_load_model": _loaded(model_folder, weights)}
    body = "\n".join("    " + line for line in _node_source(**settings).splitlines())
    with _staged(tmp_path):
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
    from utk_curio.backend.app.packages.repositories.python_modules import module_names

    manifest = load_package_manifest(PACKAGE)
    block = manifest.model
    assert (manifest.kind, block.type, block.runtime, block.entry) == (
        "model", "concept-segmentation", "transformers", "models/checkpoint")
    assert [(t.template_id, t.label, t.source) for t in manifest.templates] == [
        ("track-objects", "Track Objects", "sources/track-objects.py")]
    # The node's logic is the package's one module; its source is no module.
    assert module_names(PACKAGE, manifest) == {MODULE}
    deps = dict(manifest.python_deps)
    assert deps["transformers"] == ">=5.0,<6.0" and "safetensors" in deps
    # The node imports torch, and the processor needs torchvision as it loads.
    # Every image holds both, built for CUDA: with no version asked, they are
    # what an add finds installed, and pip installs neither.
    assert (deps["torch"], deps["torchvision"]) == ("", "")


def test_the_weights_download_from_the_copy_with_metas_digests_and_never_ship():
    """The copy, at its revision, names Meta's files by Meta's digests, so a
    file that is not Meta's is never placed; the homepage stays Meta's."""
    block = _manifest()["model"]
    fetch = block["fetch"]
    assert (fetch["huggingface"], fetch["revision"]) == (REPOSITORY, REVISION)
    assert [item["path"] for item in fetch["files"]] == CHECKPOINT_FILES
    # Hugging Face stores the weights with Git LFS, which lists a SHA-256; the
    # other files by their git blob.
    assert {
        item["path"]: next((kind, item[kind]) for kind in ("sha256", "gitSha1") if kind in item)
        for item in fetch["files"]
    } == CHECKPOINT_DIGESTS
    assert all(len(item) == 2 for item in fetch["files"]), fetch["files"]
    assert block["homepage"] == "https://huggingface.co/facebook/sam3"
    assert block["sizeBytes"] == 3_444_996_474
    assert "downloadOnFirstUse" not in _manifest()
    # The package's own files, which a clone that fetched the weights into
    # the package's folder holds beside them.
    integrity = json.loads((PACKAGE / "integrity.json").read_text(encoding="utf-8"))["sha256"]
    assert sorted(integrity) == sorted([
        "LICENSE", "README.md", "manifest.json", "sources/track-objects.py", f"sources/{MODULE}.py",
    ] + [
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


def test_the_code_tab_holds_its_settings_and_one_call_of_the_packages_module():
    """Track Objects' logic is the package's module: its code tab imports the
    module's function, sets the node's settings, and returns one call of it,
    which hands it Curio's plumbing, the model by the literal id the backend
    reads and ``curio_derived_file``, and each setting as its argument."""
    code = SOURCE.read_text(encoding="utf-8")
    assert f'curio_load_model("{MODEL_ID}")' in code
    body = ast.parse("def node(input_0):\n" + "\n".join("    " + line for line in code.splitlines())).body[0].body
    imports, assigns, returned = body[:1], body[1:-1], body[-1]
    assert [ast.unparse(statement) for statement in imports] == [f"from {MODULE} import track_objects"]
    assert all(isinstance(statement, ast.Assign) for statement in assigns), [ast.unparse(s) for s in assigns]
    settings = {statement.targets[0].id: ast.literal_eval(statement.value) for statement in assigns}
    assert list(settings) == list(SETTINGS)
    assert settings["LABELS"] == DEFAULT_LABELS
    assert set(DEFAULT_LABELS) <= set(_manifest()["model"]["labels"])
    assert (settings["EVERY_SECONDS"], settings["FROM_SECONDS"], settings["TO_SECONDS"]) == (0.5, 0, None)
    assert settings["FORGET_SECONDS"] == 10
    assert settings["MAX_SECONDS"] > 0 and settings["WIDTH"] % 2 == 0
    assert isinstance(returned, ast.Return) and isinstance(returned.value, ast.Call), ast.unparse(returned)
    call = returned.value
    assert ast.unparse(call.func) == "track_objects"
    assert [ast.unparse(arg) for arg in call.args] == [
        "input_0", f"curio_load_model('{MODEL_ID}')", "curio_derived_file"]
    assert {keyword.arg: ast.unparse(keyword.value) for keyword in call.keywords} == {
        argument: setting for setting, argument in SETTINGS.items()}


def test_the_module_offers_track_objects_says_what_it_does_and_is_handed_curios_plumbing():
    """The Functions header above the node's code lists what the module's
    ``__all__`` names, each with the first paragraph of its docstring. The
    module imports nothing of Curio's and calls none of Curio's functions: the
    node hands it the model and ``curio_derived_file``."""
    tree = ast.parse(MODULE_SOURCE.read_text(encoding="utf-8"))
    (offered,) = [
        statement for statement in tree.body
        if isinstance(statement, ast.Assign) and [ast.unparse(t) for t in statement.targets] == ["__all__"]
    ]
    assert ast.literal_eval(offered.value) == ["track_objects"]
    (function,) = [s for s in tree.body if isinstance(s, ast.FunctionDef) and s.name == "track_objects"]
    first = " ".join((ast.get_docstring(function) or "").split("\n\n", 1)[0].split())
    assert "SAM 3" in first and len(first) <= 600, first
    assert [arg.arg for arg in function.args.args] == ["media", "model", "derived_file"]
    assert [arg.arg for arg in function.args.kwonlyargs] == list(SETTINGS.values())
    imported = [alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names]
    imported += [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    assert not [name for name in imported if name.split(".")[0] == "utk_curio"]
    assert not [node.id for node in ast.walk(tree) if isinstance(node, ast.Name) and node.id.startswith("curio_")]


# ---------------------------------------------------------------------------
# The node, run
# ---------------------------------------------------------------------------

def test_without_its_weights_the_node_says_how_to_fetch_them(videos, catalog_copy, few_threads, tmp_path):
    from utk_curio.sandbox.util.models import NOT_FETCHED

    rows, helpers = videos
    with pytest.raises(RuntimeError) as raised:
        _run(rows, helpers, tmp_path, model_folder=catalog_copy, weights=None)
    assert str(raised.value) == NOT_FETCHED.format(model_id=MODEL_ID)


def test_the_nodes_code_hands_its_settings_to_the_module(videos, catalog_copy, weights, few_threads, tmp_path):
    """The code tab's call, run as the canvas runs it: the node's settings
    reach ``track_objects``, and the node returns the overlay's row."""
    import pandas as pd

    rows, helpers = videos
    out = _run(rows, helpers, tmp_path, model_folder=catalog_copy, weights=weights,
               LABELS=["pole", "person"], EVERY_SECONDS=1.0)
    (row,) = out.to_dict("records")
    # One frame a second of the 2 s clip: at 0 s and 1 s.
    assert (row["kind"], row["fps"], row["duration_s"]) == ("video", 1.0, 2.0)
    assert sorted(key for key in row if key.endswith("_objects")) == ["person_objects", "pole_objects"]
    tracks = pd.read_parquet(row["tracks"])
    assert set(tracks["label"]) <= {"pole", "person"}
    assert row["pole_objects"] + row["person_objects"] == len(tracks)


def test_track_objects_follows_each_object_through_a_clip(videos, catalog_copy, weights, few_threads, tmp_path):
    import av
    import pandas as pd

    rows, helpers = videos
    (video,) = rows[rows["kind"] == "video"].to_dict("records")
    model = _loaded(catalog_copy, weights)(MODEL_ID)
    with _staged(tmp_path) as module:
        out = module.track_objects(rows, model, helpers["curio_derived_file"], labels=DEFAULT_LABELS,
                                   every_seconds=EVERY)
        tag = module._tag(DEFAULT_LABELS, EVERY, 10, module._part_end(video, 0, None, 300), 960)

    assert len(out) == 1
    row = out.iloc[0]
    # The row is the overlay, a video Simple View plays, made from the clip,
    # named by where it starts and by what the call asked.
    assert (row["kind"], row["file_id"]) == ("video", f"{video['file_id']}@0-{tag}.mp4")
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


def test_a_part_of_a_video_is_tracked_from_where_it_starts(videos, catalog_copy, weights, few_threads, tmp_path):
    """The 2 s clip from 1 s to 2 s, a part of 1 s, within a limit of 1 s: its
    files are named by where the part starts, and so is its overlay's time."""
    rows, helpers = videos
    model = _loaded(catalog_copy, weights)(MODEL_ID)
    with _staged(tmp_path) as module:
        out = module.track_objects(rows, model, helpers["curio_derived_file"], labels=DEFAULT_LABELS,
                                   every_seconds=EVERY, from_seconds=1, to_seconds=2, max_seconds=1)
        tag = module._tag(DEFAULT_LABELS, EVERY, 10, 2, 960)
    (row,) = out.to_dict("records")
    assert (row["file_id"], row["t_s"], row["duration_s"]) == (
        f"{rows['file_id'].iloc[0]}@1000-{tag}.mp4", 1.0, 2 * EVERY)


def test_two_calls_that_ask_differently_of_one_video_keep_files_of_their_own(
        videos, catalog_copy, weights, few_threads, tmp_path):
    """Two Track Objects runs on one video from one start, with other
    settings, as two dataflows of one account run them: each keeps its own
    overlay and tracks, which the other's run leaves as they were. On dev a
    run of 0 to 300 s at a frame every 0.5 s overwrote another dataflow's
    overlay of the whole walk at a frame every 2 s, which then played 300 s
    instead of 866 s. A call that asks the same as an earlier one writes that
    call's files again."""
    import av
    import pandas as pd

    rows, helpers = videos
    model = _loaded(catalog_copy, weights)(MODEL_ID)

    def frames_of(path):
        with av.open(path) as overlay:
            return sum(1 for _ in overlay.decode(overlay.streams.video[0]))

    with _staged(tmp_path) as module:
        def track(every):
            return module.track_objects(rows, model, helpers["curio_derived_file"], labels=DEFAULT_LABELS,
                                        every_seconds=every).iloc[0]

        first = track(EVERY)
        first_tracks = pd.read_parquet(first["tracks"])
        other = track(2 * EVERY)
        assert first["path"] != other["path"] and first["tracks"] != other["tracks"], (
            f"two calls that ask differently of one video wrote one overlay ({first['path']}) "
            f"and one tracks file ({first['tracks']})")
        assert frames_of(first["path"]) == len(SAMPLED), "the other call's run changed the first call's overlay"
        assert frames_of(other["path"]) == len(SAMPLED[::2])
        assert pd.read_parquet(first["tracks"]).equals(first_tracks), (
            "the other call's run changed the first call's tracks")
        again = track(EVERY)

    assert (again["path"], again["tracks"]) == (first["path"], first["tracks"]), (
        "a call that asks the same as an earlier one got files of its own")


def test_every_frame_up_to_the_parts_end_decodes_with_frame_threading(videos, tmp_path, monkeypatch):
    """Track Objects looks at one frame every EVERY_SECONDS, but decodes every
    frame up to the part's end. On dev the 864 s SideSeeing walk at 1080p is
    25,955 frames: 271 s of decoding with FFmpeg's default, slice threading,
    50 s with frame threading, against an isolated node's 300 s."""
    import av

    rows, _helpers = videos
    video = rows[rows["kind"] == "video"].iloc[0]
    decoded_as = []
    real_open = av.open

    class _Recording:
        """The container ``_sample`` opens, noting how each stream it decodes is threaded."""

        def __init__(self, container):
            self._container = container

        def __enter__(self):
            self._container.__enter__()
            return self

        def __exit__(self, *exc):
            return self._container.__exit__(*exc)

        def __getattr__(self, name):
            return getattr(self._container, name)

        def decode(self, stream):
            decoded_as.append(stream.thread_type)
            return self._container.decode(stream)

    with _staged(tmp_path) as module:
        monkeypatch.setattr(module.av, "open", lambda *args, **kwargs: _Recording(real_open(*args, **kwargs)))
        run = SimpleNamespace(width=960, from_seconds=0, every_seconds=EVERY)
        frames, times = module._sample(run, video, CLIP_SECONDS)

    assert times == SAMPLED and len(frames) == len(SAMPLED)
    assert [getattr(kind, "name", kind) for kind in decoded_as] == ["AUTO"], decoded_as


def test_one_frame_is_looked_at_for_each_step_never_two_for_one(walk, tmp_path):
    """Track Objects looks at one frame every EVERY_SECONDS. On dev, 10 s of a
    30.033 fps walk at 0.5 s gave 22 frames, not 20: a frame just before a
    step's time was looked at for it, and the next frame too, so the overlay
    played 9.5 s of video as 11 s and drifted from the video's times. From 30 s
    to 31.75 s of a clip at that rate, each of the four steps gets one frame."""
    with _staged(tmp_path) as module:
        run = SimpleNamespace(width=960, from_seconds=30, every_seconds=EVERY)
        frames, times = module._sample(run, walk, 31.75)
    steps = [round((t - 30) / EVERY) for t in times]
    assert times == [30.0, 30.5, 30.999, 31.532], f"looked at {times}, in steps {steps}, not 30.0, 30.5, 30.999, 31.532"
    assert len(frames) == len(times)


def test_a_frame_just_before_a_steps_time_is_the_one_looked_at_for_it(walk, tmp_path):
    """A frame at most a millisecond before a step's time is that step's frame:
    the one 0.8 ms before 31 s is looked at."""
    with _staged(tmp_path) as module:
        run = SimpleNamespace(width=960, from_seconds=30, every_seconds=EVERY)
        times = module._sample(run, walk, 31.75)[1]
    assert 30.999 in times, f"looked at {times}, not the frame at 30.999 s"


def test_the_steps_end_before_to_seconds_however_the_frames_fall(corner, walk, tmp_path):
    """A part of W seconds has W / EVERY_SECONDS steps, from FROM_SECONDS up
    to TO_SECONDS: the step at TO_SECONDS is not one, whether a frame comes
    right at it, as at 1 s of the 4 fps clip, or 0.8 ms before it, as before
    31 s of the walk."""
    with _staged(tmp_path) as module:
        on_the_step = _times(module, corner, 0, 1.0)
        just_before = _times(module, walk, 30.5, 31.0)
    assert (on_the_step, just_before) == ([0.0, 0.5], [30.5]), (on_the_step, just_before)


def test_a_step_before_to_seconds_looks_at_its_frame_even_after_it(walk, tmp_path):
    """Every step from FROM_SECONDS up to TO_SECONDS gets its frame: the first
    from a millisecond before its time to a millisecond before the next
    step's, even when that frame comes after TO_SECONDS. From 30 s to 31.51 s
    of the walk, the step at 31.5 s looks at the frame at 31.532 s."""
    with _staged(tmp_path) as module:
        times = _times(module, walk, 30, 31.51)
    assert times == [30.0, 30.5, 30.999, 31.532], f"looked at {times}, not 30.0, 30.5, 30.999, 31.532"


def test_a_part_of_no_length_looks_at_the_first_frame_from_its_start(corner, walk, tmp_path):
    """FROM_SECONDS equal to TO_SECONDS looks at one frame wherever the frames
    fall: the first no more than a millisecond before FROM_SECONDS, or after
    it. That is the frame right at 1 s of the 4 fps clip, the one 0.8 ms before
    31 s of the walk, and the one 32 ms after 31.5 s, whose frame 1.3 ms
    before is too early. Past the video's end there is no frame."""
    with _staged(tmp_path) as module:
        at_it = _times(module, corner, 1.0, 1.0)
        just_before = _times(module, walk, 31.0, 31.0)
        after_it = _times(module, walk, 31.5, 31.5)
        with pytest.raises(ValueError) as past_the_end:
            _times(module, walk, 40, 40)
    assert (at_it, just_before, after_it) == ([1.0], [30.999], [31.532]), (at_it, just_before, after_it)
    assert str(past_the_end.value) == "walk.mp4 has no frames from 40 to 40 s"


def test_with_every_shorter_than_a_frame_the_overlay_plays_in_real_time(
        videos, catalog_copy, weights, few_threads, tmp_path):
    """With EVERY_SECONDS shorter than the gap between two of the video's
    frames, SAM 3 looks at every frame, and the overlay plays each at its own
    time: the 2 s clip at 4 frames a second, looked at every 0.1 s, is an
    overlay of its 8 frames over 2 s. At 1 / EVERY_SECONDS frames a second it
    would play them in 0.8 s."""
    import av

    rows, helpers = videos
    model = _loaded(catalog_copy, weights)(MODEL_ID)
    with _staged(tmp_path) as module:
        out = module.track_objects(rows, model, helpers["curio_derived_file"], labels=DEFAULT_LABELS,
                                   every_seconds=0.1)
    (row,) = out.to_dict("records")
    with av.open(row["path"]) as overlay:
        stream = overlay.streams.video[0]
        shown = [round(float(frame.time), 3) for frame in overlay.decode(stream)]
        plays_for = float(stream.duration * stream.time_base)
    assert shown == [0.0, 0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 1.75], f"the overlay shows its frames at {shown} s"
    assert (row["t_s"], row["duration_s"], row["fps"], plays_for) == (0.0, 2.0, 4.0, 2.0)


def test_each_stop_comes_before_sam3_loads_and_writes_nothing(videos, tmp_path):
    """Empty labels, a part longer than one run takes and a video not on this
    machine each stop the call before any frame is read or file written, and
    before SAM 3 loads: the model here names a folder that holds nothing. A
    collection with no video loads nothing either."""
    rows, helpers = videos
    relpath = rows["relpath"].iloc[0]
    nothing = SimpleNamespace(path=str(tmp_path / "no-weights"))
    derived = helpers["curio_derived_file"]
    with _staged(tmp_path) as module:
        with pytest.raises(ValueError) as no_labels:
            module.track_objects(rows, nothing, derived, labels=[])
        with pytest.raises(ValueError) as too_long:
            module.track_objects(rows, nothing, derived, labels=DEFAULT_LABELS, max_seconds=1)
        with pytest.raises(ValueError) as not_cached:
            module.track_objects(rows.assign(path=None), nothing, derived, labels=DEFAULT_LABELS)
        assert module.track_objects(rows.assign(kind="image"), nothing, derived, labels=DEFAULT_LABELS).empty
    assert str(no_labels.value) == "LABELS is empty: name at least one thing to look for"
    assert str(too_long.value) == (
        f"{relpath}: Track Objects takes 1 s of video in one run; "
        "set FROM_SECONDS and TO_SECONDS to the part to track, such as 0 and 1"
    )
    assert str(not_cached.value) == f"{relpath} is not on this machine yet; cache the collection's files first"
    assert not (tmp_path / "media" / "videos").exists() and not (tmp_path / "media" / "tables").exists()


# ---------------------------------------------------------------------------
# The frames one run looks at
# ---------------------------------------------------------------------------

#: The SideSeeing walk's length, which Track Objects ran on whole in dev's
#: check: 433 frames at a frame every 2 s, in 208 s of a node's 300 s.
WALK_SECONDS = 864.3
#: The node's code as a dataflow saved before MAX_FRAMES holds it.
SAVED_WITH_MAX_SECONDS = '''from sam3_tracking import track_objects

# What to look for, in plain words: SAM 3 takes any short noun phrase.
LABELS = [
    "curb ramp", "curb cut", "tactile paving", "bollard", "pole",
    "construction barrier", "traffic cone", "person",
]
EVERY_SECONDS = 0.5  # the gap between two frames SAM 3 looks at
FORGET_SECONDS = 10  # SAM 3 lets go of an object unseen this long; None keeps every object
FROM_SECONDS = 0  # the part of each video to track, in seconds from its start
TO_SECONDS = None  # None is the video's end
MAX_SECONDS = 300  # the most video one run takes
WIDTH = 960  # the widest frames are read and drawn at

return track_objects(
    input_0, curio_load_model("model.curio.sam3"), curio_derived_file,
    labels=LABELS, every_seconds=EVERY_SECONDS, forget_seconds=FORGET_SECONDS,
    from_seconds=FROM_SECONDS, to_seconds=TO_SECONDS, max_seconds=MAX_SECONDS, width=WIDTH,
)
'''


class _SamLoads(Exception):
    """SAM 3 was about to load: the call passed every stop before it."""


@pytest.fixture
def no_sam3(monkeypatch):
    """Makes a staged module raise :class:`_SamLoads` where SAM 3 would load,
    so a test sees whether a call passed its stops without loading SAM 3."""

    def stop(module):
        class _Loading:
            @staticmethod
            def from_pretrained(*_args, **_kwargs):
                raise _SamLoads("SAM 3 loads: the call passed every stop")

        monkeypatch.setattr(module, "Sam3VideoProcessor", _Loading)

    return stop


def _rows_of(video: dict):
    """The rows of a collection holding *video* alone, as Track Objects' stops
    read them."""
    import pandas as pd

    return pd.DataFrame([{"kind": "video", **video}])


def _code_tab_settings() -> dict:
    """The settings the node's code tab sets, by name."""
    code = SOURCE.read_text(encoding="utf-8")
    body = ast.parse("def node(input_0):\n" + "\n".join("    " + line for line in code.splitlines())).body[0].body
    return {
        statement.targets[0].id: ast.literal_eval(statement.value)
        for statement in body if isinstance(statement, ast.Assign)
    }


def _whole_walk(tmp_path: Path) -> dict:
    """A clip as long as the walk, 864.3 s at 10 frames a second, as
    ``_sample`` reads a video."""
    import av
    import numpy as np

    path = tmp_path / "whole-walk.mp4"
    image = np.full((32, 32, 3), 40, dtype=np.uint8)
    with av.open(str(path), "w") as out:
        stream = out.add_stream("mpeg4", rate=10)
        stream.width, stream.height, stream.pix_fmt = 32, 32, "yuv420p"
        for _ in range(round(WALK_SECONDS * 10)):
            for packet in stream.encode(av.VideoFrame.from_ndarray(image, format="rgb24")):
                out.mux(packet)
        for packet in stream.encode():
            out.mux(packet)
    return {"path": str(path), "relpath": path.name}


def test_a_part_that_needs_more_frames_than_max_frames_stops_before_sam3_loads_whatever_its_length(
        videos, tmp_path, no_sam3):
    """A run's time follows the frames SAM 3 looks at, not the seconds of the
    part: the 2 s clip at a frame every half second, and its first second at a
    frame every quarter second, each need 4 frames, so each stops at a limit
    of 3 before SAM 3 loads and writes nothing, though both are seconds long.
    The message names the limit, the frames the part needs, and an
    EVERY_SECONDS and a shorter part that fit, which each pass."""
    rows, helpers = videos
    relpath = rows["relpath"].iloc[0]
    nothing = SimpleNamespace(path=str(tmp_path / "no-weights"))
    with _staged(tmp_path) as module:
        no_sam3(module)

        def track(**settings):
            return module.track_objects(rows, nothing, helpers["curio_derived_file"], labels=DEFAULT_LABELS,
                                        max_frames=3, **settings)

        with pytest.raises(ValueError) as whole_clip:
            track(every_seconds=EVERY)
        with pytest.raises(ValueError) as first_second:
            track(every_seconds=EVERY / 2, to_seconds=1)
        for fits in ({"every_seconds": 0.7}, {"every_seconds": EVERY, "to_seconds": 1.5},
                     {"every_seconds": 0.4, "to_seconds": 1}, {"every_seconds": EVERY / 2, "to_seconds": 0.75}):
            with pytest.raises(_SamLoads):
                track(**fits)

    assert str(whole_clip.value) == (
        f"{relpath}: Track Objects looks at 3 frames of a video at most in one run, and 0 to 2 s at a frame "
        "every 0.5 s is 4 frames; raise EVERY_SECONDS to 0.7 or more, or set FROM_SECONDS and TO_SECONDS to a "
        "shorter part, such as 0 and 1.5"
    )
    assert str(first_second.value) == (
        f"{relpath}: Track Objects looks at 3 frames of a video at most in one run, and 0 to 1 s at a frame "
        "every 0.25 s is 4 frames; raise EVERY_SECONDS to 0.4 or more, or set FROM_SECONDS and TO_SECONDS to a "
        "shorter part, such as 0 and 0.75"
    )
    assert not (tmp_path / "media" / "videos").exists() and not (tmp_path / "media" / "tables").exists()


def test_a_run_may_look_at_max_frames_frames_of_a_part_and_not_one_more(corner, walk, tmp_path, no_sam3):
    """The frames the limit counts are the frames a run looks at: each part
    the steps' tests pin, whose frames fall on a step, a millisecond before it
    or after the part's end, passes a limit of the frames ``_sample`` looks at
    in it, and stops before SAM 3 loads at one fewer, naming them."""
    nothing = SimpleNamespace(path=str(tmp_path / "no-weights"))
    parts = [
        (corner, 0, None), (corner, 0, 1.0), (corner, 1.0, 1.0),
        (walk, 30, 31.75), (walk, 30.5, 31.0), (walk, 30, 31.51), (walk, 31.0, 31.0), (walk, 31.5, 31.5),
    ]
    with _staged(tmp_path) as module:
        no_sam3(module)
        for video, start, to in parts:
            looked_at = len(_times(module, video, start, CLIP_SECONDS if to is None else to))
            part = f"{video['relpath']} from {start} to {to}, {looked_at} frames"

            def track(max_frames, video=video, start=start, to=to):
                return module.track_objects(_rows_of(video), nothing, None, labels=DEFAULT_LABELS,
                                            every_seconds=EVERY, from_seconds=start, to_seconds=to,
                                            max_frames=max_frames)

            with pytest.raises(_SamLoads):
                track(looked_at)
            if looked_at > 1:
                with pytest.raises(ValueError) as refused:
                    track(looked_at - 1)
                message = str(refused.value)
                assert f"looks at {looked_at - 1} frames of a video at most" in message, (part, message)
                assert f" is {looked_at} frames; " in message, (part, message)


def test_a_part_of_exactly_max_frames_frames_runs(videos, catalog_copy, weights, few_threads, tmp_path):
    """The 2 s clip at a frame every half second is 4 frames, which a limit of
    4 runs whole."""
    import av

    rows, helpers = videos
    model = _loaded(catalog_copy, weights)(MODEL_ID)
    with _staged(tmp_path) as module:
        (row,) = module.track_objects(rows, model, helpers["curio_derived_file"], labels=TWO_LABELS,
                                      every_seconds=EVERY, max_frames=len(SAMPLED)).to_dict("records")
    with av.open(row["path"]) as overlay:
        shown = [round(float(frame.time), 3) for frame in overlay.decode(overlay.streams.video[0])]
    assert shown == SAMPLED, f"the overlay shows its frames at {shown} s"
    assert Path(row["tracks"]).is_file()


def test_a_long_part_at_a_large_every_seconds_that_fits_runs(catalog_copy, weights, few_threads, tmp_path):
    """30 s of video at a frame every 10 s is 3 frames: a limit of 3 runs it
    whole, though it is 15 times as long as the 2 s clip a limit of 3 stops at
    a frame every half second, and a limit of 2 stops it before SAM 3 loads."""
    import av

    rows, helpers = _collection(tmp_path, seconds=30)
    model = _loaded(catalog_copy, weights)(MODEL_ID)
    with _staged(tmp_path) as module:
        def track(max_frames):
            return module.track_objects(rows, model, helpers["curio_derived_file"], labels=TWO_LABELS,
                                        every_seconds=10, max_frames=max_frames)

        with pytest.raises(ValueError) as refused:
            track(2)
        (row,) = track(3).to_dict("records")
    assert " 0 to 30 s at a frame every 10 s is 3 frames; " in str(refused.value), str(refused.value)
    with av.open(row["path"]) as overlay:
        shown = [round(float(frame.time), 3) for frame in overlay.decode(overlay.streams.video[0])]
    assert shown == [0.0, 10.0, 20.0], f"the overlay shows its frames at {shown} s"
    assert (row["t_s"], row["duration_s"]) == (0.0, 30.0)


def test_the_code_tabs_max_frames_is_450_which_takes_the_whole_walk_at_a_frame_every_2_s(tmp_path, no_sam3):
    """On dev the whole 864.3 s walk at a frame every 2 s took 433 frames in
    208 s, and 0 to 300 s at the code tab's frame every 0.5 s took 600 in 269
    s, against a node's 300 s. The code tab's limit, 450 frames, takes the
    first whole, and stops the second, and the whole walk at 0.5 s, before
    SAM 3 loads, with a gap and a part that fit."""
    import inspect

    settings = _code_tab_settings()
    assert settings.get("MAX_FRAMES") == 450, f"the code tab sets {settings}"
    walk = _whole_walk(tmp_path)
    nothing = SimpleNamespace(path=str(tmp_path / "no-weights"))
    with _staged(tmp_path) as module:
        assert inspect.signature(module.track_objects).parameters["max_frames"].default == settings["MAX_FRAMES"]
        no_sam3(module)

        def track(**part):
            return module.track_objects(_rows_of(walk), nothing, None, labels=settings["LABELS"],
                                        max_frames=settings["MAX_FRAMES"], **part)

        with pytest.raises(_SamLoads):
            track(every_seconds=2)
        looked_at = module._sample(SimpleNamespace(width=960, from_seconds=0, every_seconds=2), walk, WALK_SECONDS)[1]
        with pytest.raises(ValueError) as whole_walk:
            track(every_seconds=settings["EVERY_SECONDS"])
        with pytest.raises(ValueError) as five_minutes:
            track(every_seconds=settings["EVERY_SECONDS"], to_seconds=300)
        for fits in ({"every_seconds": settings["EVERY_SECONDS"], "to_seconds": 225},
                     {"every_seconds": 0.7, "to_seconds": 300}):
            with pytest.raises(_SamLoads):
                track(**fits)

    assert (len(looked_at), looked_at[-1]) == (433, 864.0), f"one frame every 2 s of the walk: {looked_at}"
    assert str(whole_walk.value) == (
        "whole-walk.mp4: Track Objects looks at 450 frames of a video at most in one run, and 0 to 864.3 s at a "
        "frame every 0.5 s is 1729 frames; raise EVERY_SECONDS to 2 or more, or set FROM_SECONDS and TO_SECONDS "
        "to a shorter part, such as 0 and 225"
    )
    assert str(five_minutes.value) == (
        "whole-walk.mp4: Track Objects looks at 450 frames of a video at most in one run, and 0 to 300 s at a "
        "frame every 0.5 s is 600 frames; raise EVERY_SECONDS to 0.7 or more, or set FROM_SECONDS and TO_SECONDS "
        "to a shorter part, such as 0 and 225"
    )


def test_a_dataflow_saved_with_max_seconds_stops_with_the_lines_to_change(videos, tmp_path, no_sam3):
    """A dataflow saved before MAX_FRAMES keeps its code, MAX_SECONDS and all:
    run as the canvas runs it, it stops before SAM 3 loads, naming the two
    lines to change, and writes nothing."""
    from utk_curio.sandbox.util.input_names import call_as_node

    rows, helpers = videos
    nothing = SimpleNamespace(path=str(tmp_path / "no-weights"))
    namespace = {**helpers, "curio_load_model": lambda _model_id: nothing}
    body = "\n".join("    " + line for line in SAVED_WITH_MAX_SECONDS.splitlines())
    with _staged(tmp_path) as module:
        no_sam3(module)
        with pytest.raises(ValueError) as refused:
            call_as_node(body, namespace, rows, [0])
    assert str(refused.value) == (
        "MAX_SECONDS is gone: Track Objects counts the frames a run looks at. In the node's code, replace "
        "MAX_SECONDS = 300 with MAX_FRAMES = 450, and max_seconds=MAX_SECONDS with max_frames=MAX_FRAMES"
    )
    assert not (tmp_path / "media" / "videos").exists() and not (tmp_path / "media" / "tables").exists()


# ---------------------------------------------------------------------------
# What SAM 3 holds
# ---------------------------------------------------------------------------

#: Two labels, which keep a run of the tiny SAM 3 to seconds.
TWO_LABELS = ["pole", "person"]


def _held(session) -> int:
    """The bytes of the tensors a SAM 3 *session* holds, each storage counted
    once: a slice holds all of what it is a slice of."""
    import torch

    storages, items = {}, [vars(session), vars(session.cache)]
    while items:
        item = items.pop()
        if isinstance(item, torch.Tensor):
            storage = item.untyped_storage()
            storages[storage.data_ptr()] = storage.nbytes()
        elif isinstance(item, dict):
            items.extend(item.values())
        elif isinstance(item, (list, tuple, set)):
            items.extend(item)
    return sum(storages.values())


def test_what_sam3_holds_stops_growing_once_it_has_seen_what_it_reads_again(
        steady_weights, catalog_copy, few_threads, tmp_path, monkeypatch):
    """SAM 3 reads again only a few frames back: the tiny SAM 3 here, the
    memory of its last frame and the pointers of its last three. On dev,
    Track Objects held every frame's state on the GPU to the video's end, 5.5
    GiB at 50 frames, 20 at 150 and 67 at 300, so 300 s of the walk at a frame
    every 0.5 s filled the 96 GB card at about 350 frames. Through 24 frames
    of three objects, what SAM 3's session holds after each frame stops
    growing once SAM 3 has seen the frames it reads again."""
    frames = 24
    rows, helpers = _collection(tmp_path, seconds=frames / CLIP_RATE)
    model = _loaded(catalog_copy, steady_weights)(MODEL_ID)
    held, objects = [], []
    with _staged(tmp_path) as module:
        real = module.Sam3VideoModel.propagate_in_video_iterator

        def recording(self, inference_session, **kwargs):
            for output in real(self, inference_session=inference_session, **kwargs):
                yield output
                held.append(_held(inference_session))
                objects.append(len(inference_session.obj_ids))

        monkeypatch.setattr(module.Sam3VideoModel, "propagate_in_video_iterator", recording)
        module.track_objects(rows, model, helpers["curio_derived_file"], labels=TWO_LABELS,
                             every_seconds=1 / CLIP_RATE)

    assert len(held) == frames, f"SAM 3 looked at {len(held)} frames, not {frames}"
    warm = 8
    assert objects[warm:] == [3] * (frames - warm), f"the objects SAM 3 followed changed: {objects}"
    mib = [round(value / 2**20, 2) for value in held]
    assert max(held[warm:]) <= held[warm], f"after each frame SAM 3's session held {mib} MiB"


def test_sam3_finds_in_each_frame_what_it_finds_holding_every_frame(
        windowed_weights, catalog_copy, few_threads, tmp_path):
    """Track Objects hands SAM 3 one frame at a time and drops, after each
    frame, what SAM 3 never reads again: SAM 3 finds in every frame the same
    objects, scores, boxes and masks as when its session holds the whole video
    and all it saw of it. The tiny SAM 3 here reads again a few frames back,
    holds each frame back three, and takes objects again from detections every
    second frame: through 16 frames an object gains more conditioning frames
    than SAM 3 reads the memory of, and frames pass out of every window."""
    import torch
    from PIL import Image

    frames = [Image.fromarray(_street(index)) for index in range(16)]
    path = _loaded(catalog_copy, windowed_weights)(MODEL_ID).path
    with _staged(tmp_path) as module:
        processor = module.Sam3VideoProcessor.from_pretrained(path, local_files_only=True)
        sam3 = module.Sam3VideoModel.from_pretrained(path, local_files_only=True).eval()
        run = SimpleNamespace(processor=processor, sam3=sam3, device="cpu", dtype=torch.float32, labels=TWO_LABELS)
        with torch.inference_mode():
            followed = list(module._follow(run, frames))
            whole = processor.init_video_session(video=frames, inference_device="cpu", dtype=torch.float32)
            processor.add_text_prompt(whole, TWO_LABELS)
            expected = [
                (output.frame_idx, processor.postprocess_outputs(whole, output))
                for output in sam3.propagate_in_video_iterator(inference_session=whole)
            ]

    conditioning = [len(outputs["cond_frame_outputs"]) for outputs in whole.output_dict_per_obj.values()]
    assert max(conditioning) > WINDOWS["max_cond_frame_num"], f"conditioning frames per object: {conditioning}"
    assert [index for index, _ in followed] == [index for index, _ in expected] == list(range(len(frames)))
    for (index, found), (_, holding_all) in zip(followed, expected):
        assert found["prompt_to_obj_ids"] == holding_all["prompt_to_obj_ids"], f"frame {index}: the labels differ"
        for key in ("object_ids", "scores", "boxes", "masks"):
            assert torch.equal(found[key], holding_all[key]), f"frame {index}: the {key} differ"


# ---------------------------------------------------------------------------
# Objects SAM 3 has not seen for a while
# ---------------------------------------------------------------------------

#: The side of the tiny SAM 3's low-res masks, the masks it detects and
#: follows objects with.
LOW_RES = SIZE * 288 // 1008


@pytest.fixture(scope="module")
def street_weights(tmp_path_factory):
    """A tiny SAM 3 that follows up to 40 objects and holds each frame back
    until it has seen seven after it, as SAM 3 holds a frame back fourteen."""
    return _tiny_weights(tmp_path_factory, _tiny_config(max_num_objects=40, hotstart_delay=8))


class _Street:
    """A street SAM 3 is made to see, whatever its random weights would find:
    objects, each of a label, at a place of its own, each in view at the
    frames given. SAM 3's detector finds each object in view, or at the
    frames *detected* gives it, and its tracker shows each object it follows
    where the object is while it is in view, and nothing while it is not. The
    rest of SAM 3 runs as it is: it matches what it detects with what it
    follows, takes what it does not follow as a new object, and holds each
    frame back.

    After each frame SAM 3 hands back, :attr:`followed` notes the last frame
    SAM 3 has looked at, which of the street's objects it follows, and the
    ids of objects it no longer follows but still keeps entries of, such as
    their scores and first frames."""

    def __init__(self, monkeypatch, module, objects, detected=None):
        import torch

        street, sam3 = self, module.Sam3VideoModel
        #: Each object: its label, and the frames it is in view at.
        self.objects = [(label, set(frames)) for label, frames in objects]
        #: Each object: the frames SAM 3's detector finds it at, those it is
        #: in view at unless *detected* gives the object's own.
        self.detected = [set((detected or {}).get(index, frames)) for index, (_, frames) in enumerate(self.objects)]
        #: Each id SAM 3 gave an object: which of the street's it is.
        self.follows = {}
        self.followed = []
        self._frame = None
        self._masks = []
        for index in range(len(objects)):
            mask = torch.full((LOW_RES, LOW_RES), -10.0)
            top, left = 2 + 9 * (index // 7), 2 + 9 * (index % 7)
            mask[top:top + 6, left:left + 6] = 10.0
            self._masks.append(mask)
        real = {name: getattr(sam3, name) for name in (
            "_det_track_one_frame", "_tracker_add_new_objects", "run_tracker_propagation",
            "propagate_in_video_iterator")}

        def one_frame(self, inference_session, frame_idx, reverse, streaming=False):
            street._frame = frame_idx
            return real["_det_track_one_frame"](
                self, inference_session=inference_session, frame_idx=frame_idx, reverse=reverse, streaming=streaming)

        def detect(self, inference_session, vision_embeds):
            found = {}
            for prompt_id, text in inference_session.prompts.items():
                masks = [street._masks[index] for index, (label, _) in enumerate(street.objects)
                         if label == text and street._frame in street.detected[index]]
                found[prompt_id] = {
                    "bbox": torch.tensor([[0.1, 0.1, 0.2, 0.2]] * len(masks)).reshape(-1, 4).to(self.device),
                    "mask": (torch.stack(masks) if masks else torch.zeros(0, LOW_RES, LOW_RES)).to(self.device),
                    "scores": torch.full((len(masks),), 0.9).to(self.device),
                }
            return found

        def take(self, inference_session, frame_idx, new_obj_ids, new_obj_masks, reverse=False):
            for object_id, mask in zip(new_obj_ids, new_obj_masks):
                street.follows[object_id] = next(
                    index for index, own in enumerate(street._masks) if torch.equal((mask > 0).cpu(), own > 0))
            return real["_tracker_add_new_objects"](
                self, inference_session=inference_session, frame_idx=frame_idx, new_obj_ids=new_obj_ids,
                new_obj_masks=new_obj_masks, reverse=reverse)

        def track(self, inference_session, frame_idx, reverse):
            masks, scores = real["run_tracker_propagation"](
                self, inference_session=inference_session, frame_idx=frame_idx, reverse=reverse)
            masks, scores = masks.clone(), scores.clone()
            for row, object_id in enumerate(inference_session.obj_ids):
                index = street.follows[object_id]
                in_view = frame_idx in street.objects[index][1]
                masks[row] = street._masks[index].to(masks.device) if in_view else -10.0
                scores[row] = 10.0 if in_view else -10.0
            return masks, scores

        def handed_back(self, inference_session, **kwargs):
            for output in real["propagate_in_video_iterator"](self, inference_session=inference_session, **kwargs):
                yield output
                session = inference_session
                ids = set(session.obj_ids)
                kept = {*session.obj_first_frame_idx, *session.trk_keep_alive, *session.unmatched_frame_inds,
                        *session.obj_id_to_score, *(i for pair in session.overlap_pair_to_frame_inds for i in pair)}
                street.followed.append(
                    (street._frame, sorted(street.follows[i] for i in ids), sorted(kept - ids)))

        monkeypatch.setattr(sam3, "_det_track_one_frame", one_frame)
        monkeypatch.setattr(sam3, "run_detection", detect)
        monkeypatch.setattr(sam3, "_tracker_add_new_objects", take)
        monkeypatch.setattr(sam3, "run_tracker_propagation", track)
        monkeypatch.setattr(sam3, "propagate_in_video_iterator", handed_back)

    def seen_within(self, frame, frames):
        """The street's objects in view at *frame* or at one of the *frames*
        before it."""
        return [index for index, (_, at) in enumerate(self.objects) if any(frame - frames < f <= frame for f in at)]

    def tracks(self, row):
        """Each of the street's objects SAM 3 found in the video of *row*:
        its tracks, in order, each as (start_s, end_s, frames)."""
        import pandas as pd

        found = {}
        for track in pd.read_parquet(row["tracks"]).sort_values("start_s").itertuples():
            found.setdefault(self.follows[track.object_id], []).append(
                (float(track.start_s), float(track.end_s), int(track.frames)))
        return dict(sorted(found.items()))


def test_the_objects_sam3_follows_stop_adding_up_once_forget_seconds_has_passed(
        street_weights, catalog_copy, few_threads, tmp_path, monkeypatch):
    """SAM 3 drops an object only in its first frames, and follows every other
    to the video's end, seen or not. On utk's GPU, through the 864 s
    SideSeeing walk at a frame every second, the objects it followed added up
    to 517 by 750 s, and a frame took 8 s, against 0.35 s with 11 objects.
    FORGET_SECONDS, 10 by default, lets go of an object SAM 3 has not seen for
    that long: between two frames, SAM 3 follows only the objects it saw in
    the last 10 s, and keeps nothing of the others. Here an object passes
    every 2 s through 30 s of a street, and a person stays in view."""
    rows, helpers = _collection(tmp_path, seconds=30)
    model = _loaded(catalog_copy, street_weights)(MODEL_ID)
    passing = [("pole" if index % 2 else "person", [2 * index, 2 * index + 1]) for index in range(14)]
    with _staged(tmp_path) as module:
        street = _Street(monkeypatch, module, [*passing, ("person", range(30))])
        module.track_objects(rows, model, helpers["curio_derived_file"], labels=TWO_LABELS, every_seconds=1)

    # Once SAM 3 has looked at the last frame, 29, nothing is let go.
    between = [(frame, followed) for frame, followed, _ in street.followed if frame < 29]
    seen = [(frame, street.seen_within(frame, 10)) for frame, _ in between]
    assert between == seen, (
        "objects SAM 3 followed after each frame, against those it saw in the last 10 frames: "
        f"{[(frame, len(followed)) for frame, followed in between]}, not {[(f, len(s)) for f, s in seen]}")
    leftovers = [(frame, kept) for frame, _, kept in street.followed if kept]
    assert not leftovers, f"SAM 3 keeps entries of objects it no longer follows: {leftovers}"


#: A street of 24 s: a pole out of view from 4 s to 17 s, a person out of view
#: from 6 s to 13 s, and a person in view throughout.
BACK_AGAIN = [("pole", [*range(4), *range(18, 24)]), ("person", [*range(6), *range(14, 24)]), ("person", range(24))]


def test_an_object_back_after_forget_seconds_is_a_new_object_its_first_track_ending_where_it_was_last_seen(
        street_weights, catalog_copy, few_threads, tmp_path, monkeypatch):
    """The pole out of view for 14 s, longer than FORGET_SECONDS, 10 by
    default, is let go: its track ends at 3 s, where SAM 3 last saw it, and at
    18 s SAM 3 finds it again as a new object, with a new id, so it is counted
    twice. The person out of view for 8 s keeps its id and its one track,
    though SAM 3 hands its frames back seven frames late: whether SAM 3 has
    seen an object is judged at the last frame it has looked at, not at the
    last it has handed back."""
    rows, helpers = _collection(tmp_path, seconds=24)
    model = _loaded(catalog_copy, street_weights)(MODEL_ID)
    with _staged(tmp_path) as module:
        street = _Street(monkeypatch, module, BACK_AGAIN)
        (row,) = module.track_objects(rows, model, helpers["curio_derived_file"], labels=TWO_LABELS,
                                      every_seconds=1).to_dict("records")

    tracks = street.tracks(row)
    assert tracks == {0: [(0.0, 3.0, 4), (18.0, 23.0, 6)], 1: [(0.0, 23.0, 16)], 2: [(0.0, 23.0, 24)]}, tracks
    # SAM 3's ids, each with the street's object it is: the pole's second is its newest.
    assert street.follows[max(street.follows)] == 0, street.follows
    assert (row["pole_objects"], row["person_objects"]) == (2, 2)


def test_with_forget_seconds_none_sam3_follows_every_object_to_the_end(
        street_weights, catalog_copy, few_threads, tmp_path, monkeypatch):
    """With FORGET_SECONDS None, SAM 3 follows every object it finds to the
    part's end, seen or not: the pole out of view for 14 s keeps its id, and
    has one track, from 0 s to 23 s."""
    rows, helpers = _collection(tmp_path, seconds=24)
    model = _loaded(catalog_copy, street_weights)(MODEL_ID)
    with _staged(tmp_path) as module:
        street = _Street(monkeypatch, module, BACK_AGAIN)
        (row,) = module.track_objects(rows, model, helpers["curio_derived_file"], labels=TWO_LABELS,
                                      every_seconds=1, forget_seconds=None).to_dict("records")

    tracks = street.tracks(row)
    assert tracks == {0: [(0.0, 23.0, 10)], 1: [(0.0, 23.0, 16)], 2: [(0.0, 23.0, 24)]}, tracks
    assert (row["pole_objects"], row["person_objects"]) == (1, 2)
    assert {frame: followed for frame, followed, _ in street.followed}[23] == [0, 1, 2]


def test_letting_go_of_an_object_leaves_what_sam3_finds_of_every_other(
        street_weights, catalog_copy, few_threads, tmp_path, monkeypatch):
    """Letting go of an object that does not come back changes nothing SAM 3
    finds: in each frame, the same objects, with the same ids, labels, scores,
    boxes and masks, as when SAM 3 follows it to the end. Here SAM 3 lets go
    of an object three frames after it last saw it, fewer than the seven
    frames it holds back, so the frames it still holds back show objects it
    has let go; at 15 s it lets go of the only object it follows; and the
    person it finds at 16 s gets the id it gets when SAM 3 lets go of
    nothing."""
    import torch
    from PIL import Image

    frames = [Image.fromarray(_street(index)) for index in range(20)]
    path = _loaded(catalog_copy, street_weights)(MODEL_ID).path
    objects = [("pole", range(5)), ("person", range(2, 10)), ("pole", range(11, 13)), ("person", range(16, 20))]
    with _staged(tmp_path) as module:
        street = _Street(monkeypatch, module, objects)
        processor = module.Sam3VideoProcessor.from_pretrained(path, local_files_only=True)
        sam3 = module.Sam3VideoModel.from_pretrained(path, local_files_only=True).eval()
        run = SimpleNamespace(processor=processor, sam3=sam3, device="cpu", dtype=torch.float32, labels=TWO_LABELS)
        with torch.inference_mode():
            kept = list(module._follow(run, frames))
            kept_followed, street.followed = street.followed, []
            let_go = list(module._follow(run, frames, 3))

    assert kept_followed[-1][1] == [0, 1, 2, 3], kept_followed
    between = [(frame, followed) for frame, followed, _ in street.followed if frame < 19]
    assert between == [(frame, street.seen_within(frame, 3)) for frame, _ in between], between
    assert ({frame: followed for frame, followed in between}[15], street.followed[-1][1]) == ([], [3])
    assert [index for index, _ in let_go] == [index for index, _ in kept] == list(range(len(frames)))
    shown = [found["object_ids"].tolist() for _, found in let_go]
    assert shown[1:5] == [[0], [0, 1], [0, 1], [0, 1]] and shown[11:13] == [[2], [2]], shown
    for (index, found), (_, followed_to_the_end) in zip(let_go, kept):
        assert found["prompt_to_obj_ids"] == followed_to_the_end["prompt_to_obj_ids"], f"frame {index}: the labels differ"
        for key in ("object_ids", "scores", "boxes", "masks"):
            assert torch.equal(found[key], followed_to_the_end[key]), f"frame {index}: the {key} differ"


# ---------------------------------------------------------------------------
# Objects SAM 3 drops in their first frames
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def dropping_weights(tmp_path_factory):
    """A tiny SAM 3 that holds each frame back until it has seen seven after
    it, as ``street_weights`` does, and drops an object it found in those
    frames once its detector has missed the object in three."""
    return _tiny_weights(tmp_path_factory, _tiny_config(
        max_num_objects=40, hotstart_delay=8, hotstart_unmatch_thresh=3))


#: A street of 12 frames: two poles and a person in view throughout, and a
#: third pole in view from frame 1, but at frame 3.
DROPPING = [("pole", range(12)), ("pole", range(12)), ("person", range(12)), ("pole", [1, 2, *range(4, 12)])]


def test_on_a_frame_where_sam3_drops_an_object_each_other_object_keeps_its_own_mask_and_score(
        dropping_weights, catalog_copy, few_threads, tmp_path, monkeypatch):
    """SAM 3 drops an object it found in its first frames once its detector
    keeps missing it. Transformers drops it before it pairs the frame's
    masks, one per object SAM 3 followed as the frame started, with the
    objects left, so on that frame each object after the one dropped got the
    mask of the object before it. On utk's GPU, through the SideSeeing walk
    at a frame every second, SAM 3 dropped an object with others after it in
    28 of 865 frames, 279 objects in all. Here SAM 3 finds two poles and a
    person at frame 0, and the third pole at frame 1; its detector finds the
    second pole only at frame 0, so SAM 3 drops it at frame 3, where the
    third pole is out of view. In every frame each object SAM 3 shows has its
    own box, and at frame 3 each object it follows has its own score, which
    decides which of two objects of a label keeps the pixels both cover."""
    import torch
    from PIL import Image

    frames = [Image.fromarray(_street(index)) for index in range(12)]
    path = _loaded(catalog_copy, dropping_weights)(MODEL_ID).path
    outputs = {}

    def keep(_sam3, _args, output):
        outputs[output.frame_idx] = output

    with _staged(tmp_path) as module:
        street = _Street(monkeypatch, module, DROPPING, detected={1: [0]})
        processor = module.Sam3VideoProcessor.from_pretrained(path, local_files_only=True)
        sam3 = module.Sam3VideoModel.from_pretrained(path, local_files_only=True).eval()
        run = SimpleNamespace(processor=processor, sam3=sam3, device="cpu", dtype=torch.float32, labels=TWO_LABELS)
        hook = sam3.register_forward_hook(keep)
        try:
            with torch.inference_mode():
                followed = list(module._follow(run, frames))
        finally:
            hook.remove()

    # SAM 3's ids are the street's objects, in the order it found them; at
    # frame 3 it drops the second pole, with the person and a pole after it.
    assert street.follows == {0: 0, 1: 1, 2: 2, 3: 3}, street.follows
    assert [(outputs[f].object_ids, sorted(outputs[f].removed_obj_ids)) for f in (2, 3)] == [
        ([0, 1, 2, 3], []), ([0, 2, 3], [1])], [(outputs[f].object_ids, outputs[f].removed_obj_ids) for f in (2, 3)]
    assert [index for index, _ in followed] == list(range(len(frames)))
    # Each object's box, as SAM 3's processor sizes a mask to the frame.
    width, height = frames[0].size
    boxes = [
        torch.nn.functional.interpolate(mask[None, None], size=(height, width), mode="bilinear",
                                        align_corners=False)[0, 0] > 0
        for mask in street._masks
    ]
    # Each object shown, with the street's object whose box its mask is.
    shown = [
        (index, {street.follows[object_id]: next((own for own, box in enumerate(boxes) if torch.equal(mask, box)), None)
                 for object_id, mask in zip(found["object_ids"].tolist(), found["masks"])})
        for index, found in followed
    ]
    in_view = [
        (index, {own: own for own, (_, at) in enumerate(street.objects) if index in at and own != 1})
        for index, _ in followed
    ]
    assert shown == in_view, "objects SAM 3 showed, each with the object whose box it had, where they differ: " + str(
        [(index, got, want) for (index, got), (_, want) in zip(shown, in_view) if got != want])
    scores = {street.follows[object_id]: round(outputs[3].obj_id_to_tracker_score[object_id], 3)
              for object_id in outputs[3].object_ids}
    assert scores == {0: 1.0, 2: 1.0, 3: 0.0}, f"each object's tracker score at frame 3: {scores}"


#: A street of 12 frames: a pole in view to frame 2, and a person in view from
#: frame 5.
ONLY_ONE_LEFT = [("pole", range(3)), ("person", range(5, 12))]


def test_objects_let_go_keep_their_labels_when_sam3_drops_the_last_object_it_follows(
        dropping_weights, catalog_copy, few_threads, tmp_path, monkeypatch):
    """Dropping the last object it follows, SAM 3 clears every label of its
    session, those of objects let go that frames it still holds back show
    among them, so Track Objects stopped with a KeyError as SAM 3 handed one
    of those frames back. Here the pole, last seen at frame 2, is let go
    after frame 7, three frames on, while SAM 3 still holds frames 1 and 2
    back; at frame 8 SAM 3 drops the person, the only object it then
    follows, whom its detector found only at frame 5. Every frame is handed
    back, and frames 0 to 2 show the pole with its label."""
    import torch
    from PIL import Image

    frames = [Image.fromarray(_street(index)) for index in range(12)]
    path = _loaded(catalog_copy, dropping_weights)(MODEL_ID).path
    outputs = {}

    def keep(_sam3, _args, output):
        outputs[output.frame_idx] = output

    with _staged(tmp_path) as module:
        street = _Street(monkeypatch, module, ONLY_ONE_LEFT, detected={1: [5]})
        processor = module.Sam3VideoProcessor.from_pretrained(path, local_files_only=True)
        sam3 = module.Sam3VideoModel.from_pretrained(path, local_files_only=True).eval()
        run = SimpleNamespace(processor=processor, sam3=sam3, device="cpu", dtype=torch.float32, labels=TWO_LABELS)
        hook = sam3.register_forward_hook(keep)
        try:
            with torch.inference_mode():
                shown = [(index, found["prompt_to_obj_ids"]) for index, found in module._follow(run, frames, 3)]
        finally:
            hook.remove()

    assert street.follows == {0: 0, 1: 1}, street.follows
    # After frame 8 SAM 3 follows nothing: it dropped the person.
    assert (outputs[8].object_ids, sorted(outputs[8].removed_obj_ids)) == ([], [1]), (
        outputs[8].object_ids, outputs[8].removed_obj_ids)
    assert shown == [(index, {"pole": [0]} if index < 3 else {}) for index in range(len(frames))], shown
