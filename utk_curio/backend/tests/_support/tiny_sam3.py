"""A tiny SAM 3, which the tests run in place of Meta's weights, and the clip they run it on.

SAM 3's weights are Meta's, 3.4 GB: no clone, image or pip install holds them,
a node's first run downloads them, and no test fetches them. The suites use a
tiny SAM 3 video model built here with random weights, about 5.8 M
parameters, saved as the package's ``fetch`` lists the files of Meta's:

- the unit tests of ``model.curio.sam3@1`` read it in place where
  ``--model-weights-dir`` puts the package's weights (:func:`weights`), as
  ``curio_load_model`` gives a node its ``model.path``;
- the e2e harness plants its files in the catalog's copy of the package, each
  stamped as fetched (``/api/testing/fetched-weights``,
  ``test_frontend/utils/stand_ins.py``), so example 31's Track Objects runs on
  it (:func:`checkpoint_files`);
- the ``-m cuda`` guard runs it on the GPU runner's GPU
  (``utk_curio/sandbox/tests/test_cuda_sam3.py``).

Its detection thresholds are 0, so random weights find something, and it
follows six objects at most, which keeps a run to seconds. torch,
transformers and av are imported inside the functions, so a checkout without
them fails each test that builds the model on its own.
"""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
PACKAGE = REPO / "packages" / "model.curio.sam3@1"
#: The side of the tiny model's square input.
SIZE = 224
#: The synthetic clip: 2 s at 4 frames a second.
CLIP_SECONDS, CLIP_RATE = 2.0, 4


def _entry() -> str:
    """The package's entry folder, where its checkpoint's files are."""
    return json.loads((PACKAGE / "manifest.json").read_text(encoding="utf-8"))["model"]["entry"]


def tokenizer(folder: Path):
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


def config(tracking=None, **video):
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
    model_config = Sam3VideoConfig(**{
        "detector_config": detector, "tracker_config": tracker,
        "score_threshold_detection": 0.0, "new_det_thresh": 0.0, "hotstart_delay": 0,
        "low_res_mask_size": SIZE * 288 // 1008,
        **video,
    })
    model_config.image_size = SIZE
    model_config.max_num_objects = objects
    return model_config


def save(checkpoint: Path, model_config, words: Path) -> Path:
    """Save a tiny SAM 3 of *model_config* and its processor in the folder
    *checkpoint*, its tokenizer's files written in *words* first: every file
    the package's ``fetch`` lists."""
    import torch
    from transformers import Sam2VideoVideoProcessor, Sam3ImageProcessor, Sam3VideoModel, Sam3VideoProcessor

    checkpoint.mkdir(parents=True)
    size = {"height": SIZE, "width": SIZE}
    processor = Sam3VideoProcessor(
        Sam3ImageProcessor(size=size), Sam2VideoVideoProcessor(size=size), tokenizer(words),
    )
    torch.manual_seed(0)
    Sam3VideoModel(model_config).save_pretrained(checkpoint)
    processor.save_pretrained(checkpoint)
    # The checkpoint as Hugging Face holds SAM 3's: the tokenizer's vocabulary
    # and merges beside its tokenizer.json, and its special tokens.
    for name in ("vocab.json", "merges.txt"):
        shutil.copyfile(words / name, checkpoint / name)
    (checkpoint / "special_tokens_map.json").write_text(json.dumps({
        "bos_token": "<|startoftext|>", "eos_token": "<|endoftext|>",
        "pad_token": "<|endoftext|>", "unk_token": "<|endoftext|>",
    }), encoding="utf-8")
    return checkpoint


def weights(tmp_path_factory, model_config) -> Path:
    """The package's folder under ``--model-weights-dir``, its entry holding a
    tiny SAM 3 of *model_config* and its processor: every file the package's
    ``fetch`` lists."""
    root = tmp_path_factory.mktemp("model-weights") / PACKAGE.name
    save(root / _entry(), model_config, tmp_path_factory.mktemp("tokenizer"))
    return root


def checkpoint_files(model_config=None) -> dict[str, bytes]:
    """The files of a tiny SAM 3 of *model_config* (:func:`config` when None),
    by their path in the package's entry folder, as the package's ``fetch``
    names them: what ``/api/testing/fetched-weights`` plants."""
    with tempfile.TemporaryDirectory(prefix="tiny-sam3-") as folder:
        checkpoint = save(Path(folder) / "checkpoint", model_config or config(), Path(folder))
        return {
            path.relative_to(checkpoint).as_posix(): path.read_bytes()
            for path in sorted(checkpoint.rglob("*")) if path.is_file()
        }


def street(index: int):
    """Frame *index* of the clip: an orange box crossing a dark street, 8
    pixels further each frame, as an RGB array."""
    import numpy as np

    image = np.full((64, 96, 3), 40, dtype=np.uint8)
    image[20:44, 8 + 8 * index:24 + 8 * index] = (230, 120, 40)
    return image


def clip(path: Path, seconds: float = CLIP_SECONDS) -> None:
    """A clip of :func:`street`, *seconds* long, in MPEG-4 Part 2, which every
    FFmpeg build reads and writes, so the overlay alone needs H.264."""
    import av

    with av.open(str(path), "w") as out:
        stream = out.add_stream("mpeg4", rate=CLIP_RATE)
        stream.width, stream.height, stream.pix_fmt = 96, 64, "yuv420p"
        for index in range(int(seconds * CLIP_RATE)):
            for packet in stream.encode(av.VideoFrame.from_ndarray(street(index), format="rgb24")):
                out.mux(packet)
        for packet in stream.encode():
            out.mux(packet)
