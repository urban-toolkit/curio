"""Add a model source's model to the Model Catalog, as a model package in the user's store.

The model half of :mod:`application.acquire`: a Hugging Face repo becomes a
model package (kind ``model``) of the user's own, as a portal's file becomes a
Data Catalog dataset. The provider chooses the files
(``providers/huggingface_models.py``); here they are fetched, each through the
transport with the model ceiling, into what becomes the package's
``models/``. The package's ``model`` block is written from what the repo says:
its labels from ``config.json``, an ONNX graph's input from
``preprocessor_config.json``, the weights' license from the model card. Its
node is the one Curio writes for a segmentation model
(``packages.service.model_template``), and the packages install it
(``packages.service.install_downloaded_model``) and its libraries.
"""

from __future__ import annotations

import json
import shutil
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from utk_curio.backend.app.common.user_storage import user_key_segment, users_base
from utk_curio.backend.app.discovery.domain.errors import (
    CapabilityUnsupported,
    CredentialRequired,
    DiscoveryError,
)
from utk_curio.backend.app.discovery.domain.manifest import DiscoverySourceManifest
from utk_curio.backend.app.discovery.infrastructure.transport import DiscoveryTransportError
from utk_curio.backend.app.discovery.providers.autark_osm import Cancelled
from utk_curio.backend.app.discovery.providers.huggingface_models import (
    MAX_MODEL_BYTES,
    ModelPlan,
    unwritable,
)

#: The libraries each runtime needs, declared in the model package's
#: ``dependencies.python`` and installed with it. torch 2.6 is the first to
#: load weights without running pickled code by default.
RUNTIME_DEPS = {
    "onnx": {"onnxruntime": ">=1.17"},
    "transformers": {"torch": ">=2.6", "transformers": ">=4.45", "safetensors": ">=0.4"},
}

#: Where a Transformers checkpoint's files go under the package's ``models/``:
#: a model block's entry is a path under ``models/``, never the folder itself.
CHECKPOINT_DIR = "checkpoint"

#: The type of every model the Hugging Face source adds.
MODEL_TYPE = "semantic-segmentation"

#: ImageNet's, which a preprocessor config that names none means.
_IMAGENET_MEAN = [0.485, 0.456, 0.406]
_IMAGENET_STD = [0.229, 0.224, 0.225]


def labels_of(config: dict[str, Any]) -> list[str]:
    """``config.json``'s ``id2label``, in channel order."""
    raw = config.get("id2label") if isinstance(config.get("id2label"), dict) else {}
    try:
        ordered = sorted(((int(k), str(v)) for k, v in raw.items()), key=lambda kv: kv[0])
    except (TypeError, ValueError):
        return []
    if [k for k, _v in ordered] != list(range(len(ordered))):
        return []
    return [v.strip()[:80] or str(k) for k, v in ordered]


def onnx_input(pre: dict[str, Any]) -> dict[str, Any]:
    """An ONNX graph's input, from ``preprocessor_config.json``."""
    size = pre.get("size")
    if isinstance(size, dict) and "height" in size and "width" in size:
        height, width = int(size["height"]), int(size["width"])
    elif isinstance(size, dict) and "shortest_edge" in size:
        height = width = int(size["shortest_edge"])
    elif isinstance(size, int):
        height = width = size
    else:
        height = width = 512
    height, width = max(8, min(height, 8192)), max(8, min(width, 8192))
    out: dict[str, Any] = {"width": width, "height": height, "dtype": "float32", "layout": "NCHW",
                           "scale": float(pre.get("rescale_factor") or 1 / 255) if pre.get("do_rescale", True) else 1.0}
    if pre.get("do_normalize", True):
        out["mean"] = [float(v) for v in (pre.get("image_mean") or _IMAGENET_MEAN)][:3]
        out["std"] = [float(v) for v in (pre.get("image_std") or _IMAGENET_STD)][:3]
    return out


class ModelAcquire:
    """Turns one model source row into a model package in the user's store.

    *models* gives the Model Catalog's service, which says whether this
    account already holds the row's model, whether it may add one, and the
    row a client is shown for the package it added."""

    def __init__(
        self,
        *,
        user_key: str,
        provider_for: Callable[[DiscoverySourceManifest], Any],
        models: Callable[[], Any],
    ) -> None:
        self.user_key = user_key
        self._provider_for = provider_for
        self._models = models

    def already_held(self, manifest: DiscoverySourceManifest, repo: str) -> dict[str, Any] | None:
        return self._models().find_by_discovery_resource(manifest.dir_name, repo)

    def acquire(
        self,
        manifest: DiscoverySourceManifest,
        repo: str,
        *,
        refresh: bool = False,
        progress: Callable[[int, int | None], None] | None = None,
        stage: Callable[[str], None] | None = None,
        cancelled: Callable[[], bool] | None = None,
    ) -> dict[str, Any]:
        """Fetch *repo*'s files and add them as a model package. Returns
        ``{model, dependencies, alreadyPresent, unchanged}``."""
        from utk_curio.backend.app.packages import service as packages

        held = self.already_held(manifest, repo)
        if held is not None and not refresh:
            return {"model": held, "alreadyPresent": True, "unchanged": True}
        # Refused before anything is fetched: a guest on a --deploy instance
        # adds no model, whatever its runtime needs (#623).
        refusal = self._models().model_refusal()
        if refusal:
            raise CapabilityUnsupported(refusal)
        provider = self._provider_for(manifest)
        if stage is not None:
            stage("Reading the model's files…")
        plan: ModelPlan = provider.plan(repo)
        # Refused before anything is fetched, for the reason a package install
        # would be: the model's runtime libraries are installed with it.
        needs = RUNTIME_DEPS[plan.runtime]
        refusal = self._models().install_refusal() if needs else None
        if refusal:
            raise CapabilityUnsupported(f"{plan.repo} needs {', '.join(needs)}: {refusal}")
        work = (
            users_base() / user_key_segment(self.user_key) / "discovery" / "tmp"
            / f"model{uuid.uuid4().hex[:16]}"
        )
        # The package's models/: an ONNX repo's files at their own paths, a
        # checkpoint's in a folder of its own.
        files = work / "models"
        weights = files if plan.runtime == "onnx" else files / CHECKPOINT_DIR
        try:
            self._fetch(provider, plan, weights, progress=progress, stage=stage, cancelled=cancelled)
            package = self._package_manifest(manifest, plan, weights, held=held)
            if stage is not None:
                stage("Adding to your Model Catalog…")
            installed = packages.install_downloaded_model(self.user_key, files, package, replace=held is not None)
        except packages.InstallerError as exc:
            raise DiscoveryError(f"{plan.repo} could not be added: {exc}") from exc
        finally:
            shutil.rmtree(work, ignore_errors=True)
        report = None
        if needs:
            if stage is not None:
                stage(f"Installing {', '.join(needs)}…")
            report = packages.install_downloaded_model_deps(self.user_key, installed)
        model = self._models().get_model(installed.package_id)
        return {"model": model, "dependencies": report, "alreadyPresent": False, "unchanged": False}

    def _fetch(self, provider, plan: ModelPlan, target: Path, *, progress, stage, cancelled) -> None:
        total = plan.total_bytes
        done = 0
        root = target.resolve()
        for index, (path, size) in enumerate(plan.files, start=1):
            if cancelled is not None and cancelled():
                raise Cancelled()
            destination = target / path
            # Checked before any folder is made: a repo names its own files.
            resolved = destination.resolve()
            if resolved == root or not resolved.is_relative_to(root):
                raise unwritable(plan.repo, path)
            if stage is not None:
                stage(f"Downloading {path} ({index} of {len(plan.files)})…")
            destination.parent.mkdir(parents=True, exist_ok=True)
            part = destination.with_name(destination.name + ".part")
            base = done

            def _progress(written: int, _declared: int | None) -> None:
                if progress is not None:
                    progress(base + written, total)

            try:
                with part.open("wb") as handle:
                    def sink(chunk: bytes, _write=handle.write) -> None:
                        if cancelled is not None and cancelled():
                            raise Cancelled()
                        _write(chunk)

                    provider.transport.download(
                        provider.file_url(plan, path), sink,
                        max_bytes=size + 1024 * 1024, ceiling=MAX_MODEL_BYTES, progress=_progress,
                    )
            except DiscoveryTransportError as exc:
                if any(f"answered {code}" in str(exc) for code in (401, 403)):
                    raise CredentialRequired(
                        f"Hugging Face refused {plan.repo}"
                        + (": accept its terms on huggingface.co" if plan.gated else "")
                        + ", then add a Hugging Face token that may read it in API Settings"
                    ) from exc
                raise
            part.replace(destination)
            done += destination.stat().st_size

    def _package_manifest(
        self, manifest: DiscoverySourceManifest, plan: ModelPlan, weights: Path, *, held: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """The model package's manifest for *plan*'s files in *weights*: a new
        ``imported.x<hex>`` id, or *held*'s id and date for a refresh."""
        from utk_curio.backend.app.common.record_clock import utc_now
        from utk_curio.backend.app.packages import service as packages

        def read(name: str) -> dict[str, Any]:
            try:
                value = json.loads((weights / name).read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise DiscoveryError(f"{plan.repo}: its {name} could not be read") from exc
            return value if isinstance(value, dict) else {}

        labels = labels_of(read("config.json"))
        publisher = plan.repo.split("/", 1)[0]
        block: dict[str, Any] = {
            "type": MODEL_TYPE,
            "runtime": plan.runtime,
            "labels": labels,
            "license": plan.license or "See the model's page on Hugging Face",
            "publisher": publisher,
            "homepage": f"{manifest.provider.base_url}/{plan.repo}",
            "sizeBytes": sum(path.stat().st_size for path in weights.rglob("*") if path.is_file()),
            "discoverySource": {
                "sourceId": manifest.dir_name,
                "sourceName": manifest.name,
                "resourceId": plan.repo,
                "revision": plan.revision,
                "fetchedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            },
        }
        if plan.runtime == "onnx":
            if not labels:
                raise CapabilityUnsupported(f"{plan.repo} names no labels for its output in config.json")
            block["entry"] = f"models/{plan.graph}"
            block["input"] = onnx_input(read("preprocessor_config.json"))
        else:
            block["entry"] = f"models/{CHECKPOINT_DIR}"
            if plan.architecture:
                block["discoverySource"]["architecture"] = plan.architecture
        now = utc_now().strftime("%Y-%m-%dT%H:%M:%SZ")
        return {
            "id": str(held["id"]) if held is not None else f"imported.x{uuid.uuid4().hex[:12]}",
            "kind": "model",
            "name": plan.repo,
            "version": "1.0.0",
            "compatibility": {"major": 1},
            "createdAt": str((held or {}).get("createdAt") or now),
            "description": f"{plan.repo} from Hugging Face, commit {plan.revision[:12]}.",
            "publisher": publisher,
            # The package's code is its node's cell, which Curio writes.
            "license": "MIT",
            "permissions": [],
            "dependencies": {"js": {}, "packages": {}, "python": dict(RUNTIME_DEPS[plan.runtime])},
            "model": block,
            "templates": [packages.model_template(MODEL_TYPE)],
        }
