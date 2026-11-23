"""Track Objects leaves Transformers' SAM 3 as it found it.

Transformers' SAM 3 video model cleans its masks with the kernels library's
cv-utils, which it looks for at its first frame and remembers in its module's
``cv_utils_kernel``: None until it has looked, False once it found none.
Track Objects' SAM 3 cleans its masks itself, so while it runs the flag says
that the library was looked for and not found, and Transformers does not look
for it on the Hugging Face Hub.

Without isolation a node runs in the sandbox's own process, which every later
node of every dataflow shares. So the flag is as it was again once a run of
Track Objects ends, whether the run returns or raises: a later run of
Transformers' own SAM 3 looks for the library as in a fresh process, rather
than skipping its clean-up without looking.

These tests run the node's code as the canvas runs it, with the tiny SAM 3 of
``tests/_support/tiny_sam3.py``, as ``test_sam3_package.py`` does.
"""

from __future__ import annotations

import os
import shutil
import sys

import pytest

from utk_curio.backend.tests._support import tiny_sam3
from utk_curio.backend.tests.test_packages.test_sam3_package import (
    PACKAGE,
    _collection,
    _loaded,
    _node_source,
    _staged,
)


@pytest.fixture(scope="module")
def tiny_weights(tmp_path_factory):
    """The tiny SAM 3, saved where ``--model-weights-dir`` puts the package's
    weights."""
    return tiny_sam3.weights(tmp_path_factory, tiny_sam3.config())


@pytest.fixture
def offline_on_few_threads(monkeypatch):
    """No Hugging Face Hub, and a few CPU threads for torch, whatever the
    runner shows: an arcade runner shows 192 CPUs, and torch would take half."""
    import torch

    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    monkeypatch.setenv("TRANSFORMERS_OFFLINE", "1")
    threads = torch.get_num_threads()
    torch.set_num_threads(min(4, os.cpu_count() or 1))
    yield
    torch.set_num_threads(threads)


class _Stop(Exception):
    """What a run that raises raises, as it draws its first frame."""


@pytest.mark.parametrize("ending", ["returns", "raises"])
def test_transformers_sam3_is_as_it_was_once_track_objects_ends(
        ending, tiny_weights, offline_on_few_threads, tmp_path, monkeypatch):
    """Transformers' SAM 3 has not looked for the kernels library yet, as in a
    fresh process. While Track Objects' node runs, its flag says the library
    was looked for and not found; once the run returns, or raises as it draws
    its first frame, the flag is None again."""
    from utk_curio.sandbox.util.input_names import call_as_node

    catalog = tmp_path / "catalog" / PACKAGE.name
    catalog.mkdir(parents=True)
    shutil.copyfile(PACKAGE / "manifest.json", catalog / "manifest.json")
    rows, helpers = _collection(tmp_path)
    namespace = {**helpers, "curio_load_model": _loaded(catalog, tiny_weights)}
    body = "\n".join(
        "    " + line for line in _node_source(labels=["pole", "person"], every_seconds=1.0).splitlines())

    with _staged(tmp_path) as module:
        transformers_module = sys.modules[module.TransformersSam3VideoModel.__module__]
        monkeypatch.setattr(transformers_module, "cv_utils_kernel", None)
        while_it_ran = []
        draw = module._draw

        def watched_draw(run, image, found, label_of):
            while_it_ran.append(transformers_module.cv_utils_kernel)
            if ending == "raises":
                raise _Stop("the run fails as it draws its first frame")
            return draw(run, image, found, label_of)

        monkeypatch.setattr(module, "_draw", watched_draw)
        if ending == "raises":
            with pytest.raises(_Stop):
                call_as_node(body, namespace, rows, [0])
        else:
            out = call_as_node(body, namespace, rows, [0])
            assert len(out["videos"]) == 1, out
        after = transformers_module.cv_utils_kernel

    assert while_it_ran and all(flag is False for flag in while_it_ran), (
        f"while Track Objects ran, Transformers' cv_utils_kernel was {while_it_ran}, not False: "
        "Transformers would look for the kernels library on the Hub")
    assert after is None, (
        f"once Track Objects {ending}, Transformers' cv_utils_kernel is {after!r}, not None as it was: every "
        "later run of Transformers' own SAM 3 in this process skips its clean-up without looking for the library")
